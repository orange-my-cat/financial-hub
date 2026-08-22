"""The cash flow endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from cashflow.models import Category, Direction, Frequency, RecurringTemplate, Transaction
from cashflow.services.recurring import outstanding_proposals, proposals_for_month
from cashflow.services.summary import category_flow, monthly_summary
from core.services.tasks import outstanding_tasks
from fx.models import ExchangeRate

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in(client, django_user_model):
    user = django_user_model.objects.create_user(username="owner", password="pw-long-enough")
    client.force_login(user)
    return client


def child_id(name: str) -> int:
    return Category.objects.get(name=name, parent__isnull=False).pk


READ_ENDPOINTS = [
    "/api/cashflow/transactions/?month=2026-07",
    "/api/cashflow/categories/",
    "/api/cashflow/recurring/",
    "/api/cashflow/recurring/proposals/?month=2026-07",
    "/api/cashflow/category-report/?month=2026-07",
    "/api/cashflow/category-flow/?month=2026-07&currency=USD",
    "/api/cashflow/category-trend/?from_month=2026-01&to_month=2026-07",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_every_endpoint_requires_a_session(client, path):
    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_every_read_endpoint_wraps_its_payload_in_data(signed_in, path):
    assert "data" in signed_in.get(path).json()


def test_recording_a_transaction(signed_in):
    response = signed_in.post(
        "/api/cashflow/transactions/",
        data={
            "date": "2026-07-15",
            "amount": "82.40",
            "currency": "AUD",
            "category_id": child_id("Groceries"),
            "note": "Coles",
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["direction"] == "Expense"
    assert body["data"]["amount"] == "82.40"
    assert body["advisories"] == []


def test_the_duplicate_advisory_arrives_with_a_saved_transaction(signed_in):
    payload = {
        "date": "2026-07-15",
        "amount": "4.50",
        "currency": "AUD",
        "category_id": child_id("Eating Out"),
    }
    signed_in.post("/api/cashflow/transactions/", data=payload, content_type="application/json")

    response = signed_in.post(
        "/api/cashflow/transactions/", data=payload, content_type="application/json"
    )

    assert response.status_code == 201
    assert response.json()["advisories"][0]["kind"] == "probable_duplicate"
    assert Transaction.objects.count() == 2


def test_editing_a_transaction_over_http(signed_in):
    created = signed_in.post(
        "/api/cashflow/transactions/",
        data={
            "date": "2026-07-15",
            "amount": "82.40",
            "currency": "AUD",
            "category_id": child_id("Groceries"),
            "note": "Coles",
        },
        content_type="application/json",
    ).json()["data"]

    response = signed_in.patch(
        f"/api/cashflow/transactions/{created['id']}/",
        data={
            "date": "2026-07-18",
            "amount": "91.05",
            "currency": "AUD",
            "category_id": child_id("Salary"),
            "note": "Woolworths",
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["date"] == "2026-07-18"
    assert body["amount"] == "91.05"
    assert body["note"] == "Woolworths"
    # Taken from the category, never from the form.
    assert body["direction"] == "Income"
    assert body["category"] == "Salary"


def test_an_edited_row_comes_back_in_the_same_shape_as_the_month_list(signed_in):
    created = signed_in.post(
        "/api/cashflow/transactions/",
        data={
            "date": "2026-07-15",
            "amount": "82.40",
            "currency": "AUD",
            "category_id": child_id("Groceries"),
        },
        content_type="application/json",
    ).json()["data"]

    edited = signed_in.patch(
        f"/api/cashflow/transactions/{created['id']}/",
        data={"note": "Coles"},
        content_type="application/json",
    ).json()["data"]
    listed = signed_in.get("/api/cashflow/transactions/?month=2026-07").json()["data"][0]

    assert edited == listed


def test_an_edit_that_lands_on_a_twin_advises_and_still_saves(signed_in):
    payload = {
        "date": "2026-07-15",
        "amount": "4.50",
        "currency": "AUD",
        "category_id": child_id("Eating Out"),
    }
    signed_in.post("/api/cashflow/transactions/", data=payload, content_type="application/json")
    other = signed_in.post(
        "/api/cashflow/transactions/",
        data={**payload, "amount": "6.00"},
        content_type="application/json",
    ).json()["data"]

    response = signed_in.patch(
        f"/api/cashflow/transactions/{other['id']}/",
        data={"amount": "4.50"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["advisories"][0]["kind"] == "probable_duplicate"
    assert response.json()["data"]["amount"] == "4.50"


def test_an_edit_to_a_parent_category_is_refused_and_nothing_changes(signed_in):
    parent = Category.objects.get(name="Food", parent__isnull=True)
    created = signed_in.post(
        "/api/cashflow/transactions/",
        data={
            "date": "2026-07-15",
            "amount": "82.40",
            "currency": "AUD",
            "category_id": child_id("Groceries"),
            "note": "Coles",
        },
        content_type="application/json",
    ).json()["data"]

    response = signed_in.patch(
        f"/api/cashflow/transactions/{created['id']}/",
        data={"note": "Woolworths", "category_id": parent.pk},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "category" in response.json()["error"]["field_errors"]
    # An error blocks and nothing was saved — including the note beside it.
    assert Transaction.objects.get(pk=created["id"]).note == "Coles"


def test_a_transaction_on_a_deactivated_category_stays_editable(signed_in):
    created = signed_in.post(
        "/api/cashflow/transactions/",
        data={
            "date": "2026-07-15",
            "amount": "82.40",
            "currency": "AUD",
            "category_id": child_id("Groceries"),
        },
        content_type="application/json",
    ).json()["data"]
    signed_in.patch(
        f"/api/cashflow/categories/{child_id('Groceries')}/",
        data={"is_active": False},
        content_type="application/json",
    )

    # The category is untouched by the edit, so its deactivation is not in the
    # way. Its history stays intact and editable.
    response = signed_in.patch(
        f"/api/cashflow/transactions/{created['id']}/",
        data={"note": "Coles"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["note"] == "Coles"


def test_a_parent_category_is_refused_as_a_field_error(signed_in):
    parent = Category.objects.get(name="Food", parent__isnull=True)

    response = signed_in.post(
        "/api/cashflow/transactions/",
        data={
            "date": "2026-07-15",
            "amount": "10",
            "currency": "USD",
            "category_id": parent.pk,
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "category" in response.json()["error"]["field_errors"]


def test_the_taxonomy_is_served_as_a_tree(signed_in):
    body = signed_in.get("/api/cashflow/categories/").json()["data"]

    assert len(body) == 12
    food = next(row for row in body if row["name"] == "Food")
    assert {c["name"] for c in food["children"]} == {"Groceries", "Eating Out"}


def test_a_used_category_cannot_be_deleted_over_http(signed_in):
    signed_in.post(
        "/api/cashflow/transactions/",
        data={
            "date": "2026-07-15",
            "amount": "10",
            "currency": "USD",
            "category_id": child_id("Groceries"),
        },
        content_type="application/json",
    )

    response = signed_in.delete(f"/api/cashflow/categories/{child_id('Groceries')}/")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "category_in_use"


def test_deactivating_a_category(signed_in):
    response = signed_in.patch(
        f"/api/cashflow/categories/{child_id('Groceries')}/",
        data={"is_active": False},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert Category.objects.get(pk=child_id("Groceries")).is_active is False


def test_proposals_are_listed_and_nothing_is_posted(signed_in):
    RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        anchor_date=date(2026, 6, 5),
    )

    body = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-07").json()["data"]

    assert [p["occurrence"] for p in body] == ["2026-07-05"]
    assert Transaction.objects.count() == 0


def test_the_list_is_the_months_own_and_no_others(signed_in):
    """June's occurrence is June's business, on a screen showing July."""
    RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        anchor_date=date(2026, 6, 5),
    )

    july = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-07").json()["data"]
    june = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-06").json()["data"]
    may = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-05").json()["data"]

    assert [p["occurrence"] for p in july] == ["2026-07-05"]
    assert [p["occurrence"] for p in june] == ["2026-06-05"]
    # Before the anchor. A template proposes nothing backwards.
    assert may == []


def test_an_undecided_earlier_occurrence_is_still_counted_on_the_dashboard(signed_in):
    """OI-09. Scoped out of the panel, never out of the tasks that chase it."""
    RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        anchor_date=date(2026, 6, 5),
    )

    # August's panel is August's occurrence alone.
    august = proposals_for_month("2026-08")
    assert [p.occurrence.isoformat() for p in august] == ["2026-08-05"]

    # June and July were never decided, and are still being asked about.
    recurring = [
        task for task in outstanding_tasks("2026-07") if task.kind == "recurring"
    ]
    assert recurring and recurring[0].count == 2


def test_answered_occurrences_sort_to_the_end(signed_in):
    """The panel is a queue first: what is still owed a decision leads it."""
    template = RecurringTemplate.objects.create(
        name="Gym",
        amount=Decimal("30"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Fitness"),
        frequency=Frequency.WEEKLY,
        anchor_date=date(2026, 7, 6),
    )

    # The first and third Mondays answered, the rest still open.
    signed_in.post(
        "/api/cashflow/recurring/confirm/",
        data={"template_id": template.pk, "occurrence": "2026-07-06"},
        content_type="application/json",
    )
    signed_in.post(
        "/api/cashflow/recurring/dismiss/",
        data={"template_id": template.pk, "occurrence": "2026-07-20"},
        content_type="application/json",
    )

    body = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-07").json()[
        "data"
    ]

    assert [(row["occurrence"], row["status"]) for row in body] == [
        # Outstanding, oldest first.
        ("2026-07-13", "Outstanding"),
        ("2026-07-27", "Outstanding"),
        # Then the answered ones, in the same order among themselves.
        ("2026-07-06", "Confirmed"),
        ("2026-07-20", "Skipped"),
    ]


def test_the_month_is_required(signed_in):
    """A list about some other month is the failure the parameter prevents."""
    assert signed_in.get("/api/cashflow/recurring/proposals/").status_code == 400


def test_confirming_a_proposal_with_an_adjusted_amount(signed_in):
    template = RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        anchor_date=date(2026, 6, 5),
    )

    response = signed_in.post(
        "/api/cashflow/recurring/confirm/",
        data={
            "template_id": template.pk,
            "occurrence": "2026-06-05",
            "amount": "2350.00",
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["data"]["amount"] == "2350.00"
    assert Transaction.objects.count() == 1


def test_dismissing_a_proposal_keeps_it_dismissed(signed_in):
    template = RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        anchor_date=date(2026, 6, 5),
    )

    signed_in.post(
        "/api/cashflow/recurring/dismiss/",
        data={"template_id": template.pk, "occurrence": "2026-06-05"},
        content_type="application/json",
    )

    body = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-06").json()["data"]

    # It stays on the month's list saying what was decided, and is never
    # proposed again — a skipped occurrence and one that never existed are two
    # different facts about June.
    assert [(row["occurrence"], row["status"]) for row in body] == [
        ("2026-06-05", "Skipped")
    ]
    assert outstanding_proposals(through="2026-06") == []


def test_a_confirmed_occurrence_stays_listed_with_what_was_recorded(signed_in):
    """The amount is adjustable at confirmation, so the row states the real one."""
    template = RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        anchor_date=date(2026, 6, 5),
    )

    signed_in.post(
        "/api/cashflow/recurring/confirm/",
        data={
            "template_id": template.pk,
            "occurrence": "2026-06-05",
            "amount": "2350.00",
        },
        content_type="application/json",
    )

    row = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-06").json()[
        "data"
    ][0]

    assert row["status"] == "Confirmed"
    # The template still proposes 2,200; the month recorded 2,350.
    assert row["amount"] == "2200.0000"
    assert row["recorded_amount"] == "2350.0000"
    assert row["recorded_date"] == "2026-06-05"
    assert outstanding_proposals(through="2026-06") == []


def test_deleting_the_transaction_returns_the_occurrence_to_outstanding(signed_in):
    """The decision was undone, so the month is owed it again."""
    template = RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        anchor_date=date(2026, 6, 5),
    )

    confirmed = signed_in.post(
        "/api/cashflow/recurring/confirm/",
        data={"template_id": template.pk, "occurrence": "2026-06-05"},
        content_type="application/json",
    ).json()["data"]

    signed_in.delete(f"/api/cashflow/transactions/{confirmed['id']}/")

    row = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-06").json()[
        "data"
    ][0]
    assert row["status"] == "Outstanding"
    assert row["recorded_amount"] is None


def test_creating_a_template_then_listing_it(signed_in):
    response = signed_in.post(
        "/api/cashflow/recurring/",
        data={
            "name": "Rent",
            "amount": "2200.00",
            "currency": "AUD",
            "category_id": child_id("Rent"),
            "frequency": Frequency.MONTHLY,
            "anchor_date": "2026-06-05",
        },
        content_type="application/json",
    )

    assert response.status_code == 201

    row = signed_in.get("/api/cashflow/recurring/").json()["data"][0]
    assert row["name"] == "Rent"
    assert row["amount"] == "2200.00"
    assert row["parent"] == "Housing"
    assert row["is_active"] is True
    assert row["anchor_date"] == "2026-06-05"
    assert row["end_date"] is None


def test_a_weekly_template_proposes_every_seventh_day(signed_in):
    signed_in.post(
        "/api/cashflow/recurring/",
        data={
            "name": "Groceries",
            "amount": "180.00",
            "currency": "AUD",
            "category_id": child_id("Groceries"),
            "frequency": Frequency.WEEKLY,
            "anchor_date": "2026-07-02",
        },
        content_type="application/json",
    )

    body = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-07").json()["data"]

    assert [row["occurrence"] for row in body] == [
        "2026-07-02",
        "2026-07-09",
        "2026-07-16",
        "2026-07-23",
        "2026-07-30",
    ]


def test_a_template_anchored_to_a_day_proposes_that_date(signed_in):
    signed_in.post(
        "/api/cashflow/recurring/",
        data={
            "name": "Rent",
            "amount": "2200.00",
            "currency": "AUD",
            "category_id": child_id("Rent"),
            "frequency": Frequency.MONTHLY,
            "anchor_date": "2026-07-03",
            "anchor_day": 3,
        },
        content_type="application/json",
    )

    row = signed_in.get("/api/cashflow/recurring/").json()["data"][0]
    assert row["anchor_date"] == "2026-07-03"

    # The anchor's day of the month, every month, from the anchor onwards —
    # asked for one month at a time, which is how the screen asks.
    for month, occurrence in (("2026-07", "2026-07-03"), ("2026-08", "2026-08-03")):
        body = signed_in.get(
            f"/api/cashflow/recurring/proposals/?month={month}"
        ).json()["data"]
        assert [proposal["occurrence"] for proposal in body] == [occurrence]


def test_a_date_that_does_not_exist_is_refused(signed_in):
    response = signed_in.post(
        "/api/cashflow/recurring/",
        data={
            "name": "Rent",
            "amount": "2200.00",
            "currency": "AUD",
            "category_id": child_id("Rent"),
            "frequency": Frequency.MONTHLY,
            "anchor_date": "2026-02-30",
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert RecurringTemplate.objects.count() == 0


def test_ending_a_template_stops_proposals_and_keeps_the_row(signed_in):
    template = RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        anchor_date=date(2026, 6, 5),
    )

    response = signed_in.post(
        f"/api/cashflow/recurring/{template.pk}/end/",
        data={"end_date": "2026-06-05"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["is_active"] is False
    assert response.json()["data"]["end_date"] == "2026-06-05"

    # Ended, not deleted: it stays listed, and proposes nothing past that date.
    assert len(signed_in.get("/api/cashflow/recurring/").json()["data"]) == 1
    body = signed_in.get("/api/cashflow/recurring/proposals/?month=2026-06").json()["data"]
    assert [row["occurrence"] for row in body] == ["2026-06-05"]
    assert signed_in.get("/api/cashflow/recurring/proposals/?month=2026-07").json()["data"] == []


def test_ending_a_template_that_does_not_exist(signed_in):
    response = signed_in.post(
        "/api/cashflow/recurring/9999/end/", data={}, content_type="application/json"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "template_not_found"


def test_the_category_report_never_combines_currencies(signed_in):
    for currency, amount in (("AUD", "100"), ("MYR", "400")):
        signed_in.post(
            "/api/cashflow/transactions/",
            data={
                "date": "2026-07-05",
                "amount": amount,
                "currency": currency,
                "category_id": child_id("Groceries"),
            },
            content_type="application/json",
        )

    body = signed_in.get("/api/cashflow/category-report/?month=2026-07").json()["data"]

    assert [block["currency"] for block in body["currencies"]] == ["AUD", "MYR"]
    # BR-12: no combined total exists anywhere in this payload.
    assert "total" not in body
    assert all("total" not in block for block in body["currencies"])


def test_no_cashflow_endpoint_returns_a_balance_figure(signed_in):
    """BR-12 enforced by the shape of the API rather than by remembering."""
    for path in READ_ENDPOINTS:
        body = signed_in.get(path).json()
        assert "net_worth" not in str(body)
        assert "balance" not in str(body).lower()


# ---------------------------------------------------------------------------
# The combined category flow
#
# The one place in cash flow reporting where currencies are added together. The
# tests below are mostly about the conditions on that: the same rate the
# dashboard used, the whole currency excluded where there is none, and a total
# that stays the summary's total however the categories are cut.
# ---------------------------------------------------------------------------


def rate(currency: str, on: date, value: str) -> None:
    ExchangeRate.objects.create(currency=currency, rate_date=on, rate=Decimal(value))


@pytest.fixture
def two_currencies(db):
    """Groceries bought in two currencies, against one salary."""
    Transaction.objects.create(
        date=date(2026, 7, 10), amount=Decimal("8000"), currency="USD",
        direction=Direction.INCOME, category_id=child_id("Salary"),
    )
    Transaction.objects.create(
        date=date(2026, 7, 12), amount=Decimal("2000"), currency="USD",
        direction=Direction.EXPENSE, category_id=child_id("Groceries"),
    )
    Transaction.objects.create(
        date=date(2026, 7, 20), amount=Decimal("1000"), currency="AUD",
        direction=Direction.EXPENSE, category_id=child_id("Groceries"),
    )


def test_one_category_bought_in_two_currencies_is_one_row(signed_in, two_currencies):
    """AUD 1,000 at 0.66 is USD 660, added to the USD 2,000 already spent."""
    rate("AUD", date(2026, 7, 31), "0.66")

    body = signed_in.get(
        "/api/cashflow/category-flow/?month=2026-07&currency=USD"
    ).json()["data"]

    groceries = [row for row in body["children"] if row["category"] == "Groceries"]
    assert len(groceries) == 1
    assert groceries[0]["total"] == {"amount": "2660.00", "currency": "USD"}
    assert groceries[0]["count"] == 2


def test_the_flow_and_the_summary_cannot_disagree(two_currencies):
    """One definition of the month's income and expense, cut two ways."""
    rate("AUD", date(2026, 7, 31), "0.66")

    flow = category_flow("2026-07", "USD")
    summary = monthly_summary("2026-07", "USD")

    assert flow["income"] == summary.income.api()
    assert flow["expense"] == summary.expense.api()

    # Exact here because the rate and the amounts are. Every figure is carried
    # at full precision and rounded once at display, so on a triangulated rate
    # the rows and the total can each be right and still differ by a cent.
    spent = sum(
        Decimal(row["total"]["amount"])
        for row in flow["children"]
        if row["direction"] == Direction.EXPENSE
    )
    assert spent == Decimal(flow["expense"]["amount"])


def test_parents_are_rolled_up_on_the_server(two_currencies):
    rate("AUD", date(2026, 7, 31), "0.66")

    flow = category_flow("2026-07", "USD")

    food = [row for row in flow["parents"] if row["parent"] == "Food"]
    assert food == [
        {
            "parent": "Food",
            "direction": Direction.EXPENSE,
            "total": {"amount": "2660.00", "currency": "USD"},
            "count": 2,
        }
    ]


def test_a_currency_with_no_rate_is_excluded_and_never_zeroed(two_currencies):
    """FR-46. The AUD groceries leave the diagram; they do not arrive as zero."""
    flow = category_flow("2026-07", "USD")

    assert [row["currency"] for row in flow["exclusions"]] == ["AUD"]

    groceries = [row for row in flow["children"] if row["category"] == "Groceries"]
    assert groceries[0]["total"] == {"amount": "2000.00", "currency": "USD"}
    assert flow["expense"] == {"amount": "2000.00", "currency": "USD"}


def test_a_month_excluded_entirely_is_not_reportable(db):
    """Nothing to draw, and the reason stated rather than an empty diagram."""
    Transaction.objects.create(
        date=date(2026, 7, 20), amount=Decimal("1000"), currency="AUD",
        direction=Direction.EXPENSE, category_id=child_id("Groceries"),
    )

    flow = category_flow("2026-07", "USD")

    assert flow["reportable"] is False
    assert flow["children"] == []
    assert flow["exclusions"][0]["currency"] == "AUD"
    assert "no AUD/USD rate" in flow["exclusions"][0]["reason"]


def test_the_flow_obeys_the_reporting_currency(signed_in, two_currencies):
    rate("AUD", date(2026, 7, 31), "0.66")

    body = signed_in.get(
        "/api/cashflow/category-flow/?month=2026-07&currency=AUD"
    ).json()["data"]

    assert body["currency"] == "AUD"
    assert body["income"]["currency"] == "AUD"
    assert all(row["total"]["currency"] == "AUD" for row in body["children"])


def test_gold_is_not_a_currency_a_report_is_stated_in(signed_in):
    """OI-01. XAU denominates a balance; it is never a unit of account here."""
    response = signed_in.get("/api/cashflow/category-flow/?month=2026-07&currency=XAU")

    assert response.status_code == 400
