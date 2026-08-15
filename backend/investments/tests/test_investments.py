"""Investments through the models and the API.

The replay engine is tested separately and without a database. What is tested
here is the wiring, the two refusals, and the rules that only make sense once
a holding has a currency and a tax percentage attached.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from accounts.models import Account, AccountType, LiquidityTier
from core.services.exceptions import BusinessRuleError
from investments.models import Holding, InvestmentTransaction
from investments.services.positions import (
    net_of_tax,
    realised_gains_by_currency,
    record,
    replay_holding,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def brokerage(db) -> Account:
    return Account.objects.create(
        name="Brokerage",
        account_type=AccountType.INVESTMENT,
        liquidity_tier=LiquidityTier.LONG,
        currency="USD",
        opened_month="2026-01",
    )


@pytest.fixture
def holding(brokerage) -> Holding:
    return Holding.objects.create(
        name="Acme Corp",
        symbol="ACME",
        currency="USD",
        account=brokerage,
        estimated_tax_percent=Decimal("20"),
    )


@pytest.fixture
def signed_in(client, django_user_model):
    user = django_user_model.objects.create_user(username="owner", password="pw-long-enough")
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# FR-33 — an over-sale is refused at the point of entry
# ---------------------------------------------------------------------------


def test_selling_more_than_is_held_is_refused_at_entry(holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("50"), unit_price=Decimal("10"))

    with pytest.raises(BusinessRuleError, match="held 50 units"):
        record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("80"), unit_price=Decimal("12"))


def test_selling_exactly_what_is_held_is_allowed(holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("50"), unit_price=Decimal("10"))

    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("50"), unit_price=Decimal("12"))

    assert replay_holding(holding).total_quantity == Decimal("0")


def test_a_sale_cannot_draw_on_units_bought_after_it(holding):
    record(holding, action="Buy", on_date=date(2026, 6, 1), quantity=Decimal("50"), unit_price=Decimal("10"))

    with pytest.raises(BusinessRuleError):
        record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("10"), unit_price=Decimal("12"))


def test_a_sale_invalidated_by_a_later_edit_is_flagged_not_blocked(holding):
    """ADR-07. The figures still display and entry still works."""
    buy = record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("50"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("50"), unit_price=Decimal("12"))

    # The historic edit that invalidates it.
    buy.delete()

    result = replay_holding(holding)
    assert not result.is_consistent
    assert result.inconsistencies[0].shortfall == Decimal("50")
    # Entry still works.
    record(holding, action="Buy", on_date=date(2026, 3, 1), quantity=Decimal("10"), unit_price=Decimal("9"))


def test_a_split_needs_a_ratio(holding):
    with pytest.raises(BusinessRuleError, match="needs a ratio"):
        record(holding, action="Split", on_date=date(2026, 2, 1))


def test_same_day_transactions_get_increasing_sequences(holding):
    first = record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("5"))
    second = record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("50"))

    assert second.sequence > first.sequence
    # The one entered first is consumed first.
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("10"), unit_price=Decimal("60"))
    assert replay_holding(holding).disposals[0].cost_basis == Decimal("50")


# ---------------------------------------------------------------------------
# BR-21 — estimated tax is a user-typed percentage
# ---------------------------------------------------------------------------


def test_tax_is_applied_to_a_gain():
    net, applied = net_of_tax(Decimal("1000"), Decimal("20"))

    assert net == Decimal("800")
    assert applied is True


def test_tax_is_never_applied_to_a_loss():
    """OI-05 — losses are shown gross."""
    net, applied = net_of_tax(Decimal("-500"), Decimal("20"))

    assert net == Decimal("-500")
    assert applied is False


def test_no_percentage_means_net_equals_gross():
    net, applied = net_of_tax(Decimal("1000"), None)

    assert net == Decimal("1000")
    assert applied is False


def test_changing_the_percentage_restates_historic_sales(holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("100"), unit_price=Decimal("20"))

    before = realised_gains_by_currency()[0]["net"]
    holding.estimated_tax_percent = Decimal("50")
    holding.save()
    after = realised_gains_by_currency()[0]["net"]

    assert before == "800.00"   # 1000 gain less 20%
    assert after == "500.00"    # restated at 50%


# ---------------------------------------------------------------------------
# BR-18 — never summed across currencies
# ---------------------------------------------------------------------------


def test_realised_gains_are_grouped_by_currency_with_no_grand_total(brokerage):
    for name, currency, price in (("US Co", "USD", "20"), ("Aus Co", "AUD", "30")):
        row = Holding.objects.create(name=name, currency=currency, account=brokerage)
        record(row, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("10"))
        record(row, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("10"), unit_price=Decimal(price))

    blocks = realised_gains_by_currency()

    assert [block["currency"] for block in blocks] == ["AUD", "USD"]
    # No key anywhere is a cross-currency total.
    assert all("grand_total" not in block for block in blocks)


def test_gains_can_be_filtered_to_a_year(holding):
    record(holding, action="Buy", on_date=date(2025, 1, 1), quantity=Decimal("20"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2025, 6, 1), quantity=Decimal("10"), unit_price=Decimal("20"))
    record(holding, action="Sell", on_date=date(2026, 6, 1), quantity=Decimal("10"), unit_price=Decimal("30"))

    assert len(realised_gains_by_currency(year=2025)[0]["sales"]) == 1
    assert len(realised_gains_by_currency(year=2026)[0]["sales"]) == 1


# ---------------------------------------------------------------------------
# BR-19 — holdings and balances are independent
# ---------------------------------------------------------------------------


def test_recording_a_buy_alters_no_account_balance(holding, brokerage):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))

    assert brokerage.balances.count() == 0


def test_the_same_instrument_at_two_brokers_is_two_holdings(brokerage):
    """Scoped to one account, with independent queues — a one-way door."""
    other = Account.objects.create(
        name="Second broker",
        account_type=AccountType.INVESTMENT,
        liquidity_tier=LiquidityTier.LONG,
        currency="USD",
        opened_month="2026-01",
    )

    first = Holding.objects.create(name="Acme Corp", currency="USD", account=brokerage)
    second = Holding.objects.create(name="Acme Corp", currency="USD", account=other)

    record(first, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("5"))

    assert replay_holding(first).total_quantity == Decimal("10")
    assert replay_holding(second).total_quantity == Decimal("0")


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


def test_the_holdings_endpoint_requires_a_session(client):
    assert client.get("/api/investments/holdings/").status_code == 403


def test_the_holdings_endpoint_returns_the_open_lot_queue(signed_in, holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"), fees=Decimal("15"))

    body = signed_in.get("/api/investments/holdings/").json()["data"]

    position = body["holdings"][0]
    assert position["total_quantity"] == "100.0000000000"
    assert position["total_cost_basis"] == "1015.00"
    assert position["lots"][0]["unit_cost"] == "10.15000000"


def test_the_prohibitions_are_returned_so_the_screen_cannot_forget_them(signed_in):
    body = signed_in.get("/api/investments/holdings/").json()["data"]

    assert "does not exist in this system" in body["prohibitions"]["unrealised_gain"]
    assert "not a calculation" in body["prohibitions"]["estimated_tax"]


def test_no_investments_endpoint_returns_a_market_price_or_unrealised_gain(signed_in, holding):
    """Checked as absent *fields*, not absent prose — the prohibition copy
    mentions the words on purpose."""
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("5"), unit_price=Decimal("20"))

    forbidden = {
        "market_price",
        "market_value",
        "unrealised_gain",
        "current_value",
        "return_percent",
        "total_return",
    }

    holdings = signed_in.get("/api/investments/holdings/").json()["data"]["holdings"]
    gains = signed_in.get("/api/investments/realised-gains/").json()["data"]["currencies"]

    assert not forbidden & set(holdings[0])
    assert not forbidden & set(holdings[0]["lots"][0])
    assert not forbidden & set(gains[0]["sales"][0])


def test_an_oversale_over_http_is_a_field_error(signed_in, holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("10"))

    response = signed_in.post(
        f"/api/investments/holdings/{holding.pk}/transactions/",
        data={"action": "Sell", "date": "2026-02-01", "quantity": "50", "unit_price": "12"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "oversale"
    assert "quantity" in response.json()["error"]["field_errors"]


def test_realised_gains_label_the_net_figure_as_estimated(signed_in, holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("100"), unit_price=Decimal("20"), fees=Decimal("10"))

    body = signed_in.get("/api/investments/realised-gains/").json()["data"]
    sale = body["currencies"][0]["sales"][0]

    assert sale["realised_gain"] == "990.00"
    assert sale["estimated_tax_percent"] == "20"
    assert sale["net_realised_gain"] == "792.00"
    assert sale["tax_applied"] is True


def test_deleting_a_holding_is_soft(signed_in, holding):
    assert signed_in.delete(f"/api/investments/holdings/{holding.pk}/").status_code == 204
    assert Holding.objects.count() == 0
    assert Holding.all_objects.count() == 1


def test_a_deleted_transaction_leaves_the_replay(signed_in, holding):
    row = record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("10"))

    signed_in.delete(f"/api/investments/transactions/{row.pk}/")

    assert replay_holding(holding).total_quantity == Decimal("0")
    assert InvestmentTransaction.all_objects.count() == 1
