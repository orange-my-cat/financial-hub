"""Recording rates — including the advisory that must never block.

The rate-variance advisory is the only thing in this system that would catch a
misplaced decimal on a rate. A wrong rate misstates every foreign balance for
that month and nothing else notices. But a genuine 12% move in a month is not an
error, so it advises and saves; it does not refuse.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db.utils import IntegrityError

from core.services.advisories import AdvisoryKind
from core.services.exceptions import BusinessRuleError, NotFoundError
from fx.models import ExchangeRate, RateSource
from fx.services.entry import delete_rate, record_rate, record_rates_for_date

pytestmark = pytest.mark.django_db

JAN_31 = date(2026, 1, 31)
FEB_28 = date(2026, 2, 28)


def test_recording_a_rate_stores_it_with_its_provenance():
    result = record_rate("AUD", JAN_31, Decimal("0.66"))

    assert result.created is True
    assert result.rate.rate == Decimal("0.66")
    assert result.rate.source == RateSource.ENTERED
    assert result.rate.pair == "AUD/USD"
    assert result.advisories == ()


def test_recording_the_same_pair_and_date_again_replaces_rather_than_duplicates():
    record_rate("AUD", JAN_31, Decimal("0.66"))
    result = record_rate("AUD", JAN_31, Decimal("0.67"))

    assert result.created is False
    assert ExchangeRate.objects.filter(currency="AUD", rate_date=JAN_31).count() == 1
    assert ExchangeRate.objects.get(currency="AUD", rate_date=JAN_31).rate == Decimal("0.67")


def test_the_database_refuses_a_duplicate_written_around_the_service():
    """A rule enforced only in application code holds until something writes
    around it (§9.1)."""
    ExchangeRate.objects.create(currency="AUD", rate_date=JAN_31, rate=Decimal("0.66"))

    with pytest.raises(IntegrityError):
        ExchangeRate.objects.create(
            currency="AUD", rate_date=JAN_31, rate=Decimal("0.67")
        )


def test_the_database_refuses_a_rate_for_the_base_against_itself():
    with pytest.raises(IntegrityError):
        ExchangeRate.objects.create(
            currency="USD", rate_date=JAN_31, rate=Decimal("1")
        )


def test_the_service_refuses_the_base_currency_with_an_explanation():
    with pytest.raises(BusinessRuleError, match="always 1 and is never entered"):
        record_rate("USD", JAN_31, Decimal("1"))


def test_the_database_refuses_a_non_positive_rate():
    with pytest.raises(IntegrityError):
        ExchangeRate.objects.create(currency="AUD", rate_date=JAN_31, rate=Decimal("0"))


def test_the_service_refuses_a_non_positive_rate_with_a_field_error():
    with pytest.raises(BusinessRuleError) as caught:
        record_rate("AUD", JAN_31, Decimal("-1"))

    assert caught.value.field == "rate"
    assert caught.value.code == "rate_not_positive"


# ---------------------------------------------------------------------------
# The rate-variance advisory — advises, never blocks
# ---------------------------------------------------------------------------


def test_a_large_move_advises_and_still_saves():
    record_rate("AUD", JAN_31, Decimal("0.66"))

    result = record_rate("AUD", FEB_28, Decimal("0.90"), variance_percent=Decimal("10"))

    assert len(result.advisories) == 1
    advisory = result.advisories[0]
    assert advisory.kind is AdvisoryKind.RATE_VARIANCE
    # The data was saved. That is what makes it an advisory.
    assert ExchangeRate.objects.get(currency="AUD", rate_date=FEB_28).rate == Decimal("0.90")


def test_the_advisory_states_the_previous_rate_and_the_difference():
    record_rate("AUD", JAN_31, Decimal("0.66"))

    advisory = record_rate("AUD", FEB_28, Decimal("0.99")).advisories[0]

    assert advisory.detail["previous_rate"] == "0.66"
    assert advisory.detail["previous_as_at"] == "2026-01-31"
    assert advisory.detail["difference_percent"] == "+50.00"
    assert "AUD/USD" in advisory.message


def test_a_misplaced_decimal_is_exactly_what_this_catches():
    record_rate("MYR", JAN_31, Decimal("4.20"))

    result = record_rate("MYR", FEB_28, Decimal("42.0"))

    assert result.advisories
    assert "900.00" in result.advisories[0].detail["difference_percent"]


def test_a_move_within_the_threshold_is_silent():
    record_rate("AUD", JAN_31, Decimal("0.66"))

    result = record_rate("AUD", FEB_28, Decimal("0.70"), variance_percent=Decimal("10"))

    assert result.advisories == ()


def test_a_move_exactly_at_the_threshold_is_silent():
    record_rate("AUD", JAN_31, Decimal("1.00"))

    result = record_rate("AUD", FEB_28, Decimal("1.10"), variance_percent=Decimal("10"))

    assert result.advisories == ()


def test_a_downward_move_is_measured_too():
    record_rate("AUD", JAN_31, Decimal("1.00"))

    advisory = record_rate("AUD", FEB_28, Decimal("0.50")).advisories[0]

    assert advisory.detail["difference_percent"] == "-50.00"


def test_the_first_rate_for_a_pair_has_nothing_to_compare_against():
    assert record_rate("AUD", JAN_31, Decimal("0.66")).advisories == ()


def test_the_comparison_is_against_the_predecessor_not_the_row_being_replaced():
    """Editing a rate should compare with the rate before it, not with itself."""
    record_rate("AUD", JAN_31, Decimal("0.66"))
    record_rate("AUD", FEB_28, Decimal("0.67"))

    result = record_rate("AUD", FEB_28, Decimal("0.68"))

    assert result.advisories == ()


def test_the_threshold_is_configurable():
    record_rate("AUD", JAN_31, Decimal("1.00"))

    tight = record_rate("AUD", FEB_28, Decimal("1.05"), variance_percent=Decimal("1"))

    assert tight.advisories


# ---------------------------------------------------------------------------
# Bulk entry — one date, committed as a unit
# ---------------------------------------------------------------------------


def test_bulk_entry_records_every_pair_for_the_date():
    saved, advisories = record_rates_for_date(
        JAN_31, {"AUD": Decimal("0.66"), "MYR": Decimal("4.20")}
    )

    assert len(saved) == 2
    assert advisories == ()
    assert ExchangeRate.objects.count() == 2


def test_bulk_entry_collects_advisories_across_pairs():
    record_rates_for_date(JAN_31, {"AUD": Decimal("0.66"), "MYR": Decimal("4.20")})

    _, advisories = record_rates_for_date(
        FEB_28, {"AUD": Decimal("0.99"), "MYR": Decimal("8.40")}
    )

    assert len(advisories) == 2
    assert {a.detail["currency"] for a in advisories} == {"AUD", "MYR"}


def test_bulk_entry_rolls_back_entirely_when_one_pair_is_invalid():
    """Half the rates landing would translate a month on a mixture of dates."""
    with pytest.raises(BusinessRuleError):
        record_rates_for_date(JAN_31, {"AUD": Decimal("0.66"), "MYR": Decimal("-1")})

    assert ExchangeRate.objects.count() == 0


def test_bulk_entry_of_nothing_is_refused():
    with pytest.raises(BusinessRuleError, match="No rates"):
        record_rates_for_date(JAN_31, {})


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def test_deleting_a_rate_is_soft():
    record_rate("AUD", JAN_31, Decimal("0.66"))

    delete_rate("AUD", JAN_31)

    assert ExchangeRate.objects.count() == 0
    assert ExchangeRate.all_objects.count() == 1


def test_the_same_pair_and_date_can_be_entered_again_after_a_delete():
    """The unique constraint is scoped to live rows, so a delete does not
    poison that slot forever."""
    record_rate("AUD", JAN_31, Decimal("0.66"))
    delete_rate("AUD", JAN_31)

    result = record_rate("AUD", JAN_31, Decimal("0.70"))

    assert result.created is True
    assert ExchangeRate.objects.count() == 1
    assert ExchangeRate.all_objects.count() == 2


def test_deleting_a_rate_that_is_not_there_is_refused():
    """NotFoundError, so the API layer answers 404 rather than 400."""
    with pytest.raises(NotFoundError, match="No AUD/USD rate"):
        delete_rate("AUD", JAN_31)
