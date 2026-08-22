"""Recurring proposals — outstanding until confirmed or explicitly dismissed.

Nothing here is stored as a "pending transaction". A proposal is **derived**:
the occurrences a template covers, minus the ones already confirmed, minus the
ones explicitly skipped. That is the same principle as everywhere else in this
system — no computed state persisted, so nothing can drift out of step with the
transactions themselves.

An occurrence is a date, not a month. A weekly arrangement falls four or five
times in a month and a fortnightly one twice, so a month key cannot name which
of them is being decided. Every occurrence is counted from the template's anchor
date, which is what fixes the weekday of a weekly item and the day of the month
of a monthly one.

An unconfirmed proposal creates no transaction and leaves no trace in reporting
(BR-14). A skipped occurrence stays skipped rather than reappearing, and stays
recorded rather than vanishing, because a proposal that disappears on its own is
one the user never actually decided about (OI-09).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from core.months import month_end, month_of, month_start
from core.services.exceptions import BusinessRuleError, NotFoundError
from cashflow.models import (
    Direction,
    Frequency,
    RecurringDismissal,
    RecurringTemplate,
    Transaction,
)
from cashflow.services.entry import record_transaction

#: A guard, not a policy. Ten years of weekly occurrences is ~520; anything past
#: this is a template anchored centuries ago by mistake, and generating for it
#: would hang the request rather than report the error.
_MAX_OCCURRENCES = 2000


class ProposalStatus(StrEnum):
    """What has been decided about an occurrence. The exact words, in code and UI.

    Three, not two. An occurrence nobody has answered yet and one deliberately
    skipped are different facts about the month, and a screen that showed both
    as an absence could not tell the user which had happened.
    """

    OUTSTANDING = "Outstanding"
    CONFIRMED = "Confirmed"
    SKIPPED = "Skipped"


@dataclass(frozen=True)
class Proposal:
    template_id: int
    name: str
    #: The date this occurrence falls on. Its identity, and the date the
    #: confirmed transaction carries unless the user overrides it.
    occurrence: date
    amount: Decimal
    currency: str
    direction: str
    category_id: int
    category_name: str
    status: str = ProposalStatus.OUTSTANDING
    #: What was actually recorded, where this was confirmed. The amount is
    #: adjustable at confirmation and the date can be moved off the occurrence,
    #: so neither is safely assumed from the template: a confirmed row that
    #: restated the template would be reporting the proposal, not the
    #: transaction it became.
    recorded_amount: Decimal | None = None
    recorded_date: date | None = None

    def as_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "occurrence": self.occurrence.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "direction": self.direction,
            "category_id": self.category_id,
            "category": self.category_name,
            "status": str(self.status),
            "recorded_amount": (
                str(self.recorded_amount) if self.recorded_amount is not None else None
            ),
            "recorded_date": (
                self.recorded_date.isoformat() if self.recorded_date else None
            ),
        }


def add_months(anchor: date, months: int) -> date:
    """`anchor` shifted by whole months, clamped to a month that is shorter.

    Rent anchored to the 31st falls on the 28th of February and on the 31st of
    March again — clamping the derived date rather than moving the anchor, so one
    short month does not permanently drag the arrangement earlier.
    """
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    last = month_end(f"{year:04d}-{month:02d}")
    return last.replace(day=min(anchor.day, last.day))


def occurrences(template: RecurringTemplate, through: str) -> list[date]:
    """Every occurrence from the anchor date to the end of `through`.

    Bounded by the month asked for first and by the template's own end date
    second, so a template that ends next year proposes nothing beyond the month
    the caller asked about.
    """
    last = month_end(through)
    if template.end_date and template.end_date < last:
        last = template.end_date

    step = template.step_days
    dates: list[date] = []
    index = 0
    while len(dates) < _MAX_OCCURRENCES:
        moment = (
            template.anchor_date + timedelta(days=step * index)
            if step is not None
            else add_months(template.anchor_date, index)
        )
        if moment > last:
            break
        dates.append(moment)
        index += 1
    return dates


def _derive(through: str) -> list[Proposal]:
    """Every occurrence to the end of `through`, each carrying its status.

    The one derivation. What separates its callers is which of these rows they
    are interested in, never how a row is arrived at, so an occurrence cannot be
    outstanding on one screen and answered on another.

    A confirmed occurrence is one whose transaction still exists. Deleting that
    transaction returns the occurrence to Outstanding, which is right: the
    decision was undone, and the delete was soft, so nothing was lost either way
    (ADR-03).
    """
    # Every template, ended ones included. An occurrence that fell before the end
    # date and was never decided is still owed a decision (OI-09) — ending an
    # arrangement is not a way to make its unanswered weeks disappear. Nothing
    # runs away here: generation is bounded by the month asked for either way.
    templates = list(RecurringTemplate.objects.select_related("category"))
    if not templates:
        return []

    template_ids = [template.pk for template in templates]

    confirmed = {
        (row["recurring_template_id"], row["recurring_occurrence"]): row
        for row in Transaction.objects.filter(
            recurring_template_id__in=template_ids, recurring_occurrence__isnull=False
        ).values("recurring_template_id", "recurring_occurrence", "amount", "date")
    }
    dismissed = {
        (row["template_id"], row["occurrence"])
        for row in RecurringDismissal.objects.filter(
            template_id__in=template_ids
        ).values("template_id", "occurrence")
    }

    proposals: list[Proposal] = []
    for template in templates:
        for moment in occurrences(template, through):
            recorded = confirmed.get((template.pk, moment))

            if recorded is not None:
                status = ProposalStatus.CONFIRMED
            elif (template.pk, moment) in dismissed:
                status = ProposalStatus.SKIPPED
            else:
                status = ProposalStatus.OUTSTANDING

            proposals.append(
                Proposal(
                    template_id=template.pk,
                    name=template.name,
                    occurrence=moment,
                    amount=template.amount,
                    currency=template.currency,
                    direction=template.direction,
                    category_id=template.category_id,
                    category_name=template.category.name,
                    status=status,
                    recorded_amount=recorded["amount"] if recorded else None,
                    recorded_date=recorded["date"] if recorded else None,
                )
            )

    proposals.sort(key=lambda proposal: (proposal.occurrence, proposal.name))
    return proposals


def outstanding_proposals(through: str | None = None) -> list[Proposal]:
    """Every occurrence awaiting a decision, oldest first.

    The undecided ones alone. This is what the dashboard counts, and a count
    that included answered occurrences would nag about work already done.
    """
    through = through or month_of(date.today())
    return [
        proposal
        for proposal in _derive(through)
        if proposal.status == ProposalStatus.OUTSTANDING
    ]


def proposals_for_month(month: str) -> list[Proposal]:
    """Every occurrence inside one month, answered or not, each with its status.

    Answered occurrences stay on the list. A row that vanished on confirmation
    would leave the screen silent about what had just happened, and would make a
    skipped occurrence indistinguishable from one that was never proposed — so
    the month reads as the arrangement it is: what is due, what was taken, and
    what was let go. Only the undecided rows still offer a decision.

    The Cash Flow screen works a month at a time — the spine picks the month,
    the entry form records into it — and a panel there listing every occurrence
    ever left undecided is a list about other months on a screen about this one.

    Nothing is lost by their absence. An occurrence never decided is still owed
    a decision (OI-09), and that is what the dashboard's outstanding tasks panel
    is for: it counts every proposal through the last month that has ended,
    cumulatively, which is the one place work left undone is meant to surface.
    Scoping here and counting there is the same division the tasks panel already
    states from its own side.

    Cut from the same derivation as :func:`outstanding_proposals`, so the two
    can never disagree about what has been decided. This one only takes a
    different slice of it, and orders it differently.

    **Undecided first, then the answered ones, each by date.** The panel is a
    queue before it is a record: what is still owed a decision is the work, and
    a month whose first fortnight is answered would otherwise open on rows with
    nothing left to do. Order is decided here rather than in the browser so the
    API and the screen agree on what "first" means.
    """
    first, last = month_start(month), month_end(month)
    return sorted(
        (
            proposal
            for proposal in _derive(month)
            if first <= proposal.occurrence <= last
        ),
        key=lambda proposal: (
            proposal.status != ProposalStatus.OUTSTANDING,
            proposal.occurrence,
            proposal.name,
        ),
    )


def get_template(pk: int) -> RecurringTemplate:
    """The template, or a NotFoundError naming what was missing."""
    template = RecurringTemplate.objects.filter(pk=pk).first()
    if template is None:
        raise NotFoundError("No such recurring template.", code="template_not_found")
    return template


def templates() -> list[RecurringTemplate]:
    """Every template, active or ended, with its category loaded."""
    return list(RecurringTemplate.objects.select_related("category__parent").all())


def confirm(
    template_id: int,
    occurrence: date,
    *,
    amount: Decimal | None = None,
    on_date: date | None = None,
):
    """Turn a proposal into a real transaction.

    The amount is adjustable here — that is the whole point of proposing rather
    than posting — and so is the date, which otherwise falls on the occurrence
    itself. Once confirmed, the transaction is independent of its template:
    changing the template later never alters it.
    """
    template = get_template(template_id)

    already = Transaction.objects.filter(
        recurring_template=template, recurring_occurrence=occurrence
    ).first()
    if already is not None:
        raise BusinessRuleError(
            f"{template.name} has already been confirmed for {occurrence:%d %b %Y}.",
            code="already_confirmed",
        )

    return record_transaction(
        on_date=on_date or occurrence,
        amount=amount if amount is not None else template.amount,
        currency=template.currency,
        category_id=template.category_id,
        note=template.name,
        recurring_template_id=template.pk,
        recurring_occurrence=occurrence,
    )


def dismiss(template_id: int, occurrence: date) -> RecurringDismissal:
    """Skip an occurrence. It stops being proposed and stays recorded as skipped."""
    template = get_template(template_id)
    dismissal, _ = RecurringDismissal.objects.update_or_create(
        template=template, occurrence=occurrence, defaults={}
    )
    return dismissal


def end_template(
    template: RecurringTemplate,
    end_date: date | None = None,
    *,
    today: date | None = None,
) -> RecurringTemplate:
    """Stop proposals after `end_date`, defaulting to today. History is untouched.

    `is_active` is a statement about the date, not a second switch: a template
    ending next month is still running, and one that ended in June is not. The
    end date is what actually stops the occurrences, which is why an arrangement
    cancelled before it ever started — an end date earlier than the anchor —
    correctly proposes nothing at all.
    """
    now = today or date.today()
    template.end_date = end_date or now
    template.is_active = template.end_date > now
    template.save(update_fields=["is_active", "end_date", "updated_at"])
    return template


__all__ = [
    "Direction",
    "Frequency",
    "Proposal",
    "ProposalStatus",
    "add_months",
    "confirm",
    "dismiss",
    "end_template",
    "get_template",
    "occurrences",
    "outstanding_proposals",
    "proposals_for_month",
    "templates",
]
