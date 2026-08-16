"""Month-on-month movement — one definition of a change and its proportion.

Three screens state how a figure moved on the month before it: the dashboard's
net worth panel, its cash flow panel, and the Net Worth trend. Three copies of
`(current - prior) / abs(prior)` is exactly the arrangement the third invariant
forbids — a screen and a report that disagree, with no way to tell which is
right — so the arithmetic lives here and the views serialise what it returns.

Two nulls, and they mean different things:

  * **Both halves null** where either month has no figure at all. A month
    nobody recorded is not a month worth zero (FR-46), so there is nothing to
    subtract from and no change to state.
  * **The percentage alone null** against a *zero* prior month, because a rise
    from nothing has no proportion. The absolute change is still real: a quiet
    cash flow month genuinely earned and spent nothing, so the difference
    against it is a fact, which is not true of a month with no balances.

Pure, like every other calculation here — plain decimals in, plain values out,
no model import and no database write.
"""

from __future__ import annotations

from decimal import Decimal

CENTS = Decimal("0.01")
TENTHS = Decimal("0.1")


def movement(current: Decimal | None, prior: Decimal | None) -> dict:
    """One figure's movement on the figure before it.

    Computed from the full-precision figures and rounded once here, for
    display: the change to the cent, the proportion to a tenth of a percent.
    """
    if current is None or prior is None:
        return {"change": None, "change_percent": None}

    difference = current - prior
    percent = (difference / abs(prior) * 100).quantize(TENTHS) if prior != 0 else None

    return {
        "change": str(difference.quantize(CENTS)),
        "change_percent": str(percent) if percent is not None else None,
    }
