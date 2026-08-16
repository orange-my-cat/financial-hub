"""Recording rates.

Two rates per month-end, not six (ADR-08). Entry is create-or-replace on
(currency, date), so a second rate for the same pair and date is impossible
rather than merely discouraged — and the database says so too.

**The rate-variance advisory never blocks.** A misplaced decimal misstates every
foreign balance for that month and nothing else in the system would catch it, so
the advisory exists; but a genuine 12% move in a month is not an error, so
refusing the save would be wrong. It saves either way, and says what it noticed
(ADR-08, §8.3).

Bulk entry for a date commits as a unit (§9.6). That is the one place in this
system where atomicity is right: the rates for a month-end are entered together
in a single pass, and half of them landing would leave a month translated on a
mixture of dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction

from core.currencies import (
    BASE_CURRENCY,
    definition,
    format_rate,
    pair_label,
)
from core.services.advisories import Advisory, AdvisoryKind
from core.services.exceptions import BusinessRuleError, NotFoundError
from fx.models import ExchangeRate, RateSource

DEFAULT_VARIANCE_PERCENT = Decimal("10")


@dataclass(frozen=True)
class RecordedRate:
    rate: ExchangeRate
    created: bool
    advisories: tuple[Advisory, ...]


def _variance_advisory(
    currency: str,
    rate_date: date,
    new_rate: Decimal,
    threshold_percent: Decimal,
) -> Advisory | None:
    """Compare against the most recent earlier rate for this pair."""
    previous = (
        ExchangeRate.objects.filter(currency=currency, rate_date__lt=rate_date)
        .order_by("-rate_date")
        .first()
    )
    if previous is None or previous.rate == 0:
        return None

    difference = (new_rate - previous.rate) / previous.rate * 100
    if abs(difference) <= threshold_percent:
        return None

    # Stated in the stored pair's own market convention, and it names that pair,
    # because that is the number the user can check against the site they read it
    # from. Where the entry was re-based onto a reporting currency the figure
    # quoted here is therefore not the one they typed — which is why the pair
    # label is in the sentence rather than assumed.
    return Advisory(
        kind=AdvisoryKind.RATE_VARIANCE,
        message=(
            f"{pair_label(currency)} moved {difference:+.2f}% against the previous "
            f"rate of {format_rate(previous.rate)} on "
            f"{previous.rate_date:%d %b %Y}. "
            f"Saved — check the decimal point if that looks wrong."
        ),
        detail={
            "currency": currency,
            "pair": pair_label(currency),
            "quote_label": definition(currency).quote_label,
            "previous_rate": format_rate(previous.rate),
            "previous_as_at": previous.rate_date.isoformat(),
            "entered_rate": format_rate(new_rate),
            # Signed, matching the message. A bare "50.00" leaves the reader to
            # work out which way it moved from the two rates beside it.
            "difference_percent": f"{difference:+.2f}",
            "threshold_percent": str(threshold_percent),
        },
    )


def record_rate(
    currency: str,
    rate_date: date,
    rate: Decimal,
    *,
    variance_percent: Decimal = DEFAULT_VARIANCE_PERCENT,
    source: str = RateSource.ENTERED,
    provider: str = "",
) -> RecordedRate:
    """Create or replace the rate for one pair on one date."""
    if currency == BASE_CURRENCY:
        raise BusinessRuleError(
            f"{BASE_CURRENCY} is the base currency. Its rate against itself is "
            f"always 1 and is never entered.",
            code="base_currency_rate",
            field="currency",
        )
    definition(currency)

    if rate <= 0:
        raise BusinessRuleError(
            "A rate must be greater than zero.",
            code="rate_not_positive",
            field="rate",
        )

    # Computed before the write, so it compares against the genuine predecessor
    # rather than against the row being replaced.
    advisory = _variance_advisory(currency, rate_date, rate, variance_percent)

    instance, created = ExchangeRate.objects.update_or_create(
        currency=currency,
        rate_date=rate_date,
        defaults={"rate": rate, "source": source, "provider": provider},
    )

    return RecordedRate(
        rate=instance,
        created=created,
        advisories=(advisory,) if advisory else (),
    )


@transaction.atomic
def record_rates_for_date(
    rate_date: date,
    rates: dict[str, Decimal],
    *,
    variance_percent: Decimal = DEFAULT_VARIANCE_PERCENT,
) -> tuple[tuple[ExchangeRate, ...], tuple[Advisory, ...]]:
    """Bulk entry for a single date, committing as a unit.

    Advisories are collected across every pair and returned together, so the
    screen shows one list rather than interrupting between fields.
    """
    if not rates:
        raise BusinessRuleError(
            "No rates were supplied.", code="no_rates", field="rates"
        )

    saved: list[ExchangeRate] = []
    advisories: list[Advisory] = []

    for currency in sorted(rates):
        result = record_rate(
            currency,
            rate_date,
            rates[currency],
            variance_percent=variance_percent,
        )
        saved.append(result.rate)
        advisories.extend(result.advisories)

    return tuple(saved), tuple(advisories)


def delete_rate(currency: str, rate_date: date) -> None:
    """Soft-delete one rate.

    The unique constraint is scoped to live rows, so the same pair and date can
    be entered again afterwards — and the deleted row stays recoverable through
    the admin (ADR-03).
    """
    instance = ExchangeRate.objects.filter(
        currency=currency, rate_date=rate_date
    ).first()
    if instance is None:
        # NotFoundError rather than the plain business-rule error: the resource
        # addressed does not exist, which is a 404 and not a rejected request.
        raise NotFoundError(
            f"No {pair_label(currency)} rate is recorded for "
            f"{rate_date:%d %b %Y}.",
            code="rate_not_found",
        )
    instance.delete()
