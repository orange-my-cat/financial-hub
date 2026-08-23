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
    create_holding,
    held_summary,
    held_summary_with_change,
    held_trend,
    holding_detail,
    holding_history,
    net_of_tax,
    units_bought,
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


def test_the_register_states_realised_gain_and_its_percentage(signed_in, holding):
    """Gain over what the sold units cost — never over units still held."""
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("50"), unit_price=Decimal("20"), fees=Decimal("10"))

    row = signed_in.get("/api/investments/holdings/").json()["data"]["holdings"][0]

    # 990 realised on a 500 FIFO cost basis, and the 500 still held is not in it.
    assert row["realised_gain"] == "490.00"
    assert row["realised_gain_percent"] == "98"


def test_a_holding_that_has_sold_nothing_realised_nothing_rather_than_zero(signed_in, holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))

    row = signed_in.get("/api/investments/holdings/").json()["data"]["holdings"][0]

    assert row["realised_gain"] is None
    assert row["realised_gain_percent"] is None


def test_a_realised_loss_carries_its_sign_into_the_percentage(signed_in, holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("100"), unit_price=Decimal("6"))

    row = signed_in.get("/api/investments/holdings/").json()["data"]["holdings"][0]

    assert row["realised_gain"] == "-400.00"
    assert row["realised_gain_percent"] == "-40"


def test_the_month_history_holds_cost_basis_at_each_month_end(holding):
    """Continuous from the first transaction to the present, newest first, and
    absent — not zero — for the months before the holding existed."""
    record(holding, action="Buy", on_date=date(2026, 1, 10), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 3, 5), quantity=Decimal("40"), unit_price=Decimal("15"))

    history = holding_history(list(holding.transactions.all()), today=date(2026, 4, 30))
    by_month = {row["month"]: row for row in history}

    assert [row["month"] for row in history] == ["2026-04", "2026-03", "2026-02", "2026-01"]
    assert by_month["2026-01"]["cost_basis"] == "1000.00"
    # February moved nothing: the January lot is still whole.
    assert by_month["2026-02"]["cost_basis"] == "1000.00"
    # FIFO took 40 units off a lot that cost 10 each, so 600 of basis is left.
    assert by_month["2026-03"]["cost_basis"] == "600.00"
    assert by_month["2026-03"]["quantity"] == "60.0000000000"
    assert by_month["2026-04"]["cost_basis"] == "600.00"


def test_a_holding_sold_out_keeps_its_months_at_zero(holding):
    """Zero is the honest figure once the units are gone — the holding still
    exists, and the line has to show it flat rather than stop."""
    record(holding, action="Buy", on_date=date(2026, 1, 10), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 5), quantity=Decimal("100"), unit_price=Decimal("12"))

    history = holding_history(list(holding.transactions.all()), today=date(2026, 3, 31))

    assert history[0] == {"month": "2026-03", "quantity": "0", "cost_basis": "0.00"}


def test_a_holding_with_no_transactions_has_no_history(holding):
    assert holding_history([]) == []
    assert holding_detail(holding)["history"] == []


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
# Editing a holding — and the two facts that are one-way doors
# ---------------------------------------------------------------------------


def test_a_holding_can_be_renamed_and_reclassified(signed_in, holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("10"), unit_price=Decimal("10"))

    response = signed_in.patch(
        f"/api/investments/holdings/{holding.pk}/",
        data={"name": "Acme Corporation", "symbol": "ACMX", "instrument_type": "ETF"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["name"] == "Acme Corporation"
    assert body["symbol"] == "ACMX"
    assert body["instrument_type"] == "ETF"
    # Renaming restates no figure: the position is what the transactions say.
    assert body["total_cost_basis"] == "100.00"


def test_renaming_a_holding_does_not_move_its_account_or_currency(signed_in, holding, brokerage):
    """Both are one-way doors (§13.4, BR-18), so the serialiser has no field for
    either and an attempt is ignored rather than obeyed."""
    other = Account.objects.create(
        name="Other Brokerage",
        account_type=AccountType.INVESTMENT,
        liquidity_tier=LiquidityTier.LONG,
        currency="AUD",
        opened_month="2026-01",
    )

    signed_in.patch(
        f"/api/investments/holdings/{holding.pk}/",
        data={"name": "Renamed", "account_id": other.pk, "currency": "AUD"},
        content_type="application/json",
    )

    holding.refresh_from_db()
    assert holding.name == "Renamed"
    assert holding.account_id == brokerage.pk
    assert holding.currency == "USD"


def test_two_holdings_in_one_account_cannot_share_a_name(signed_in, holding, brokerage):
    """The database enforces this (§9.1). What is asserted here is that hitting
    it is a refusal naming the field, not an IntegrityError and a 500 — a rename
    that collides is ordinary user error."""
    other = Holding.objects.create(
        name="Beta Corp", symbol="BETA", currency="USD", account=brokerage
    )

    response = signed_in.patch(
        f"/api/investments/holdings/{other.pk}/",
        data={"name": holding.name},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "duplicate_holding_name"
    assert "name" in response.json()["error"]["field_errors"]
    other.refresh_from_db()
    assert other.name == "Beta Corp"


def test_creating_a_holding_with_a_name_the_account_already_uses_is_refused(signed_in, holding, brokerage):
    response = signed_in.post(
        "/api/investments/holdings/",
        data={
            "name": holding.name,
            "currency": "USD",
            "account_id": brokerage.pk,
            "instrument_type": "Equity",
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "duplicate_holding_name"


def test_the_same_name_in_a_different_account_is_two_holdings(signed_in, holding):
    """The rule is per account, and deliberately: the same instrument at two
    brokers is two holdings with independent FIFO queues (§13.4)."""
    elsewhere = Account.objects.create(
        name="Second Brokerage",
        account_type=AccountType.INVESTMENT,
        liquidity_tier=LiquidityTier.LONG,
        currency="USD",
        opened_month="2026-01",
    )

    twin = create_holding(
        name=holding.name, symbol=holding.symbol, currency="USD", account_id=elsewhere.pk
    )

    assert twin.pk != holding.pk
    assert twin.name == holding.name


def test_a_soft_deleted_holding_does_not_hold_its_name_hostage(signed_in, holding, brokerage):
    """The constraint is scoped to live rows, and so is the refusal."""
    name = holding.name
    holding.delete()

    revived = create_holding(name=name, currency="USD", account_id=brokerage.pk)

    assert revived.name == name


def test_renaming_a_holding_to_its_own_name_is_not_a_clash(signed_in, holding):
    response = signed_in.patch(
        f"/api/investments/holdings/{holding.pk}/",
        data={"name": holding.name, "symbol": "ACMX"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["symbol"] == "ACMX"


def test_the_tax_percentage_clears_to_null_and_the_net_returns_to_the_gross(signed_in, holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("100"), unit_price=Decimal("20"))

    signed_in.patch(
        f"/api/investments/holdings/{holding.pk}/",
        data={"estimated_tax_percent": None},
        content_type="application/json",
    )

    sale = signed_in.get("/api/investments/realised-gains/").json()["data"]["currencies"][0]["sales"][0]
    assert sale["estimated_tax_percent"] is None
    assert sale["net_realised_gain"] == sale["realised_gain"]
    assert sale["tax_applied"] is False


# ---------------------------------------------------------------------------
# The holding's own screen — the transaction register
# ---------------------------------------------------------------------------
# The register is what the holding detail exists for: every transaction, and
# what replay made of it. What is asserted here is that the browser is never
# asked to work anything out (ADR-12) and that the register and the realised
# gains report cannot disagree, because both render the same sale through one
# function.


def test_the_register_states_what_a_purchase_cost(holding):
    """Units x price plus fees, from the engine rather than re-derived."""
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"), fees=Decimal("15"))

    row = holding_detail(holding)["transactions"][0]

    assert row["action"] == "Buy"
    assert row["acquired"]["cost"] == "1015.00"
    assert row["acquired"]["remaining_quantity"] == "100.0000000000"
    assert row["realised"] is None and row["distributed"] is None


def test_a_sale_names_the_lots_it_consumed_oldest_first(holding):
    """The other half of the FIFO queue: where a sale's cost basis came from."""
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("50"), unit_price=Decimal("10"))
    record(holding, action="Buy", on_date=date(2026, 2, 1), quantity=Decimal("50"), unit_price=Decimal("20"))
    record(holding, action="Sell", on_date=date(2026, 3, 1), quantity=Decimal("70"), unit_price=Decimal("30"))

    sale = next(
        row for row in holding_detail(holding)["transactions"] if row["action"] == "Sell"
    )
    consumed = sale["realised"]["consumed"]

    assert [taken["acquired"] for taken in consumed] == ["2026-01-01", "2026-02-01"]
    assert [taken["quantity"] for taken in consumed] == ["50.0000000000", "20.0000000000"]
    # 500 from the whole January lot, 400 from two fifths of February's.
    assert [taken["cost_basis"] for taken in consumed] == ["500.00", "400.00"]
    assert sale["realised"]["cost_basis"] == "900.00"


def test_a_purchase_sold_down_to_nothing_says_zero_remaining_not_absent(holding):
    """A consumed lot is empty, which is a figure. Absent would be a different claim."""
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("50"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("50"), unit_price=Decimal("12"))

    buy = next(
        row for row in holding_detail(holding)["transactions"] if row["action"] == "Buy"
    )

    assert buy["acquired"]["remaining_quantity"] == "0"
    assert buy["acquired"]["remaining_cost"] == "0.00"


def test_a_split_moves_no_money_in_the_register(holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("50"), unit_price=Decimal("10"))
    record(holding, action="Split", on_date=date(2026, 2, 1), split_ratio=Decimal("2"))

    split = next(
        row for row in holding_detail(holding)["transactions"] if row["action"] == "Split"
    )

    assert split["acquired"] is None
    assert split["realised"] is None
    assert split["distributed"] is None
    assert split["split_ratio"] == "2.0000000000"


def test_every_register_row_carries_the_units_held_after_it(holding):
    """The register's running total, newest row first — the order it reads in."""
    record(holding, action="Buy", on_date=date(2026, 1, 1), amount=Decimal("1000"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("40"), unit_price=Decimal("12"))
    record(holding, action="Split", on_date=date(2026, 3, 1), split_ratio=Decimal("2"))

    held = [row["units_held"] for row in holding_detail(holding)["transactions"]]

    assert held == ["120.0000000000", "60.0000000000", "100.0000000000"]


def test_a_reinvestment_row_states_both_the_cash_and_the_units(holding):
    """The one row in this system with two money effects. Every other action
    populates exactly one of the three, and a split none."""
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("50"), unit_price=Decimal("10"))
    record(
        holding,
        action="Reinvestment",
        on_date=date(2026, 2, 1),
        quantity=Decimal("10"),
        unit_price=Decimal("11"),
        cash_amount=Decimal("110.00"),
    )

    row = next(
        r for r in holding_detail(holding)["transactions"] if r["action"] == "Reinvestment"
    )

    assert row["distributed"] == "110.00"
    assert row["acquired"]["cost"] == "110.00"
    assert row["acquired"]["from_reinvestment"] is True
    assert row["realised"] is None


def test_a_purchase_is_entered_by_what_it_cost(holding):
    """Dollar value and price in, units out — the paperwork's own two figures."""
    row = record(
        holding,
        action="Buy",
        on_date=date(2026, 1, 10),
        amount=Decimal("1000.00"),
        unit_price=Decimal("10.00"),
    )

    assert row.quantity == Decimal("100.0000000000")
    # And the cost basis comes back to what was paid, which is the whole point.
    assert replay_holding(holding).total_cost_basis.quantize(Decimal("0.01")) == Decimal("1000.00")


def test_units_are_derived_to_ten_places_and_cost_basis_still_lands(holding):
    """A real reinvestment from the seeded history: $34.40 of a $74.97 unit.

    Ten decimal places is what makes this safe — the rounding error is the price
    times 5e-11, which disappears long before cost basis is quantized to cents.
    """
    assert units_bought(Decimal("34.40"), Decimal("74.97")) == Decimal("0.4588502067")

    record(
        holding,
        action="Buy",
        on_date=date(2026, 1, 10),
        amount=Decimal("34.40"),
        unit_price=Decimal("74.97"),
    )

    basis = replay_holding(holding).total_cost_basis
    assert basis.quantize(Decimal("0.01")) == Decimal("34.40")


def test_a_reinvestment_derives_its_units_from_the_cash_distributed(holding):
    """One figure, two jobs: the income the holding paid, and what bought the
    units. Nothing else is entered."""
    row = record(
        holding,
        action="Reinvestment",
        on_date=date(2026, 2, 1),
        cash_amount=Decimal("45.00"),
        unit_price=Decimal("15.00"),
    )

    assert row.quantity == Decimal("3.0000000000")
    assert replay_holding(holding).total_distributions == Decimal("45.0000")


def test_a_purchase_states_the_cost_or_the_units_but_not_both(holding):
    with pytest.raises(BusinessRuleError) as refused:
        record(
            holding,
            action="Buy",
            on_date=date(2026, 1, 10),
            amount=Decimal("1000.00"),
            quantity=Decimal("100"),
            unit_price=Decimal("10.00"),
        )

    assert refused.value.code == "amount_and_quantity"


def test_units_cannot_be_derived_without_a_price(holding):
    """Guarded, not divided by. A price of zero is a mistyped row or a gift, and
    neither is a number of units."""
    with pytest.raises(BusinessRuleError) as refused:
        record(
            holding,
            action="Buy",
            on_date=date(2026, 1, 10),
            amount=Decimal("1000.00"),
        )

    assert refused.value.code == "unit_price_required"
    assert refused.value.field == "unit_price"


def test_a_purchase_over_http_is_entered_by_amount(signed_in, holding):
    response = signed_in.post(
        f"/api/investments/holdings/{holding.pk}/transactions/",
        data={"action": "Buy", "date": "2026-01-10", "amount": "1000", "unit_price": "10"},
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["data"]["position"]["total_quantity"] == "100.0000000000"


def test_a_distribution_cannot_be_recorded_as_cash_alone(holding):
    """It is not a rejected action but an absent one: there is no Distribution
    left to name, and a reinvestment without its cash is refused."""
    with pytest.raises(ValueError):
        record(holding, action="Distribution", on_date=date(2026, 2, 1), cash_amount=Decimal("42.50"))

    with pytest.raises(BusinessRuleError) as refused:
        record(
            holding,
            action="Reinvestment",
            on_date=date(2026, 2, 1),
            quantity=Decimal("10"),
            unit_price=Decimal("11"),
        )

    assert refused.value.code == "cash_amount_required"
    assert refused.value.field == "cash_amount"


def test_a_reinvestment_over_http_is_refused_without_its_cash(signed_in, holding):
    response = signed_in.post(
        f"/api/investments/holdings/{holding.pk}/transactions/",
        data={
            "action": "Reinvestment",
            "date": "2026-02-01",
            "quantity": "10",
            "unit_price": "11",
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cash_amount_required"
    assert "cash_amount" in response.json()["error"]["field_errors"]


def test_the_api_no_longer_has_a_distribution_action(signed_in, holding):
    """Refused by the vocabulary itself, before any rule is consulted."""
    response = signed_in.post(
        f"/api/investments/holdings/{holding.pk}/transactions/",
        data={"action": "Distribution", "date": "2026-02-01", "cash_amount": "42.50"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "action" in response.json()["error"]["field_errors"]
    assert InvestmentTransaction.objects.count() == 0


def test_the_register_and_the_gains_report_agree_about_a_sale(holding):
    """One definition per calculation. Both render through `disposal_row`."""
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("100"), unit_price=Decimal("20"), fees=Decimal("10"))

    reported = realised_gains_by_currency()[0]["sales"][0]
    registered = holding_detail(holding)["realised"]["sales"][0]

    assert registered == reported


def test_an_invalidated_sale_is_flagged_on_its_own_row(holding):
    """ADR-07 on the register: the row says which sale, and the figures stay."""
    buy = record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("50"), unit_price=Decimal("10"))
    sale = record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("50"), unit_price=Decimal("12"))
    buy.delete()

    detail = holding_detail(holding)
    row = next(r for r in detail["transactions"] if r["id"] == sale.pk)

    assert detail["consistent"] is False
    assert row["flagged"] is True
    assert row["realised"]["proceeds"] == "600.00"


def test_the_holding_detail_endpoint_returns_the_register(signed_in, holding):
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("40"), unit_price=Decimal("20"))

    body = signed_in.get(f"/api/investments/holdings/{holding.pk}/").json()["data"]

    # Newest first, as the model orders and the screen lists.
    assert [row["action"] for row in body["transactions"]] == ["Sell", "Buy"]
    assert body["realised"]["gross"] == "400.00"
    assert body["lots"][0]["remaining_quantity"] == "60.0000000000"
    assert "does not exist in this system" in body["prohibitions"]["unrealised_gain"]


def test_the_holding_detail_states_no_market_price_or_unrealised_gain(signed_in, holding):
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

    body = signed_in.get(f"/api/investments/holdings/{holding.pk}/").json()["data"]

    assert not forbidden & set(body)
    for row in body["transactions"]:
        assert not forbidden & set(row)


def test_a_holding_with_no_transactions_has_an_empty_register(signed_in, holding):
    body = signed_in.get(f"/api/investments/holdings/{holding.pk}/").json()["data"]

    assert body["transactions"] == []
    assert body["realised"] == {"gross": "0.00", "sales": []}


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


def test_a_past_position_replays_only_the_transactions_up_to_that_date(
    two_currency_portfolio,
):
    """As at 31 January nothing had been sold and the AUD holding did not exist:
    150 USD units at their 10.00 cost, marked at that same 10.00.
    """
    summary = held_summary("USD", through=date(2026, 1, 31))

    assert summary.holdings == 1
    assert summary.cost_basis.api() == {"amount": "1500.00", "currency": "USD"}
    assert summary.estimated_value.api() == {"amount": "1500.00", "currency": "USD"}


def test_the_figures_are_the_reported_month_and_not_today(two_currency_portfolio):
    """Reporting March in May states March's position, not May's.

    The sale on 10 March is in it; nothing after March would be. 100 USD units at
    10.00 and 200 AUD units at USD 650 — cost basis 1,650, and the change is March
    on February rather than on the month before now.
    """
    changed = held_summary_with_change("USD", month="2026-03", today=date(2026, 5, 20))

    assert changed["month"] == "2026-03"
    assert changed["previous_month"] == "2026-02"
    assert changed["cost_basis"] == {"amount": "1650.00", "currency": "USD"}


def test_each_held_figure_carries_its_movement_on_the_month_before(
    two_currency_portfolio,
):
    """Nothing moved between March and April, so all three changes are zero — and
    a zero change is a change, stated rather than omitted."""
    changed = held_summary_with_change("USD", month="2026-04", today=date(2026, 6, 15))

    assert changed["previous_month"] == "2026-03"
    assert changed["change"]["cost_basis"]["change"] == "0.00"
    assert changed["change"]["estimated_value"]["change"] == "0.00"
    assert changed["change"]["estimated_gain"]["change"] == "0.00"


def test_a_month_that_bought_and_a_month_that_sold_move_by_what_they_did(
    two_currency_portfolio,
):
    """February bought the AUD holding — cost basis up by its whole USD 650, from
    1,500 to 2,150. March sold 50 USD units, taking 500 of the cost back out.
    """
    february = held_summary_with_change("USD", month="2026-02", today=date(2026, 6, 15))
    march = held_summary_with_change("USD", month="2026-03", today=date(2026, 6, 15))

    assert february["change"]["cost_basis"]["change"] == "650.00"
    assert march["change"]["cost_basis"]["change"] == "-500.00"


def test_a_figure_that_did_not_exist_last_month_has_no_change_rather_than_all_of_it(
    two_currency_portfolio,
):
    """FR-46 applied to a change: an estimate nobody could make is not an
    estimate of nothing, so there is nothing to subtract from."""
    ExchangeRate.objects.all().delete()
    Holding.objects.filter(currency="USD").delete()

    changed = held_summary_with_change("USD", month="2026-04", today=date(2026, 6, 15))

    assert changed["estimated_value"] is None
    assert changed["change"]["estimated_value"] == {"change": None, "change_percent": None}


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
