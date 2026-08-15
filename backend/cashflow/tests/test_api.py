"""The cash flow endpoints."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cashflow.models import Category, Direction, Frequency, RecurringTemplate, Transaction

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
    "/api/cashflow/recurring/proposals/",
    "/api/cashflow/category-report/?month=2026-07",
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
        start_month="2026-06",
    )

    body = signed_in.get("/api/cashflow/recurring/proposals/?through=2026-07").json()["data"]

    assert [p["period"] for p in body] == ["2026-06", "2026-07"]
    assert Transaction.objects.count() == 0


def test_confirming_a_proposal_with_an_adjusted_amount(signed_in):
    template = RecurringTemplate.objects.create(
        name="Rent",
        amount=Decimal("2200"),
        currency="AUD",
        direction=Direction.EXPENSE,
        category_id=child_id("Rent"),
        frequency=Frequency.MONTHLY,
        start_month="2026-06",
    )

    response = signed_in.post(
        "/api/cashflow/recurring/confirm/",
        data={"template_id": template.pk, "period": "2026-06", "amount": "2350.00"},
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
        start_month="2026-06",
    )

    signed_in.post(
        "/api/cashflow/recurring/dismiss/",
        data={"template_id": template.pk, "period": "2026-06"},
        content_type="application/json",
    )

    body = signed_in.get("/api/cashflow/recurring/proposals/?through=2026-06").json()["data"]
    assert body == []


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
