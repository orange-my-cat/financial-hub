"""Module 4 — FX Rates.

**ExchangeRate** — USD-based pairs only. Two rates per month-end, not six: a
full pair table would mean three times the monthly typing, and independently
entered pairs can silently disagree, producing a net worth that depends on which
route the translation took (ADR-08).

AUD↔MYR is triangulated through USD on demand and **never stored**. Storing a
derived rate creates a second copy that disagrees with its inputs the moment one
of them is edited.

Because every stored pair has USD on one side, the pair is identified by its
other currency alone — which is also what makes "one rate per pair per date" a
single unique constraint rather than a convention.
"""

from __future__ import annotations

from django.db import models

from core.currencies import (
    BASE_CURRENCY,
    QUOTED_CURRENCY_CHOICES,
    definition,
    pair_label,
)
from core.models import SoftDeleteModel, quantity_field


class RateSource(models.TextChoices):
    """Where the row came from.

    Captured from day one, and a **one-way door** (§13.4): a rate stored without
    knowing its origin cannot later be told apart from one that was typed. The
    Phase 2 rate API needs exactly this to honour "manual entry overrides the
    API" and to re-fetch a date safely.

    v1 only ever writes ENTERED. The other two exist so that adding the API is a
    second implementation rather than a schema migration against historic rows.
    """

    ENTERED = "entered", "Entered by hand"
    API = "api", "Fetched from a provider"
    CARRIED = "carried", "Materialised from a carry-forward"


class ExchangeRate(SoftDeleteModel):
    """One rate, for one USD-based pair, on one date."""

    #: The non-USD side of the pair. USD is excluded: the base against itself is
    #: always 1 and is never entered (BR-09).
    currency = models.CharField(max_length=3, choices=QUOTED_CURRENCY_CHOICES)

    #: A plain calendar date, no time component and no offset (BR-24).
    rate_date = models.DateField()

    #: In this currency's own market convention — AUD as USD per 1 AUD, MYR as
    #: MYR per 1 USD. See core.currencies for why direction belongs to the
    #: currency and never to the row.
    rate = quantity_field()

    source = models.CharField(
        max_length=16, choices=RateSource.choices, default=RateSource.ENTERED
    )
    provider = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            # One rate per pair per date, in the database rather than only in
            # application code (§9.1). Scoped to live rows: without the
            # condition, deleting a rate would permanently poison that
            # (currency, date) slot against ever being entered again.
            models.UniqueConstraint(
                fields=["currency", "rate_date"],
                condition=models.Q(deleted_at__isnull=True),
                name="fx_one_rate_per_pair_per_date",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gt=0),
                name="fx_rate_is_positive",
            ),
            models.CheckConstraint(
                # BR-09, in the schema. A USD/USD row would be meaningless and
                # would give the lookup two answers for the base currency.
                condition=~models.Q(currency=BASE_CURRENCY),
                name="fx_no_rate_for_the_base_against_itself",
            ),
        ]
        indexes = [
            # The dominant query in this system, by a wide margin: "the most
            # recent rate for this pair at or before this date". Descending, so
            # carry-forward is an index scan that stops at the first row.
            models.Index(
                fields=["currency", "-rate_date"],
                name="fx_rate_pair_date_desc",
            ),
        ]
        ordering = ["-rate_date", "currency"]

    def __str__(self) -> str:
        return f"{self.pair} {self.rate} on {self.rate_date:%Y-%m-%d}"

    @property
    def pair(self) -> str:
        """How this pair reads in its own direction — `AUD/USD`, `USD/MYR`."""
        return pair_label(self.currency)

    @property
    def quote_label(self) -> str:
        return definition(self.currency).quote_label
