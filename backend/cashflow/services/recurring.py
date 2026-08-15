"""Recurring proposals — outstanding until confirmed or explicitly dismissed.

Nothing here is stored as a "pending transaction". A proposal is **derived**:
the periods a template covers, minus the periods already confirmed, minus the
periods explicitly skipped. That is the same principle as everywhere else in
this system — no computed state persisted, so nothing can drift out of step with
the transactions themselves.

An unconfirmed proposal creates no transaction and leaves no trace in reporting
(BR-14). A skipped period stays skipped rather than reappearing, and stays
recorded rather than vanishing, because a proposal that disappears on its own is
one the user never actually decided about (OI-09).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.months import month_end, month_of, sequence
from core.services.exceptions import BusinessRuleError, NotFoundError
from cashflow.models import (
    Direction,
    Frequency,
    RecurringDismissal,
    RecurringTemplate,
    Transaction,
)
from cashflow.services.entry import record_transaction


@dataclass(frozen=True)
class Proposal:
    template_id: int
    name: str
    period: str
    amount: Decimal
    currency: str
    direction: str
    category_id: int
    category_name: str
    #: The date the confirmed transaction would carry — the period's month end.
    suggested_date: str

    def as_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "period": self.period,
            "amount": str(self.amount),
            "currency": self.currency,
            "direction": self.direction,
            "category_id": self.category_id,
            "category": self.category_name,
            "suggested_date": self.suggested_date,
        }


def _periods_for(template: RecurringTemplate, through: str) -> list[str]:
    """Every period this template covers, from its start to `through`."""
    last = template.end_month or through
    if template.end_month and template.end_month < through:
        last = template.end_month

    step = template.period_months
    return [
        month
        for index, month in enumerate(sequence(template.start_month, last))
        if index % step == 0
    ]


def outstanding_proposals(through: str | None = None) -> list[Proposal]:
    """Every period awaiting a decision, oldest first."""
    through = through or month_of(date.today())

    templates = list(
        RecurringTemplate.objects.filter(is_active=True).select_related("category")
    )
    if not templates:
        return []

    template_ids = [template.pk for template in templates]

    confirmed = {
        (row["recurring_template_id"], row["recurring_period"])
        for row in Transaction.objects.filter(
            recurring_template_id__in=template_ids, recurring_period__isnull=False
        ).values("recurring_template_id", "recurring_period")
    }
    dismissed = {
        (row["template_id"], row["period"])
        for row in RecurringDismissal.objects.filter(
            template_id__in=template_ids
        ).values("template_id", "period")
    }

    proposals: list[Proposal] = []
    for template in templates:
        for period in _periods_for(template, through):
            key = (template.pk, period)
            if key in confirmed or key in dismissed:
                continue
            proposals.append(
                Proposal(
                    template_id=template.pk,
                    name=template.name,
                    period=period,
                    amount=template.amount,
                    currency=template.currency,
                    direction=template.direction,
                    category_id=template.category_id,
                    category_name=template.category.name,
                    suggested_date=month_end(period).isoformat(),
                )
            )

    proposals.sort(key=lambda proposal: (proposal.period, proposal.name))
    return proposals


def _template(pk: int) -> RecurringTemplate:
    template = RecurringTemplate.objects.filter(pk=pk).first()
    if template is None:
        raise NotFoundError("No such recurring template.", code="template_not_found")
    return template


def confirm(
    template_id: int,
    period: str,
    *,
    amount: Decimal | None = None,
    on_date: date | None = None,
):
    """Turn a proposal into a real transaction.

    The amount is adjustable here — that is the whole point of proposing rather
    than posting. Once confirmed, the transaction is independent of its
    template: changing the template later never alters it.
    """
    template = _template(template_id)

    already = Transaction.objects.filter(
        recurring_template=template, recurring_period=period
    ).first()
    if already is not None:
        raise BusinessRuleError(
            f"{template.name} has already been confirmed for {period}.",
            code="already_confirmed",
        )

    return record_transaction(
        on_date=on_date or month_end(period),
        amount=amount if amount is not None else template.amount,
        currency=template.currency,
        category_id=template.category_id,
        note=template.name,
        recurring_template_id=template.pk,
        recurring_period=period,
    )


def dismiss(template_id: int, period: str) -> RecurringDismissal:
    """Skip a period. It stops being proposed and stays recorded as skipped."""
    template = _template(template_id)
    dismissal, _ = RecurringDismissal.objects.update_or_create(
        template=template, period=period, defaults={}
    )
    return dismissal


def end_template(template: RecurringTemplate, end_month: str | None = None) -> RecurringTemplate:
    """Stop future proposals. History is untouched."""
    template.is_active = False
    if end_month:
        template.end_month = end_month
    template.save(update_fields=["is_active", "end_month", "updated_at"])
    return template


__all__ = [
    "Direction",
    "Frequency",
    "Proposal",
    "confirm",
    "dismiss",
    "end_template",
    "outstanding_proposals",
]
