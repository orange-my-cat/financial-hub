"""BR-09, by name — every documented edge case, one test each.

ADR-17 is explicit that coverage is the floor and named edge cases are the
ceiling: a lookup can reach 100% line coverage from a single exact hit while
never testing a carry-forward across a gap, a triangulation, or the staleness
boundary. These are the cases the design actually names.

The two rates in use are quoted in opposite market conventions, which is the
single easiest thing to get backwards:

    AUD    0.6600    USD per 1 AUD
    MYR    4.2000    MYR per 1 USD
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.services.rate_lookup import Provenance, RateResolver
from fx.models import ExchangeRate

pytestmark = [pytest.mark.django_db, pytest.mark.invariant]

JAN_31 = date(2026, 1, 31)
FEB_28 = date(2026, 2, 28)


def rate(currency: str, on: date, value: str) -> ExchangeRate:
    return ExchangeRate.objects.create(
        currency=currency, rate_date=on, rate=Decimal(value)
    )


# ---------------------------------------------------------------------------
# BR-09 — exact hit
# ---------------------------------------------------------------------------


def test_exact_hit_uses_the_rate_recorded_on_that_date():
    rate("AUD", JAN_31, "0.66")

    quote = RateResolver().quote("AUD", "USD", JAN_31)

    assert quote is not None
    assert quote.factor == Decimal("0.66")
    assert quote.as_at == JAN_31
    assert quote.provenance is Provenance.EXACT
    assert quote.age_days == 0
    assert quote.is_stale is False


def test_the_reverse_direction_is_the_reciprocal():
    rate("AUD", JAN_31, "0.66")

    quote = RateResolver().quote("USD", "AUD", JAN_31)

    assert quote is not None
    # 1 / 0.66 = 1.5151... AUD to the USD. Non-terminating, and carried at full
    # precision rather than rounded here.
    assert quote.factor == Decimal(1) / Decimal("0.66")
    assert quote.provenance is Provenance.EXACT


def test_a_units_per_usd_pair_is_read_in_its_own_convention():
    """MYR is quoted as MYR per 1 USD, the opposite way round from AUD."""
    rate("MYR", JAN_31, "4.20")

    resolver = RateResolver()

    # 1 USD buys 4.20 MYR — the number as typed.
    assert resolver.quote("USD", "MYR", JAN_31).factor == Decimal("4.20")
    # And 1 MYR buys 1/4.20 USD.
    assert resolver.quote("MYR", "USD", JAN_31).factor == Decimal(1) / Decimal("4.20")


# ---------------------------------------------------------------------------
# BR-09 / FR-44 — carry-forward across a gap
# ---------------------------------------------------------------------------


def test_carry_forward_uses_the_most_recent_earlier_rate():
    """Given a rate on the 20th and none since, the 31st uses the 20th's."""
    rate("AUD", date(2026, 1, 20), "0.66")

    quote = RateResolver(staleness_days=30).quote("AUD", "USD", JAN_31)

    assert quote is not None
    assert quote.factor == Decimal("0.66")
    assert quote.as_at == date(2026, 1, 20)
    assert quote.provenance is Provenance.CARRIED
    assert quote.age_days == 11


def test_carry_forward_takes_the_nearest_earlier_rate_not_the_oldest():
    rate("AUD", date(2025, 6, 30), "0.62")
    rate("AUD", date(2026, 1, 20), "0.66")

    quote = RateResolver(staleness_days=365).quote("AUD", "USD", JAN_31)

    assert quote.as_at == date(2026, 1, 20)
    assert quote.factor == Decimal("0.66")


def test_a_later_rate_is_never_used_for_an_earlier_date():
    """A rate entered in February must not retroactively value January."""
    rate("AUD", FEB_28, "0.70")

    assert RateResolver().quote("AUD", "USD", JAN_31) is None


def test_carry_forward_spans_months_and_years():
    rate("MYR", date(2024, 12, 31), "4.40")

    quote = RateResolver(staleness_days=10_000).quote("USD", "MYR", date(2026, 3, 31))

    assert quote.factor == Decimal("4.40")
    assert quote.provenance is Provenance.CARRIED
    assert quote.as_at == date(2024, 12, 31)


# ---------------------------------------------------------------------------
# BR-09 / FR-46 — no rate at any earlier date
# ---------------------------------------------------------------------------


def test_no_rate_at_any_earlier_date_returns_nothing_not_zero():
    """The FR-46 case. `None` is not a number, and cannot be added to a total."""
    quote = RateResolver().quote("AUD", "USD", JAN_31)

    assert quote is None


def test_a_triangulated_pair_is_unavailable_when_either_leg_is_missing():
    rate("AUD", JAN_31, "0.66")  # MYR has nothing

    assert RateResolver().quote("AUD", "MYR", JAN_31) is None
    assert RateResolver().quote("MYR", "AUD", JAN_31) is None


# ---------------------------------------------------------------------------
# BR-09 — the base against itself is always 1 and is never entered
# ---------------------------------------------------------------------------


def test_the_base_against_itself_is_one_without_any_rate_being_recorded():
    quote = RateResolver().quote("USD", "USD", JAN_31)

    assert quote is not None
    assert quote.factor == Decimal(1)
    assert quote.provenance is Provenance.EXACT
    assert quote.is_stale is False
    assert quote.legs == ()
    assert ExchangeRate.objects.count() == 0


def test_any_currency_against_itself_is_one():
    quote = RateResolver().quote("MYR", "MYR", JAN_31)

    assert quote.factor == Decimal(1)
    assert quote.legs == ()


# ---------------------------------------------------------------------------
# ADR-08 — triangulation through USD, computed on demand and never stored
# ---------------------------------------------------------------------------


def test_aud_to_myr_is_triangulated_through_usd():
    rate("AUD", JAN_31, "0.66")   # USD per 1 AUD
    rate("MYR", JAN_31, "4.20")   # MYR per 1 USD

    quote = RateResolver().quote("AUD", "MYR", JAN_31)

    assert quote is not None
    assert quote.provenance is Provenance.TRIANGULATED
    # 1 AUD = 0.66 USD = 0.66 x 4.20 = 2.772 MYR. Exactly, with no trailing
    # error: the ratio is cross-multiplied so only one division ever happens.
    assert quote.factor == Decimal("2.772")
    assert len(quote.legs) == 2


def test_triangulation_is_symmetric():
    rate("AUD", JAN_31, "0.66")
    rate("MYR", JAN_31, "4.20")

    resolver = RateResolver()
    there = resolver.quote("AUD", "MYR", JAN_31).factor
    back = resolver.quote("MYR", "AUD", JAN_31).factor

    assert there * back == Decimal(1)


def test_no_triangulated_rate_is_ever_stored():
    """Storing a derived rate creates a second copy that can disagree (ADR-08)."""
    rate("AUD", JAN_31, "0.66")
    rate("MYR", JAN_31, "4.20")

    RateResolver().quote("AUD", "MYR", JAN_31)

    assert ExchangeRate.objects.count() == 2
    assert set(ExchangeRate.objects.values_list("currency", flat=True)) == {"AUD", "MYR"}


def test_a_triangulated_quote_carries_the_oldest_contributing_date():
    """Erring toward overstating staleness is the safe direction (ADR-09)."""
    rate("AUD", date(2026, 1, 5), "0.66")
    rate("MYR", JAN_31, "4.20")

    quote = RateResolver(staleness_days=365).quote("AUD", "MYR", JAN_31)

    assert quote.as_at == date(2026, 1, 5)
    assert quote.age_days == 26
    assert quote.provenance is Provenance.TRIANGULATED


def test_a_triangulated_quote_is_stale_when_its_oldest_leg_is():
    rate("AUD", date(2026, 1, 1), "0.66")
    rate("MYR", JAN_31, "4.20")

    quote = RateResolver(staleness_days=7).quote("AUD", "MYR", JAN_31)

    assert quote.is_stale is True
    assert quote.as_at == date(2026, 1, 1)


# ---------------------------------------------------------------------------
# ADR-09 — the staleness boundary, at exactly the threshold
# ---------------------------------------------------------------------------


def test_a_rate_exactly_at_the_threshold_is_not_yet_stale():
    """"Breaches" means exceeds. Seven days old against a seven-day threshold
    is the last day it is fine."""
    rate("AUD", date(2026, 1, 24), "0.66")  # 7 days before the 31st

    quote = RateResolver(staleness_days=7).quote("AUD", "USD", JAN_31)

    assert quote.age_days == 7
    assert quote.is_stale is False


def test_a_rate_one_day_past_the_threshold_is_stale():
    rate("AUD", date(2026, 1, 23), "0.66")  # 8 days

    quote = RateResolver(staleness_days=7).quote("AUD", "USD", JAN_31)

    assert quote.age_days == 8
    assert quote.is_stale is True


def test_the_threshold_is_configurable():
    rate("AUD", date(2026, 1, 1), "0.66")

    assert RateResolver(staleness_days=7).quote("AUD", "USD", JAN_31).is_stale is True
    assert RateResolver(staleness_days=60).quote("AUD", "USD", JAN_31).is_stale is False


def test_an_exact_rate_is_never_stale():
    rate("AUD", JAN_31, "0.66")

    assert RateResolver(staleness_days=0).quote("AUD", "USD", JAN_31).is_stale is False


# ---------------------------------------------------------------------------
# BR-09 — editing a historic rate restates what used it
# ---------------------------------------------------------------------------


def test_editing_a_historic_rate_changes_what_a_later_lookup_returns():
    """Free, because no computed figure is ever persisted (ADR-05). There is no
    cache to invalidate and no total to drift."""
    row = rate("AUD", JAN_31, "0.66")
    assert RateResolver().quote("AUD", "USD", JAN_31).factor == Decimal("0.66")

    row.rate = Decimal("0.70")
    row.save()

    assert RateResolver().quote("AUD", "USD", JAN_31).factor == Decimal("0.70")


def test_a_soft_deleted_rate_is_invisible_to_the_lookup():
    rate("AUD", date(2026, 1, 10), "0.60")
    newer = rate("AUD", date(2026, 1, 20), "0.66")

    newer.delete()

    quote = RateResolver(staleness_days=365).quote("AUD", "USD", JAN_31)
    assert quote.factor == Decimal("0.60")
    assert quote.as_at == date(2026, 1, 10)


# ---------------------------------------------------------------------------
# The resolver's cache
# ---------------------------------------------------------------------------


def test_repeated_lookups_hit_the_cache(django_assert_num_queries):
    rate("AUD", JAN_31, "0.66")
    resolver = RateResolver()

    with django_assert_num_queries(1):
        for _ in range(5):
            resolver.quote("AUD", "USD", JAN_31)


def test_a_fresh_resolver_sees_an_edit():
    """One resolver per request. An edited rate must restate the next report."""
    row = rate("AUD", JAN_31, "0.66")
    RateResolver().quote("AUD", "USD", JAN_31)

    row.rate = Decimal("0.70")
    row.save()

    assert RateResolver().quote("AUD", "USD", JAN_31).factor == Decimal("0.70")


def test_an_unknown_currency_is_refused():
    with pytest.raises(ValueError, match="not a currency"):
        RateResolver().quote("GBP", "USD", JAN_31)
