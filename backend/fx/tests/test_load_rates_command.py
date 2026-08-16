"""The one entry point a person actually types.

Thin by design (§5.2.2) — it parses two dates, builds the provider and calls one
service — so what is tested here is only the thin part: that `--to` defaults to
today rather than to nothing, that a provider outage reads as an outage rather
than as a rejected request, and that the count of hand-typed rates it left alone
is actually printed. That last one is the only place BRD §4.3 is visible to the
user, and a rule nobody can see is a rule nobody trusts.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from fx.models import ExchangeRate, RateSource
from fx.services.entry import record_rate
from fx.services.providers import DailyClose, RateProviderError

MON = date(2026, 8, 10)
TUE = date(2026, 8, 11)


class _StubProvider:
    name = "massive"
    #: Set by each test; the last range the command asked for.
    asked: tuple[date, date] | None = None

    def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
        pass

    def daily_closes(self, currency, start, end):
        type(self).asked = (start, end)
        if currency != "AUD":
            return ()
        return tuple(
            DailyClose(currency="AUD", rate_date=day, close=Decimal(value))
            for day, value in ((MON, "0.70549"), (TUE, "0.70635"))
            if start <= day <= end
        )


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(
        "fx.management.commands.load_rates.MassiveProvider", _StubProvider
    )
    _StubProvider.asked = None
    return _StubProvider


@pytest.mark.django_db
def test_it_loads_a_range_and_reports_what_it_stored(stub):
    out = StringIO()

    call_command("load_rates", "--from", "2026-08-10", "--to", "2026-08-11", stdout=out)

    assert ExchangeRate.objects.filter(source=RateSource.API).count() == 2
    assert ExchangeRate.objects.get(currency="AUD", rate_date=MON).provider == "massive"
    assert "2 rates stored" in out.getvalue()


@pytest.mark.django_db
def test_the_end_of_the_range_defaults_to_today(stub):
    call_command("load_rates", "--from", "2026-08-10", stdout=StringIO())

    assert stub.asked is not None
    # `localdate`, so "today" is the configured timezone's today and not UTC's.
    assert stub.asked[1] == timezone.localdate()


@pytest.mark.django_db
def test_it_says_how_many_typed_rates_it_left_alone(stub):
    record_rate("AUD", MON, Decimal("0.66"))
    out = StringIO()

    call_command("load_rates", "--from", "2026-08-10", "--to", "2026-08-11", stdout=out)

    assert "left as typed by hand" in out.getvalue()
    assert ExchangeRate.objects.get(currency="AUD", rate_date=MON).rate == Decimal("0.66")


@pytest.mark.django_db
def test_a_dry_run_saves_nothing(stub):
    out = StringIO()

    call_command(
        "load_rates", "--from", "2026-08-10", "--to", "2026-08-11", "--dry-run", stdout=out
    )

    assert ExchangeRate.objects.count() == 0
    assert "Nothing was saved." in out.getvalue()


@pytest.mark.django_db
def test_one_pair_can_be_loaded_on_its_own(stub):
    call_command(
        "load_rates", "--from", "2026-08-10", "--to", "2026-08-11",
        "--currency", "MYR", stdout=StringIO(),
    )

    assert ExchangeRate.objects.count() == 0


@pytest.mark.django_db
def test_a_malformed_date_is_refused_before_anything_is_fetched(stub):
    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        call_command("load_rates", "--from", "10 Aug 2026", stdout=StringIO())

    assert stub.asked is None


@pytest.mark.django_db
def test_a_provider_outage_is_reported_as_an_outage(monkeypatch):
    class _Broken(_StubProvider):
        def daily_closes(self, currency, start, end):
            raise RateProviderError("The rate provider is unreachable: timed out")

    monkeypatch.setattr("fx.management.commands.load_rates.MassiveProvider", _Broken)

    with pytest.raises(CommandError, match="unreachable"):
        call_command("load_rates", "--from", "2026-08-10", stdout=StringIO())

    assert ExchangeRate.objects.count() == 0


@pytest.mark.django_db
def test_the_base_currency_is_refused(stub):
    with pytest.raises(CommandError, match="base currency"):
        call_command("load_rates", "--from", "2026-08-10", "--currency", "USD", stdout=StringIO())
