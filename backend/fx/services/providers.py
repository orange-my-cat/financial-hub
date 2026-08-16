"""Fetching rates from outside — the second implementation of the ingestion seam.

ADR-08 kept rate ingestion behind a single interface with one manual v1
implementation, precisely so that this file could be *added* rather than
retrofitted. Nothing above it changes: rows still land through
`fx.services.entry.record_rate`, still carry a source and a provider, and are
still one-per-pair-per-date in the database.

**Only the daily close is read.** The provider also serves open, high, low,
volume, live quotes and tick data; none of it is fetched, and none of it has
anywhere to go. This system stores one rate per pair per date, so a bar
contributes exactly one number — `c` — and the rest is noise that would invite
someone to store a second, disagreeing figure later.

**The ticker direction is the stored convention, and that is not a coincidence
worth relying on silently.** `core.currencies` fixes AUD as *USD per 1 AUD* and
MYR as *MYR per 1 USD*; the provider's tickers for those quotes are `C:AUDUSD`
and `C:USDMYR`. So the ticker is `pair_label` with the slash removed, and the
close comes back already in the convention the column stores. No inversion
happens anywhere in this file — if it ever needs to, the mapping below is wrong
rather than the arithmetic.

**Closes are parsed as Decimal, never through float.** The wire format is a JSON
number, and `json.loads` would make `4.0831` a float — which is ADR-02's whole
objection, arriving through the one door nobody was watching. `parse_float` is
what closes it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol

from core.currencies import definition, pair_label, quantize_rate

#: The provider's own maximum for one aggregates request. A ten-year daily range
#: is ~2,600 bars per pair, so one request covers any span this system will ask
#: for — but a truncated response would look exactly like a short history, so
#: hitting this is an error rather than a page boundary to follow.
MAX_BARS_PER_REQUEST = 50_000

DEFAULT_BASE_URL = "https://api.massive.com"
DEFAULT_TIMEOUT_SECONDS = 30


class RateProviderError(RuntimeError):
    """The provider could not be reached, or did not answer with rates.

    Deliberately not a `BusinessRuleError`: nothing about the user's request was
    invalid. This is an outage, a bad key or a changed contract, and the command
    that catches it should say so rather than render it as a rejected entry.
    """


@dataclass(frozen=True)
class DailyClose:
    """One trading day's closing rate for one pair, in market convention."""

    currency: str
    rate_date: date
    close: Decimal


class RateProvider(Protocol):
    """The ingestion seam. One method, because one number is wanted."""

    #: Recorded on every row this provider's rates produce, so a re-fetch and
    #: "which provider said that" both stay answerable (§13.4).
    name: str

    def daily_closes(
        self, currency: str, start: date, end: date
    ) -> tuple[DailyClose, ...]:
        """Closing rates for every trading day in `start`..`end`, inclusive."""
        ...


def _as_decimal(value: object, *, field: str) -> Decimal:
    """Whatever the wire gave us, as an exact Decimal — or an error.

    `parse_float=Decimal` covers `4.0831`, but a close that happens to be a whole
    number arrives as an `int`, and a provider that switches to quoted strings
    would arrive as `str`. All three are exact; a `float` never reaches here, and
    if one somehow did it would be a defect rather than a value to salvage.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except ArithmeticError:
            pass
    raise RateProviderError(
        f"The provider returned {value!r} for {field}, which is not an exact "
        f"number this system can store."
    )


def _bar_date(milliseconds: object) -> date:
    """The calendar day a bar belongs to.

    Bars are stamped at 00:00 UTC of their own trading day, so the mapping is the
    UTC date and nothing more. Reading it in the configured timezone instead
    would shift every bar in the file forward by eight hours and, for the first
    of a month, into the wrong month — which is the sort of error that misstates
    a close and leaves no trace (BR-24).
    """
    if not isinstance(milliseconds, int) or isinstance(milliseconds, bool):
        raise RateProviderError(
            f"The provider returned {milliseconds!r} as a bar timestamp."
        )
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).date()


def ticker_for(currency: str) -> str:
    """`AUD` → `C:AUDUSD`, `MYR` → `C:USDMYR`.

    See the module docstring: this is `pair_label` with the slash removed, which
    is what makes the returned close need no inversion.
    """
    definition(currency)
    return "C:" + pair_label(currency).replace("/", "")


class MassiveProvider:
    """Daily closes from Massive's forex aggregates endpoint.

    `urllib` rather than `requests` or `httpx`: quality attribute 4 is "runs
    untouched for years", and two GET requests a year do not justify a
    dependency that can be abandoned or need a security patch. The smoke test
    already reaches HTTP the same way.
    """

    name = "massive"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key:
            raise RateProviderError(
                "MASSIVE_API_KEY is not set. Add it to .env — it is documented "
                "in .env.example — or run with --dry-run against a fixture."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def daily_closes(
        self, currency: str, start: date, end: date
    ) -> tuple[DailyClose, ...]:
        if start > end:
            raise RateProviderError(
                f"{start:%d %b %Y} is after {end:%d %b %Y}; nothing to fetch."
            )

        payload = self._get(
            f"/v2/aggs/ticker/{ticker_for(currency)}/range/1/day"
            f"/{start:%Y-%m-%d}/{end:%Y-%m-%d}"
            f"?sort=asc&limit={MAX_BARS_PER_REQUEST}"
        )
        return self._closes_from(currency, payload)

    # -- the wire ----------------------------------------------------------
    def _get(self, path: str) -> dict:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            headers={
                # The key travels in a header, not the query string, so it stays
                # out of proxy and server access logs.
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # Never interpolate the key into a message. The status is the
            # diagnostic; 401 and 403 get named because they are the two a
            # reader would otherwise go looking for the key to explain.
            hint = {
                401: " — the API key was rejected",
                403: " — the API key is not entitled to this data",
                429: " — the provider's rate limit was hit; try again shortly",
            }.get(exc.code, "")
            raise RateProviderError(
                f"The rate provider answered {exc.code}{hint}."
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise RateProviderError(f"The rate provider is unreachable: {exc}") from exc

        try:
            # The load-bearing argument. See the module docstring.
            payload = json.loads(body, parse_float=Decimal)
        except ValueError as exc:
            raise RateProviderError(
                "The rate provider did not answer with JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise RateProviderError("The rate provider did not answer with an object.")

        status = payload.get("status", "")
        # `OK` and `DELAYED` both carry real bars; `DELAYED` only means the
        # entitlement is the delayed feed, which for a month-end close read days
        # later is no difference at all.
        if status not in {"OK", "DELAYED"}:
            message = payload.get("message") or payload.get("error") or status
            raise RateProviderError(f"The rate provider answered '{message}'.")
        return payload

    # -- the reading -------------------------------------------------------
    def _closes_from(self, currency: str, payload: dict) -> tuple[DailyClose, ...]:
        results = payload.get("results") or []
        if not isinstance(results, list):
            raise RateProviderError("The rate provider's `results` was not a list.")

        if len(results) >= MAX_BARS_PER_REQUEST:
            raise RateProviderError(
                f"The provider returned {len(results)} bars, its per-request "
                f"maximum, so the range was silently truncated. Load it in "
                f"shorter spans."
            )

        closes: list[DailyClose] = []
        for bar in results:
            if not isinstance(bar, dict):
                raise RateProviderError("The rate provider returned a malformed bar.")

            bar_date = _bar_date(bar.get("t"))

            # The FX week opens on Sunday evening UTC, so the provider emits a
            # two-hour Sunday bar whose "close" is a thin partial session — a
            # number that would sit in the table looking exactly like Monday's
            # and translate a Sunday-dated balance slightly wrong. Weekend bars
            # are dropped rather than stored and explained later.
            if bar_date.weekday() >= 5:
                continue

            # Quantised here, and this is not belt-and-braces. The provider does
            # its own arithmetic in binary floating point and lets the result
            # reach the wire: gold's close for 11 Aug 2026 arrives literally as
            # `4371.2699999999995`. Thirteen decimal places do not fit
            # NUMERIC(19,10), so *something* rounds — and left alone that
            # something is Postgres, silently, on the way into the column.
            # ADR-02 says rounded once, half-up, in a place you can point at.
            close = quantize_rate(_as_decimal(bar.get("c"), field=f"the close on {bar_date}"))
            if close <= 0:
                raise RateProviderError(
                    f"The provider returned a close of {close} for "
                    f"{pair_label(currency)} on {bar_date:%d %b %Y}."
                )
            closes.append(DailyClose(currency=currency, rate_date=bar_date, close=close))

        # Sorted here rather than trusted from `sort=asc`, because everything
        # downstream reads in date order and one out-of-order bar would make the
        # variance advisory compare against the wrong predecessor.
        closes.sort(key=lambda item: item.rate_date)
        return tuple(closes)
