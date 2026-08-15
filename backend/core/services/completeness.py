"""Completeness — four states, not two.

    Complete       every required account and rate is present
    Incomplete     some entered, some absent
    Missing        the month is within range and nothing has been entered
    Outside Range  before the first account had a balance — not a fault

The fourth state is the one that earns the design its keep. A binary
done/not-done would paint every month before the user started recording as a
failure, which is both wrong and demoralising on a screen whose entire job is to
be worth returning to each month.

**Completeness is a status, never a prohibition.** Nothing here prevents any
action. A partly closed month is a legitimate, expressible state — Month Close is
deliberately not a transaction, because making it atomic would mean an
interruption discards the work (§9.6).

**No month table.** Months are derived from the data that exists (ADR-04), and
an account is required only from the *later* of its opening date and the first
month a balance was actually recorded for it. That second clause is what makes
back-filling a lossy spreadsheet survivable: recording an account from 2019
onward does not retrospectively indict every month since it was opened in 2012.

This module is pure. It takes plain values and returns plain values, with no
model import anywhere, so the account and balance rows it describes can arrive
at Stage 2 without it changing.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from core.currencies import BASE_CURRENCY
from core.months import require_month


class CompletenessState(StrEnum):
    """The exact words. Used in code, UI and tests alike."""

    COMPLETE = "Complete"
    INCOMPLETE = "Incomplete"
    MISSING = "Missing"
    OUTSIDE_RANGE = "Outside Range"


@dataclass(frozen=True)
class AccountHistory:
    """What completeness needs to know about one account.

    Supplied by the accounts module from Stage 2. Held as a plain value here so
    the rule can be tested against a dozen shapes of history in milliseconds.
    """

    account_id: int
    name: str
    currency: str
    #: `YYYY-MM` the account was opened.
    opened_month: str
    #: The first month a balance was actually recorded. None where the account
    #: has no history at all, in which case it is required for no month yet.
    first_recorded_month: str | None
    #: `YYYY-MM` the account was closed, if it has been.
    closed_month: str | None = None

    @property
    def required_from(self) -> str | None:
        """The later of opening and first recorded balance (ADR-04)."""
        if self.first_recorded_month is None:
            return None
        return max(self.opened_month, self.first_recorded_month)

    def is_required_for(self, month: str) -> bool:
        start = self.required_from
        if start is None or month < start:
            return False
        if self.closed_month is not None and month > self.closed_month:
            return False
        return True


@dataclass(frozen=True)
class MonthCompleteness:
    month: str
    state: CompletenessState
    balances_expected: int
    balances_recorded: int
    rates_expected: int
    rates_recorded: int
    outstanding_accounts: tuple[str, ...] = field(default_factory=tuple)
    outstanding_currencies: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_complete(self) -> bool:
        return self.state is CompletenessState.COMPLETE

    def as_dict(self) -> dict:
        return {
            "month": self.month,
            "state": str(self.state),
            "balances": {
                "expected": self.balances_expected,
                "recorded": self.balances_recorded,
            },
            "rates": {"expected": self.rates_expected, "recorded": self.rates_recorded},
            "outstanding_accounts": list(self.outstanding_accounts),
            "outstanding_currencies": list(self.outstanding_currencies),
        }


def required_currencies(accounts: Sequence[AccountHistory], month: str) -> tuple[str, ...]:
    """The non-base currencies needing a month-end rate for this month.

    USD is excluded: the base against itself is always 1 and is never entered
    (BR-09). Only month-end rates are required; any other date is optional and
    exists solely to enrich the trend chart (ADR-08).
    """
    codes = {
        account.currency
        for account in accounts
        if account.is_required_for(month) and account.currency != BASE_CURRENCY
    }
    return tuple(sorted(codes))


def month_completeness(
    month: str,
    accounts: Sequence[AccountHistory],
    *,
    balances_recorded_for: Collection[int] = (),
    rates_recorded_for: Collection[str] = (),
) -> MonthCompleteness:
    """The state of one month.

    `balances_recorded_for` is the account ids with a balance for this month;
    `rates_recorded_for` is the currencies with a rate **on the month-end date**.
    A carried-forward rate keeps reports working but does not make the month
    complete — nobody entered it.
    """
    require_month(month)

    required = [account for account in accounts if account.is_required_for(month)]
    recorded_ids = set(balances_recorded_for)
    recorded_rates = set(rates_recorded_for)

    currencies = required_currencies(accounts, month)

    balances_expected = len(required)
    balances_recorded = sum(1 for a in required if a.account_id in recorded_ids)
    rates_expected = len(currencies)
    rates_recorded = sum(1 for code in currencies if code in recorded_rates)

    outstanding_accounts = tuple(
        a.name for a in required if a.account_id not in recorded_ids
    )
    outstanding_currencies = tuple(
        code for code in currencies if code not in recorded_rates
    )

    expected = balances_expected + rates_expected
    present = balances_recorded + rates_recorded

    if balances_expected == 0:
        # Nothing was ever required of this month. Before the first account had
        # a balance — not a fault, and not something to colour red.
        state = CompletenessState.OUTSIDE_RANGE
    elif present == 0:
        state = CompletenessState.MISSING
    elif present == expected:
        state = CompletenessState.COMPLETE
    else:
        state = CompletenessState.INCOMPLETE

    return MonthCompleteness(
        month=month,
        state=state,
        balances_expected=balances_expected,
        balances_recorded=balances_recorded,
        rates_expected=rates_expected,
        rates_recorded=rates_recorded,
        outstanding_accounts=outstanding_accounts,
        outstanding_currencies=outstanding_currencies,
    )


def recorded_from(accounts: Sequence[AccountHistory]) -> str | None:
    """The first month any account recorded a balance, or None if none has.

    This is where the ledger spine starts. Before it there is no history to
    show, which is why the spine renders from here rather than over a fixed
    trailing window.
    """
    starts = [a.required_from for a in accounts if a.required_from is not None]
    return min(starts) if starts else None
