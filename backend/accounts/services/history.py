"""One account's balance history, and how its latest month moved.

Account detail asks a single question — *is this account's balance increasing?* —
and answers it three ways at once: on the month before, on the quarter before,
on the year before. All three are the same arithmetic over a different offset,
so all three come from `core.services.movement` and none of them is computed on
the screen. The browser has no arithmetic on money (ADR-12), and the three
figures sitting in one panel is exactly the arrangement where a locally
subtracted total starts disagreeing with the table beneath it.

**The offsets are calendar months, not rows.** Twelve entries back in a list of
recorded months is twelve months back only for an account with no gaps; for one
missing a few it reaches further and still calls itself a year. So each offset
looks up the month it names, and where that month has no balance the movement is
absent rather than measured against whatever the nearest record happened to be —
a month nobody recorded is not a month worth zero (FR-46).

Pure but for the one query: balances in, rows and movements out, no writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.months import shift
from core.services.movement import movement
from accounts.models import Account

#: The three offsets the panel states, in the order it states them, each named
#: for the span it covers rather than for the number of months in it.
OFFSETS: tuple[tuple[str, int], ...] = (
    ("month_on_month", 1),
    ("quarter_on_quarter", 3),
    ("year_on_year", 12),
)


@dataclass(frozen=True)
class BalanceHistory:
    """Every month this account has a balance for, newest first."""

    #: Month key to full-precision balance.
    balances: dict[str, Decimal]
    #: The recorded months, newest first — the order the table reads in.
    months: tuple[str, ...]

    @property
    def latest(self) -> str | None:
        """The most recent recorded month, or None for an account with none."""
        return self.months[0] if self.months else None

    def rows(self) -> list[dict]:
        """The table: each recorded month against the one recorded before it.

        Consecutive *records*, deliberately — the row states which month it
        compared against in `previous_month`, so a gap is visible rather than
        implied, and the column stays populated for a sparse account.
        """
        rows = []
        for index, month in enumerate(self.months):
            older = self.months[index + 1] if index + 1 < len(self.months) else None
            rows.append(
                {
                    "month": month,
                    "amount": str(self.balances[month]),
                    **movement(
                        self.balances[month],
                        self.balances[older] if older else None,
                    ),
                    "previous_month": older,
                }
            )
        return rows

    def offsets(self) -> dict:
        """The latest month against the month one, three and twelve back.

        Both halves null where the named month has no balance, which is also the
        whole answer for an account with no history at all.
        """
        latest = self.latest
        current = self.balances[latest] if latest else None

        return {
            name: {
                "month": shift(latest, -months) if latest else None,
                **movement(
                    current,
                    self.balances.get(shift(latest, -months)) if latest else None,
                ),
            }
            for name, months in OFFSETS
        }

    def as_dict(self) -> dict:
        return {"history": self.rows(), "movement": self.offsets()}


def balance_history(account: Account) -> BalanceHistory:
    """One query, newest first — the order both the table and the offsets want."""
    rows = list(account.balances.order_by("-month"))
    return BalanceHistory(
        balances={row.month: row.amount for row in rows},
        months=tuple(row.month for row in rows),
    )
