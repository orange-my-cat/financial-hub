"""One error shape, from every endpoint (§8.3).

The shape is load-bearing rather than cosmetic: the front end renders
`field_errors` inline against the offending input and `non_field_errors` as a
banner stating nothing was saved. An endpoint that answers in a different shape
is an endpoint whose errors are invisible.
"""

from __future__ import annotations

import pytest
from django.test import override_settings
from rest_framework.exceptions import NotAuthenticated, ValidationError

from core.api.errors import exception_handler
from core.services.exceptions import BusinessRuleError, ConflictError, NotFoundError

CONTEXT: dict = {"view": None, "request": None}


def _error(response):
    return response.data["error"]


def test_business_rule_error_is_a_non_field_error():
    exc = BusinessRuleError("Nothing was saved.", code="currency_locked")

    response = exception_handler(exc, CONTEXT)

    assert response.status_code == 400
    error = _error(response)
    assert error["code"] == "currency_locked"
    assert error["field_errors"] == {}
    assert error["non_field_errors"] == [
        {"code": "currency_locked", "message": "Nothing was saved."}
    ]
    assert len(error["correlation_id"]) == 12


def test_business_rule_error_with_a_field_renders_inline():
    exc = BusinessRuleError("Enter a positive number.", code="not_positive", field="amount")

    response = exception_handler(exc, CONTEXT)

    error = _error(response)
    assert error["non_field_errors"] == []
    assert error["field_errors"] == {
        "amount": [{"code": "not_positive", "message": "Enter a positive number."}]
    }


def test_conflict_error_answers_409():
    response = exception_handler(ConflictError("A balance already exists."), CONTEXT)
    assert response.status_code == 409
    assert _error(response)["code"] == "conflict"


def test_not_found_error_answers_404():
    response = exception_handler(NotFoundError("No such account."), CONTEXT)
    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


def test_validation_error_splits_field_from_non_field():
    exc = ValidationError(
        {
            "amount": ["Enter a number."],
            "non_field_errors": ["The two dates are the wrong way round."],
        }
    )

    response = exception_handler(exc, CONTEXT)

    assert response.status_code == 400
    error = _error(response)
    assert error["code"] == "validation_failed"
    assert error["field_errors"]["amount"][0]["message"] == "Enter a number."
    assert (
        error["non_field_errors"][0]["message"]
        == "The two dates are the wrong way round."
    )


def test_validation_error_from_a_bare_list_is_non_field():
    response = exception_handler(ValidationError(["Something is wrong."]), CONTEXT)

    error = _error(response)
    assert error["field_errors"] == {}
    assert error["non_field_errors"][0]["message"] == "Something is wrong."


def test_nested_serializer_errors_are_flattened_with_their_key():
    exc = ValidationError({"rates": {"usd_aud": ["Enter a number."]}})

    response = exception_handler(exc, CONTEXT)

    assert _error(response)["field_errors"]["rates"][0]["message"] == (
        "usd_aud: Enter a number."
    )


def test_other_api_exceptions_keep_the_shape():
    response = exception_handler(NotAuthenticated(), CONTEXT)

    assert response.status_code in (401, 403)
    error = _error(response)
    assert error["field_errors"] == {}
    assert error["non_field_errors"]
    assert error["correlation_id"]


@override_settings(DEBUG=False)
def test_unhandled_exception_never_leaks_internals():
    response = exception_handler(RuntimeError("psycopg: password authentication failed"), CONTEXT)

    assert response.status_code == 500
    error = _error(response)
    assert error["code"] == "internal_error"
    assert "psycopg" not in error["message"]
    assert "nothing was saved" in error["message"]
    assert error["correlation_id"]


@override_settings(DEBUG=True)
def test_unhandled_exception_is_re_raised_in_development():
    """So the development server can render its own debug page."""
    assert exception_handler(RuntimeError("boom"), CONTEXT) is None


@pytest.mark.django_db
def test_shape_arrives_over_http(client):
    """The handler is wired in, not merely importable."""
    response = client.post(
        "/api/session/",
        data={"username": "nobody"},
        content_type="application/json",
    )

    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "validation_failed"
    assert "password" in body["field_errors"]
