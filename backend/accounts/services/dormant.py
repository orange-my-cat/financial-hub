"""Dormant balances, materialised month by month.

A dormant account is one nobody touches, so its balance does not change: this
month holds what last month held. Every report already behaved that way — net
worth carries the last recorded figure forward on read (BR-03) — but only in
memory. The months in between held no balance at all, so Month Close showed
them as empty and the database disagreed with every screen that read it.

They are stored now. One `Balance` per dormant account per month with none of its
own, holding the most recent figure recorded before it, indistinguishable from a
figure typed on the screen because there is nothing about it that differs. A
dormant account is complete in the database as well as in the reports.

Every gap from the account's first recorded month onward, not only the months
after its newest figure. That is not extra ambition: net worth already reads a
dormant account this way — `_balance_for` looks at the status the account has
now, so a now-dormant account is already reported at its last known figure in
every month it has none, gaps in the middle included. Filling them changes no
total anywhere. It makes the rows say what the reports have always said.

Nothing before the first recorded month, ever. An account is required only from
the later of its opening and its first recorded balance (ADR-04), and there is no
figure to carry into a month that precedes every figure there is.

**On ADR-05.** Nothing computed is stored, and it is worth being precise about
which part of that this touches. What is written is not a computed figure: it is
a copy of an entered fact, at full precision, for an account whose defining
property is that the fact has not changed. No total, no aggregate and no derived
quantity is persisted by this or by anything else. What it does give up is the
propagation a derived-on-read carry-forward had for free — correcting the source
month's figure after a roll leaves the copies holding the old one, because
nothing marks a copy as a copy. That cost was weighed and accepted.

Three properties, each a decision:

**Idempotent.** A month that already holds a figure is never touched, typed or
rolled. So this can run on every read of a month and do nothing the second time,
which is what makes it safe to call from the Month Close query. The first roll
for a long-dormant account writes a row per month since its first figure, which
is a few dozen rows once.

**Never ahead of today.** A month that has not arrived gets no figure. "The
balance has not changed" is a statement about the past; writing it forward would
be a forecast, and this system does not forecast.

**A discarded month is refilled.** For an account nobody touches, "this month
has no balance" is not a state that means anything — so a month whose figure was
cleared gets the figure again on the next roll. The screen does not offer a
control that undoes itself: Month Close hides the discard bin on a dormant row,
because what would be discarded is a property of dormancy rather than an entry.
A row is added rather than the deleted one revived, which is what
`lifecycle.upsert_balance` does after a clear too.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction

from core.months import month_of, sequence
from accounts.models import Account, AccountStatus, Balance


@transaction.atomic
def roll_dormant_balances(month: str, *, today: date | None = None) -> tuple[Balance, ...]:
    """Store every dormant account's balance for each month up to `month`.

    Returns the rows written, which is empty on every call after the first for a
    given month — the useful property, not a detail.

    `today` is what "now" means when refusing to write ahead of it, and exists so
    the bound can be tested without waiting for a month to pass.
    """
    horizon = min(month, month_of(today or date.today()))

    written: list[Balance] = []
    for account in Account.objects.filter(status=AccountStatus.DORMANT):
        written.extend(_roll_one(account, horizon))

    return tuple(written)


def _roll_one(account: Account, horizon: str) -> list[Balance]:
    """One account's copies: every month with no figure, up to `horizon`.

    Walks the months in order and carries the last figure it has seen, which is
    the same walk net worth makes on read — so a gap in the middle is filled from
    the figure before it rather than from the newest one, and the stored rows
    match what every report already says.
    """
    stored = dict(account.balances.filter(month__lte=horizon).values_list("month", "amount"))
    if not stored:
        # `set_dormant` refuses an account with no balance to carry, so this is
        # reachable only for a horizon earlier than the account's first figure.
        return []

    # A closed account is never dormant (the status constraint says so), but the
    # closing month is honoured anyway rather than trusted to be absent.
    if account.closed_month is not None:
        horizon = min(horizon, account.closed_month)

    # The walk starts on a month that has a figure — it starts on the earliest
    # one there is — so there is always something to carry, and no month before
    # the first figure is ever reached.
    months = sequence(min(stored), horizon)
    carried = stored[months[0]]

    rows: list[Balance] = []
    for candidate in months:
        figure = stored.get(candidate)
        if figure is not None:
            carried = figure
            continue
        rows.append(Balance(account=account, month=candidate, amount=carried))

    if not rows:
        return []

    # `ignore_conflicts`, because the one conflict this can hit is the one row it
    # would have written anyway: two Month Close reads arriving together — a
    # refetch on window focus is enough — would otherwise race into the unique
    # constraint and turn a read into a 500. The month keeps whichever figure
    # landed first, which is the same figure either way.
    return Balance.objects.bulk_create(rows, ignore_conflicts=True)
