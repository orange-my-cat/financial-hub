"""Rate trend, and the missing-and-stale summary.

The trend chart will be sparse unless extra dates are entered voluntarily, and
it shows that honestly as a line through the dates that exist rather than
inventing points between them (ADR-08).

Triangulated points are labelled derived. A triangulated AUD↔MYR will not
exactly match a quoted market rate for that pair — immaterial for personal net
worth, and surfaced rather than concealed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.currencies import (
    BASE_CURRENCY,
    QUOTED_CURRENCY_CODES,
    definition,
    format_rate,
    pair_label,
)
from core.services.rate_lookup import Provenance, RateResolver
from fx.models import ExchangeRate

#: Trend points are rendered, so they are rounded here rather than carrying
#: full precision into a chart that can draw six decimal places at best.
TREND_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class TrendPoint:
    on_date: date
    #: In the market convention of the pair being charted.
    rate: Decimal
    provenance: Provenance

    @property
    def is_derived(self) -> bool:
        return self.provenance is Provenance.TRIANGULATED


@dataclass(frozen=True)
class RateTrend:
    from_currency: str
    to_currency: str
    pair: str
    points: tuple[TrendPoint, ...]

    @property
    def is_derived(self) -> bool:
        """True where every point is triangulated — an unstored pair."""
        return bool(self.points) and all(point.is_derived for point in self.points)

    def as_dict(self) -> dict:
        return {
            "pair": self.pair,
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "derived": self.is_derived,
            "points": [
                {
                    "date": point.on_date.isoformat(),
                    "rate": str(point.rate),
                    "provenance": str(point.provenance),
                    "derived": point.is_derived,
                }
                for point in self.points
            ],
        }


def _contributing_currencies(from_currency: str, to_currency: str) -> tuple[str, ...]:
    return tuple(
        code
        for code in (from_currency, to_currency)
        if code != BASE_CURRENCY
    )


def rate_trend(
    from_currency: str,
    to_currency: str,
    start: date,
    end: date,
    *,
    resolver: RateResolver | None = None,
) -> RateTrend:
    """The series for one pair over a range.

    Points appear on the dates a contributing rate was actually recorded. For a
    triangulated pair that is the union of both legs' dates — each such point is
    a genuine observation of one leg, translated through the other's most recent
    value.
    """
    definition(from_currency)
    definition(to_currency)
    resolver = resolver or RateResolver()

    contributing = _contributing_currencies(from_currency, to_currency)
    if from_currency == to_currency or not contributing:
        return RateTrend(from_currency, to_currency, f"{from_currency}/{to_currency}", ())

    dates = (
        ExchangeRate.objects.filter(
            currency__in=contributing, rate_date__gte=start, rate_date__lte=end
        )
        .values_list("rate_date", flat=True)
        .distinct()
        .order_by("rate_date")
    )

    points: list[TrendPoint] = []
    for on_date in dates:
        quote = resolver.quote(from_currency, to_currency, on_date)
        if quote is None:
            # One leg has no rate at or before this date. Omitted rather than
            # interpolated: a gap in the line is the truth.
            continue
        points.append(
            TrendPoint(
                on_date=on_date,
                rate=quote.factor.quantize(TREND_PLACES),
                provenance=quote.provenance,
            )
        )

    label = (
        pair_label(contributing[0])
        if len(contributing) == 1
        else f"{from_currency}/{to_currency}"
    )
    return RateTrend(from_currency, to_currency, label, tuple(points))


# ---------------------------------------------------------------------------
# The daily table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyRateEntry:
    currency: str
    pair: str
    quote_label: str
    rate: Decimal
    as_at: date
    provenance: Provenance
    is_stale: bool
    #: True where this exact date has a stored row, so the screen knows which
    #: cells are editable and which are showing an earlier date's figure.
    is_recorded: bool

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "pair": self.pair,
            "quote_label": self.quote_label,
            "rate": format_rate(self.rate),
            "as_at": self.as_at.isoformat(),
            "provenance": str(self.provenance),
            "stale": self.is_stale,
            "recorded": self.is_recorded,
        }


@dataclass(frozen=True)
class DailyRateRow:
    on_date: date
    entries: tuple[DailyRateEntry, ...]

    def as_dict(self) -> dict:
        return {
            "date": self.on_date.isoformat(),
            "entries": [entry.as_dict() for entry in self.entries],
        }


def daily_rates(
    start: date, end: date, *, staleness_days: int
) -> tuple[DailyRateRow, ...]:
    """One row per date that has any rate, with every pair resolved on that date.

    Showing only the stored rows would make provenance meaningless — a stored
    row is exact by definition. The table earns its "provenance per rate" column
    by showing what a translation on that date would *actually* use, so a pair
    that was not entered that month is visibly carried rather than silently
    absent.
    """
    resolver = RateResolver(staleness_days=staleness_days)

    dates = (
        ExchangeRate.objects.filter(rate_date__gte=start, rate_date__lte=end)
        .values_list("rate_date", flat=True)
        .distinct()
        .order_by("-rate_date")
    )

    recorded = {
        (currency, on_date)
        for currency, on_date in ExchangeRate.objects.filter(
            rate_date__gte=start, rate_date__lte=end
        ).values_list("currency", "rate_date")
    }

    rows: list[DailyRateRow] = []
    for on_date in dates:
        entries: list[DailyRateEntry] = []
        for currency in QUOTED_CURRENCY_CODES:
            leg = resolver.leg(currency, on_date)
            if leg is None:
                # No rate for this pair at or before this date. Omitted rather
                # than shown as blank-but-present.
                continue
            entries.append(
                DailyRateEntry(
                    currency=currency,
                    pair=leg.pair,
                    quote_label=definition(currency).quote_label,
                    rate=leg.quoted_rate,
                    as_at=leg.as_at,
                    provenance=leg.provenance,
                    is_stale=leg.is_stale,
                    is_recorded=(currency, on_date) in recorded,
                )
            )
        rows.append(DailyRateRow(on_date=on_date, entries=tuple(entries)))

    return tuple(rows)


# ---------------------------------------------------------------------------
# Missing and stale
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateStatus:
    currency: str
    pair: str
    quote_label: str
    #: None where no rate has ever been recorded for this pair.
    latest_rate: Decimal | None
    latest_as_at: date | None
    age_days: int | None
    is_missing: bool
    is_stale: bool

    @property
    def state(self) -> str:
        """The word, so the meaning survives without the colour."""
        if self.is_missing:
            return "No rate on record"
        if self.is_stale:
            return f"{self.age_days} days old"
        return "Current"

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "pair": self.pair,
            "quote_label": self.quote_label,
            "rate": str(self.latest_rate) if self.latest_rate is not None else None,
            "as_at": self.latest_as_at.isoformat() if self.latest_as_at else None,
            "age_days": self.age_days,
            "missing": self.is_missing,
            "stale": self.is_stale,
            "state": self.state,
        }


def rate_status(as_of: date, *, staleness_days: int) -> tuple[RateStatus, ...]:
    """One row per pair: missing, stale by n days, or current.

    Drives the FX screen's summary and the dashboard's outstanding tasks. A
    currency that breaches the threshold is a task, not merely a colour.
    """
    statuses: list[RateStatus] = []

    for currency in QUOTED_CURRENCY_CODES:
        row = (
            ExchangeRate.objects.filter(currency=currency, rate_date__lte=as_of)
            .order_by("-rate_date")
            .first()
        )
        if row is None:
            statuses.append(
                RateStatus(
                    currency=currency,
                    pair=pair_label(currency),
                    quote_label=definition(currency).quote_label,
                    latest_rate=None,
                    latest_as_at=None,
                    age_days=None,
                    is_missing=True,
                    is_stale=False,
                )
            )
            continue

        age = (as_of - row.rate_date).days
        statuses.append(
            RateStatus(
                currency=currency,
                pair=pair_label(currency),
                quote_label=definition(currency).quote_label,
                latest_rate=row.rate,
                latest_as_at=row.rate_date,
                age_days=age,
                is_missing=False,
                is_stale=age > staleness_days,
            )
        )

    return tuple(statuses)
