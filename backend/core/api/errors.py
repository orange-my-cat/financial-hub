"""One error shape, from every endpoint.

    {
      "error": {
        "code": "validation_failed",
        "message": "The submitted data was not valid.",
        "field_errors": {
          "amount": [{"code": "invalid", "message": "Enter a number."}]
        },
        "non_field_errors": [
          {"code": "currency_locked", "message": "..."}
        ],
        "correlation_id": "9f2a1c40b7e3"
      }
    }

Field errors render inline against the offending input; non-field errors render
as a banner stating that nothing was saved (§8.3). Free-text messages per
endpoint were rejected because they make every screen handle errors
differently; a full RFC 9457 implementation was rejected as more ceremony than
one user needs.

Advisories are not errors and never travel in this shape — see
:mod:`core.api.responses`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.conf import settings
from rest_framework import status as http
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.services.exceptions import BusinessRuleError, ConflictError, NotFoundError

logger = logging.getLogger("financial_hub")

# DRF's key for errors that belong to the payload rather than to one field.
NON_FIELD_KEY = "non_field_errors"

INTERNAL_ERROR_MESSAGE = (
    "Something went wrong and nothing was saved. If this recurs, quote the "
    "reference below."
)


def error_payload(
    *,
    code: str,
    message: str,
    correlation_id: str,
    field_errors: dict[str, list[dict[str, str]]] | None = None,
    non_field_errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "field_errors": field_errors or {},
            "non_field_errors": non_field_errors or [],
            "correlation_id": correlation_id,
        }
    }


def _items(value: Any) -> list[dict[str, str]]:
    """Flatten whatever DRF put in ``detail`` into ``[{code, message}, ...]``."""
    if isinstance(value, ErrorDetail):
        return [{"code": str(value.code), "message": str(value)}]
    if isinstance(value, str):
        return [{"code": "invalid", "message": value}]
    if isinstance(value, list):
        return [item for entry in value for item in _items(entry)]
    if isinstance(value, dict):
        # A nested serializer. The key is folded into the message rather than
        # inventing a nested error structure the front end would have to walk.
        return [
            {**item, "message": f"{key}: {item['message']}"}
            for key, nested in value.items()
            for item in _items(nested)
        ]
    return [{"code": "invalid", "message": str(value)}]


def _split(detail: Any) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    if not isinstance(detail, dict):
        return {}, _items(detail)

    field_errors: dict[str, list[dict[str, str]]] = {}
    non_field: list[dict[str, str]] = []
    for key, value in detail.items():
        if key == NON_FIELD_KEY:
            non_field.extend(_items(value))
        else:
            field_errors[key] = _items(value)
    return field_errors, non_field


def _business_rule_response(exc: BusinessRuleError, correlation_id: str) -> Response:
    if isinstance(exc, NotFoundError):
        status_code = http.HTTP_404_NOT_FOUND
    elif isinstance(exc, ConflictError):
        status_code = http.HTTP_409_CONFLICT
    else:
        status_code = http.HTTP_400_BAD_REQUEST

    item = {"code": exc.code, "message": exc.message}
    payload = error_payload(
        code=exc.code,
        message=exc.message,
        correlation_id=correlation_id,
        field_errors={exc.field: [item]} if exc.field else None,
        non_field_errors=None if exc.field else [item],
    )
    return Response(payload, status=status_code)


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """The DRF ``EXCEPTION_HANDLER``. Every API failure passes through here."""
    correlation_id = uuid.uuid4().hex[:12]
    view = context.get("view")
    request = context.get("request")
    path = getattr(getattr(request, "_request", request), "path", "?")

    # Services raise these. They know nothing about HTTP, which is the point of
    # the three-layer rule — the translation happens exactly here (§5.2.2).
    if isinstance(exc, BusinessRuleError):
        logger.info(
            "business rule refused request path=%s code=%s correlation_id=%s",
            path,
            exc.code,
            correlation_id,
        )
        return _business_rule_response(exc, correlation_id)

    response = drf_exception_handler(exc, context)

    if response is None:
        # Nothing recognised it. Log the trace and answer in the standard shape
        # with a reference — never with raw internals (§9.2).
        logger.exception(
            "unhandled exception view=%s path=%s correlation_id=%s",
            getattr(view, "__class__", type(view)).__name__,
            path,
            correlation_id,
        )
        if settings.DEBUG:
            # Let it through to Django's debug page, which is the whole reason
            # to run a development server in the first place.
            return None
        return Response(
            error_payload(
                code="internal_error",
                message=INTERNAL_ERROR_MESSAGE,
                correlation_id=correlation_id,
            ),
            status=http.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = getattr(exc, "detail", response.data)

    if isinstance(exc, ValidationError):
        field_errors, non_field = _split(detail)
        code, message = "validation_failed", "The submitted data was not valid."
    else:
        field_errors, non_field = {}, _items(detail)
        code = non_field[0]["code"] if non_field else "error"
        message = non_field[0]["message"] if non_field else "The request could not be completed."

    response.data = error_payload(
        code=code,
        message=message,
        correlation_id=correlation_id,
        field_errors=field_errors,
        non_field_errors=non_field,
    )
    return response
