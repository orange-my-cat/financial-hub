"""Money is exact decimal, and never a float (ADR-02).

Stage 1 builds the money primitives. What Stage 0 fixes is the shape every
number in this system takes, because changing a column's precision later is a
data migration against a decade of rows.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import models

from core.models import (
    MONEY_DIGITS,
    MONEY_PLACES,
    PRICE_DIGITS,
    PRICE_PLACES,
    QUANTITY_DIGITS,
    QUANTITY_PLACES,
    money_field,
    price_field,
    quantity_field,
)


@pytest.mark.parametrize(
    ("factory", "digits", "places"),
    [
        (money_field, MONEY_DIGITS, MONEY_PLACES),
        (quantity_field, QUANTITY_DIGITS, QUANTITY_PLACES),
        (price_field, PRICE_DIGITS, PRICE_PLACES),
    ],
)
def test_the_three_shapes_a_number_takes(factory, digits, places):
    field = factory()

    assert isinstance(field, models.DecimalField)
    assert not isinstance(field, models.FloatField)
    assert field.max_digits == digits
    assert field.decimal_places == places


def test_the_documented_precisions():
    """NUMERIC(19,4) money, (19,10) quantities and rates, (19,8) unit prices."""
    assert (MONEY_DIGITS, MONEY_PLACES) == (19, 4)
    assert (QUANTITY_DIGITS, QUANTITY_PLACES) == (19, 10)
    assert (PRICE_DIGITS, PRICE_PLACES) == (19, 8)


def test_field_options_pass_through():
    field = money_field(null=True, default=Decimal("0"))

    assert field.null is True
    assert field.max_digits == MONEY_DIGITS
