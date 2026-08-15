"""Money is exact decimal, never a float, and never crosses currencies silently."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.money import CurrencyMismatch, Money, total

pytestmark = pytest.mark.invariant


def test_a_float_is_refused_at_construction():
    """A float cannot represent 0.10 exactly, so it never gets in."""
    with pytest.raises(TypeError, match="cannot represent"):
        Money(0.1, "USD")  # type: ignore[arg-type]


def test_an_unknown_currency_is_refused():
    with pytest.raises(ValueError, match="not a currency"):
        Money(Decimal("1"), "XYZ")


def test_adding_two_currencies_is_refused():
    with pytest.raises(CurrencyMismatch, match="translation service"):
        Money(Decimal("100"), "AUD") + Money(Decimal("100"), "USD")


def test_subtracting_two_currencies_is_refused():
    with pytest.raises(CurrencyMismatch):
        Money(Decimal("100"), "AUD") - Money(Decimal("100"), "USD")


def test_comparing_two_currencies_is_refused():
    with pytest.raises(CurrencyMismatch):
        _ = Money(Decimal("100"), "AUD") < Money(Decimal("100"), "USD")


def test_adding_within_one_currency_works():
    assert Money(Decimal("100.25"), "USD") + Money(Decimal("0.75"), "USD") == Money(
        Decimal("101.00"), "USD"
    )


def test_multiplying_two_money_values_is_refused():
    """Squared currency is not a thing."""
    with pytest.raises(TypeError, match="not meaningful"):
        Money(Decimal("2"), "USD") * Money(Decimal("3"), "USD")


def test_scaling_by_a_decimal_is_allowed():
    assert Money(Decimal("10"), "USD") * Decimal("2.5") == Money(Decimal("25.0"), "USD")


def test_scaling_by_a_float_is_refused():
    with pytest.raises(TypeError):
        Money(Decimal("10"), "USD") * 2.5


def test_the_liability_sign_is_applied_by_negation():
    assert -Money(Decimal("1500"), "USD") == Money(Decimal("-1500"), "USD")


# ---------------------------------------------------------------------------
# Rounding — once, at display, half-up
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.005", "1.01"),    # half rounds up, not to even
        ("1.015", "1.02"),
        ("2.675", "2.68"),
        ("-1.005", "-1.01"),  # away from zero, matching a bank statement
        ("-2.675", "-2.68"),
        ("0.994", "0.99"),
        ("1234.5650", "1234.57"),
    ],
)
def test_rounding_is_half_up_not_bankers(raw, expected):
    """Python's default is half-even, which disagrees with every spreadsheet
    the user will check these figures against."""
    assert Money(Decimal(raw), "USD").rounded() == Decimal(expected)


def test_full_precision_is_kept_until_rounding():
    value = Money(Decimal("0.123456789"), "USD")

    assert value.amount == Decimal("0.123456789")
    assert value.rounded() == Decimal("0.12")


def test_summing_rounds_once_rather_than_per_addend():
    """Three amounts that each round down still carry their thirds into the total."""
    amounts = [Money(Decimal("0.004"), "USD")] * 3

    assert total(amounts).amount == Decimal("0.012")
    assert total(amounts).rounded() == Decimal("0.01")
    # Rounding first would have produced 0.00 three times.
    assert sum(a.rounded() for a in amounts) == Decimal("0.00")


def test_the_api_form_is_a_string_and_a_code():
    assert Money(Decimal("1234.5"), "AUD").api() == {
        "amount": "1234.50",
        "currency": "AUD",
    }


# ---------------------------------------------------------------------------
# total()
# ---------------------------------------------------------------------------


def test_total_refuses_to_cross_currencies():
    with pytest.raises(CurrencyMismatch):
        total([Money(Decimal("1"), "USD"), Money(Decimal("1"), "AUD")])


def test_total_of_nothing_needs_a_currency():
    with pytest.raises(ValueError, match="needs a currency"):
        total([])


def test_total_of_nothing_in_a_stated_currency_is_zero():
    assert total([], "MYR") == Money(Decimal(0), "MYR")


def test_total_checks_the_stated_currency_against_the_contents():
    with pytest.raises(CurrencyMismatch):
        total([Money(Decimal("1"), "USD")], "AUD")
