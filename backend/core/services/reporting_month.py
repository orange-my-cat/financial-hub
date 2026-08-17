"""Which month the dashboard reports on — one definition of "the last close".

The dashboard was fixed to the current month, and that made it uninformative for
most of every month. A balance is stated as at the last calendar day of its month
(BR-02) and is entered when the month ends, so the month in progress holds
nothing until the day it closes: a headline reading "No balances recorded for
2026-08 yet" for thirty days is a screen nobody opens on the other twenty-nine.

So the dashboard reports the **last month that has ended and has balances
recorded** — with one exception, which is the reason this is a service rather
than a `previous()` at the call site: **a month whose balances are all in is
closed.** Once every balance the month in progress requires is present there is
nothing left to wait for, and standing back a month would hide work the user has
finished.

Two things this deliberately does not do:

  * **It does not require a month to be Complete**, in either branch. Completeness
    also demands a rate dated on the month's as-at date, and for the month in
    progress that date is today and therefore moves daily (ADR-08) — so a month
    with every balance entered would fall short of Complete on every day but the
    one a rate was typed on, and the exception above would almost never fire. In
    the other branch a single missing rate would push the dashboard back past a
    month whose balances are all in, hiding the newest figures the user has on
    account of the one thing they are already being nagged about. Carrying a rate
    forward is permitted without limit (ADR-09); the month's completeness, its
    exclusions and its rate provenance all travel in the response beside its total
    (§8.2), so the figure is qualified rather than withheld.
  * **It does not decide what the outstanding tasks panel asks about.** That
    panel is about now — the current month and the one before it (FR-51) — and it
    stays anchored there whichever month the figures are for. Otherwise it would
    fall silent about the close that is actually due, and disagree with the rail
    badge, which counts the same tasks as at today.

Derived on read from the balances that exist, like everything else here. There is
no month table and nothing anywhere records that a month was closed (ADR-04), so
"closed" is a question asked of the data, never a flag someone sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from core.months import month_of


class MonthBasis(StrEnum):
    """Why this month, so a screen can say so rather than appear to be showing
    the present. The exact words, used in code, UI and tests alike."""

    #: The last month that has ended and has balances recorded.
    CLOSED = "closed"
    #: The month in progress, closed early — every balance it requires is in.
    CURRENT = "current"
    #: Asked for explicitly by the caller.
    REQUESTED = "requested"
    #: No balance has ever been recorded, so there is no close to report.
    EMPTY = "empty"


@dataclass(frozen=True)
class ReportingMonth:
    month: str
    basis: MonthBasis
    #: The month in progress. Carried so a screen can name the month it is *not*
    #: showing without consulting a second clock — a browser resolving "now"
    #: itself would disagree with the server either side of midnight on the first.
    current_month: str

    @property
    def is_current(self) -> bool:
        return self.month == self.current_month

    def as_dict(self) -> dict:
        return {
            "month": self.month,
            "basis": str(self.basis),
            "current_month": self.current_month,
            "is_current": self.is_current,
        }


def latest_closed_month(service=None, *, today: date | None = None) -> ReportingMonth:
    """The month the dashboard reports on.

    `service` is an optional :class:`~accounts.services.net_worth.NetWorthService`
    to borrow — the caller already holds one, and sharing it shares its rate
    cache for the completeness check.
    """
    # Imported here, not at module scope: `core` is the base app and does not
    # import the modules built on it (§5.2.2). `core.services.tasks` reaches into
    # accounts the same way, for the same reason.
    from accounts.models import Balance
    from accounts.services.net_worth import NetWorthService
    from core.models import Settings

    current = month_of(today or date.today())

    if service is None:
        service = NetWorthService(staleness_days=Settings.load().rate_staleness_days)

    # An early close counts as a close. Judged as at `today`, which for the month
    # in progress is the date its balances were actually recorded against — not a
    # month-end that has not arrived (core.months.as_at_of).
    if service.completeness_for(current, today=today).all_balances_recorded:
        return ReportingMonth(current, MonthBasis.CURRENT, current)

    # Strictly before the current month: a month that has not ended has not been
    # closed, whatever has been entered against it, and a balance dated ahead of
    # today is not a close either.
    #
    # `YYYY-MM` sorts chronologically under plain string comparison, which is the
    # property that makes this one indexed query rather than a walk backwards
    # asking each month in turn.
    latest = (
        Balance.objects.filter(month__lt=current)
        .order_by("-month")
        .values_list("month", flat=True)
        .first()
    )

    if latest is None:
        return ReportingMonth(current, MonthBasis.EMPTY, current)

    return ReportingMonth(latest, MonthBasis.CLOSED, current)
