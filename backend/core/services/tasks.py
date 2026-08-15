"""Outstanding tasks — the product's conscience.

The dashboard panel this feeds is the only bordered one on the screen, and that
is deliberate: it is the thing that tells the user what the system needs from
them. Everything else on the dashboard reports; this asks.

Three kinds of task, and no more. Each one corresponds to something that makes a
reported figure less trustworthy than it looks:

  * an account with no balance for the current month — the total is computed
    from what is present, and is understating
  * a currency whose rate is missing or stale — a figure is being carried on old
    data, or an account is excluded from the total entirely
  * a recurring proposal awaiting a decision — income or expense that has
    happened but has not been recorded

A fourth task type is a design decision, not an addition. Every task is
something the user must act on during a close, and quality attribute 3 is the
close completing in one sitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from core.months import month_end, month_of


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


def outstanding_tasks(month: str | None = None) -> list[Task]:
    from accounts.services.net_worth import NetWorthService
    from cashflow.services.recurring import outstanding_proposals
    from core.models import Settings
    from core.services.completeness import required_currencies
    from fx.services.reporting import rate_status

    month = month or month_of(date.today())
    preferences = Settings.load()
    tasks: list[Task] = []

    # -- balances ---------------------------------------------------------
    service = NetWorthService(staleness_days=preferences.rate_staleness_days)
    completeness = service.completeness_for(month)

    missing_balances = len(completeness.outstanding_accounts)
    if missing_balances:
        tasks.append(
            Task(
                kind="balances",
                count=missing_balances,
                message=(
                    f"{missing_balances} account"
                    f"{'s have' if missing_balances != 1 else ' has'} no balance for "
                    f"{month}. Net worth is computed from what is present, so it is "
                    f"understating."
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

    statuses = [
        row
        for row in rate_status(
            month_end(month), staleness_days=preferences.rate_staleness_days
        )
        if row.currency in in_use
    ]
    missing_rates = [row for row in statuses if row.is_missing]
    stale_rates = [row for row in statuses if row.is_stale]

    if missing_rates:
        pairs = ", ".join(row.pair for row in missing_rates)
        tasks.append(
            Task(
                kind="rates_missing",
                count=len(missing_rates),
                message=(
                    f"No rate on record for {pairs}. Accounts in "
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
                kind="rates_stale",
                count=len(stale_rates),
                message=(
                    f"{pairs} exceed the {preferences.rate_staleness_days}-day "
                    f"threshold. Figures still compute, on rates that old."
                ),
                route="/fx-rates",
                is_breach=False,
            )
        )

    # -- recurring --------------------------------------------------------
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
