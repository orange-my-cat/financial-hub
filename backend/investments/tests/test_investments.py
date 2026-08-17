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
from fx.models import ExchangeRate
from investments.services.positions import (
    held_summary,
    held_trend,
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


# ---------------------------------------------------------------------------
# Currently held, estimated and combined — the departure, tested
# ---------------------------------------------------------------------------
# Market prices and unrealised gain are excluded by the BRD, and combining across
# currencies by BR-18. The dashboard's holdings panel does all three at the
# Product Owner's explicit instruction, so what is asserted here is that each
# departure is made honestly: the estimate is dated, an absent price is named
# rather than counted as zero, and a currency with no rate is excluded rather
# than dropped silently.


@pytest.fixture
def two_currency_portfolio(brokerage, holding):
    """USD 150 units at 10.00 with 50 sold at 12.00; AUD 200 units at 5.00.

    The AUD holding is never re-priced, so its estimate equals its cost basis —
    which is the honest answer, and the reason the panel dates its figures.
    """
    aud_account = Account.objects.create(
        name="Aussie Brokerage", account_type=AccountType.INVESTMENT,
        liquidity_tier=LiquidityTier.LONG, currency="AUD", opened_month="2026-01",
    )
    aussie = Holding.objects.create(
        name="Bunnings Ltd", symbol="BUN", currency="AUD", account=aud_account
    )

    record(holding, action="Buy", on_date=date(2026, 1, 10), quantity=Decimal("150"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 3, 10), quantity=Decimal("50"), unit_price=Decimal("12"))
    record(aussie, action="Buy", on_date=date(2026, 2, 5), quantity=Decimal("200"), unit_price=Decimal("5"))

    ExchangeRate.objects.create(currency="AUD", rate_date=date(2026, 1, 1), rate=Decimal("0.65"))
    return {"usd": holding, "aud": aussie}


def test_the_three_figures_combine_across_currencies_through_the_one_service(
    two_currency_portfolio,
):
    """100 USD units cost 1,000 and mark at 12.00 = 1,200.
    200 AUD units cost 1,000 = USD 650, and mark at the same 5.00 they cost.

    Cost basis 1,650. Estimated value 1,850. Estimated gain 200 — the USD holding's
    2.00 a unit on 100 units, and nothing invented for the AUD one.
    """
    summary = held_summary("USD")

    assert summary.holdings == 2
    assert summary.cost_basis.api() == {"amount": "1650.00", "currency": "USD"}
    assert summary.estimated_value.api() == {"amount": "1850.00", "currency": "USD"}
    assert summary.estimated_gain.api() == {"amount": "200.00", "currency": "USD"}
    # The estimate is only as fresh as its oldest price, and says so.
    assert summary.priced_from == date(2026, 2, 5)
    assert summary.unpriced == ()


def test_a_holding_sold_out_is_not_currently_held(two_currency_portfolio):
    """Its realised gain stands; it has nothing left to value."""
    record(
        two_currency_portfolio["usd"], action="Sell", on_date=date(2026, 4, 1),
        quantity=Decimal("100"), unit_price=Decimal("12"),
    )

    summary = held_summary("USD")

    assert summary.holdings == 1
    assert summary.cost_basis.api() == {"amount": "650.00", "currency": "USD"}


def test_a_currency_with_no_rate_is_excluded_and_named_never_zeroed(two_currency_portfolio):
    """FR-46 survives the departure: the AUD holding leaves the total and says so."""
    ExchangeRate.objects.all().delete()

    summary = held_summary("USD")

    assert summary.holdings == 1
    assert summary.cost_basis.api() == {"amount": "1000.00", "currency": "USD"}
    assert [row["holding"] for row in summary.exclusions] == ["Bunnings Ltd"]
    assert "AUD" in summary.exclusions[0]["reason"]


def test_a_held_holding_with_no_price_is_named_rather_than_valued_at_zero(
    two_currency_portfolio,
):
    """And the gain is measured against the priced subset, so the two figures
    shown beside each other always reconcile."""
    gift = Holding.objects.create(
        name="Inherited Shares", currency="USD", account=two_currency_portfolio["usd"].account
    )
    record(gift, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("0"))

    summary = held_summary("USD")

    assert summary.unpriced == ("Inherited Shares",)
    assert summary.holdings == 3
    # Unchanged by a holding that contributes nothing to either figure.
    assert summary.estimated_value.api() == {"amount": "1850.00", "currency": "USD"}
    assert summary.estimated_gain.amount == (
        summary.estimated_value.amount - summary.priced_cost_basis.amount
    )


def test_an_empty_system_states_zero_rather_than_nothing(db):
    summary = held_summary("USD")

    assert summary.holdings == 0
    assert summary.cost_basis.api() == {"amount": "0.00", "currency": "USD"}
    assert summary.estimated_value is None
    assert summary.estimated_gain is None


# ---------------------------------------------------------------------------
# The trend — each point the position as at that month, sells included
# ---------------------------------------------------------------------------


def test_the_trend_is_the_position_as_at_each_month_not_today_plotted_backwards(
    two_currency_portfolio,
):
    """The USD holding: 150 units bought in January, 50 sold in March.

    January and February therefore hold 150 units at 10.00 — the sale has not
    happened yet — and March onward holds 100. A trend built from today's position
    would show 100 units in January and misstate every month before the sale.
    """
    rows = {
        row["month"]: row
        for row in held_trend(["2026-01", "2026-02", "2026-03"], "USD")
    }

    # January: 150 x 10.00 cost, valued at the same 10.00 — no other price yet.
    assert rows["2026-01"]["cost_basis"] == "1500.00"
    assert rows["2026-01"]["estimated_value"] == "1500.00"
    # February adds the AUD holding: 1,000 AUD at 0.65 = 650.
    assert rows["2026-02"]["cost_basis"] == "2150.00"
    # March: 50 units gone at cost, and the remaining 100 now marked at 12.00.
    assert rows["2026-03"]["cost_basis"] == "1650.00"
    assert rows["2026-03"]["estimated_value"] == "1850.00"


def test_a_month_before_anything_was_held_is_zero_not_absent(two_currency_portfolio):
    """Derived from transactions rather than entered, so nothing held is nothing
    held — unlike a net worth month with no balances recorded."""
    rows = held_trend(["2025-12"], "USD")

    assert rows == [{"month": "2025-12", "cost_basis": "0.00", "estimated_value": "0.00"}]


def test_a_month_after_everything_was_sold_returns_to_zero(two_currency_portfolio):
    record(
        two_currency_portfolio["usd"], action="Sell", on_date=date(2026, 4, 1),
        quantity=Decimal("100"), unit_price=Decimal("12"),
    )
    record(
        two_currency_portfolio["aud"], action="Sell", on_date=date(2026, 4, 2),
        quantity=Decimal("200"), unit_price=Decimal("5"),
    )

    rows = {row["month"]: row for row in held_trend(["2026-03", "2026-04"], "USD")}

    assert rows["2026-03"]["cost_basis"] == "1650.00"
    assert rows["2026-04"]["cost_basis"] == "0.00"
