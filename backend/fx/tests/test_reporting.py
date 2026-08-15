"""Rate trend and the missing-and-stale summary.

The trend is honest about being sparse. Only month-end rates are required, so a
chart of a pair will usually be twelve points a year, and it draws a line through
the dates that exist rather than inventing points between them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.services.rate_lookup import Provenance
from fx.models import ExchangeRate
from fx.services.reporting import rate_status, rate_trend

pytestmark = pytest.mark.django_db

JAN_31 = date(2026, 1, 31)
FEB_28 = date(2026, 2, 28)
MAR_31 = date(2026, 3, 31)
START = date(2025, 1, 1)
END = date(2026, 12, 31)


def rate(currency: str, on: date, value: str) -> None:
    ExchangeRate.objects.create(currency=currency, rate_date=on, rate=Decimal(value))


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def test_a_stored_pair_plots_the_dates_that_exist():
    rate("AUD", JAN_31, "0.66")
    rate("AUD", FEB_28, "0.67")

    trend = rate_trend("AUD", "USD", START, END)

    assert [p.on_date for p in trend.points] == [JAN_31, FEB_28]
    assert [p.rate for p in trend.points] == [Decimal("0.660000"), Decimal("0.670000")]
    assert trend.pair == "AUD/USD"
    assert trend.is_derived is False


def test_points_outside_the_range_are_excluded():
    rate("AUD", date(2024, 6, 30), "0.60")
    rate("AUD", JAN_31, "0.66")

    trend = rate_trend("AUD", "USD", START, END)

    assert [p.on_date for p in trend.points] == [JAN_31]


def test_every_point_of_an_unstored_pair_is_labelled_derived():
    rate("AUD", JAN_31, "0.66")
    rate("MYR", JAN_31, "4.20")

    trend = rate_trend("AUD", "MYR", START, END)

    assert trend.is_derived is True
    assert all(p.is_derived for p in trend.points)
    assert trend.points[0].provenance is Provenance.TRIANGULATED
    assert trend.points[0].rate == Decimal("2.772000")


def test_a_triangulated_trend_plots_the_union_of_both_legs_dates():
    """Each point is a genuine observation of one leg, carried on the other."""
    rate("AUD", JAN_31, "0.66")
    rate("MYR", JAN_31, "4.20")
    rate("MYR", FEB_28, "4.40")

    trend = rate_trend("AUD", "MYR", START, END)

    assert [p.on_date for p in trend.points] == [JAN_31, FEB_28]
    # February uses February's MYR and January's carried AUD.
    assert trend.points[1].rate == Decimal("2.904000")


def test_a_point_is_omitted_where_one_leg_has_no_rate_yet():
    """A gap in the line is the truth; interpolating would not be."""
    rate("MYR", JAN_31, "4.20")
    rate("AUD", FEB_28, "0.66")

    trend = rate_trend("AUD", "MYR", START, END)

    assert [p.on_date for p in trend.points] == [FEB_28]


def test_a_pair_against_itself_has_no_trend():
    assert rate_trend("USD", "USD", START, END).points == ()


def test_an_empty_table_gives_an_empty_trend():
    assert rate_trend("AUD", "USD", START, END).points == ()


def test_the_trend_serialises_with_its_derived_flags():
    rate("AUD", JAN_31, "0.66")
    rate("MYR", JAN_31, "4.20")

    payload = rate_trend("AUD", "MYR", START, END).as_dict()

    assert payload["derived"] is True
    assert payload["points"][0]["provenance"] == "triangulated"
    assert payload["points"][0]["rate"] == "2.772000"


# ---------------------------------------------------------------------------
# Missing and stale
# ---------------------------------------------------------------------------


def test_a_pair_with_no_rate_at_all_is_missing():
    statuses = {s.currency: s for s in rate_status(JAN_31, staleness_days=7)}

    assert statuses["AUD"].is_missing is True
    assert statuses["AUD"].latest_rate is None
    assert statuses["AUD"].state == "No rate on record"


def test_a_fresh_pair_is_current():
    rate("AUD", JAN_31, "0.66")
    rate("MYR", JAN_31, "4.20")

    statuses = {s.currency: s for s in rate_status(JAN_31, staleness_days=7)}

    assert statuses["AUD"].state == "Current"
    assert statuses["AUD"].is_stale is False
    assert statuses["AUD"].age_days == 0


def test_a_stale_pair_states_its_age_in_days():
    rate("AUD", date(2026, 1, 1), "0.66")

    status = next(s for s in rate_status(JAN_31, staleness_days=7) if s.currency == "AUD")

    assert status.is_stale is True
    assert status.age_days == 30
    assert status.state == "30 days old"


def test_the_boundary_matches_the_lookup_service():
    rate("AUD", date(2026, 1, 24), "0.66")  # exactly 7 days

    status = next(s for s in rate_status(JAN_31, staleness_days=7) if s.currency == "AUD")

    assert status.is_stale is False


def test_every_quoted_pair_appears_and_the_base_never_does():
    statuses = rate_status(JAN_31, staleness_days=7)

    assert {s.currency for s in statuses} == {"AUD", "MYR"}


def test_the_status_carries_the_quote_label_so_direction_is_never_in_doubt():
    statuses = {s.currency: s for s in rate_status(JAN_31, staleness_days=7)}

    assert statuses["AUD"].quote_label == "USD per 1 AUD"
    assert statuses["MYR"].quote_label == "MYR per 1 USD"


def test_a_future_rate_does_not_count_as_current():
    rate("AUD", MAR_31, "0.66")

    status = next(s for s in rate_status(JAN_31, staleness_days=7) if s.currency == "AUD")

    assert status.is_missing is True


def test_the_status_serialises():
    rate("AUD", JAN_31, "0.66")

    payload = next(
        s for s in rate_status(JAN_31, staleness_days=7) if s.currency == "AUD"
    ).as_dict()

    assert payload["pair"] == "AUD/USD"
    assert payload["as_at"] == "2026-01-31"
    assert payload["missing"] is False
    # Trimmed the same way the daily table trims it, so one screen does not show
    # the same rate two ways.
    assert payload["rate"] == "0.66"
