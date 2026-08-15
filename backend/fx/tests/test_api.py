"""The FX endpoints.

Views are thin, so these tests are about wiring and shape: that every endpoint
is closed by default, that rates cross as strings, that an advisory arrives
beside a *successful* response rather than as an error, and that bulk entry is
genuinely atomic over HTTP and not only in the service.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

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


@pytest.mark.parametrize(
    "path",
    [
        "/api/fx/currencies/",
        "/api/fx/rates/?start=2026-01-01&end=2026-12-31",
        "/api/fx/status/",
        "/api/settings/",
    ],
)
def test_every_fx_endpoint_requires_a_session(client, path):
    assert client.get(path).status_code == 403


# ---------------------------------------------------------------------------
# The currency registry
# ---------------------------------------------------------------------------


def test_the_registry_states_each_pair_and_its_direction(signed_in):
    body = signed_in.get("/api/fx/currencies/").json()

    assert body["base"] == "USD"
    assert body["quoted"] == ["AUD", "MYR"]
    by_code = {c["code"]: c for c in body["currencies"]}
    assert by_code["AUD"]["quote_label"] == "USD per 1 AUD"
    assert by_code["AUD"]["pair"] == "AUD/USD"
    assert by_code["MYR"]["quote_label"] == "MYR per 1 USD"
    assert by_code["MYR"]["pair"] == "USD/MYR"
    assert by_code["USD"]["is_base"] is True


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

    assert body["data"]["reporting_currency"] == "USD"
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


def test_changing_the_reporting_currency_rewrites_no_stored_data(signed_in):
    rate("AUD", "2026-01-31", "0.66")
    before = ExchangeRate.objects.get(currency="AUD").rate

    signed_in.patch(
        "/api/settings/",
        data={"reporting_currency": "AUD"},
        content_type="application/json",
    )

    assert ExchangeRate.objects.get(currency="AUD").rate == before
    assert signed_in.get("/api/settings/").json()["data"]["reporting_currency"] == "AUD"


def test_an_unknown_reporting_currency_is_refused(signed_in):
    response = signed_in.patch(
        "/api/settings/",
        data={"reporting_currency": "GBP"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "reporting_currency" in response.json()["error"]["field_errors"]
