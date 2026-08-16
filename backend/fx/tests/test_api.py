"""The FX endpoints.

Views are thin, so these tests are about wiring and shape: that every endpoint
is closed by default, that rates cross as strings, that an advisory arrives
beside a *successful* response rather than as an error, and that bulk entry is
genuinely atomic over HTTP and not only in the service.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.currencies import QUOTED_CURRENCY_CODES
from fx.models import ExchangeRate

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in(client, django_user_model):
    user = django_user_model.objects.create_user(username="owner", password="pw-long-enough")
    client.force_login(user)
    return client


def rate(currency: str, on: str, value: str) -> None:
    from datetime import date

    ExchangeRate.objects.create(
        currency=currency, rate_date=date.fromisoformat(on), rate=Decimal(value)
    )


# ---------------------------------------------------------------------------
# Closed by default
# ---------------------------------------------------------------------------


READ_ENDPOINTS = [
    "/api/fx/currencies/",
    "/api/fx/rates/?start=2026-01-01&end=2026-12-31",
    "/api/fx/status/",
    "/api/fx/trend/?from_currency=AUD&to_currency=USD&start=2026-01-01&end=2026-12-31",
    "/api/settings/",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_every_fx_endpoint_requires_a_session(client, path):
    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_every_read_endpoint_wraps_its_payload_in_data(signed_in, path):
    """One envelope, from every read endpoint.

    Written after `/fx/currencies/` shipped unwrapped and reached the browser as
    a blank screen — TanStack Query throws when a query function resolves to
    undefined, and `response.data` is undefined when there is no `data` key. The
    endpoint's own test had asserted the unwrapped shape, so it passed while
    encoding the inconsistency. A shape convention that only some endpoints
    follow is not a convention.
    """
    body = signed_in.get(path).json()

    assert "data" in body, f"{path} does not wrap its payload in `data`"
    assert body["data"] is not None


# ---------------------------------------------------------------------------
# The currency registry
# ---------------------------------------------------------------------------


def test_the_registry_states_each_pair_and_its_direction(signed_in):
    body = signed_in.get("/api/fx/currencies/").json()["data"]

    assert body["base"] == "USD"
    assert body["quoted"] == list(QUOTED_CURRENCY_CODES)
    by_code = {c["code"]: c for c in body["currencies"]}
    assert by_code["AUD"]["quote_label"] == "USD per 1 AUD"
    assert by_code["AUD"]["pair"] == "AUD/USD"
    assert by_code["MYR"]["quote_label"] == "MYR per 1 USD"
    assert by_code["MYR"]["pair"] == "USD/MYR"
    # Gold, quoted the only way the market and the provider quote it. Stated
    # here explicitly rather than derived, because a direction that flips
    # silently is the failure this endpoint exists to prevent.
    assert by_code["XAU"]["quote_label"] == "USD per 1 XAU"
    assert by_code["XAU"]["pair"] == "XAU/USD"
    assert by_code["USD"]["is_base"] is True


def test_the_registry_says_which_currencies_net_worth_may_be_stated_in(signed_in):
    """Served, so the Settings screen does not decide it for itself."""
    body = signed_in.get("/api/fx/currencies/").json()["data"]

    assert "XAU" not in body["reporting"]
    assert body["reporting"] == ["USD", "AUD", "MYR"]
    by_code = {c["code"]: c for c in body["currencies"]}
    assert by_code["XAU"]["can_report"] is False
    assert by_code["AUD"]["can_report"] is True


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def test_recording_a_rate(signed_in):
    response = signed_in.post(
        "/api/fx/rates/",
        data={"currency": "AUD", "rate_date": "2026-01-31", "rate": "0.66"},
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["pair"] == "AUD/USD"
    # A string, never a JSON number.
    assert isinstance(body["data"]["rate"], str)
    assert body["advisories"] == []


def test_a_rate_variance_advisory_arrives_with_a_successful_save(signed_in):
    """Advisories never block. The 200 and the saved row are the point."""
    rate("AUD", "2026-01-31", "0.66")

    response = signed_in.post(
        "/api/fx/rates/",
        data={"currency": "AUD", "rate_date": "2026-02-28", "rate": "0.99"},
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["advisories"][0]["kind"] == "rate_variance"
    assert body["advisories"][0]["detail"]["difference_percent"] == "+50.00"
    assert ExchangeRate.objects.count() == 2


def test_the_base_currency_is_refused_as_a_field_error(signed_in):
    response = signed_in.post(
        "/api/fx/rates/",
        data={"currency": "USD", "rate_date": "2026-01-31", "rate": "1"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "currency" in response.json()["error"]["field_errors"]


def test_a_negative_rate_is_refused_by_the_serializer(signed_in):
    response = signed_in.post(
        "/api/fx/rates/",
        data={"currency": "AUD", "rate_date": "2026-01-31", "rate": "-1"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "rate" in response.json()["error"]["field_errors"]


# ---------------------------------------------------------------------------
# Bulk entry
# ---------------------------------------------------------------------------


def test_bulk_entry_saves_every_pair(signed_in):
    response = signed_in.post(
        "/api/fx/rates/bulk/",
        data={"rate_date": "2026-01-31", "rates": {"AUD": "0.66", "MYR": "4.20"}},
        content_type="application/json",
    )

    assert response.status_code == 201
    assert len(response.json()["data"]["saved"]) == 2
    assert ExchangeRate.objects.count() == 2


def test_bulk_entry_is_atomic_over_http(signed_in):
    response = signed_in.post(
        "/api/fx/rates/bulk/",
        data={"rate_date": "2026-01-31", "rates": {"AUD": "0.66", "GBP": "1.25"}},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert ExchangeRate.objects.count() == 0


def test_bulk_entry_of_nothing_is_refused(signed_in):
    response = signed_in.post(
        "/api/fx/rates/bulk/",
        data={"rate_date": "2026-01-31", "rates": {}},
        content_type="application/json",
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# The daily table
# ---------------------------------------------------------------------------


def test_the_daily_table_marks_carried_rates(signed_in):
    rate("AUD", "2026-01-31", "0.66")
    rate("MYR", "2026-01-31", "4.20")
    rate("AUD", "2026-02-28", "0.67")

    body = signed_in.get("/api/fx/rates/?start=2026-01-01&end=2026-03-31").json()

    february = next(row for row in body["data"] if row["date"] == "2026-02-28")
    entries = {e["currency"]: e for e in february["entries"]}
    assert entries["AUD"]["provenance"] == "exact"
    assert entries["AUD"]["recorded"] is True
    # MYR was not entered in February, so a translation that month would carry
    # January's — which the table says rather than leaving blank.
    assert entries["MYR"]["provenance"] == "carried"
    assert entries["MYR"]["recorded"] is False
    assert entries["MYR"]["as_at"] == "2026-01-31"


def test_the_daily_table_trims_stored_padding(signed_in):
    rate("AUD", "2026-01-31", "0.66")

    body = signed_in.get("/api/fx/rates/?start=2026-01-01&end=2026-03-31").json()

    assert body["data"][0]["entries"][0]["rate"] == "0.66"


def test_a_reversed_range_is_a_field_error(signed_in):
    response = signed_in.get("/api/fx/rates/?start=2026-12-31&end=2026-01-01")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Trend and status
# ---------------------------------------------------------------------------


def test_the_trend_labels_triangulated_points_as_derived(signed_in):
    rate("AUD", "2026-01-31", "0.66")
    rate("MYR", "2026-01-31", "4.20")

    body = signed_in.get(
        "/api/fx/trend/?from_currency=AUD&to_currency=MYR&start=2026-01-01&end=2026-12-31"
    ).json()

    assert body["data"]["derived"] is True
    assert body["data"]["points"][0]["provenance"] == "triangulated"
    assert body["data"]["points"][0]["rate"] == "2.772000"


def test_an_unknown_currency_in_the_trend_is_refused(signed_in):
    response = signed_in.get(
        "/api/fx/trend/?from_currency=GBP&to_currency=USD&start=2026-01-01&end=2026-12-31"
    )

    assert response.status_code in (400, 500)


def test_the_status_summary_lists_every_pair(signed_in):
    rate("AUD", "2026-01-31", "0.66")

    body = signed_in.get("/api/fx/status/?as_of=2026-01-31").json()

    pairs = {p["currency"]: p for p in body["data"]["pairs"]}
    assert pairs["AUD"]["state"] == "Current"
    assert pairs["MYR"]["missing"] is True
    assert body["data"]["staleness_days"] == 7


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def test_deleting_a_rate_is_soft(signed_in):
    rate("AUD", "2026-01-31", "0.66")

    response = signed_in.delete("/api/fx/rates/AUD/2026-01-31/")

    assert response.status_code == 204
    assert ExchangeRate.objects.count() == 0
    assert ExchangeRate.all_objects.count() == 1


def test_deleting_a_rate_that_is_not_there_is_a_404_shaped_error(signed_in):
    response = signed_in.delete("/api/fx/rates/AUD/2026-01-31/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "rate_not_found"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_are_created_with_their_defaults_on_first_read(signed_in):
    body = signed_in.get("/api/settings/").json()

    assert body["data"]["default_currency"] == "USD"
    assert body["data"]["rate_staleness_days"] == 7
    # Trimmed, so it reads identically before and after a database round-trip.
    assert body["data"]["rate_variance_percent"] == "10"
    assert body["data"]["timezone"] == "Asia/Kuala_Lumpur"


def test_changing_the_staleness_threshold_takes_effect_without_a_deploy(signed_in):
    signed_in.patch(
        "/api/settings/",
        data={"rate_staleness_days": 30},
        content_type="application/json",
    )

    body = signed_in.get("/api/fx/status/").json()
    assert body["data"]["staleness_days"] == 30


def test_changing_the_default_currency_rewrites_no_stored_data(signed_in):
    rate("AUD", "2026-01-31", "0.66")
    before = ExchangeRate.objects.get(currency="AUD").rate

    signed_in.patch(
        "/api/settings/",
        data={"default_currency": "AUD"},
        content_type="application/json",
    )

    assert ExchangeRate.objects.get(currency="AUD").rate == before
    assert signed_in.get("/api/settings/").json()["data"]["default_currency"] == "AUD"


def test_gold_is_a_currency_but_not_one_net_worth_can_be_stated_in(signed_in):
    """XAU denominates a balance and does not report.

    A distinct refusal from the unknown-code one below: XAU *is* a currency this
    system knows, holds rates for and will translate — it simply is not a unit
    net worth is stated in. The endpoint has to tell those two apart, or the
    error sends the reader looking for a typo that is not there.
    """
    response = signed_in.patch(
        "/api/settings/",
        data={"default_currency": "XAU"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert signed_in.get("/api/settings/").json()["data"]["default_currency"] == "USD"


def test_an_unknown_default_currency_is_refused(signed_in):
    response = signed_in.patch(
        "/api/settings/",
        data={"default_currency": "GBP"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "default_currency" in response.json()["error"]["field_errors"]


def test_a_rate_posted_against_a_basis_is_refused_rather_than_misread(signed_in):
    """The re-based form is gone, and its absence must not be silent.

    DRF drops unknown fields, so without the guard this request would store
    1.5152 as `USD per 1 AUD` — a rate wrong by a factor of five, misstating
    every AUD balance for that month with nothing else to catch it.
    """
    response = signed_in.post(
        "/api/fx/rates/",
        data={
            "currency": "AUD",
            "basis": "USD",
            "rate_date": "2026-01-31",
            "rate": "1.5151515152",
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "basis" in response.json()["error"]["field_errors"]
    assert not ExchangeRate.objects.filter(currency="AUD").exists()


# ---------------------------------------------------------------------------
# Loading from the provider — the FX screen's button
# ---------------------------------------------------------------------------


class _StubProvider:
    """Stands in for Massive. No test in this file reaches the network."""

    name = "massive"
    asked: tuple = ()

    def __init__(self, *args, **kwargs) -> None:  # noqa: ARG002
        pass

    def daily_closes(self, currency, start, end):
        from datetime import date as _date
        from decimal import Decimal as _Decimal

        from fx.services.providers import DailyClose

        type(self).asked = (start, end)
        if currency != "AUD":
            return ()
        return (
            DailyClose(currency="AUD", rate_date=_date(2026, 8, 14), close=_Decimal("0.70835")),
        )


@pytest.fixture
def stub_provider(monkeypatch):
    monkeypatch.setattr("fx.api.views.MassiveProvider", _StubProvider)
    _StubProvider.asked = ()
    return _StubProvider


def test_loading_from_the_provider_stores_rates_and_reports_what_it_did(
    signed_in, stub_provider
):
    response = signed_in.post("/api/fx/rates/load/")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["provider"] == "massive"
    assert body["written"] == 1
    assert body["kept_manual"] == 0
    stored = ExchangeRate.objects.get(currency="AUD")
    assert stored.rate == Decimal("0.70835")
    assert stored.source == "api"


def test_the_button_loads_a_year_ending_today(signed_in, stub_provider):
    from django.utils import timezone

    from fx.services.ingest import RECENT_WINDOW_DAYS

    signed_in.post("/api/fx/rates/load/")

    start, end = stub_provider.asked
    assert end == timezone.localdate()
    assert (end - start).days + 1 == RECENT_WINDOW_DAYS


def test_loading_never_overwrites_a_rate_that_was_typed(signed_in, stub_provider):
    """BRD §4.3, over HTTP. The count is what the screen shows for it."""
    rate("AUD", "2026-08-14", "0.66")

    body = signed_in.post("/api/fx/rates/load/").json()["data"]

    assert body["kept_manual"] == 1
    assert body["written"] == 0
    assert ExchangeRate.objects.get(currency="AUD").rate == Decimal("0.66")


def test_a_provider_outage_is_an_error_banner_and_saves_nothing(signed_in, monkeypatch):
    from fx.services.providers import RateProviderError

    class _Broken(_StubProvider):
        def daily_closes(self, currency, start, end):
            raise RateProviderError("The rate provider is unreachable: timed out")

    monkeypatch.setattr("fx.api.views.MassiveProvider", _Broken)

    response = signed_in.post("/api/fx/rates/load/")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "rate_provider_unavailable"
    assert ExchangeRate.objects.count() == 0


def test_loading_requires_a_session(client):
    assert client.post("/api/fx/rates/load/").status_code == 403
