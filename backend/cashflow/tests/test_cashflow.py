"""Cash flow — BR-12 to BR-15 and BR-22.

The rule with the most consequences is the one that produces no code at all:
**no report sums cash flow figures together with balance figures** (BR-12). It
is tested here by asserting that the reporting service never translates and
never reaches into accounts — because the day something does, the double count
BR-15 exists to prevent arrives quietly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone

from core.services.advisories import AdvisoryKind
from core.services.exceptions import BusinessRuleError, ConflictError
from cashflow.models import (
    Category,
    Direction,
    Frequency,
    RecurringDismissal,
    RecurringTemplate,
    Transaction,
)
from cashflow.services import categories, recurring, reporting
from cashflow.services.entry import (
    delete_transaction,
    record_transaction,
    update_transaction,
)

pytestmark = pytest.mark.django_db


def child(name: str) -> Category:
    return Category.objects.get(name=name, parent__isnull=False)


def parent(name: str, direction: str = Direction.EXPENSE) -> Category:
    return Category.objects.get(name=name, parent__isnull=True, direction=direction)


# ---------------------------------------------------------------------------
# BR-22 — the seeded taxonomy
# ---------------------------------------------------------------------------


def test_the_taxonomy_is_seeded_two_levels_deep():
    assert Category.objects.filter(parent__isnull=True).count() == 12
    assert Category.objects.filter(parent__isnull=False).exists()
    # No grandchildren. Two levels and no deeper.
    assert not Category.objects.filter(parent__parent__isnull=False).exists()


def test_dividends_and_realised_gains_are_not_seeded():
    """OI-06. They belong to Investments only (BR-15), and seeding a category
    that must never be used invites the double count BR-15 prevents."""
    gains = parent("Gains", Direction.INCOME)

    assert list(gains.children.values_list("name", flat=True)) == ["Interest"]
    assert not Category.objects.filter(name="Dividends").exists()
    assert not Category.objects.filter(name="Realised Investment Gains").exists()


def test_interest_is_seeded_because_it_attaches_to_a_cash_account():
    """A savings account has no holding to attach interest to (BR-15)."""
    assert child("Interest").parent.name == "Gains"
    assert child("Interest").direction == Direction.INCOME


def test_every_category_is_title_case():
    for name in Category.objects.values_list("name", flat=True):
        assert name == name[0].upper() + name[1:], name


# ---------------------------------------------------------------------------
# BR-13 — entry
# ---------------------------------------------------------------------------


def test_recording_a_transaction_takes_its_direction_from_the_category():
    result = record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("82.40"),
        currency="AUD",
        category_id=child("Groceries").pk,
    )

    assert result.transaction.direction == Direction.EXPENSE
    assert result.advisories == ()


def test_income_categories_produce_income_transactions():
    result = record_transaction(
        on_date=date(2026, 7, 25),
        amount=Decimal("5000"),
        currency="USD",
        category_id=child("Salary").pk,
    )

    assert result.transaction.direction == Direction.INCOME


def test_a_parent_category_is_not_selectable():
    """Parents exist for rollup only (BR-22)."""
    with pytest.raises(BusinessRuleError, match="rollup only"):
        record_transaction(
            on_date=date(2026, 7, 15),
            amount=Decimal("10"),
            currency="USD",
            category_id=parent("Food").pk,
        )


def test_a_deactivated_category_is_unavailable_for_new_transactions():
    groceries = child("Groceries")
    categories.set_active(groceries, False)

    with pytest.raises(BusinessRuleError, match="deactivated"):
        record_transaction(
            on_date=date(2026, 7, 15),
            amount=Decimal("10"),
            currency="USD",
            category_id=groceries.pk,
        )


def test_the_amount_is_entered_positive_whichever_direction_it_is():
    with pytest.raises(BusinessRuleError, match="positive figure"):
        record_transaction(
            on_date=date(2026, 7, 15),
            amount=Decimal("-10"),
            currency="USD",
            category_id=child("Groceries").pk,
        )


def test_the_database_refuses_a_non_positive_amount():
    with pytest.raises(IntegrityError):
        Transaction.objects.create(
            date=date(2026, 7, 15),
            amount=Decimal("0"),
            currency="USD",
            direction=Direction.EXPENSE,
            category=child("Groceries"),
        )


def test_the_two_one_way_doors_are_captured_and_default_to_empty():
    """Read by nothing in v1, and impossible to add retrospectively (ADR-13)."""
    result = record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("10"),
        currency="USD",
        category_id=child("Groceries").pk,
    )

    assert result.transaction.account_id is None
    assert result.transaction.import_batch is None


def test_there_is_no_transfer_category_anywhere():
    """Moving money between your own accounts is not a transaction (BR-11)."""
    names = {name.lower() for name in Category.objects.values_list("name", flat=True)}

    assert "transfer" not in names
    assert not any("transfer" in name for name in names)


# ---------------------------------------------------------------------------
# FR-23 — the probable-duplicate advisory
# ---------------------------------------------------------------------------


def test_a_matching_date_amount_and_category_advises_and_still_saves():
    fields = dict(
        on_date=date(2026, 7, 15),
        amount=Decimal("4.50"),
        currency="AUD",
        category_id=child("Eating Out").pk,
    )
    record_transaction(**fields)

    result = record_transaction(**fields)

    assert result.advisories[0].kind is AdvisoryKind.PROBABLE_DUPLICATE
    # Two coffees on one day is ordinary. Both are saved.
    assert Transaction.objects.count() == 2


def test_the_advisory_does_not_fire_on_a_different_day():
    record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("4.50"),
        currency="AUD",
        category_id=child("Eating Out").pk,
    )

    result = record_transaction(
        on_date=date(2026, 7, 16),
        amount=Decimal("4.50"),
        currency="AUD",
        category_id=child("Eating Out").pk,
    )

    assert result.advisories == ()


def test_the_advisory_does_not_fire_on_a_different_category():
    record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("4.50"),
        currency="AUD",
        category_id=child("Eating Out").pk,
    )

    result = record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("4.50"),
        currency="AUD",
        category_id=child("Groceries").pk,
    )

    assert result.advisories == ()


def test_editing_a_transaction_does_not_flag_itself_as_its_own_duplicate():
    result = record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("4.50"),
        currency="AUD",
        category_id=child("Eating Out").pk,
    )

    updated = update_transaction(result.transaction, note="coffee")

    assert updated.advisories == ()


# ---------------------------------------------------------------------------
# BR-23 — everything is editable, deletes are soft
# ---------------------------------------------------------------------------


def test_a_transaction_can_be_recategorised_and_its_direction_follows():
    result = record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("100"),
        currency="USD",
        category_id=child("Groceries").pk,
    )

    updated = update_transaction(result.transaction, category_id=child("Salary").pk)

    assert updated.transaction.direction == Direction.INCOME


def test_deleting_a_transaction_is_soft():
    result = record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("100"),
        currency="USD",
        category_id=child("Groceries").pk,
    )

    delete_transaction(result.transaction)

    assert Transaction.objects.count() == 0
    assert Transaction.all_objects.count() == 1


# ---------------------------------------------------------------------------
# BR-22 — a used category is deactivated, never deleted
# ---------------------------------------------------------------------------


def test_an_unused_child_category_can_be_deleted():
    added = categories.add_child(parent("Food").pk, "Takeaway")

    categories.delete(added)

    assert not Category.objects.filter(name="Takeaway").exists()


def test_a_used_category_cannot_be_deleted():
    groceries = child("Groceries")
    record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("10"),
        currency="USD",
        category_id=groceries.pk,
    )

    with pytest.raises(BusinessRuleError, match="Deactivate it instead"):
        categories.delete(groceries)


def test_the_database_refuses_a_used_category_deletion_written_around_the_service():
    """Soft delete is an UPDATE, so on_delete=PROTECT never sees it (§9.1)."""
    groceries = child("Groceries")
    record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("10"),
        currency="USD",
        category_id=groceries.pk,
    )

    with pytest.raises(IntegrityError, match="BR-22"):
        with db_transaction.atomic():
            Category.objects.filter(pk=groceries.pk).update(deleted_at=timezone.now())


def test_a_parent_with_children_cannot_be_deleted():
    with pytest.raises(BusinessRuleError, match="child categories"):
        categories.delete(parent("Food"))


def test_deactivating_leaves_history_intact():
    groceries = child("Groceries")
    record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("10"),
        currency="USD",
        category_id=groceries.pk,
    )

    categories.set_active(groceries, False)

    assert Transaction.objects.count() == 1
    assert reporting.category_report("2026-07")[0]["children"][0]["category"] == "Groceries"


def test_deactivating_a_parent_takes_its_children_with_it():
    categories.set_active(parent("Food"), False)

    assert child("Groceries").is_active is False
    assert child("Eating Out").is_active is False


def test_renaming_restates_the_label_across_all_history():
    groceries = child("Groceries")
    record_transaction(
        on_date=date(2026, 7, 15),
        amount=Decimal("10"),
        currency="USD",
        category_id=groceries.pk,
    )

    categories.rename(groceries, "Supermarket")

    assert reporting.category_report("2026-07")[0]["children"][0]["category"] == "Supermarket"


def test_a_duplicate_name_within_a_parent_is_refused():
    with pytest.raises(ConflictError, match="already has a category"):
        categories.add_child(parent("Food").pk, "Groceries")


def test_the_taxonomy_is_two_levels_and_no_deeper():
    with pytest.raises(BusinessRuleError, match="two levels deep"):
        categories.add_child(child("Groceries").pk, "Fruit")


# ---------------------------------------------------------------------------
# BR-14 — recurring proposals
# ---------------------------------------------------------------------------


@pytest.fixture
def rent_template(db) -> RecurringTemplate:
    return RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200.00"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category=child("Rent"),
        frequency=Frequency.MONTHLY,
        start_month="2026-05",
    )


def test_a_template_proposes_every_period_and_posts_nothing(rent_template):
    proposals = recurring.outstanding_proposals(through="2026-07")

    assert [p.period for p in proposals] == ["2026-05", "2026-06", "2026-07"]
    # Never posted automatically. Nothing exists until confirmed.
    assert Transaction.objects.count() == 0


def test_confirming_creates_a_transaction_and_stops_the_proposal(rent_template):
    recurring.confirm(rent_template.pk, "2026-06")

    remaining = [p.period for p in recurring.outstanding_proposals(through="2026-07")]
    assert remaining == ["2026-05", "2026-07"]
    assert Transaction.objects.count() == 1


def test_the_amount_is_adjustable_at_confirmation(rent_template):
    """The whole point of proposing rather than posting."""
    result = recurring.confirm(rent_template.pk, "2026-06", amount=Decimal("2350.00"))

    assert result.transaction.amount == Decimal("2350.00")
    assert rent_template.amount == Decimal("2200.00")


def test_a_confirmed_transaction_is_independent_of_its_template(rent_template):
    result = recurring.confirm(rent_template.pk, "2026-06")

    rent_template.amount = Decimal("9999")
    rent_template.save()

    result.transaction.refresh_from_db()
    assert result.transaction.amount == Decimal("2200.00")


def test_a_skipped_period_stays_skipped(rent_template):
    """OI-09 — outstanding until confirmed or explicitly dismissed."""
    recurring.dismiss(rent_template.pk, "2026-06")

    remaining = [p.period for p in recurring.outstanding_proposals(through="2026-07")]
    assert "2026-06" not in remaining
    assert RecurringDismissal.objects.count() == 1
    assert Transaction.objects.count() == 0


def test_confirming_twice_is_refused(rent_template):
    recurring.confirm(rent_template.pk, "2026-06")

    with pytest.raises(BusinessRuleError, match="already been confirmed"):
        recurring.confirm(rent_template.pk, "2026-06")


def test_a_quarterly_template_proposes_every_third_month():
    template = RecurringTemplate.objects.create(
        name="Insurance",
        amount=Decimal("400"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category=child("Insurance"),
        frequency=Frequency.QUARTERLY,
        start_month="2026-01",
    )

    periods = [p.period for p in recurring.outstanding_proposals(through="2026-08")]

    assert periods == ["2026-01", "2026-04", "2026-07"]
    assert template.period_months == 3


def test_ending_a_template_stops_future_proposals_and_leaves_history(rent_template):
    recurring.confirm(rent_template.pk, "2026-05")

    recurring.end_template(rent_template, end_month="2026-06")

    assert recurring.outstanding_proposals(through="2026-12") == []
    assert Transaction.objects.count() == 1


def test_an_unconfirmed_proposal_leaves_no_trace_in_reporting(rent_template):
    recurring.outstanding_proposals(through="2026-07")

    assert reporting.category_report("2026-06") == []


# ---------------------------------------------------------------------------
# BR-12 — a parallel ledger, per currency, never translated
# ---------------------------------------------------------------------------


def test_the_report_separates_currencies_and_never_combines_them():
    record_transaction(
        on_date=date(2026, 7, 5),
        amount=Decimal("100"),
        currency="AUD",
        category_id=child("Groceries").pk,
    )
    record_transaction(
        on_date=date(2026, 7, 6),
        amount=Decimal("400"),
        currency="MYR",
        category_id=child("Groceries").pk,
    )

    report = reporting.category_report("2026-07")

    assert [block["currency"] for block in report] == ["AUD", "MYR"]
    assert report[0]["expense"] == "100.00"
    assert report[1]["expense"] == "400.00"
    # No combined total anywhere in the payload.
    assert all("total" not in block for block in report)


def test_income_and_expense_are_separated():
    record_transaction(
        on_date=date(2026, 7, 25),
        amount=Decimal("5000"),
        currency="USD",
        category_id=child("Salary").pk,
    )
    record_transaction(
        on_date=date(2026, 7, 5),
        amount=Decimal("1200"),
        currency="USD",
        category_id=child("Rent").pk,
    )

    block = reporting.category_report("2026-07")[0]

    assert block["income"] == "5000.00"
    assert block["expense"] == "1200.00"
    assert block["net"] == "3800.00"


def test_children_roll_up_to_their_parents():
    for name, amount in (("Groceries", "300"), ("Eating Out", "120")):
        record_transaction(
            on_date=date(2026, 7, 5),
            amount=Decimal(amount),
            currency="USD",
            category_id=child(name).pk,
        )

    block = reporting.category_report("2026-07")[0]
    food = next(row for row in block["parents"] if row["parent"] == "Food")

    assert food["total"] == "420.00"
    assert food["count"] == 2


def test_a_month_outside_the_range_reports_nothing():
    assert reporting.category_report("2020-01") == []


def test_the_trend_reports_a_month_with_no_spending_as_zero():
    """Unlike net worth, absence and zero genuinely coincide here."""
    record_transaction(
        on_date=date(2026, 7, 5),
        amount=Decimal("100"),
        currency="USD",
        category_id=child("Groceries").pk,
    )

    trend = reporting.category_trend("2026-06", "2026-07")

    assert trend["months"] == ["2026-06", "2026-07"]
    assert trend["series"][0]["points"] == ["0.00", "100.00"]


def test_the_trend_can_be_scoped_to_one_category():
    record_transaction(
        on_date=date(2026, 7, 5),
        amount=Decimal("100"),
        currency="USD",
        category_id=child("Groceries").pk,
    )
    record_transaction(
        on_date=date(2026, 7, 5),
        amount=Decimal("900"),
        currency="USD",
        category_id=child("Rent").pk,
    )

    trend = reporting.category_trend("2026-07", "2026-07", category_id=child("Rent").pk)

    assert trend["series"][0]["points"] == ["900.00"]
