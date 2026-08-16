"""The currency conventions, and reporting-month arithmetic.

The convention test matters more than it looks. AUD and MYR are quoted in
opposite directions, and getting one backwards misstates every balance in that
currency for every month — silently, and in a way that looks plausible.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core import months
from core.currencies import (
    BASE_CURRENCY,
    QUOTED_CURRENCY_CODES,
    QuoteConvention,
    definition,
    pair_label,
    usd_per_unit,
    usd_ratio,
)

pytestmark = pytest.mark.invariant


# ---------------------------------------------------------------------------
# Conventions
# ---------------------------------------------------------------------------


def test_usd_is_the_base_and_is_not_a_quoted_pair():
    assert BASE_CURRENCY == "USD"
    assert "USD" not in QUOTED_CURRENCY_CODES


def test_aud_is_quoted_as_usd_per_one_aud():
    assert definition("AUD").convention is QuoteConvention.USD_PER_UNIT
    assert definition("AUD").quote_label == "USD per 1 AUD"
    # 0.66 typed means one AUD is worth 0.66 USD — used as-is.
    assert usd_per_unit("AUD", Decimal("0.66")) == Decimal("0.66")


def test_myr_is_quoted_as_myr_per_one_usd():
    assert definition("MYR").convention is QuoteConvention.UNITS_PER_USD
    assert definition("MYR").quote_label == "MYR per 1 USD"
    # 4.20 typed means one USD is worth 4.20 MYR, so one MYR is 1/4.20 USD.
    assert usd_per_unit("MYR", Decimal("4.20")) == Decimal(1) / Decimal("4.20")


def test_the_pair_label_reads_in_its_own_direction():
    assert pair_label("AUD") == "AUD/USD"
    assert pair_label("MYR") == "USD/MYR"


def test_the_base_against_itself_is_one():
    assert usd_per_unit("USD", Decimal("999")) == Decimal(1)
    assert usd_ratio("USD", Decimal("999")) == (Decimal(1), Decimal(1))


def test_the_ratio_is_returned_undivided():
    """So translating performs one division rather than two."""
    assert usd_ratio("AUD", Decimal("0.66")) == (Decimal("0.66"), Decimal(1))
    assert usd_ratio("MYR", Decimal("4.20")) == (Decimal(1), Decimal("4.20"))


def test_a_non_positive_rate_is_refused():
    with pytest.raises(ValueError, match="greater than zero"):
        usd_per_unit("AUD", Decimal("0"))
    with pytest.raises(ValueError, match="greater than zero"):
        usd_ratio("MYR", Decimal("-1"))


def test_an_unknown_currency_is_refused():
    with pytest.raises(ValueError, match="not a currency"):
        definition("GBP")


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------


def test_a_reporting_month_ends_on_its_last_calendar_day():
    assert months.month_end("2026-01") == date(2026, 1, 31)
    assert months.month_end("2026-04") == date(2026, 4, 30)
    assert months.month_end("2026-02") == date(2026, 2, 28)


def test_february_in_a_leap_year():
    assert months.month_end("2028-02") == date(2028, 2, 29)


def test_month_start():
    assert months.month_start("2026-08") == date(2026, 8, 1)


def test_month_of_a_date():
    assert months.month_of(date(2026, 8, 15)) == "2026-08"


# -- as-at ------------------------------------------------------------------


def test_a_month_that_has_ended_is_valued_at_its_last_day():
    assert months.as_at_of("2026-07", today=date(2026, 8, 16)) == date(2026, 7, 31)


def test_the_month_in_progress_is_valued_at_today():
    """The 31st has not happened, so nothing can be recorded as at the 31st."""
    assert months.as_at_of("2026-08", today=date(2026, 8, 16)) == date(2026, 8, 16)


def test_the_last_day_of_the_current_month_is_both_answers_at_once():
    assert months.as_at_of("2026-08", today=date(2026, 8, 31)) == date(2026, 8, 31)


def test_a_month_that_has_not_begun_keeps_its_own_month_end():
    """Today is not inside it, so today is not its as-at date."""
    assert months.as_at_of("2026-12", today=date(2026, 8, 16)) == date(2026, 12, 31)


def test_as_at_refuses_something_that_is_not_a_month():
    with pytest.raises(ValueError, match="not a reporting month"):
        months.as_at_of("2026-8", today=date(2026, 8, 16))


def test_shifting_across_a_year_boundary():
    assert months.previous("2026-01") == "2025-12"
    assert months.following("2025-12") == "2026-01"
    assert months.shift("2026-01", -13) == "2024-12"
    assert months.shift("2024-12", 13) == "2026-01"


def test_distance_counts_whole_months_and_signs_them():
    assert months.distance("2026-01", "2026-01") == 0
    assert months.distance("2025-12", "2026-03") == 3
    assert months.distance("2026-03", "2025-12") == -3


def test_a_sequence_is_inclusive_at_both_ends():
    assert months.sequence("2026-01", "2026-03") == ("2026-01", "2026-02", "2026-03")


def test_a_reversed_range_is_empty_rather_than_an_error():
    assert months.sequence("2026-03", "2026-01") == ()


def test_descending_is_the_order_the_spine_reads_in():
    assert months.descending("2026-01", "2026-03") == ("2026-03", "2026-02", "2026-01")


def test_months_sort_chronologically_as_plain_strings():
    """The property the whole derived-month design leans on."""
    assert sorted(["2026-01", "2025-12", "2026-10", "2026-02"]) == [
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-10",
    ]


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "202601", "2026-1", "nonsense"])
def test_a_malformed_month_is_refused(bad):
    with pytest.raises(ValueError, match="not a reporting month"):
        months.require_month(bad)


# ---------------------------------------------------------------------------
# Rate formatting for human eyes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ("0.6600000000", "0.66"),
        ("4.2000000000", "4.2"),
        # normalize() alone renders this as 4.2E+3, which is worse than the
        # padding it was fixing.
        ("4200.0000000000", "4200"),
        ("1.0000000000", "1"),
        ("0.0000000001", "0.0000000001"),
    ],
)
def test_a_rate_is_shown_as_a_person_would_write_it(stored, shown):
    from core.currencies import format_rate

    assert format_rate(Decimal(stored)) == shown
