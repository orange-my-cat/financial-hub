"""Property-based tests for FIFO (ADR-17).

The hand-worked scenario proves one case in depth. These prove invariants that
must hold for *every* case — including the shapes nobody thinks to write by
hand, which is exactly where a replay engine goes wrong.

Everything here is exact decimal. Generated values are drawn as integers and
scaled, so no float ever reaches the engine.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from investments.replay import Action, ReplayTransaction, replay

pytestmark = pytest.mark.invariant

START = date(2020, 1, 1)

# Small, exact decimals. Integers scaled by a hundredth keep the arithmetic
# readable when a counterexample is printed.
quantities = st.integers(min_value=1, max_value=10_000).map(lambda n: Decimal(n) / 100)
prices = st.integers(min_value=1, max_value=100_000).map(lambda n: Decimal(n) / 100)
fees = st.integers(min_value=0, max_value=10_000).map(lambda n: Decimal(n) / 100)
ratios = st.sampled_from([Decimal("2"), Decimal("3"), Decimal("0.5"), Decimal("0.1")])
days = st.integers(min_value=0, max_value=3_000)


@st.composite
def transactions(draw):
    """A plausible holding history: buys, sells, splits and reinvestments."""
    count = draw(st.integers(min_value=1, max_value=12))
    rows = []
    for index in range(count):
        action = draw(
            st.sampled_from(
                [Action.BUY, Action.BUY, Action.SELL, Action.SPLIT, Action.REINVESTMENT]
            )
        )
        on_date = START + timedelta(days=draw(days))

        if action is Action.SPLIT:
            rows.append(
                ReplayTransaction(
                    id=index,
                    action=action,
                    on_date=on_date,
                    sequence=index,
                    split_ratio=draw(ratios),
                )
            )
        else:
            rows.append(
                ReplayTransaction(
                    id=index,
                    action=action,
                    on_date=on_date,
                    sequence=index,
                    quantity=draw(quantities),
                    unit_price=draw(prices),
                    fees=draw(fees),
                )
            )
    return rows


@settings(max_examples=200, deadline=None)
@given(transactions())
def test_consumed_quantity_never_exceeds_purchased_quantity(rows):
    """The invariant BUILD_PLAN names. FIFO must never hand out units that were
    never bought."""
    result = replay(rows)

    purchased = sum(
        (row.quantity for row in rows if row.action in (Action.BUY, Action.REINVESTMENT)),
        Decimal(0),
    )
    consumed = sum(
        (consumption.quantity for disposal in result.disposals for consumption in disposal.consumed),
        Decimal(0),
    )

    # Splits multiply quantities, so consumed can exceed the raw purchased
    # figure legitimately — but never when no split occurred.
    if not any(row.action is Action.SPLIT for row in rows):
        assert consumed <= purchased


@settings(max_examples=200, deadline=None)
@given(transactions())
def test_no_lot_ever_holds_a_negative_quantity_or_cost(rows):
    result = replay(rows)

    for lot in result.lots:
        assert lot.remaining_quantity > 0
        assert lot.remaining_cost >= 0


@settings(max_examples=200, deadline=None)
@given(transactions())
def test_a_disposal_never_consumes_more_than_it_disposes_of(rows):
    result = replay(rows)

    for disposal in result.disposals:
        consumed = sum((c.quantity for c in disposal.consumed), Decimal(0))
        assert consumed <= disposal.quantity


@settings(max_examples=200, deadline=None)
@given(transactions())
def test_cost_basis_is_conserved(rows):
    """Every unit of cost that goes in comes out — either still open in a lot,
    or consumed by a disposal. Nothing is created and nothing evaporates."""
    result = replay(rows)

    paid = sum(
        (
            row.quantity * row.unit_price + row.fees
            for row in rows
            if row.action in (Action.BUY, Action.REINVESTMENT)
        ),
        Decimal(0),
    )
    accounted = result.total_cost_basis + sum(
        (disposal.cost_basis for disposal in result.disposals), Decimal(0)
    )

    # Proportional consumption of a partial lot divides, so allow a hair of
    # rounding at Decimal's 28-significant-digit precision.
    assert abs(paid - accounted) < Decimal("0.0000000001")


@settings(max_examples=200, deadline=None)
@given(transactions())
def test_a_replay_is_flagged_inconsistent_exactly_when_a_sale_overdraws(rows):
    result = replay(rows)

    overdrawn = any(
        sum((c.quantity for c in disposal.consumed), Decimal(0)) < disposal.quantity
        for disposal in result.disposals
    )

    assert result.is_consistent is not overdrawn


@settings(max_examples=100, deadline=None)
@given(transactions())
def test_replay_is_pure(rows):
    """Same input, same output, and the input unchanged."""
    snapshot = list(rows)

    first = replay(rows)
    second = replay(rows)

    assert first == second
    assert rows == snapshot


@settings(max_examples=100, deadline=None)
@given(transactions())
def test_a_split_never_changes_total_cost_basis(rows):
    """BR-20 — quantity moves, total cost does not."""
    without_splits = [row for row in rows if row.action is not Action.SPLIT]

    with_result = replay(rows)
    without_result = replay(without_splits)

    # Only comparable when no sale intervenes, since a split changes how many
    # units a sale consumes and therefore what it costs.
    if not any(row.action is Action.SELL for row in rows):
        assert with_result.total_cost_basis == without_result.total_cost_basis
