"""Reporting months.

A reporting month is a calendar month whose boundary is its **last calendar
day**; every balance is as at that date (BR-24, design handoff §state).

Months are handled as `YYYY-MM` strings rather than as a model. There is no
month table and there never will be — months are derived from the data that
exists (ADR-04), and a table of them would be a second thing to keep in step
with the first. The string form sorts chronologically under plain comparison,
which is the property that makes the derivation cheap everywhere it happens.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def is_month(value: str) -> bool:
    return bool(MONTH_PATTERN.match(value))


def require_month(value: str) -> str:
    if not is_month(value):
        raise ValueError(f"{value!r} is not a reporting month; expected YYYY-MM.")
    return value


def month_of(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def parts(month: str) -> tuple[int, int]:
    require_month(month)
    year, mon = month.split("-")
    return int(year), int(mon)


def month_end(month: str) -> date:
    """The last calendar day — 28, 29, 30 or 31, whichever it actually is."""
    year, mon = parts(month)
    return date(year, mon, calendar.monthrange(year, mon)[1])


def month_start(month: str) -> date:
    year, mon = parts(month)
    return date(year, mon, 1)


def as_at_of(month: str, *, today: date | None = None) -> date:
    """The date a month is valued at — its last day, or today if it is still running.

    A month boundary is its last calendar day (BR-24), and for every month that
    has ended that is the answer. The month currently in progress is the one
    exception, and it is the reason this function exists: closing August on the
    16th cannot record a balance or a rate as at the 31st, because the 31st has
    not happened. Stating a future date on a screen that then saves against it
    is the kind of small dishonesty a ledger cannot afford.

    A month that has not begun keeps its own month-end. Today is not inside it,
    so today is not its as-at date, and nothing is recorded for it anyway.

    **The as-at date of the current month moves.** A rate recorded for it on the
    16th sits on the 16th, and when the month ends the month-end figure is a
    different figure that was never entered. That is a true statement about an
    early close rather than a defect, but it is the reason this is one function
    and not a `min()` written out at each call site.
    """
    current = today or date.today()
    return current if month_of(current) == require_month(month) else month_end(month)


def shift(month: str, by: int) -> str:
    year, mon = parts(month)
    index = year * 12 + (mon - 1) + by
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def previous(month: str) -> str:
    return shift(month, -1)


def following(month: str) -> str:
    return shift(month, 1)


def distance(earlier: str, later: str) -> int:
    """Whole months from `earlier` to `later`; negative if the order is reversed."""
    ey, em = parts(earlier)
    ly, lm = parts(later)
    return (ly * 12 + lm) - (ey * 12 + em)


def sequence(first: str, last: str) -> tuple[str, ...]:
    """Every month from `first` to `last` inclusive, oldest first.

    Empty when `first` is after `last`, which is the honest answer for a range
    that has not begun rather than an error to handle at every call site.
    """
    span = distance(first, last)
    if span < 0:
        return ()
    return tuple(shift(first, step) for step in range(span + 1))


def descending(first: str, last: str) -> tuple[str, ...]:
    """As :func:`sequence`, newest first — the order the ledger spine reads in."""
    return tuple(reversed(sequence(first, last)))
