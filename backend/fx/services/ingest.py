"""Loading fetched rates — where "manual entry overrides the API" is enforced.

Fetching is `fx.services.providers`. Writing is `fx.services.entry.record_rate`.
This module is the rule between them, and it is one rule:

    **A rate the user typed is never overwritten by a fetched one** (BRD §4.3).

That is the whole reason `source` and `provider` were captured from day one
(§13.4). Without them a loader could not tell a hand-typed rate from a fetched
one, and a backfill would quietly replace the figure a month was actually closed
on — restating history from a source the user had already chosen to override.
Rows written by an earlier fetch *are* replaced, so re-running a range is safe
and idempotent.

Nothing here is a second definition of anything. Rates land through the same
`record_rate` as hand entry, so they get the same validation, the same
create-or-replace on (currency, date), and the same rate-variance advisory — the
one thing that would catch a provider sending a decimal in the wrong place. The
advisories are collected and reported rather than shown one at a time; on daily
data a >10% move against the previous *trading day* is close to proof of a bad
figure, so they are worth surfacing even in a batch of thousands.

A date commits as a unit (§9.6). Both pairs for one day land together or neither
does, so an interrupted load never leaves a day translated on a mixture of
fetched and missing rates.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from core.currencies import BASE_CURRENCY, QUOTED_CURRENCY_CODES, definition, pair_label
from core.services.advisories import Advisory
from core.services.exceptions import BusinessRuleError
from fx.models import ExchangeRate, RateSource
from fx.services.entry import DEFAULT_VARIANCE_PERCENT, record_rate
from fx.services.providers import DailyClose, RateProvider

logger = logging.getLogger("financial_hub")

#: The window the FX Rates screen's one button loads, in days ending today.
#:
#: A year, and fixed rather than asked for. It is long enough to cover any lapse
#: in running it and to fill a trend chart, short enough that the request is a
#: few seconds rather than a request the browser gives up on, and — because a
#: re-fetch replaces only rows an earlier fetch wrote — running it repeatedly
#: costs nothing but time. Letting the client name the span would eventually
#: mean someone asking for a decade through a synchronous endpoint.
RECENT_WINDOW_DAYS = 365


@dataclass(frozen=True)
class CurrencyOutcome:
    """What the load did to one pair."""

    currency: str
    fetched: int
    written: int
    replaced: int
    kept_manual: int
    first_date: date | None
    last_date: date | None

    @property
    def pair(self) -> str:
        return pair_label(self.currency)

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "pair": self.pair,
            "fetched": self.fetched,
            "written": self.written,
            "replaced": self.replaced,
            "kept_manual": self.kept_manual,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "last_date": self.last_date.isoformat() if self.last_date else None,
        }


@dataclass(frozen=True)
class LoadOutcome:
    provider: str
    start: date
    end: date
    dry_run: bool
    per_currency: tuple[CurrencyOutcome, ...]
    advisories: tuple[Advisory, ...]

    @property
    def fetched(self) -> int:
        return sum(outcome.fetched for outcome in self.per_currency)

    @property
    def written(self) -> int:
        return sum(outcome.written for outcome in self.per_currency)

    @property
    def kept_manual(self) -> int:
        return sum(outcome.kept_manual for outcome in self.per_currency)

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "dry_run": self.dry_run,
            "fetched": self.fetched,
            "written": self.written,
            # Named in the payload rather than left to be inferred from the
            # difference: it is the only place BRD §4.3 is visible to whoever
            # pressed the button.
            "kept_manual": self.kept_manual,
            "pairs": [outcome.as_dict() for outcome in self.per_currency],
        }


def _manual_dates(currency: str, start: date, end: date) -> set[date]:
    """Dates in the range whose stored rate was typed by hand.

    Live rows only, which is the `objects` manager's default. A soft-deleted
    manual rate is not a rate the user is standing behind any more, so it does
    not veto a fetch — and the unique constraint is scoped the same way, so the
    slot is genuinely free (ADR-03).
    """
    return set(
        ExchangeRate.objects.filter(
            currency=currency,
            rate_date__gte=start,
            rate_date__lte=end,
            source=RateSource.ENTERED,
        ).values_list("rate_date", flat=True)
    )


def _validated(currencies: tuple[str, ...] | None) -> tuple[str, ...]:
    if currencies is None:
        return QUOTED_CURRENCY_CODES

    chosen: list[str] = []
    for code in currencies:
        code = code.upper()
        if code == BASE_CURRENCY:
            raise BusinessRuleError(
                f"{BASE_CURRENCY} is the base currency. Its rate against itself "
                f"is always 1 and is never fetched.",
                code="base_currency_rate",
                field="currency",
            )
        try:
            definition(code)
        except ValueError as exc:
            raise BusinessRuleError(
                str(exc), code="unknown_currency", field="currency"
            ) from exc
        if code not in chosen:
            chosen.append(code)
    return tuple(chosen)


def load_daily_closes(
    provider: RateProvider,
    start: date,
    end: date,
    currencies: tuple[str, ...] | None = None,
    *,
    variance_percent: Decimal = DEFAULT_VARIANCE_PERCENT,
    dry_run: bool = False,
) -> LoadOutcome:
    """Fetch each trading day's close in `start`..`end` and store it.

    `dry_run` fetches and reports without writing, which is how a range is
    checked against what is already stored before a backfill touches anything.
    """
    if start > end:
        raise BusinessRuleError(
            f"{start:%d %b %Y} is after {end:%d %b %Y}.",
            code="range_inverted",
            field="start",
        )

    chosen = _validated(currencies)

    # Fetched first, in full, before anything is written. A provider failing
    # halfway through the second pair would otherwise leave the first pair
    # loaded and the day incomplete.
    by_currency: dict[str, tuple[DailyClose, ...]] = {
        currency: provider.daily_closes(currency, start, end) for currency in chosen
    }

    manual = {
        currency: _manual_dates(currency, start, end) for currency in chosen
    }

    # Regrouped by date so that a day commits as a unit (§9.6).
    by_date: dict[date, list[DailyClose]] = defaultdict(list)
    for currency, closes in by_currency.items():
        for close in closes:
            if close.rate_date in manual[currency]:
                continue
            by_date[close.rate_date].append(close)

    written: dict[str, int] = {currency: 0 for currency in chosen}
    replaced: dict[str, int] = {currency: 0 for currency in chosen}
    advisories: list[Advisory] = []

    if not dry_run:
        for rate_date in sorted(by_date):
            with transaction.atomic():
                for close in sorted(by_date[rate_date], key=lambda item: item.currency):
                    result = record_rate(
                        close.currency,
                        close.rate_date,
                        close.close,
                        variance_percent=variance_percent,
                        source=RateSource.API,
                        provider=provider.name,
                    )
                    written[close.currency] += 1
                    if not result.created:
                        replaced[close.currency] += 1
                    advisories.extend(result.advisories)
    else:
        for rate_date, closes in by_date.items():
            for close in closes:
                written[close.currency] += 1

    per_currency = tuple(
        CurrencyOutcome(
            currency=currency,
            fetched=len(by_currency[currency]),
            written=written[currency],
            replaced=replaced[currency],
            kept_manual=sum(
                1 for close in by_currency[currency] if close.rate_date in manual[currency]
            ),
            first_date=by_currency[currency][0].rate_date if by_currency[currency] else None,
            last_date=by_currency[currency][-1].rate_date if by_currency[currency] else None,
        )
        for currency in chosen
    )

    outcome = LoadOutcome(
        provider=provider.name,
        start=start,
        end=end,
        dry_run=dry_run,
        per_currency=per_currency,
        advisories=tuple(advisories),
    )

    # Rate entries are financially significant events, which is what the
    # `financial_hub` logger is for (§9.2).
    logger.info(
        "%s daily closes from %s for %s to %s: %d written, %d manual rates kept, "
        "%d advisories%s",
        outcome.fetched,
        outcome.provider,
        f"{start:%Y-%m-%d}",
        f"{end:%Y-%m-%d}",
        outcome.written,
        outcome.kept_manual,
        len(outcome.advisories),
        " (dry run, nothing written)" if dry_run else "",
    )

    return outcome


def load_recent(
    provider: RateProvider,
    today: date,
    *,
    days: int = RECENT_WINDOW_DAYS,
    variance_percent: Decimal = DEFAULT_VARIANCE_PERCENT,
) -> LoadOutcome:
    """Every trading day's close in the `days` ending `today`, inclusive.

    The window is computed here rather than in the view so that "the last 365
    days" is one definition with one test, and so the endpoint stays what §5.2.2
    asks of it — authenticate, call one service, serialise.

    `today` is passed in rather than read here: what "today" means is a question
    about the configured timezone, and the caller is the layer that knows it.
    """
    return load_daily_closes(
        provider,
        today - timedelta(days=days - 1),
        today,
        variance_percent=variance_percent,
    )
