"""Recording transactions, and the probable-duplicate advisory.

Entry is manual and per-transaction. There is no import path in v1, so entry
speed is the whole battle — which is why the advisory here warns and never
blocks. Two identical amounts to the same category on the same day is a
perfectly ordinary thing (two coffees, two fares), and refusing the second would
be wrong far more often than it would be right.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.services.advisories import Advisory, AdvisoryKind
from core.services.exceptions import BusinessRuleError, NotFoundError
from cashflow.models import Category, Direction, Transaction


@dataclass(frozen=True)
class RecordedTransaction:
    transaction: Transaction
    advisories: tuple[Advisory, ...] = ()


def _require_child_category(category_id: int) -> Category:
    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        raise NotFoundError("No such category.", code="category_not_found", field="category")

    if category.is_parent:
        raise BusinessRuleError(
            f"{category.name} is a parent category. Parents exist for rollup only; "
            f"every transaction attaches to a child category (BR-22).",
            code="parent_category_not_selectable",
            field="category",
        )
    if not category.is_active:
        raise BusinessRuleError(
            f"{category.name} has been deactivated and is unavailable for new "
            f"transactions. Its history is intact.",
            code="category_inactive",
            field="category",
        )
    return category


def duplicate_advisory(
    on_date: date,
    amount: Decimal,
    category: Category,
    *,
    exclude_id: int | None = None,
) -> Advisory | None:
    """Matching date, amount and category (FR-23). Adding anyway is permitted."""
    matches = Transaction.objects.filter(
        date=on_date, amount=amount, category=category
    )
    if exclude_id is not None:
        matches = matches.exclude(pk=exclude_id)

    existing = matches.first()
    if existing is None:
        return None

    count = matches.count()
    return Advisory(
        kind=AdvisoryKind.PROBABLE_DUPLICATE,
        message=(
            f"{count} transaction{'s' if count != 1 else ''} already recorded for "
            f"{on_date:%d %b %Y} at {amount} {existing.currency} in "
            f"{category.name}. Adding this one anyway is fine — two identical "
            f"amounts on one day are ordinary."
        ),
        detail={
            "existing_id": existing.pk,
            "existing_count": count,
            "date": on_date.isoformat(),
            "amount": str(amount),
            "currency": existing.currency,
            "category": category.name,
        },
    )


def record_transaction(
    *,
    on_date: date,
    amount: Decimal,
    currency: str,
    category_id: int,
    note: str = "",
    account_id: int | None = None,
    recurring_template_id: int | None = None,
    recurring_period: str | None = None,
) -> RecordedTransaction:
    if amount <= 0:
        raise BusinessRuleError(
            "Enter the amount as a positive figure. Income and expense are "
            "distinguished by the category, not by the sign.",
            code="amount_not_positive",
            field="amount",
        )

    category = _require_child_category(category_id)
    advisory = duplicate_advisory(on_date, amount, category)

    transaction = Transaction.objects.create(
        date=on_date,
        amount=amount,
        currency=currency,
        # Taken from the category, not from the form. A transaction whose
        # direction disagreed with its category would corrupt every report that
        # separates income from expense.
        direction=category.direction,
        category=category,
        note=note,
        account_id=account_id,
        recurring_template_id=recurring_template_id,
        recurring_period=recurring_period,
    )

    return RecordedTransaction(
        transaction=transaction, advisories=(advisory,) if advisory else ()
    )


def update_transaction(
    transaction: Transaction,
    *,
    on_date: date | None = None,
    amount: Decimal | None = None,
    currency: str | None = None,
    category_id: int | None = None,
    note: str | None = None,
    account_id: int | None = ...,  # type: ignore[assignment]
) -> RecordedTransaction:
    """Everything is editable at any time, including history (BR-23)."""
    if amount is not None:
        if amount <= 0:
            raise BusinessRuleError(
                "Enter the amount as a positive figure.",
                code="amount_not_positive",
                field="amount",
            )
        transaction.amount = amount

    if on_date is not None:
        transaction.date = on_date
    if currency is not None:
        transaction.currency = currency
    if note is not None:
        transaction.note = note
    if account_id is not ...:
        transaction.account_id = account_id

    if category_id is not None:
        category = _require_child_category(category_id)
        transaction.category = category
        transaction.direction = category.direction

    transaction.save()

    advisory = duplicate_advisory(
        transaction.date,
        transaction.amount,
        transaction.category,
        exclude_id=transaction.pk,
    )
    return RecordedTransaction(
        transaction=transaction, advisories=(advisory,) if advisory else ()
    )


def delete_transaction(transaction: Transaction) -> None:
    transaction.delete()


__all__ = [
    "Direction",
    "RecordedTransaction",
    "delete_transaction",
    "duplicate_advisory",
    "record_transaction",
    "update_transaction",
]
