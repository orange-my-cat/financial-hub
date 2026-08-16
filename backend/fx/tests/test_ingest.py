"""Fetching daily closes, and the one rule that governs them.

Two things are being protected here, and neither is obvious from reading the
happy path.

**A typed rate is never overwritten by a fetched one** (BRD §4.3). It is the
only reason `source` was captured from day one, and the failure it prevents is
silent: a backfill restating the figure a month was actually closed on, from a
source the user had already looked at and overridden.

**A close never becomes a float.** The provider sends `0.70549` as a JSON
number, and `json.loads` would hand back a float — ADR-02's entire objection,
arriving through the one door that is not a form field. The assertion below
compares against an exact `Decimal` and checks the type, because
`Decimal(0.70549) != Decimal("0.70549")` is exactly the difference that would
otherwise go unnoticed for a decade.

The provider tests never reach the network. `urlopen` is replaced, so what is
under test is the reading of a real response shape rather than the provider's
availability.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from decimal import Decimal

import pytest

from core.currencies import QUOTED_CURRENCY_CODES
from core.services.advisories import AdvisoryKind
from core.services.exceptions import BusinessRuleError
from fx.models import ExchangeRate, RateSource
from fx.services.entry import record_rate
from fx.services.ingest import RECENT_WINDOW_DAYS, load_daily_closes, load_recent
from fx.services.providers import (
    DailyClose,
    MassiveProvider,
    RateProviderError,
    ticker_for,
)

MON = date(2026, 8, 10)
TUE = date(2026, 8, 11)
WED = date(2026, 8, 12)

#: 00:00 UTC on each of those days, which is how the provider stamps a bar.
MON_MS = 1_786_320_000_000
DAY_MS = 86_400_000


def _bar(offset_days: int, close: str) -> dict:
    return {
        "t": MON_MS + offset_days * DAY_MS,
        "o": 0.5,
        "h": 0.5,
        "l": 0.5,
        "c": close,
        "v": 1,
    }


def _payload(*bars: dict, status: str = "OK") -> str:
    """A response as it comes off the wire — closes as bare JSON numbers.

    The closes are written as strings here and spliced in unquoted, so the test
    exercises the same `parse_float` path the real provider does rather than a
    pre-made Decimal.
    """
    body = {"ticker": "C:AUDUSD", "status": status, "results": list(bars)}
    text = json.dumps(body)
    for bar in bars:
        text = text.replace(f'"c": "{bar["c"]}"', f'"c": {bar["c"]}')
    return text


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _serving(text: str, monkeypatch) -> list[urllib.request.Request]:
    """Replace `urlopen`, and hand back the requests it was given."""
    seen: list[urllib.request.Request] = []

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        seen.append(request)
        return _FakeResponse(text.encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def _provider() -> MassiveProvider:
    return MassiveProvider("test-key", base_url="https://example.invalid")


# ---------------------------------------------------------------------------
# Direction — the mapping that means no close is ever inverted
# ---------------------------------------------------------------------------


def test_the_ticker_is_the_stored_pair_and_so_needs_no_inversion():
    # AUD is quoted USD per 1 AUD and MYR is quoted MYR per 1 USD, so the two
    # tickers read in opposite directions. If either of these flipped, every
    # fetched rate for that pair would be the reciprocal of the truth and
    # nothing downstream would notice.
    assert ticker_for("AUD") == "C:AUDUSD"
    assert ticker_for("MYR") == "C:USDMYR"
    # Gold is USD per troy ounce, and `C:USDXAU` does not exist at the provider
    # — so a flipped convention here fails loudly rather than storing the
    # reciprocal of the gold price.
    assert ticker_for("XAU") == "C:XAUUSD"


def test_the_base_currency_has_no_ticker():
    with pytest.raises(ValueError):
        ticker_for("GBP")


# ---------------------------------------------------------------------------
# Reading a response
# ---------------------------------------------------------------------------


def test_a_close_is_read_as_an_exact_decimal_and_never_a_float(monkeypatch):
    _serving(_payload(_bar(0, "0.70549")), monkeypatch)

    closes = _provider().daily_closes("AUD", MON, MON)

    assert len(closes) == 1
    assert isinstance(closes[0].close, Decimal)
    assert closes[0].close == Decimal("0.70549")
    # The float route gives 0.7054899999999999575..., which compares unequal.
    assert closes[0].close != Decimal(0.70549)


def test_the_providers_own_float_noise_is_rounded_once_here(monkeypatch):
    """`4371.2699999999995` is what gold's close for 11 Aug 2026 actually is on
    the wire — the provider does its arithmetic in binary floating point and
    lets the result out. Thirteen decimals do not fit NUMERIC(19,10), so
    something rounds; ADR-02 says it happens once, half-up, somewhere a person
    can point at, rather than implicitly in Postgres on the way into the column.
    """
    _serving(_payload(_bar(0, "4371.2699999999995")), monkeypatch)

    closes = _provider().daily_closes("XAU", MON, MON)

    assert closes[0].close == Decimal("4371.2700000000")
    assert closes[0].close.as_tuple().exponent == -10


def test_a_bar_lands_on_the_calendar_day_it_is_stamped_for(monkeypatch):
    _serving(_payload(_bar(0, "0.70549"), _bar(1, "0.70635")), monkeypatch)

    closes = _provider().daily_closes("AUD", MON, TUE)

    assert [close.rate_date for close in closes] == [MON, TUE]


def test_the_partial_sunday_bar_is_dropped(monkeypatch):
    # The FX week opens Sunday evening UTC, so a two-hour Sunday session comes
    # back looking like any other bar. Its close is not a daily close.
    sunday = _bar(-1, "4.0878")  # 9 Aug 2026
    _serving(_payload(sunday, _bar(0, "4.0890"), _bar(1, "4.0900")), monkeypatch)

    closes = _provider().daily_closes("MYR", date(2026, 8, 9), TUE)

    assert [close.rate_date for close in closes] == [MON, TUE]
    assert all(close.rate_date.weekday() < 5 for close in closes)


def test_closes_are_returned_in_date_order_whatever_the_response_order(monkeypatch):
    _serving(_payload(_bar(2, "0.70835"), _bar(0, "0.70549"), _bar(1, "0.70635")), monkeypatch)

    closes = _provider().daily_closes("AUD", MON, WED)

    assert [close.rate_date for close in closes] == [MON, TUE, WED]


def test_the_key_travels_in_a_header_and_not_the_query_string(monkeypatch):
    seen = _serving(_payload(_bar(0, "0.70549")), monkeypatch)

    _provider().daily_closes("AUD", MON, MON)

    request = seen[0]
    assert request.get_header("Authorization") == "Bearer test-key"
    assert "test-key" not in request.full_url


def test_a_rejected_key_is_reported_without_repeating_the_key(monkeypatch):
    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, None
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RateProviderError) as exc:
        _provider().daily_closes("AUD", MON, MON)

    assert "401" in str(exc.value)
    assert "test-key" not in str(exc.value)


def test_a_provider_error_status_is_not_read_as_an_empty_history(monkeypatch):
    # The failure this prevents: a 200 carrying `NOT_AUTHORIZED` and no results
    # would otherwise look identical to "this pair did not trade", and the
    # command would report a clean run that stored nothing.
    _serving(_payload(status="NOT_AUTHORIZED"), monkeypatch)

    with pytest.raises(RateProviderError):
        _provider().daily_closes("AUD", MON, MON)


def test_a_missing_key_says_so_before_any_request_is_made():
    with pytest.raises(RateProviderError) as exc:
        MassiveProvider("")

    assert "MASSIVE_API_KEY" in str(exc.value)


def test_a_zero_or_negative_close_is_refused(monkeypatch):
    _serving(_payload(_bar(0, "0")), monkeypatch)

    with pytest.raises(RateProviderError):
        _provider().daily_closes("AUD", MON, MON)


# ---------------------------------------------------------------------------
# Storing what was fetched
# ---------------------------------------------------------------------------


class FakeProvider:
    """A provider with a fixed answer, so the rules can be tested without HTTP."""

    name = "fake"

    def __init__(self, closes: dict[str, list[tuple[date, str]]]) -> None:
        self._closes = closes

    def daily_closes(self, currency, start, end):
        return tuple(
            DailyClose(currency=currency, rate_date=day, close=Decimal(value))
            for day, value in self._closes.get(currency, [])
            if start <= day <= end
        )


def _fake(**closes: list[tuple[date, str]]) -> FakeProvider:
    return FakeProvider(dict(closes))


@pytest.mark.django_db
def test_fetched_rates_are_stored_with_their_provenance():
    outcome = load_daily_closes(
        _fake(AUD=[(MON, "0.70549"), (TUE, "0.70635")], MYR=[(MON, "4.0890")]),
        MON,
        TUE,
    )

    assert outcome.written == 3
    stored = ExchangeRate.objects.get(currency="AUD", rate_date=MON)
    assert stored.rate == Decimal("0.70549")
    # Without these two fields a later run could not tell this row from a typed
    # one, and the rule below would have nothing to stand on (§13.4).
    assert stored.source == RateSource.API
    assert stored.provider == "fake"


@pytest.mark.django_db
def test_a_hand_typed_rate_is_never_overwritten_by_a_fetched_one():
    record_rate("AUD", MON, Decimal("0.66"))

    outcome = load_daily_closes(
        _fake(AUD=[(MON, "0.70549"), (TUE, "0.70635")]), MON, TUE
    )

    kept = ExchangeRate.objects.get(currency="AUD", rate_date=MON)
    assert kept.rate == Decimal("0.66")
    assert kept.source == RateSource.ENTERED
    assert outcome.kept_manual == 1
    assert outcome.written == 1
    assert outcome.per_currency[0].kept_manual == 1


@pytest.mark.django_db
def test_a_previously_fetched_rate_is_replaced_so_a_range_can_be_rerun():
    first = load_daily_closes(_fake(AUD=[(MON, "0.70549")]), MON, MON)
    assert first.written == 1

    outcome = load_daily_closes(_fake(AUD=[(MON, "0.70600")]), MON, MON)

    assert ExchangeRate.objects.filter(currency="AUD", rate_date=MON).count() == 1
    assert ExchangeRate.objects.get(currency="AUD", rate_date=MON).rate == Decimal("0.70600")
    assert outcome.per_currency[0].replaced == 1


@pytest.mark.django_db
def test_a_soft_deleted_manual_rate_does_not_veto_a_fetch():
    record_rate("AUD", MON, Decimal("0.66")).rate.delete()

    load_daily_closes(_fake(AUD=[(MON, "0.70549")]), MON, MON)

    live = ExchangeRate.objects.get(currency="AUD", rate_date=MON)
    assert live.rate == Decimal("0.70549")
    assert live.source == RateSource.API


@pytest.mark.django_db
def test_a_dry_run_reports_what_it_would_do_and_writes_nothing():
    record_rate("AUD", MON, Decimal("0.66"))

    outcome = load_daily_closes(
        _fake(AUD=[(MON, "0.70549"), (TUE, "0.70635")]), MON, TUE, dry_run=True
    )

    assert outcome.dry_run is True
    assert outcome.written == 1
    assert outcome.kept_manual == 1
    assert ExchangeRate.objects.filter(currency="AUD", rate_date=TUE).count() == 0
    assert ExchangeRate.objects.get(currency="AUD", rate_date=MON).rate == Decimal("0.66")


@pytest.mark.django_db
def test_the_variance_advisory_is_collected_and_never_blocks():
    # A tenfold jump is what a misplaced decimal from a provider looks like.
    outcome = load_daily_closes(
        _fake(AUD=[(MON, "0.70549"), (TUE, "7.0635")]), MON, TUE
    )

    assert outcome.written == 2
    assert ExchangeRate.objects.get(currency="AUD", rate_date=TUE).rate == Decimal("7.0635")
    assert [advisory.kind for advisory in outcome.advisories] == [
        AdvisoryKind.RATE_VARIANCE
    ]


@pytest.mark.django_db
def test_the_base_currency_is_never_fetched():
    with pytest.raises(BusinessRuleError) as exc:
        load_daily_closes(_fake(), MON, TUE, ("USD",))

    assert exc.value.code == "base_currency_rate"


@pytest.mark.django_db
def test_an_inverted_range_is_refused():
    with pytest.raises(BusinessRuleError) as exc:
        load_daily_closes(_fake(), TUE, MON)

    assert exc.value.code == "range_inverted"


@pytest.mark.django_db
def test_every_quoted_currency_is_loaded_when_none_is_named():
    outcome = load_daily_closes(
        _fake(AUD=[(MON, "0.70549")], MYR=[(MON, "4.0890")], XAU=[(MON, "4402.01")]),
        MON,
        MON,
    )

    # From the registry, so adding a currency does not quietly stop being loaded
    # by default (AS-05).
    assert {pair.currency for pair in outcome.per_currency} == set(QUOTED_CURRENCY_CODES)
    assert outcome.written == 3


# ---------------------------------------------------------------------------
# The last-365-days window, and the endpoint behind the button
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_recent_window_is_a_year_ending_today_inclusive():
    provider = _fake(AUD=[(MON, "0.70549")])

    outcome = load_recent(provider, TUE)

    assert outcome.end == TUE
    # Inclusive at both ends: 365 days ending today is today minus 364.
    assert outcome.start == TUE - timedelta(days=364)
    assert (outcome.end - outcome.start).days + 1 == RECENT_WINDOW_DAYS


@pytest.mark.django_db
def test_the_outcome_serialises_for_the_screen():
    outcome = load_daily_closes(
        _fake(AUD=[(MON, "0.70549"), (TUE, "0.70635")], MYR=[(MON, "4.0890")]), MON, TUE
    )

    body = outcome.as_dict()

    assert body["provider"] == "fake"
    assert body["written"] == 3
    assert body["kept_manual"] == 0
    aud = next(pair for pair in body["pairs"] if pair["currency"] == "AUD")
    assert aud["pair"] == "AUD/USD"
    assert aud["first_date"] == MON.isoformat()
    assert aud["last_date"] == TUE.isoformat()
