"""Advisories never block, and there are exactly three of them.

The count is the design. Every advisory is something the user must read and
dismiss during a monthly close, and quality attribute 3 is the close completing
in one sitting. A fourth advisory is a decision, not an addition — which is why
the enum is the enforcement and a bare string will not do.
"""

from __future__ import annotations

import pytest

from core.api.responses import aggregate, with_advisories
from core.services.advisories import Advisory, AdvisoryKind


def test_there_are_exactly_three_advisories():
    assert {str(kind) for kind in AdvisoryKind} == {
        "probable_duplicate",
        "rate_variance",
        "historic_restatement",
    }


def test_an_advisory_serialises_with_its_detail():
    advisory = Advisory(
        kind=AdvisoryKind.RATE_VARIANCE,
        message="This rate is 12.4% away from the previous one for USD/AUD.",
        detail={"previous": "1.5100", "entered": "1.6973", "difference_pct": "12.40"},
    )

    assert advisory.as_dict() == {
        "kind": "rate_variance",
        "message": "This rate is 12.4% away from the previous one for USD/AUD.",
        "detail": {"previous": "1.5100", "entered": "1.6973", "difference_pct": "12.40"},
    }


def test_an_invented_kind_is_refused():
    with pytest.raises(ValueError, match="three advisories"):
        Advisory(kind="looks_odd", message="Something.")  # type: ignore[arg-type]


def test_an_advisory_without_an_explanation_is_refused():
    """A vague advisory is dismissed reflexively, which makes it worse than none."""
    with pytest.raises(ValueError, match="noise"):
        Advisory(kind=AdvisoryKind.PROBABLE_DUPLICATE, message="   ")


def test_advisories_travel_with_a_successful_response():
    """Because a response carrying an advisory is a response whose data saved."""
    advisory = Advisory(
        kind=AdvisoryKind.PROBABLE_DUPLICATE,
        message="A transaction with this date, amount and category already exists.",
    )

    response = with_advisories({"id": 7}, [advisory])

    assert response.status_code == 200
    assert response.data["data"] == {"id": 7}
    assert response.data["advisories"][0]["kind"] == "probable_duplicate"


def test_the_advisories_key_is_always_present():
    """So a client never distinguishes 'none' from 'this endpoint has none'."""
    assert with_advisories({"id": 7}).data["advisories"] == []


def test_an_aggregate_cannot_be_returned_without_its_completeness():
    """§8.2 — a total whose completeness is invisible gets rendered as whole."""
    with pytest.raises(TypeError):
        aggregate({"total": "1000.00"})  # type: ignore[call-arg]


def test_an_aggregate_carries_exclusions_and_provenance():
    response = aggregate(
        {"total": "1000.0000", "currency": "USD"},
        completeness={"state": "Incomplete", "missing_accounts": 2},
        exclusions=[{"account": "DBS SGD", "reason": "no USD/SGD rate exists"}],
        rate_provenance=[{"pair": "USD/AUD", "as_at": "2026-07-31", "provenance": "carried"}],
    )

    assert response.data["completeness"]["state"] == "Incomplete"
    assert response.data["exclusions"][0]["reason"] == "no USD/SGD rate exists"
    assert response.data["rate_provenance"][0]["provenance"] == "carried"
    assert response.data["advisories"] == []
