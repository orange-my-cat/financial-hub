"""The FIFO replay engine — BR-16 and BR-20 by name, and the hand-worked case.

No database. The engine is a pure function, so these run in milliseconds and can
be read as arithmetic rather than as plumbing.

ADR-17 is blunt about why this file matters more than its coverage number: a
FIFO replay can reach 100% line coverage from a single simple sale while never
testing a partial lot consumption, a split, or a sale spanning three lots. The
risk is not a coding error — it is the code faithfully implementing a
misunderstanding, and only a worked example catches that.

===========================================================================
THE HAND-WORKED SCENARIO — a multi-lot sale with fees and an intervening split
===========================================================================

  10 Jan 2026   BUY    100 units @ 20.00, fee 15.00
  14 Mar 2026   BUY     50 units @ 26.00, fee 10.00
  20 Apr 2026   SPLIT  2:1
  05 Jun 2026   BUY     40 units @ 11.00, fee  8.00
  18 Aug 2026   SELL   260 units @ 14.00, fee 25.00

Lot cost bases at purchase (fees join cost basis, BR-16):

  Lot A   100 x 20.00 + 15.00 = 2,015.00   for 100 units
  Lot B    50 x 26.00 + 10.00 = 1,310.00   for  50 units
  Lot C    40 x 11.00 +  8.00 =   448.00   for  40 units

The 2:1 split on 20 Apr doubles the quantity of every lot OPEN AT THAT DATE and
leaves each one's total cost unchanged. Lot C is bought in June and is untouched
— that is the case a stored-lot design gets wrong:

  Lot A   200 units, cost 2,015.00   (unit cost 20.00 → 10.075)
  Lot B   100 units, cost 1,310.00   (unit cost 26.00 → 13.10)
  Lot C    40 units, cost   448.00   (unit cost 11.20, never split)

  Total held before the sale: 200 + 100 + 40 = 340 units

The sale of 260 units consumes oldest first, spanning three lots:

  from A   200 units (all of it)      cost 2,015.00
  from B   100 units (all of it)      cost 1,310.00
  from C    ...only 60 more needed, but A+B already give 300 > 260.

  Recount: 200 from A leaves 60 outstanding.
           60 from B, which holds 100 → partial.

  from A   200 units, cost 2,015.00
  from B    60 units, cost 1,310.00 x (60/100) = 786.00
                                    ----------
  FIFO cost basis of the 260 units   2,801.00

  Proceeds       260 x 14.00 = 3,640.00
  Less sale fee                   25.00     (off proceeds, NOT onto cost basis)
                              ----------
  Net proceeds                 3,615.00
  Less cost basis              2,801.00
                              ----------
  REALISED GAIN                  814.00

Remaining open lots after the sale:

  Lot B    40 units, cost 1,310.00 − 786.00 = 524.00   (unit cost 13.10)
  Lot C    40 units, cost   448.00                      (unit cost 11.20)
           --------
  Total     80 units, cost basis 972.00

Check: 340 held − 260 sold = 80. ✓
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from investments.replay import (
    Action,
    ReplayTransaction,
    replay,
    units_held_at,
)

pytestmark = pytest.mark.invariant


def buy(id, on, quantity, price, fees="0"):
    return ReplayTransaction(
        id=id,
        action=Action.BUY,
        on_date=on,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        fees=Decimal(fees),
    )


def sell(id, on, quantity, price, fees="0"):
    return ReplayTransaction(
        id=id,
        action=Action.SELL,
        on_date=on,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        fees=Decimal(fees),
    )


def split(id, on, ratio):
    return ReplayTransaction(
        id=id, action=Action.SPLIT, on_date=on, split_ratio=Decimal(ratio)
    )


# ---------------------------------------------------------------------------
# The hand-worked scenario
# ---------------------------------------------------------------------------

SCENARIO = [
    buy(1, date(2026, 1, 10), "100", "20.00", "15.00"),
    buy(2, date(2026, 3, 14), "50", "26.00", "10.00"),
    split(3, date(2026, 4, 20), "2"),
    buy(4, date(2026, 6, 5), "40", "11.00", "8.00"),
    sell(5, date(2026, 8, 18), "260", "14.00", "25.00"),
]


def test_the_hand_worked_realised_gain():
    """The one assertion this file exists for."""
    result = replay(SCENARIO)

    assert result.disposals[0].realised_gain == Decimal("814.00")


def test_the_hand_worked_cost_basis_of_the_units_sold():
    result = replay(SCENARIO)

    assert result.disposals[0].cost_basis == Decimal("2801.00")


def test_the_hand_worked_remaining_position():
    result = replay(SCENARIO)

    assert result.total_quantity == Decimal("80")
    assert result.total_cost_basis == Decimal("972.00")


def test_the_sale_spans_three_lots_and_consumes_two():
    result = replay(SCENARIO)
    consumed = result.disposals[0].consumed

    assert [c.lot_transaction_id for c in consumed] == [1, 2]
    assert consumed[0].quantity == Decimal("200")
    assert consumed[0].cost_basis == Decimal("2015.00")
    assert consumed[1].quantity == Decimal("60")
    assert consumed[1].cost_basis == Decimal("786.00")


def test_the_lot_bought_after_the_split_is_untouched_by_it():
    """The case a stored-lot design gets wrong."""
    result = replay(SCENARIO)
    lot_c = next(lot for lot in result.lots if lot.transaction_id == 4)

    assert lot_c.remaining_quantity == Decimal("40")
    assert lot_c.remaining_cost == Decimal("448.00")
    assert lot_c.unit_cost == Decimal("11.20")


def test_the_partly_consumed_lot_keeps_its_original_unit_cost():
    """A sale consuming part of a lot leaves the remainder open at its original
    unit cost (BR-16)."""
    result = replay(SCENARIO)
    lot_b = next(lot for lot in result.lots if lot.transaction_id == 2)

    assert lot_b.remaining_quantity == Decimal("40")
    assert lot_b.remaining_cost == Decimal("524.00")
    assert lot_b.unit_cost == Decimal("13.10")


def test_the_scenario_is_consistent():
    assert replay(SCENARIO).is_consistent


# ---------------------------------------------------------------------------
# BR-16 — partial consumption, ordering, over-sale, fees
# ---------------------------------------------------------------------------


def test_a_partial_sale_leaves_the_remainder_open_at_its_original_unit_cost():
    result = replay([buy(1, date(2026, 1, 1), "100", "10.00"), sell(2, date(2026, 2, 1), "30", "12.00")])

    lot = result.lots[0]
    assert lot.remaining_quantity == Decimal("70")
    assert lot.unit_cost == Decimal("10.00")
    assert result.disposals[0].cost_basis == Decimal("300.00")


def test_lots_are_consumed_oldest_first():
    result = replay(
        [
            buy(1, date(2026, 1, 1), "10", "5.00"),
            buy(2, date(2026, 2, 1), "10", "50.00"),
            sell(3, date(2026, 3, 1), "10", "100.00"),
        ]
    )

    # The cheap lot goes first, not the one that flatters the gain.
    assert result.disposals[0].cost_basis == Decimal("50.00")
    assert result.lots[0].transaction_id == 2


def test_a_sale_spanning_three_lots():
    result = replay(
        [
            buy(1, date(2026, 1, 1), "10", "1.00"),
            buy(2, date(2026, 2, 1), "10", "2.00"),
            buy(3, date(2026, 3, 1), "10", "3.00"),
            sell(4, date(2026, 4, 1), "25", "10.00"),
        ]
    )

    consumed = result.disposals[0].consumed
    assert [c.quantity for c in consumed] == [Decimal("10"), Decimal("10"), Decimal("5")]
    # 10.00 + 20.00 + 15.00
    assert result.disposals[0].cost_basis == Decimal("45.00")
    assert result.total_quantity == Decimal("5")


def test_purchase_fees_join_cost_basis():
    result = replay([buy(1, date(2026, 1, 1), "100", "10.00", "25.00")])

    assert result.total_cost_basis == Decimal("1025.00")
    assert result.lots[0].unit_cost == Decimal("10.25")


def test_sale_fees_come_off_proceeds_and_never_onto_cost_basis():
    result = replay(
        [buy(1, date(2026, 1, 1), "100", "10.00"), sell(2, date(2026, 2, 1), "100", "12.00", "30.00")]
    )

    disposal = result.disposals[0]
    assert disposal.proceeds == Decimal("1200.00")
    assert disposal.net_proceeds == Decimal("1170.00")
    assert disposal.cost_basis == Decimal("1000.00")
    assert disposal.realised_gain == Decimal("170.00")


def test_a_realised_loss_is_negative_and_shown_as_such():
    result = replay(
        [buy(1, date(2026, 1, 1), "100", "10.00"), sell(2, date(2026, 2, 1), "100", "6.00", "5.00")]
    )

    assert result.disposals[0].realised_gain == Decimal("-405.00")
    assert result.disposals[0].is_loss


def test_a_fully_consumed_queue_leaves_no_open_lots():
    result = replay(
        [buy(1, date(2026, 1, 1), "100", "10.00"), sell(2, date(2026, 2, 1), "100", "12.00")]
    )

    assert result.lots == ()
    assert result.total_quantity == Decimal("0")


def test_units_held_at_a_date_ignores_later_transactions():
    """Used to reject an over-sale at the point of entry (FR-33)."""
    transactions = [
        buy(1, date(2026, 1, 1), "100", "10.00"),
        buy(2, date(2026, 6, 1), "100", "10.00"),
    ]

    assert units_held_at(transactions, date(2026, 3, 1)) == Decimal("100")
    assert units_held_at(transactions, date(2026, 7, 1)) == Decimal("200")


def test_an_oversale_is_flagged_and_never_raises():
    """ADR-07 — a sale invalidated by a later edit is flagged, not blocked."""
    result = replay(
        [buy(1, date(2026, 1, 1), "50", "10.00"), sell(2, date(2026, 2, 1), "80", "12.00")]
    )

    assert not result.is_consistent
    problem = result.inconsistencies[0]
    assert problem.requested == Decimal("80")
    assert problem.available == Decimal("50")
    assert problem.shortfall == Decimal("30")
    # The figures still compute from what is recorded.
    assert result.disposals[0].cost_basis == Decimal("500.00")


def test_the_inconsistency_explains_itself_specifically():
    result = replay(
        [buy(1, date(2026, 1, 1), "50", "10.00"), sell(2, date(2026, 2, 1), "80", "12.00")]
    )

    message = result.inconsistencies[0].message
    assert "80" in message and "50" in message
    assert "correcting the earlier entry clears this" in message.lower()


def test_the_flag_clears_when_the_underlying_data_is_corrected():
    broken = [buy(1, date(2026, 1, 1), "50", "10.00"), sell(2, date(2026, 2, 1), "80", "12.00")]
    assert not replay(broken).is_consistent

    corrected = [*broken, buy(3, date(2026, 1, 15), "30", "11.00")]

    assert replay(corrected).is_consistent


# ---------------------------------------------------------------------------
# BR-20 — splits, consolidations, reinvestment
# ---------------------------------------------------------------------------


def test_a_split_doubles_quantity_and_leaves_total_cost_unchanged():
    result = replay(
        [buy(1, date(2026, 1, 1), "100", "20.00"), split(2, date(2026, 2, 1), "2")]
    )

    lot = result.lots[0]
    assert lot.remaining_quantity == Decimal("200")
    assert lot.remaining_cost == Decimal("2000.00")
    assert lot.unit_cost == Decimal("10.00")


def test_a_split_across_lots_with_a_purchase_either_side():
    """The BR-20 case named in the build plan."""
    result = replay(
        [
            buy(1, date(2026, 1, 1), "100", "10.00"),
            split(2, date(2026, 2, 1), "2"),
            buy(3, date(2026, 3, 1), "100", "5.00"),
        ]
    )

    before, after = result.lots
    assert before.remaining_quantity == Decimal("200")
    assert after.remaining_quantity == Decimal("100")
    assert result.total_quantity == Decimal("300")


def test_a_consolidation_is_a_split_with_a_ratio_below_one():
    result = replay(
        [buy(1, date(2026, 1, 1), "100", "1.00"), split(2, date(2026, 2, 1), "0.1")]
    )

    lot = result.lots[0]
    assert lot.remaining_quantity == Decimal("10.0")
    assert lot.remaining_cost == Decimal("100.00")
    assert lot.unit_cost == Decimal("10.00")


def test_two_splits_compound():
    result = replay(
        [
            buy(1, date(2026, 1, 1), "100", "12.00"),
            split(2, date(2026, 2, 1), "2"),
            split(3, date(2026, 3, 1), "3"),
        ]
    )

    assert result.lots[0].remaining_quantity == Decimal("600")
    assert result.lots[0].remaining_cost == Decimal("1200.00")


def test_a_split_affects_only_lots_open_at_its_date_even_when_entered_later():
    """Backdating a split needs no migration, because nothing was written down."""
    entered_out_of_order = [
        buy(1, date(2026, 1, 1), "100", "10.00"),
        buy(3, date(2026, 3, 1), "100", "5.00"),
        split(2, date(2026, 2, 1), "2"),
    ]

    result = replay(entered_out_of_order)

    assert result.total_quantity == Decimal("300")


def test_a_distribution_changes_no_lot_and_no_cost_basis():
    result = replay(
        [
            buy(1, date(2026, 1, 1), "100", "10.00"),
            ReplayTransaction(
                id=2,
                action=Action.DISTRIBUTION,
                on_date=date(2026, 6, 1),
                cash_amount=Decimal("45.00"),
            ),
        ]
    )

    assert result.total_quantity == Decimal("100")
    assert result.total_cost_basis == Decimal("1000.00")
    assert result.total_distributions == Decimal("45.00")


def test_a_reinvestment_creates_a_lot_at_the_reinvestment_price():
    result = replay(
        [
            buy(1, date(2026, 1, 1), "100", "10.00"),
            ReplayTransaction(
                id=2,
                action=Action.DISTRIBUTION,
                on_date=date(2026, 6, 1),
                cash_amount=Decimal("45.00"),
            ),
            ReplayTransaction(
                id=3,
                action=Action.REINVESTMENT,
                on_date=date(2026, 6, 1),
                sequence=1,
                quantity=Decimal("3"),
                unit_price=Decimal("15.00"),
            ),
        ]
    )

    assert result.total_quantity == Decimal("103")
    reinvested = result.lots[1]
    assert reinvested.from_reinvestment is True
    assert reinvested.remaining_cost == Decimal("45.00")
    assert reinvested.acquired == date(2026, 6, 1)


def test_a_reinvested_lot_is_consumed_by_fifo_like_any_other():
    result = replay(
        [
            buy(1, date(2026, 1, 1), "10", "10.00"),
            ReplayTransaction(
                id=2,
                action=Action.REINVESTMENT,
                on_date=date(2026, 2, 1),
                quantity=Decimal("5"),
                unit_price=Decimal("20.00"),
            ),
            sell(3, date(2026, 3, 1), "12", "30.00"),
        ]
    )

    consumed = result.disposals[0].consumed
    assert [c.lot_transaction_id for c in consumed] == [1, 2]
    assert result.disposals[0].cost_basis == Decimal("140.00")


# ---------------------------------------------------------------------------
# Ordering and purity
# ---------------------------------------------------------------------------


def test_transactions_replay_in_date_order_regardless_of_entry_order():
    forwards = replay(
        [buy(1, date(2026, 1, 1), "10", "1.00"), buy(2, date(2026, 2, 1), "10", "2.00")]
    )
    backwards = replay(
        [buy(2, date(2026, 2, 1), "10", "2.00"), buy(1, date(2026, 1, 1), "10", "1.00")]
    )

    assert [lot.transaction_id for lot in forwards.lots] == [1, 2]
    assert [lot.transaction_id for lot in backwards.lots] == [1, 2]


def test_same_day_transactions_use_the_sequence_to_stay_deterministic():
    """A non-deterministic cost basis is worse than a wrong one — it cannot be
    reproduced to be argued with."""
    result = replay(
        [
            ReplayTransaction(
                id=1, action=Action.BUY, on_date=date(2026, 1, 1), sequence=1,
                quantity=Decimal("10"), unit_price=Decimal("50.00"),
            ),
            ReplayTransaction(
                id=2, action=Action.BUY, on_date=date(2026, 1, 1), sequence=0,
                quantity=Decimal("10"), unit_price=Decimal("5.00"),
            ),
            sell(3, date(2026, 2, 1), "10", "60.00"),
        ]
    )

    # Sequence 0 was bought first, so it is consumed first.
    assert result.disposals[0].cost_basis == Decimal("50.00")


def test_replay_does_not_mutate_its_input():
    transactions = [buy(1, date(2026, 1, 1), "100", "10.00"), split(2, date(2026, 2, 1), "2")]
    before = list(transactions)

    replay(transactions)

    assert transactions == before
    assert transactions[0].quantity == Decimal("100")


def test_replay_is_deterministic():
    assert replay(SCENARIO) == replay(SCENARIO)


def test_an_empty_holding_replays_to_nothing():
    result = replay([])

    assert result.lots == ()
    assert result.total_quantity == Decimal("0")
    assert result.realised_gain == Decimal("0")
    assert result.is_consistent
