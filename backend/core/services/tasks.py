"""Outstanding tasks — the product's conscience.

The dashboard panel this feeds is the only bordered one on the screen, and that
is deliberate: it is the thing that tells the user what the system needs from
them. Everything else on the dashboard reports; this asks.

Three kinds of task, and no more. Each one corresponds to something that makes a
reported figure less trustworthy than it looks:

  * an account with no balance — the total is computed from what is present, and
    is understating
  * a currency whose rate is missing or stale — a figure is being carried on old
    data, or an account is excluded from the total entirely
  * a recurring proposal awaiting a decision — income or expense that has
    happened but has not been recorded

A fourth task type is a design decision, not an addition. Every task is
something the user must act on during a close, and quality attribute 3 is the
close completing in one sitting.

**Two months, not one, and not all of them.** FR-51 scopes this panel to what is
blocking the current month. The month before it is included as well, because a
close that never finished is exactly the thing a conscience panel exists to
catch, and it is invisible until someone scrolls the spine looking for it. It
stops there deliberately: a panel listing every historic gap grows without bound
and stops being read, and the ledger spine is already the view that shows the
whole history's completeness at a glance. Each task names its own month, so two
rows asking for balances are never mistaken for one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from core.months import as_at_of, month_end, month_of, previous


@dataclass(frozen=True)
class Task:
    kind: str
    count: int
    #: Plain words. A task the user has to decode is a task they postpone.
    message: str
    #: Where to go to resolve it.
    route: str
    #: True where the consequence is an excluded or missing figure rather than
    #: a merely stale one — Breach rather than Carry.
    is_breach: bool = False

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "count": self.count,
            "message": self.message,
            "route": self.route,
            "breach": self.is_breach,
        }


def _tasks_for_month(service, preferences, month: str, *, closed: bool) -> list[Task]:
    """The balance and rate tasks for one month.

    `closed` says whether this is a month the user has already moved past. It
    changes only the wording — a month still being closed is in progress, where
    the one before it is a close that never finished — and never the severity.
    Carry and Breach describe what happened to the figure, not how overdue the
    work is: a missing balance understates in both months, and a missing rate
    excludes in both.
    """
    from core.services.completeness import required_currencies
    from fx.services.reporting import rate_status

    tasks: list[Task] = []
    suffix = "_previous" if closed else ""

    # -- balances ---------------------------------------------------------
    completeness = service.completeness_for(month)

    missing_balances = len(completeness.outstanding_accounts)
    if missing_balances:
        tasks.append(
            Task(
                kind=f"balances{suffix}",
                count=missing_balances,
                message=(
                    f"{missing_balances} account"
                    f"{'s have' if missing_balances != 1 else ' has'} no balance for "
                    f"{month}"
                    f"{', which was never closed' if closed else ''}. Net worth is "
                    f"computed from what is present, so it is understating."
                ),
                route="/month-close",
                is_breach=False,
            )
        )

    # -- rates ------------------------------------------------------------
    # Scoped to the currencies actually in use this month. Reporting on every
    # quoted pair would nag about a currency no account holds — and a panel that
    # cries wolf is a panel that gets ignored, which costs more than the tasks
    # it would have surfaced.
    in_use = set(required_currencies(service.account_histories(), month))

    # As at today for the month in progress, not its month-end (see
    # core.months.as_at_of). Judging the current month at a date that has not
    # arrived ages every rate by the days remaining in it: a rate entered this
    # morning would be reported as two weeks old, and could breach the
    # threshold on the strength of time that has not passed. It would also put
    # this panel in direct contradiction with the FX screen, which asks the same
    # question as of today. For every month that has ended the two dates are the
    # same, so nothing else moves.
    as_at = as_at_of(month)
    when = "today" if as_at != month_end(month) else f"{month} month-end"

    statuses = [
        row
        for row in rate_status(as_at, staleness_days=preferences.rate_staleness_days)
        if row.currency in in_use
    ]
    missing_rates = [row for row in statuses if row.is_missing]
    stale_rates = [row for row in statuses if row.is_stale]

    if missing_rates:
        pairs = ", ".join(row.pair for row in missing_rates)
        tasks.append(
            Task(
                kind=f"rates_missing{suffix}",
                count=len(missing_rates),
                message=(
                    f"No rate on record for {pairs} as at {when}. Accounts in "
                    f"{'those currencies are' if len(missing_rates) != 1 else 'that currency are'} "
                    f"excluded from the translated total — never counted as zero."
                ),
                route="/fx-rates",
                is_breach=True,
            )
        )

    if stale_rates:
        pairs = ", ".join(f"{row.pair} ({row.age_days} days)" for row in stale_rates)
        tasks.append(
            Task(
                kind=f"rates_stale{suffix}",
                count=len(stale_rates),
                message=(
                    f"As at {when}, {pairs} exceed the "
                    f"{preferences.rate_staleness_days}-day threshold. Figures still "
                    f"compute, on rates that old."
                ),
                route="/fx-rates",
                is_breach=False,
            )
        )

    return tasks


def outstanding_tasks(month: str | None = None) -> list[Task]:
    from accounts.services.net_worth import NetWorthService
    from cashflow.services.recurring import outstanding_proposals
    from core.models import Settings

    month = month or month_of(date.today())
    preferences = Settings.load()

    # One service, so the rate resolver's cache is shared across both months.
    service = NetWorthService(staleness_days=preferences.rate_staleness_days)

    tasks = _tasks_for_month(service, preferences, month, closed=False)
    # The month before, because a close that never finished is invisible until
    # someone goes looking for it on the spine. A month that required nothing —
    # before the first account had a balance — yields nothing here, so this is
    # silent rather than apologetic on a new install.
    tasks += _tasks_for_month(service, preferences, previous(month), closed=True)

    # -- recurring --------------------------------------------------------
    # Already cumulative: `through` covers every month up to this one, so
    # proposals from earlier months are counted once, here, and not per month.
    proposals = outstanding_proposals(through=month)
    if proposals:
        tasks.append(
            Task(
                kind="recurring",
                count=len(proposals),
                message=(
                    f"{len(proposals)} recurring proposal"
                    f"{'s are' if len(proposals) != 1 else ' is'} awaiting a decision. "
                    f"Nothing is posted until confirmed."
                ),
                route="/cash-flow",
                is_breach=False,
            )
        )

    return tasks


def task_counts() -> dict[str, int]:
    """Badge counts for the rail, keyed by route."""
    counts: dict[str, int] = {}
    for task in outstanding_tasks():
        counts[task.route] = counts.get(task.route, 0) + task.count
    return counts
