"""Module 3 — Investments.

What is **absent** here is the important part.

**No lot table.** No stored cost basis, no stored remaining quantity, no stored
realised gain (ADR-06). A buy *is* a lot, and its remaining quantity is output
from replaying the holding's transactions through a pure function. Nothing can
drift, because there is nothing to drift from.

**No market price anywhere**, therefore no unrealised gain, no portfolio return
percentage, no paper gain. Inventing any of them makes the implementation wrong
rather than generous (BR-17).

**No relationship to the account's balance.** The snapshot is authoritative for
net worth; the holdings are authoritative for cost basis and realised gains. The
system enforces no relationship between them, performs no comparison, and raises
no discrepancy (BR-19). Recording a buy alters no balance.
"""

from __future__ import annotations

from django.core.validators import MinValueValidator
from django.db import models

from core.currencies import CURRENCY_CHOICES
from core.models import SoftDeleteModel, money_field, price_field, quantity_field
from investments.replay import Action


class InstrumentType(models.TextChoices):
    EQUITY = "Equity", "Equity"
    ETF = "ETF", "ETF"
    FUND = "Fund", "Managed Fund"
    BOND = "Bond", "Bond"
    OTHER = "Other", "Other"


class Holding(SoftDeleteModel):
    """One instrument, in one account.

    **Scoped to one account, and that is a one-way door** (§13.4). The same
    instrument at two brokers is two holdings with independent FIFO queues.
    Merging them later would need a decision about which broker's lots came
    first that the data cannot answer.
    """

    name = models.CharField(max_length=120)
    symbol = models.CharField(max_length=32, blank=True, default="")
    instrument_type = models.CharField(
        max_length=16, choices=InstrumentType.choices, default=InstrumentType.EQUITY
    )

    #: All performance figures are stated in this currency and never translated
    #: (BR-18). Translating performance would conflate market movement with
    #: currency movement, producing a figure that answers neither question.
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="holdings",
        help_text="Holdings are scoped to one account. This cannot be changed later.",
    )

    #: A user-typed percentage, applied to realised gains to produce an
    #: indicative net figure. The system applies no jurisdiction rules, no
    #: holding-period rules, no allowances and no thresholds (BR-21). Null means
    #: no estimate has been given, and the net figure equals the gross.
    estimated_tax_percent = quantity_field(
        null=True,
        blank=True,
        default=None,
        validators=[MinValueValidator(0)],
        help_text="Indicative only. Not a calculation, and not any jurisdiction's rules.",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="investments_one_holding_per_name_per_account",
            ),
            models.CheckConstraint(
                condition=models.Q(estimated_tax_percent__isnull=True)
                | models.Q(estimated_tax_percent__gte=0),
                name="investments_tax_percent_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.currency})"


class InvestmentTransaction(SoftDeleteModel):
    """Buy, sell, split, distribution or reinvestment (BR-20).

    Every other corporate action — mergers, spin-offs, rights issues, returns of
    capital — is out of scope, and must be represented by hand as a sale and a
    purchase. The resulting figures will not reflect the true event, and the
    system offers no guidance rather than guessing.
    """

    ACTION_CHOICES = [(action.value, action.value) for action in Action]

    holding = models.ForeignKey(
        Holding, on_delete=models.CASCADE, related_name="transactions"
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)

    #: A plain calendar date (BR-24).
    date = models.DateField()

    #: Breaks ties within a date. Two transactions on one day must replay in a
    #: defined order, or the FIFO queue is non-deterministic — and a
    #: non-deterministic cost basis cannot be reproduced to be argued with.
    sequence = models.PositiveSmallIntegerField(default=0)

    quantity = quantity_field(default=0)
    unit_price = price_field(default=0)
    fees = money_field(default=0)
    #: Splits: new units per old unit. 2 for 2:1, 0.1 for a 1:10 consolidation.
    split_ratio = quantity_field(default=0)
    #: Distributions: the cash received.
    cash_amount = money_field(default=0)

    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-date", "-sequence", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name="investments_quantity_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(fees__gte=0),
                name="investments_fees_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(split_ratio__gte=0),
                name="investments_split_ratio_not_negative",
            ),
        ]
        indexes = [
            # The replay query, and the only one that matters: a holding's whole
            # history in order.
            models.Index(
                fields=["holding", "date", "sequence"],
                name="investments_replay_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.holding.name} {self.action} {self.date:%Y-%m-%d}"
