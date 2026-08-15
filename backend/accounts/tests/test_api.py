"""The accounts endpoints.

Two things get particular attention: that every aggregate carries the
information qualifying it (§8.2), and that Month Close behaves as the design
requires — autosave per field, no batch save, and a partly closed month left
standing rather than rolled back.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import Account, AccountType, Balance, LiquidityTier
from fx.models import ExchangeRate

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in(client, django_user_model):
    user = django_user_model.objects.create_user(username="owner", password="pw-long-enough")
    client.force_login(user)
    return client


@pytest.fixture
def portfolio(db):
    usd = Account.objects.create(
        name="Everyday",
        account_type=AccountType.CURRENT,
        liquidity_tier=LiquidityTier.INSTANT,
        currency="USD",
        opened_month="2026-01",
    )
    aud = Account.objects.create(
        name="CommBank Saver",
        account_type=AccountType.SAVINGS,
        liquidity_tier=LiquidityTier.SHORT,
        currency="AUD",
        opened_month="2026-01",
    )
    loan = Account.objects.create(
        name="Home loan",
        account_type=AccountType.LOAN,
        liquidity_tier=LiquidityTier.LOCKED,
        currency="AUD",
        opened_month="2026-01",
    )
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 7, 31), rate=Decimal("0.66")
    )
    for account, amount in ((usd, "10000"), (aud, "50000"), (loan, "250000")):
        Balance.objects.create(account=account, month="2026-07", amount=Decimal(amount))
    return {"usd": usd, "aud": aud, "loan": loan}


READ_ENDPOINTS = [
    "/api/accounts/",
    "/api/month-close/?month=2026-07",
    "/api/net-worth/?month=2026-07",
    "/api/net-worth/trend/?from_month=2026-01&to_month=2026-07",
    "/api/net-worth/slices/?month=2026-07&dimension=type",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_every_endpoint_requires_a_session(client, path):
    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_every_read_endpoint_wraps_its_payload_in_data(signed_in, path):
    body = signed_in.get(path).json()
    assert "data" in body, f"{path} does not wrap its payload in `data`"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def test_creating_an_account(signed_in):
    response = signed_in.post(
        "/api/accounts/",
        data={
            "name": "Everyday",
            "account_type": "Current/Checking",
            "liquidity_tier": "Instant",
            "currency": "USD",
            "opened_month": "2026-01",
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["is_liability"] is False
    assert body["currency_locked"] is False
    assert body["status"] == "Open"


def test_the_currency_lock_appears_once_a_balance_exists(signed_in, portfolio):
    body = signed_in.get("/api/accounts/").json()["data"]
    by_name = {a["name"]: a for a in body}

    assert by_name["Everyday"]["currency_locked"] is True
    assert by_name["Everyday"]["has_history"] is True


def test_reclassifying_returns_the_restatement_advisory_and_saves(signed_in, portfolio):
    response = signed_in.patch(
        f"/api/accounts/{portfolio['aud'].pk}/",
        data={"account_type": "Loan/Mortgage", "liquidity_tier": "Locked"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["advisories"][0]["kind"] == "historic_restatement"
    assert body["advisories"][0]["detail"]["crosses_asset_liability_boundary"] is True
    assert body["data"]["account_type"] == "Loan/Mortgage"


def test_an_account_with_history_cannot_be_deleted(signed_in, portfolio):
    response = signed_in.delete(f"/api/accounts/{portfolio['usd'].pk}/")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "account_has_history"


def test_an_account_without_history_can_be_deleted(signed_in):
    account = Account.objects.create(
        name="Typo",
        account_type=AccountType.SAVINGS,
        liquidity_tier=LiquidityTier.SHORT,
        currency="USD",
        opened_month="2026-01",
    )

    assert signed_in.delete(f"/api/accounts/{account.pk}/").status_code == 204


def test_closing_an_account(signed_in, portfolio):
    response = signed_in.post(
        f"/api/accounts/{portfolio['usd'].pk}/close/",
        data={"closed_month": "2026-08"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "Closed"
    assert response.json()["data"]["closed_month"] == "2026-08"


def test_an_unknown_account_is_a_404(signed_in):
    assert signed_in.get("/api/accounts/9999/").status_code == 404


# ---------------------------------------------------------------------------
# Balances — the Month Close write path
# ---------------------------------------------------------------------------


def test_saving_a_balance(signed_in, portfolio):
    response = signed_in.put(
        f"/api/accounts/{portfolio['usd'].pk}/balances/2026-08/",
        data={"amount": "12345.67"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["amount"] == "12345.6700"


def test_saving_the_same_month_again_replaces_it(signed_in, portfolio):
    url = f"/api/accounts/{portfolio['usd'].pk}/balances/2026-08/"
    signed_in.put(url, data={"amount": "100"}, content_type="application/json")
    signed_in.put(url, data={"amount": "200"}, content_type="application/json")

    assert portfolio["usd"].balances.filter(month="2026-08").count() == 1


def test_a_balance_before_the_opening_month_is_refused(signed_in, portfolio):
    response = signed_in.put(
        f"/api/accounts/{portfolio['usd'].pk}/balances/2025-01/",
        data={"amount": "1"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "balance_before_opening"


def test_deleting_a_balance(signed_in, portfolio):
    response = signed_in.delete(
        f"/api/accounts/{portfolio['usd'].pk}/balances/2026-07/"
    )

    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Month Close
# ---------------------------------------------------------------------------


def test_month_close_puts_the_prior_balance_beside_each_input(signed_in, portfolio):
    Balance.objects.create(
        account=portfolio["usd"], month="2026-06", amount=Decimal("9000")
    )

    body = signed_in.get("/api/month-close/?month=2026-07").json()["data"]
    rows = {row["name"]: row for row in body["rows"]}

    assert rows["Everyday"]["prior"] == "9000.0000"
    assert rows["Everyday"]["prior_month"] == "2026-06"
    assert rows["Everyday"]["current"] == "10000.0000"
    assert rows["Everyday"]["saved"] is True


def test_month_close_lists_only_the_currencies_actually_in_use(signed_in, portfolio):
    body = signed_in.get("/api/month-close/?month=2026-07").json()["data"]

    assert [rate["currency"] for rate in body["rates"]] == ["AUD"]
    assert body["rates"][0]["quote_label"] == "USD per 1 AUD"
    assert body["rates"][0]["recorded"] is True


def test_month_close_shows_a_carried_rate_as_carried(signed_in, portfolio):
    body = signed_in.get("/api/month-close/?month=2026-08").json()["data"]
    rate = body["rates"][0]

    assert rate["recorded"] is False
    assert rate["provenance"] == "carried"
    assert rate["effective_as_at"] == "2026-07-31"


def test_a_partly_closed_month_is_a_legitimate_state(signed_in, portfolio):
    """Month Close is deliberately not a transaction (§9.6).

    The account must have history elsewhere for July to be outstanding. An
    account with no recorded balance at all is required for no month, by
    ADR-04 — which is why this deletes only July and leaves June.
    """
    Balance.objects.create(
        account=portfolio["usd"], month="2026-06", amount=Decimal("9000")
    )
    portfolio["usd"].balances.filter(month="2026-07").delete()

    body = signed_in.get("/api/month-close/?month=2026-07").json()["data"]

    assert body["completeness"]["state"] == "Incomplete"
    assert body["completeness"]["balances"]["recorded"] == 2
    assert body["completeness"]["balances"]["expected"] == 3
    assert body["completeness"]["outstanding_accounts"] == ["Everyday"]


# ---------------------------------------------------------------------------
# Net worth
# ---------------------------------------------------------------------------


def test_net_worth_carries_its_completeness_and_provenance(signed_in, portfolio):
    body = signed_in.get("/api/net-worth/?month=2026-07&currency=USD").json()

    # 10,000 + (50,000 x 0.66) - (250,000 x 0.66) = 10,000 - 132,000 = -122,000
    assert body["data"]["total"] == {"amount": "-122000.00", "currency": "USD"}
    assert body["completeness"]["state"] == "Complete"
    assert body["exclusions"] == []
    assert body["rate_provenance"][0]["currency"] == "AUD"


def test_the_as_at_date_is_silent_when_every_rate_is_fresh(signed_in, portfolio):
    """Silence is the signal (design state S3)."""
    body = signed_in.get("/api/net-worth/?month=2026-07").json()

    assert body["data"]["any_stale"] is False
    assert body["data"]["as_at"] is None


def test_the_as_at_date_appears_when_a_rate_is_stale(signed_in, portfolio):
    """Staleness is a property of *contributing* rates, so August needs
    balances — with no contributions there is nothing for a rate to be stale
    for."""
    Balance.objects.create(
        account=portfolio["aud"], month="2026-08", amount=Decimal("50000")
    )

    body = signed_in.get("/api/net-worth/?month=2026-08").json()

    assert body["data"]["any_stale"] is True
    # The July rate, carried into August and 31 days old.
    assert body["data"]["as_at"] == "2026-07-31"
    assert body["rate_provenance"][0]["provenance"] == "carried"


def test_an_excluded_account_is_named_on_the_aggregate(signed_in, portfolio):
    ExchangeRate.objects.all().delete()

    body = signed_in.get("/api/net-worth/?month=2026-07").json()

    assert {e["account"] for e in body["exclusions"]} == {"CommBank Saver", "Home loan"}
    # Never zero: the USD account alone is the total.
    assert body["data"]["total"]["amount"] == "10000.00"


def test_every_slice_totals_to_net_worth(signed_in, portfolio):
    total = signed_in.get("/api/net-worth/?month=2026-07").json()["data"]["total"]["amount"]

    for dimension in ("type", "liquidity", "currency", "account"):
        body = signed_in.get(
            f"/api/net-worth/slices/?month=2026-07&dimension={dimension}"
        ).json()["data"]
        summed = sum(Decimal(row["amount"]) for row in body["rows"])
        assert summed == Decimal(total), dimension


def test_the_trend_reports_change_and_completeness_per_month(signed_in, portfolio):
    Balance.objects.create(
        account=portfolio["usd"], month="2026-06", amount=Decimal("9000")
    )

    body = signed_in.get(
        "/api/net-worth/trend/?from_month=2026-06&to_month=2026-07"
    ).json()["data"]

    assert [p["month"] for p in body["points"]] == ["2026-06", "2026-07"]
    # June is Complete, and that is ADR-04 working rather than a gap: the AUD
    # accounts first recorded a balance in July, so they are required from July
    # onward and June is not indicted for lacking them. This is precisely what
    # makes back-filling a lossy spreadsheet survivable.
    assert body["points"][0]["completeness"] == "Complete"
    assert body["points"][1]["completeness"] == "Complete"
    assert body["points"][1]["change"] is not None


def test_a_reversed_range_is_refused(signed_in):
    response = signed_in.get(
        "/api/net-worth/trend/?from_month=2026-07&to_month=2026-01"
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Account detail
# ---------------------------------------------------------------------------


def test_account_history_is_in_the_accounts_own_currency(signed_in, portfolio):
    Balance.objects.create(
        account=portfolio["aud"], month="2026-06", amount=Decimal("48000")
    )

    body = signed_in.get(f"/api/accounts/{portfolio['aud'].pk}/history/").json()["data"]

    assert body["account"]["currency"] == "AUD"
    assert body["history"][0]["month"] == "2026-07"
    assert body["history"][0]["amount"] == "50000.0000"
    assert body["history"][0]["change"] == "2000.0000"
    # The oldest month has nothing to compare against.
    assert body["history"][-1]["change"] is None


# ---------------------------------------------------------------------------
# A month with no balances is not a month worth zero
# ---------------------------------------------------------------------------


def test_a_month_with_no_balances_has_no_total_rather_than_zero(signed_in, portfolio):
    """The FR-46 distinction, one level up.

    Found by the browser check: the trend was plotting months that predate the
    first account as 0.00, so the line fell off a cliff that never happened and
    the month-on-month table filled with two years of zeroes.
    """
    body = signed_in.get("/api/net-worth/?month=2020-01").json()

    assert body["data"]["reportable"] is False
    assert body["data"]["total"] is None
    assert body["completeness"]["state"] == "Outside Range"


def test_a_month_with_balances_is_reportable(signed_in, portfolio):
    body = signed_in.get("/api/net-worth/?month=2026-07").json()

    assert body["data"]["reportable"] is True
    assert body["data"]["total"]["amount"] == "-122000.00"


def test_the_trend_emits_a_gap_rather_than_a_zero(signed_in, portfolio):
    body = signed_in.get(
        "/api/net-worth/trend/?from_month=2026-05&to_month=2026-07"
    ).json()["data"]

    points = {p["month"]: p for p in body["points"]}
    assert points["2026-05"]["total"] is None
    assert points["2026-05"]["change"] is None
    assert points["2026-07"]["total"]["amount"] == "-122000.00"


def test_the_change_is_not_measured_across_a_gap(signed_in, portfolio):
    """A month resuming after a gap has nothing to compare against, and
    inventing a change from the last recorded month would overstate a movement
    that happened over an unknown span."""
    Balance.objects.create(
        account=portfolio["usd"], month="2026-04", amount=Decimal("5000")
    )

    body = signed_in.get(
        "/api/net-worth/trend/?from_month=2026-04&to_month=2026-07"
    ).json()["data"]

    points = {p["month"]: p for p in body["points"]}
    assert points["2026-04"]["total"] is not None
    assert points["2026-05"]["total"] is None
    # July resumes after May and June are absent, so it reports no change.
    assert points["2026-07"]["change"] is None
