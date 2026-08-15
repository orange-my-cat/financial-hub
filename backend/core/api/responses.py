"""Response envelopes.

Two conventions live here, both of them structural rather than cosmetic.

**Advisories accompany a success.** A response carrying an advisory is a
response whose data was saved. Putting advisories in the success envelope
rather than the error envelope is what makes "advisories never block"
impossible to get wrong in a client (§8.3).

**Aggregates carry their qualifications.** Every aggregate response travels
with its completeness state, its exclusions and its rate provenance, so a
consumer cannot render a total without also holding the information that
qualifies it (§8.2). The helper is defined here in Stage 0 and used from
Stage 1 onward, because the shape needs to be one shape.
"""

from __future__ import annotations

from typing import Any, Iterable

from rest_framework import status as http
from rest_framework.response import Response

from core.services.advisories import Advisory


def with_advisories(
    data: Any,
    advisories: Iterable[Advisory] = (),
    *,
    status: int = http.HTTP_200_OK,
) -> Response:
    """A successful response that may carry advisories.

    ``advisories`` is always present, even when empty, so a client never has to
    distinguish "no advisories" from "this endpoint does not produce them".
    """
    return Response(
        {"data": data, "advisories": [advisory.as_dict() for advisory in advisories]},
        status=status,
    )


def aggregate(
    data: Any,
    *,
    completeness: dict[str, Any],
    exclusions: list[dict[str, Any]] | None = None,
    rate_provenance: list[dict[str, Any]] | None = None,
    advisories: Iterable[Advisory] = (),
    status: int = http.HTTP_200_OK,
) -> Response:
    """A response carrying a computed total.

    ``completeness`` is not optional. A total whose completeness the caller
    cannot see is a total the caller will render as though it were whole, and
    an excluded account is never the same thing as a zero balance (FR-46).
    """
    return Response(
        {
            "data": data,
            "completeness": completeness,
            "exclusions": exclusions or [],
            "rate_provenance": rate_provenance or [],
            "advisories": [advisory.as_dict() for advisory in advisories],
        },
        status=status,
    )
