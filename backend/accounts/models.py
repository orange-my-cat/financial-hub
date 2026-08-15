"""Module 1 — Net Worth. Account and Balance.

Two models and no third. There is no month table (ADR-04), no computed-figure
table (ADR-05), and nothing anywhere that stores a total.

The rule doing the most work here is the one that is easiest to write and
hardest to enforce: **an account's currency cannot change once balances exist**
(BR-08). It is enforced by a database trigger rather than by a service check,
because a rule enforced only in application code is a rule that holds until the
day something writes around it (§9.1) — and the something, here, is the Django
admin that ADR-03 requires be available for recovery.
"""

from __future__ import annotations

from django.core.validators import RegexValidator
from django.db import models

from core.currencies import CURRENCY_CHOICES
from core.models import SoftDeleteModel, money_field
from core.months import MONTH_PATTERN

month_validator = RegexValidator(
    regex=MONTH_PATTERN,
    message="Enter a reporting month as YYYY-MM.",
)

#: The database's copy of the same rule, so a direct write cannot dodge it.
_MONTH_REGEX = r"^\d{4}-(0[1-9]|1[0-2])$"


class AccountType(models.TextChoices):
    """Nine, with no grouping above them — the fixed vocabulary.

    A tenth type is a decision, not an addition: every type appears in the
    by-type slice, and the asset/liability split below is what BR-06's sign
    depends on.
    """

    CURRENT = "Current/Checking", "Current/Checking"
    SAVINGS = "Savings/Deposit", "Savings/Deposit"
    INVESTMENT = "Investment/Brokerage", "Investment/Brokerage"
    PENSION = "Pension/Retirement", "Pension/Retirement"
    PROPERTY = "Property", "Property"
    PHYSICAL = "Physical Asset", "Physical Asset"
    CREDIT_CARD = "Credit Card", "Credit Card"
    LOAN = "Loan/Mortgage", "Loan/Mortgage"
    OTHER_LIABILITY = "Other Liability", "Other Liability"


#: The three liability types. Everything else is an asset, and the sign in
#: BR-04 follows from this set alone.
LIABILITY_TYPES = frozenset(
    {AccountType.CREDIT_CARD, AccountType.LOAN, AccountType.OTHER_LIABILITY}
)


def is_liability(account_type: str) -> bool:
    return account_type in LIABILITY_TYPES


class LiquidityTier(models.TextChoices):
    INSTANT = "Instant", "Instant"
    SHORT = "Short", "Short"
    LONG = "Long", "Long"
    LOCKED = "Locked", "Locked"


class AccountStatus(models.TextChoices):
    OPEN = "Open", "Open"
    DORMANT = "Dormant", "Dormant"
    CLOSED = "Closed", "Closed"


class Account(SoftDeleteModel):
    name = models.CharField(max_length=120)

    # Properties of the account, not of a point in time. Changing either
    # restates all historic reporting as though the new classification had
    # always applied (BR-07). No record is kept of the previous value.
    account_type = models.CharField(max_length=32, choices=AccountType.choices)
    liquidity_tier = models.CharField(max_length=16, choices=LiquidityTier.choices)

    status = models.CharField(
        max_length=8, choices=AccountStatus.choices, default=AccountStatus.OPEN
    )

    # Fixed at creation. A provider offering multiple currency sub-balances is
    # represented as multiple accounts (BR-08).
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)

    opened_month = models.CharField(max_length=7, validators=[month_validator])
    closed_month = models.CharField(
        max_length=7, validators=[month_validator], blank=True, null=True, default=None
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(opened_month__regex=_MONTH_REGEX),
                name="accounts_opened_month_is_a_month",
            ),
            models.CheckConstraint(
                condition=models.Q(closed_month__isnull=True)
                | models.Q(closed_month__regex=_MONTH_REGEX),
                name="accounts_closed_month_is_a_month",
            ),
            models.CheckConstraint(
                condition=models.Q(closed_month__isnull=True)
                | models.Q(closed_month__gte=models.F("opened_month")),
                name="accounts_closed_not_before_opened",
            ),
            models.CheckConstraint(
                # Closure carries a date, and a date implies closure. A Closed
                # account with no closing month has no defined last month, and
                # an Open account with one is a contradiction the reports would
                # have to guess about.
                condition=(
                    models.Q(status=AccountStatus.CLOSED, closed_month__isnull=False)
                    | (~models.Q(status=AccountStatus.CLOSED) & models.Q(closed_month__isnull=True))
                ),
                name="accounts_closed_status_has_a_closing_month",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "opened_month"], name="accounts_status_opened"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.currency})"

    @property
    def is_liability(self) -> bool:
        return is_liability(self.account_type)

    @property
    def sign(self) -> int:
        """+1 for an asset, -1 for a liability.

        Liabilities are entered as positive figures and the system applies the
        sign (BR-06) — entering a mortgage as 247,500 rather than -247,500 is
        materially less error-prone. A credit card in credit is entered as a
        negative on a liability account, and correspondingly increases net worth.
        """
        return -1 if self.is_liability else 1

    def is_active_at(self, month: str) -> bool:
        """Whether this account contributes to `month` (BR-04).

        Open and Dormant accounts count. A Closed account still counts in the
        months up to its closure — closing excludes it from later months, it
        does not erase it from earlier ones.
        """
        if month < self.opened_month:
            return False
        if self.closed_month is not None and month > self.closed_month:
            return False
        return True


class Balance(SoftDeleteModel):
    """One entered snapshot, for one account, for one month.

    Never derived, and never altered by a transaction of any kind (BR-01). The
    entered snapshot is correct by definition because it was copied from the
    real account; a derived balance silently drifts wrong the first time a
    transaction is missed.
    """

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="balances")

    #: `YYYY-MM`. Stated as at the last calendar day of that month (BR-02).
    month = models.CharField(max_length=7, validators=[month_validator])

    #: In the account's own currency, entered as a positive figure even for a
    #: liability. NUMERIC(19,4).
    amount = money_field()

    class Meta:
        ordering = ["-month"]
        constraints = [
            # One balance per account per month, in the database. Entry behaves
            # as create-or-replace, so a second balance for the same month is
            # impossible rather than discouraged. Scoped to live rows, or a
            # soft delete would poison that slot forever.
            models.UniqueConstraint(
                fields=["account", "month"],
                condition=models.Q(deleted_at__isnull=True),
                name="accounts_one_balance_per_account_per_month",
            ),
            models.CheckConstraint(
                condition=models.Q(month__regex=_MONTH_REGEX),
                name="accounts_balance_month_is_a_month",
            ),
        ]
        indexes = [
            # "The balance for this account at or before this month" — the
            # dormant carry-forward query, and the account history screen.
            models.Index(fields=["account", "-month"], name="accounts_balance_acct_month"),
            models.Index(fields=["month"], name="accounts_balance_month"),
        ]

    def __str__(self) -> str:
        return f"{self.account.name} {self.month}: {self.amount}"
