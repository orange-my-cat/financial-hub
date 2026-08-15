"""Advisories — the three of them.

Advisories never block. They sit beside the thing they concern, keep every
action live, and leave the data saved. Errors block and say nothing was saved.
The two are structurally different in the response, not merely differently
worded, so that no front end can render one as the other (§8.3).

There are exactly three, and the enumeration below is the enforcement:

    probable duplicate      a transaction matching date, amount and category (FR-23)
    rate variance           a rate differing from its predecessor beyond the threshold (ADR-08)
    historic restatement    a reclassification that changes already-reported months (FR-04)

A fourth advisory is not a small addition. Every advisory is a thing the user
must read and dismiss during a monthly close, and quality attribute 3 is the
close completing in one sitting. Adding one is a design decision, which is why
adding one means editing this enum rather than passing a new string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AdvisoryKind(StrEnum):
    PROBABLE_DUPLICATE = "probable_duplicate"
    RATE_VARIANCE = "rate_variance"
    HISTORIC_RESTATEMENT = "historic_restatement"


@dataclass(frozen=True)
class Advisory:
    """One advisory. Immutable, because it describes something already decided."""

    kind: AdvisoryKind
    message: str
    # Whatever the screen needs to state the case specifically: the prior rate
    # and the percentage difference, the number of months a reclassification
    # restates, the matching transaction's identifier. A vague advisory is
    # dismissed reflexively, which makes it worse than none.
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AdvisoryKind):
            raise ValueError(
                f"{self.kind!r} is not one of the three advisories this system has. "
                f"Adding a fourth is a design decision — see AdvisoryKind."
            )
        if not self.message.strip():
            raise ValueError("An advisory with no explanation is noise, not an advisory.")

    def as_dict(self) -> dict[str, Any]:
        return {"kind": str(self.kind), "message": self.message, "detail": self.detail}
