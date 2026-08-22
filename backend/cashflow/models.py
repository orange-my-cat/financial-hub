"""Module 2 — Cash Flow. A parallel ledger, and deliberately nothing more.

Cash flow records income and expense for spending analysis only. It does not
affect account balances, net worth, or any investment figure, and **no report
sums cash flow figures together with balance figures** (BR-12). That decoupling
is what keeps an incomplete ledger from ever corrupting net worth.

The consequence worth stating plainly, because it is a real limitation rather
than an oversight: the system cannot explain a net worth movement in terms of
saving, spending, market movement or currency movement. Interest recorded here
also shows up as balance growth in the snapshot, and that is not a double count
— it is the same event seen from two independent angles, which is safe precisely
because nothing ever adds them together.
"""

from __future__ import annotations

from django.db import models

from core.currencies import CURRENCY_CHOICES
from core.models import SoftDeleteModel, money_field


class Direction(models.TextChoices):
    INCOME = "Income", "Income"
    EXPENSE = "Expense", "Expense"


class Category(SoftDeleteModel):
    """A two-level taxonomy. Transactions attach to children only.

    Parents exist for rollup and are not directly selectable (BR-22). The
    hierarchy is deliberately two deep and no deeper: a third level would be a
    reporting dimension nobody asked for and a decision at every entry.

    A category that has been used is **deactivated, never deleted** — it
    disappears from entry and its history stays intact. The database enforces
    that, because orphaning historic transactions is not a mistake worth being
    able to make.
    """

    name = models.CharField(max_length=64)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    direction = models.CharField(max_length=8, choices=Direction.choices)

    #: Deactivated categories stay in historic reporting and leave entry.
    is_active = models.BooleanField(default=True)

    #: Ordering within a parent, so the seeded taxonomy reads in its intended
    #: order rather than alphabetically.
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["direction", "position", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="cashflow_unique_child_name_per_parent",
            ),
            models.UniqueConstraint(
                fields=["name", "direction"],
                condition=models.Q(deleted_at__isnull=True, parent__isnull=True),
                name="cashflow_unique_parent_name_per_direction",
            ),
        ]
        indexes = [
            models.Index(fields=["parent", "is_active"], name="cashflow_cat_parent_active"),
        ]

    def __str__(self) -> str:
        return self.path

    @property
    def is_parent(self) -> bool:
        return self.parent_id is None

    @property
    def path(self) -> str:
        """`Expenses → Food → Groceries`, as the taxonomy reads."""
        if self.parent_id is None:
            return f"{self.direction} → {self.name}"
        return f"{self.parent.direction} → {self.parent.name} → {self.name}"


class Transaction(SoftDeleteModel):
    """One item of income or expense.

    Date, amount, currency, direction and exactly one child category. No
    merchant field, no payee, and **no split**: a transaction covering several
    categories is assigned to the dominant one in full (BR-13).

    Two columns here are read by nothing in v1 and exist anyway, because they
    are **one-way doors** (ADR-13) — neither can be added retrospectively to
    historic rows:

    `account` makes per-account cash flow analysis possible in Phase 2. BRD §9.2
    says no relationship exists between transactions and accounts, deliberately;
    capturing an optional one costs a nullable column and forecloses nothing.

    `import_batch` exists so a Phase 2 bad import can be rolled back as a unit
    rather than deleted row by row.

    There is **no transfer type and no transfer flag**. Moving money between
    one's own accounts is not a transaction and shows only as two balance
    changes at the next close (BR-11).
    """

    #: A plain calendar date, no time component (BR-24).
    date = models.DateField()

    #: Always positive. The direction carries the sign, so income and expense
    #: can be separated in reporting without inspecting signs.
    amount = money_field()
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    direction = models.CharField(max_length=8, choices=Direction.choices)

    #: A child category. PROTECT rather than CASCADE: deleting a category out
    #: from under its transactions is exactly what BR-22 forbids.
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="transactions"
    )

    note = models.CharField(max_length=255, blank=True, default="")

    # -- the two one-way doors, unused in v1 ------------------------------
    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cashflow_transactions",
        help_text="Optional. Captured for Phase 2; read by no v1 report.",
    )
    import_batch = models.UUIDField(
        null=True,
        blank=True,
        help_text="Optional. Captured for Phase 2; read by no v1 report.",
    )

    # -- recurring provenance ---------------------------------------------
    recurring_template = models.ForeignKey(
        "cashflow.RecurringTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed",
    )
    #: The occurrence this transaction satisfied, so that occurrence stops being
    #: proposed. A date rather than a month because a weekly arrangement has four
    #: or five of them in a month. A confirmed transaction is thereafter
    #: independent of its template.
    recurring_occurrence = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="cashflow_amount_is_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["-date"], name="cashflow_txn_date"),
            models.Index(fields=["category", "-date"], name="cashflow_txn_cat_date"),
            models.Index(
                fields=["recurring_template", "recurring_occurrence"],
                name="cashflow_txn_recurring",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date:%Y-%m-%d} {self.amount} {self.currency} {self.category.name}"


class Frequency(models.TextChoices):
    """How often an arrangement falls due.

    Weekly and fortnightly are the reason the anchor is a date: a fortnightly
    salary lands on a particular Thursday, and no month key can say which one.
    """

    WEEKLY = "Weekly", "Weekly"
    FORTNIGHTLY = "Fortnightly", "Fortnightly"
    MONTHLY = "Monthly", "Monthly"


class RecurringTemplate(SoftDeleteModel):
    """An expected amount, category and frequency — proposed, never posted.

    Each period the system presents it for confirmation, and it becomes a real
    transaction only on confirmation, with the amount adjustable at that point
    (BR-14). Automatic posting would create transactions for payments that did
    not happen, which is precisely the drift a manual ledger exists to avoid.
    """

    name = models.CharField(max_length=120)
    amount = money_field()
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="recurring_templates"
    )
    frequency = models.CharField(max_length=12, choices=Frequency.choices)

    #: The first occurrence, and the only thing that fixes the rhythm: every
    #: later occurrence is counted from here. It carries the weekday a weekly or
    #: fortnightly arrangement falls on and the day of the month a monthly one
    #: does, which is why it is one date rather than a start plus a day.
    anchor_date = models.DateField()
    #: Ending a recurring item stops proposals after this date and leaves history
    #: intact. Null while it runs indefinitely. Deliberately allowed to precede
    #: the anchor date: an arrangement cancelled before its first occurrence is
    #: one that never proposes anything, and that is how it is written.
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="cashflow_template_amount_is_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.frequency})"

    @property
    def step_days(self) -> int | None:
        """Days between occurrences, or None for a monthly step.

        A month is not a number of days, so monthly stepping is calendar
        arithmetic and lives in the service with the clamping it needs.
        """
        return {Frequency.WEEKLY: 7, Frequency.FORTNIGHTLY: 14}.get(self.frequency)


class RecurringDismissal(SoftDeleteModel):
    """An occurrence the user explicitly skipped.

    OI-09: a proposal for a skipped occurrence remains outstanding until
    confirmed **or explicitly dismissed**. Without this row a skipped week would
    either nag forever or vanish silently, and the second is worse — a proposal
    that disappears on its own is one the user never decided about.
    """

    template = models.ForeignKey(
        RecurringTemplate, on_delete=models.CASCADE, related_name="dismissals"
    )
    occurrence = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["template", "occurrence"],
                condition=models.Q(deleted_at__isnull=True),
                name="cashflow_one_dismissal_per_occurrence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.template.name} skipped {self.occurrence:%Y-%m-%d}"
