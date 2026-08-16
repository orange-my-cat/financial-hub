"""Month-on-month movement — one definition, and its two distinct nulls.

The distinction under test is the one FR-46 turns on: *no figure* and *a figure
of zero* are not the same month. A month nobody recorded has no change at all;
a month that genuinely held zero has a real change and no proportion.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.services.movement import movement

pytestmark = pytest.mark.invariant


def test_a_rise_states_both_halves():
    assert movement(Decimal("11000"), Decimal("10000")) == {
        "change": "1000.00",
        "change_percent": "10.0",
    }


def test_a_fall_is_signed_on_both_halves():
    assert movement(Decimal("9000"), Decimal("10000")) == {
        "change": "-1000.00",
        "change_percent": "-10.0",
    }


def test_a_rise_from_zero_has_no_proportion():
    """The change is real; the percentage has no denominator."""
    assert movement(Decimal("500"), Decimal("0")) == {
        "change": "500.00",
        "change_percent": None,
    }


@pytest.mark.parametrize(
    ("current", "prior"),
    [(None, Decimal("10000")), (Decimal("10000"), None), (None, None)],
)
def test_a_month_with_no_figure_has_no_change_rather_than_a_zero_one(current, prior):
    """A month nobody recorded is not a month worth zero (FR-46)."""
    assert movement(current, prior) == {"change": None, "change_percent": None}


def test_a_liability_heavy_month_moves_against_a_negative_prior():
    """Net worth is routinely negative, so the proportion uses the magnitude.

    Against -10,000, a move to -9,000 is a 10% improvement, not -10%. Dividing
    by the signed prior would invert the sign of every liability-heavy month.
    """
    assert movement(Decimal("-9000"), Decimal("-10000")) == {
        "change": "1000.00",
        "change_percent": "10.0",
    }


def test_the_change_is_rounded_once_from_full_precision():
    assert movement(Decimal("10000.12345"), Decimal("10000")) == {
        "change": "0.12",
        "change_percent": "0.0",
    }
