"""Rate lookup — resolving a pair and a date to four facts at once.

Every translated figure in this system needs all four: the rate, its as-at date,
its provenance, and whether it breaches the staleness threshold. Computing them
separately per screen is how a figure and its qualification drift apart, so they
are produced together or not at all (ADR-09).

Three provenances and no more:

    exact          a rate was recorded on the date asked for
    carried        the most recent earlier rate was used (BR-09, FR-44)
    triangulated   derived through USD, because neither side is USD (ADR-08)

Where no rate exists on **or before** the date, the answer is not a number. The
lookup returns ``None`` and the caller must exclude the account and say so.
Never zero (FR-46) — the whole point being that "I don't know" and "nothing"
are different answers, and only one of them is safe to add to a total.

Lives in `core` rather than `fx` per HLD §5.2.1: the rate table belongs to `fx`,
but resolving a rate is a primitive that net worth, reporting and export all
reach through, and it is the only path by which they may.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from core.currencies import BASE_CURRENCY, ONE, definition, pair_label, usd_ratio


class Provenance(StrEnum):
    EXACT = "exact"
    CARRIED = "carried"
    TRIANGULATED = "triangulated"


@dataclass(frozen=True)
class RateLeg:
    """One stored pair contributing to a quote.

    A direct quote has one leg; a triangulated quote has two. Exposed so a
    screen can show per-currency detail without asking a second question.
    """

    currency: str
    pair: str
    quoted_rate: Decimal
    as_at: date
    provenance: Provenance
    age_days: int
    is_stale: bool


@dataclass(frozen=True)
class RateQuote:
    """The four facts, together."""

    from_currency: str
    to_currency: str
    #: Multiply an amount in `from_currency` by this to get `to_currency`.
    #: Full precision — an inverse or triangulated factor is very often
    #: non-terminating, and ADR-02 rounds once, at display.
    factor: Decimal
    #: The **oldest** contributing rate date. For a triangulated quote this
    #: deliberately errs toward overstating staleness: a headline driven by one
    #: stale minor currency is the safe direction of error (ADR-09).
    as_at: date
    provenance: Provenance
    is_stale: bool
    age_days: int
    legs: tuple[RateLeg, ...]

    @property
    def pair(self) -> str:
        return f"{self.from_currency}/{self.to_currency}"

    def as_dict(self) -> dict:
        return {
            "pair": self.pair,
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "as_at": self.as_at.isoformat(),
            "provenance": str(self.provenance),
            "stale": self.is_stale,
            "age_days": self.age_days,
            "legs": [
                {
                    "pair": leg.pair,
                    "currency": leg.currency,
                    "rate": str(leg.quoted_rate),
                    "as_at": leg.as_at.isoformat(),
                    "provenance": str(leg.provenance),
                    "stale": leg.is_stale,
                }
                for leg in self.legs
            ],
        }


DEFAULT_STALENESS_DAYS = 7


class RateResolver:
    """Resolves quotes, caching the underlying row lookups.

    Stateful on purpose. Net worth over a twenty-four month range asks for the
    same handful of (currency, date) pairs repeatedly, and the cache turns that
    from a query per figure into a query per pair per date. One resolver per
    request; never a module-level singleton, because an edited rate must restate
    the next report rather than the one after it (BR-09).
    """

    def __init__(self, staleness_days: int = DEFAULT_STALENESS_DAYS) -> None:
        self.staleness_days = staleness_days
        self._legs: dict[tuple[str, date], RateLeg | None] = {}

    # -- the stored side ---------------------------------------------------

    def leg(self, currency: str, on_date: date) -> RateLeg | None:
        """The most recent stored rate for `currency` at or before `on_date`.

        None means no rate exists at any earlier date — the FR-46 case.
        """
        key = (currency, on_date)
        if key in self._legs:
            return self._legs[key]

        # Imported here rather than at module scope: `core` is imported while
        # the app registry is still populating, and `fx.models` is not ready.
        from fx.models import ExchangeRate

        row = (
            ExchangeRate.objects.filter(currency=currency, rate_date__lte=on_date)
            .order_by("-rate_date")
            .first()
        )

        if row is None:
            self._legs[key] = None
            return None

        age = (on_date - row.rate_date).days
        result = RateLeg(
            currency=currency,
            pair=pair_label(currency),
            quoted_rate=row.rate,
            as_at=row.rate_date,
            provenance=Provenance.EXACT if age == 0 else Provenance.CARRIED,
            age_days=age,
            # Breaches, so strictly greater. A rate exactly at the threshold is
            # not yet stale; the boundary is tested by name.
            is_stale=age > self.staleness_days,
        )
        self._legs[key] = result
        return result

    def usd_ratio(
        self, currency: str, on_date: date
    ) -> tuple[tuple[Decimal, Decimal], RateLeg | None]:
        """USD per one unit as an unevaluated ratio, and the leg it came from."""
        if currency == BASE_CURRENCY:
            return (ONE, ONE), None
        leg = self.leg(currency, on_date)
        if leg is None:
            raise LookupError(currency)
        return usd_ratio(currency, leg.quoted_rate), leg

    # -- the public question -----------------------------------------------

    def quote(self, from_currency: str, to_currency: str, on_date: date) -> RateQuote | None:
        """Resolve a pair and date, or None where no rate exists at any earlier date."""
        definition(from_currency)
        definition(to_currency)

        if from_currency == to_currency:
            # Including the base against itself, which is always 1 and is never
            # entered (BR-09).
            return RateQuote(
                from_currency=from_currency,
                to_currency=to_currency,
                factor=ONE,
                as_at=on_date,
                provenance=Provenance.EXACT,
                is_stale=False,
                age_days=0,
                legs=(),
            )

        try:
            (from_num, from_den), from_leg = self.usd_ratio(from_currency, on_date)
            (to_num, to_den), to_leg = self.usd_ratio(to_currency, on_date)
        except LookupError:
            return None

        # usd(from) / usd(to), cross-multiplied so exactly one division happens
        # and reciprocals cancel before any rounding. See core.currencies.usd_ratio.
        factor = (from_num * to_den) / (from_den * to_num)
        legs = tuple(leg for leg in (from_leg, to_leg) if leg is not None)

        if len(legs) == 2:
            # Neither side is USD, so the rate is derived through it. Labelled
            # as derived wherever it appears, and never stored.
            provenance = Provenance.TRIANGULATED
        else:
            provenance = legs[0].provenance

        # The oldest contributing date carries the quote, and staleness is
        # judged on that date rather than on the freshest leg.
        as_at = min(leg.as_at for leg in legs)
        age_days = (on_date - as_at).days

        return RateQuote(
            from_currency=from_currency,
            to_currency=to_currency,
            factor=factor,
            as_at=as_at,
            provenance=provenance,
            is_stale=age_days > self.staleness_days,
            age_days=age_days,
            legs=legs,
        )
