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
