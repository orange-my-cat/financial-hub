"""Loading fetched rates — a top-up that defers to hand entry, or a replacement.

Fetching is `fx.services.providers`. Writing is `fx.services.entry.record_rate`.
This module is the rule between them, and there are two loads, chosen by the
caller:

**A top-up** — `truncate=False`, the backfill command's default. A rate the user
typed is never overwritten by a fetched one (BRD §4.3). That is the whole reason
`source` and `provider` were captured from day one (§13.4): without them a
loader could not tell a hand-typed rate from a fetched one, and a backfill would
quietly replace the figure a month was actually closed on — restating history
from a source the user had already chosen to override. Rows written by an earlier
fetch *are* replaced, so re-running a range is safe and idempotent.

**A replacement** — `truncate=True`, which is what the FX screen's button does.
Every rate stored in the window is cleared first and the provider's series is
loaded over the empty range, so what is stored afterwards is exactly what the
provider returned. This is a **deliberate departure from BRD §4.3**, made at the
Product Owner's instruction, and it has two consequences worth knowing before
pressing it: a hand-typed rate inside the window is replaced by the provider's
close for that date, and a hand-typed rate on a date the provider has no close
for — a month-end that fell on a weekend, most often — is removed and *not*
replaced, so any month closed on it re-reports on a rate carried from the
previous trading day. The clearing is a soft delete like every other delete in
this system (ADR-03), so those rows remain recoverable through the admin.

Nothing here is a second definition of anything. Rates land through the same
`record_rate` as hand entry, so they get the same validation, the same
create-or-replace on (currency, date), and the same rate-variance advisory — the
one thing that would catch a provider sending a decimal in the wrong place. The
advisories are collected and reported rather than shown one at a time; on daily
data a >10% move against the previous *trading day* is close to proof of a bad
figure, so they are worth surfacing even in a batch of thousands.

A date commits as a unit (§9.6). Both pairs for one day land together or neither
does, so an interrupted load never leaves a day translated on a mixture of
fetched and missing rates. A truncating load goes further and commits the whole
window at once — the clear and the load are one replacement, because a failure
between them would leave the range emptied rather than merely incomplete.
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
#: in running it and to fill a trend chart, and short enough that the request is
#: a few seconds rather than one the browser gives up on. Letting the client name
#: the span would eventually mean someone asking for a decade through a
#: synchronous endpoint — and, since the button replaces the window it loads,
#: naming a longer one would clear more history than the provider can refill.
RECENT_WINDOW_DAYS = 365


@dataclass(frozen=True)
class CurrencyOutcome:
    """What the load did to one pair."""

    currency: str
    fetched: int
    written: int
    replaced: int
    kept_manual: int
    #: Rates cleared from the window before loading. Zero unless truncating.
    removed: int
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
            "removed": self.removed,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "last_date": self.last_date.isoformat() if self.last_date else None,
        }


@dataclass(frozen=True)
class LoadOutcome:
    provider: str
    start: date
    end: date
    dry_run: bool
    #: Whether the window was cleared before loading.
    truncated: bool
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

    @property
    def removed(self) -> int:
        return sum(outcome.removed for outcome in self.per_currency)

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "dry_run": self.dry_run,
            "truncated": self.truncated,
            "fetched": self.fetched,
            "written": self.written,
            # Named in the payload rather than left to be inferred from the
            # difference: it is the only place BRD §4.3 is visible to whoever
            # pressed the button — and, on a truncating load, the only place
            # they see how many stored rates it cleared to get there.
            "kept_manual": self.kept_manual,
            "removed": self.removed,
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


def _stored_in_window(currency: str, start: date, end: date):
    """The live rows a truncating load will clear, for one pair.

    Every source, not only fetched ones: that is what makes it a replacement of
    the window rather than a top-up. Live rows only — an already-deleted rate
    is not stored in any sense the user would recognise, and clearing it again
    would move its deletion timestamp for no reason.
    """
    return ExchangeRate.objects.filter(
        currency=currency, rate_date__gte=start, rate_date__lte=end
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
    truncate: bool = False,
) -> LoadOutcome:
    """Fetch each trading day's close in `start`..`end` and store it.

    `truncate` clears every rate stored for the chosen pairs in the range before
    loading, so what is stored afterwards is exactly the provider's series —
    hand-typed rates included, and a hand-typed rate on a date the provider has
    no close for is simply gone. Off by default: a backfill over a decade must
    not be able to do that by omission.

    `dry_run` fetches and reports without writing or clearing, which is how a
    range is checked against what is already stored before anything is touched.
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

    # Nothing is kept when the window is being replaced, so nothing is asked.
    manual = {
        currency: set() if truncate else _manual_dates(currency, start, end)
        for currency in chosen
    }

    # Counted before the clear, and counted on a dry run too — "this would
    # remove 780 rates" is the sentence that stops a truncating load being
    # pressed by someone who meant a top-up.
    removed = {
        currency: (
            _stored_in_window(currency, start, end).count() if truncate else 0
        )
        for currency in chosen
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

    def _store(rate_date: date) -> None:
        """One date's closes, in currency order so a rerun writes identically."""
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

    if not dry_run:
        if truncate:
            # The whole window in one transaction. The clear and the load are a
            # single replacement: committing the delete separately would leave
            # the range empty if the load then failed, which is worse than
            # either outcome the caller asked for.
            with transaction.atomic():
                for currency in chosen:
                    # Soft, like every delete in this system. The rates are gone
                    # from every screen, report and calculation, and still
                    # recoverable through the admin (ADR-03).
                    _stored_in_window(currency, start, end).delete()
                for rate_date in sorted(by_date):
                    _store(rate_date)
        else:
            for rate_date in sorted(by_date):
                with transaction.atomic():
                    _store(rate_date)
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
            removed=removed[currency],
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
        truncated=truncate,
        per_currency=per_currency,
        advisories=tuple(advisories),
    )

    # Rate entries are financially significant events, which is what the
    # `financial_hub` logger is for (§9.2).
    logger.info(
        "%s daily closes from %s for %s to %s: %d written, %d stored rates "
        "cleared first, %d manual rates kept, %d advisories%s",
        outcome.fetched,
        outcome.provider,
        f"{start:%Y-%m-%d}",
        f"{end:%Y-%m-%d}",
        outcome.written,
        outcome.removed,
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
    truncate: bool = True,
) -> LoadOutcome:
    """Every trading day's close in the `days` ending `today`, inclusive.

    The screen's button. It **truncates**: the window is cleared and reloaded,
    so what is stored for the last year is exactly what the provider returned,
    and a rate typed by hand inside it does not survive. That is the whole
    difference between this and the backfill command, and it is why the window is
    a year and not a decade.

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
        truncate=truncate,
    )
