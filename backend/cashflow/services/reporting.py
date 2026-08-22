"""Category reporting — per currency, and never translated.

This is the one reporting service in the system that does **not** go through the
translation service, and the omission is deliberate. Cash flow amounts stay in
the currency they were entered in (BR-12 module note, design handoff §6). A
month's groceries in MYR and a month's rent in AUD are not meaningfully added
together at a month-end rate; they are two separate facts about two separate
lives, and combining them would invent a figure the user never observed.

The other omission: **no total here is ever added to a balance figure** (BR-12).
There is no endpoint that returns both, which is what makes that structural
rather than a matter of remembering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Sum

from core.months import month_end, month_start, previous, sequence
from core.services.movement import movement
from cashflow.models import Direction, Transaction


@dataclass
class CategoryTotal:
    category_id: int
    name: str
    parent: str
    direction: str
    currency: str
    total: Decimal
    count: int
    #: The same category's total a month earlier, in the same currency. Zero
    #: where it had none: a month with no spending in a category genuinely spent
    #: nothing in it, which is the one place absence and zero coincide — the
    #: reason :func:`category_trend` gives. A month with no *balances*, by
    #: contrast, has no figure at all.
    prior: Decimal = Decimal(0)

    def as_dict(self) -> dict:
        return {
            "category_id": self.category_id,
            "category": self.name,
            "parent": self.parent,
            "direction": self.direction,
            "currency": self.currency,
            "total": str(self.total.quantize(Decimal("0.01"))),
            "count": self.count,
            # Through the one definition of a change, so this column and the
            # dashboard's cannot disagree.
            "change": movement(self.total, self.prior),
        }


@dataclass
class CurrencyBlock:
    """One currency's income, expense and net. Never combined with another's."""

    currency: str
    income: Decimal = Decimal(0)
    expense: Decimal = Decimal(0)
    children: list[CategoryTotal] = field(default_factory=list)
    #: Last month's parent totals for this currency, keyed (direction, parent).
    prior_parents: dict[tuple[str, str], Decimal] = field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        return self.income - self.expense

    def parents(self) -> list[dict]:
        rollup: dict[tuple[str, str], dict] = {}
        for child in self.children:
            key = (child.direction, child.parent)
            entry = rollup.setdefault(
                key,
                {
                    "parent": child.parent,
                    "direction": child.direction,
                    "total": Decimal(0),
                    "count": 0,
                },
            )
            entry["total"] += child.total
            entry["count"] += child.count
        return [
            {
                **entry,
                "total": str(entry["total"].quantize(Decimal("0.01"))),
                # Rolled up from last month's children the same way this month's
                # are, rather than summed from the changes: adding differences
                # and differencing sums agree in arithmetic but not in rounding.
                "change": movement(
                    entry["total"],
                    self.prior_parents.get(
                        (entry["direction"], entry["parent"]), Decimal(0)
                    ),
                ),
            }
            for entry in sorted(
                rollup.values(), key=lambda row: (row["direction"], row["parent"])
            )
        ]

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "income": str(self.income.quantize(Decimal("0.01"))),
            "expense": str(self.expense.quantize(Decimal("0.01"))),
            "net": str(self.net.quantize(Decimal("0.01"))),
            "parents": self.parents(),
            "children": [child.as_dict() for child in self.children],
        }


def _category_rows(month: str):
    """One month's transactions, totalled per category and currency."""
    return (
        Transaction.objects.filter(
            date__gte=month_start(month), date__lte=month_end(month)
        )
        .values(
            "currency",
            "direction",
            "category_id",
            "category__name",
            "category__parent__name",
        )
        .annotate(total=Sum("amount"), count=Sum(1))
        .order_by("currency", "direction", "category__parent__name", "category__name")
    )


def _prior_totals(month: str) -> tuple[dict, dict]:
    """Last month's totals, keyed for lookup: by category, and by parent.

    Read for the change column only. The figures themselves are never taken from
    here — a row states this month's total, and the month before it is a
    comparison, not a second figure to render.
    """
    children: dict[tuple[str, int], Decimal] = {}
    parents: dict[tuple[str, str, str], Decimal] = {}

    for row in _category_rows(month):
        total = row["total"] or Decimal(0)
        children[(row["currency"], row["category_id"])] = total
        key = (
            row["currency"],
            row["direction"],
            row["category__parent__name"] or "—",
        )
        parents[key] = parents.get(key, Decimal(0)) + total

    return children, parents


def category_report(month: str) -> list[dict]:
    """Totals by child and parent category for one month, split by currency.

    Every row carries its movement on the same category a month earlier, in the
    same currency — never across currencies, for the reason at the top of this
    module.
    """
    prior_children, prior_parents = _prior_totals(previous(month))

    blocks: dict[str, CurrencyBlock] = {}
    for row in _category_rows(month):
        block = blocks.setdefault(row["currency"], CurrencyBlock(currency=row["currency"]))
        total = row["total"] or Decimal(0)

        if row["direction"] == Direction.INCOME:
            block.income += total
        else:
            block.expense += total

        parent = row["category__parent__name"] or "—"
        block.prior_parents[(row["direction"], parent)] = prior_parents.get(
            (row["currency"], row["direction"], parent), Decimal(0)
        )

        block.children.append(
            CategoryTotal(
                category_id=row["category_id"],
                name=row["category__name"],
                parent=parent,
                direction=row["direction"],
                currency=row["currency"],
                total=total,
                count=row["count"],
                prior=prior_children.get(
                    (row["currency"], row["category_id"]), Decimal(0)
                ),
            )
        )

    return [blocks[currency].as_dict() for currency in sorted(blocks)]


def category_trend(from_month: str, to_month: str, category_id: int | None = None) -> dict:
    """A category's totals over a range, per currency.

    Months with no transactions are reported as zero rather than omitted: unlike
    net worth, where a month with no balances has no figure at all, a month with
    no spending in a category genuinely spent nothing in it. Absence and zero
    coincide here, and only here.
    """
    months = sequence(from_month, to_month)
    if not months:
        return {"months": [], "series": []}

    query = Transaction.objects.filter(
        date__gte=month_start(months[0]), date__lte=month_end(months[-1])
    )
    if category_id is not None:
        query = query.filter(category_id=category_id)

    rows = (
        query.values("currency", "direction", "date__year", "date__month")
        .annotate(total=Sum("amount"))
        .order_by()
    )

    buckets: dict[tuple[str, str], dict[str, Decimal]] = {}
    for row in rows:
        month = f"{row['date__year']:04d}-{row['date__month']:02d}"
        key = (row["currency"], row["direction"])
        buckets.setdefault(key, {})[month] = row["total"] or Decimal(0)

    series = [
        {
            "currency": currency,
            "direction": direction,
            "points": [
                str(values.get(month, Decimal(0)).quantize(Decimal("0.01")))
                for month in months
            ],
        }
        for (currency, direction), values in sorted(buckets.items())
    ]

    return {"months": list(months), "series": series}


def transaction_row(row: Transaction) -> dict:
    """The one shape a transaction takes on the wire.

    The month list and the responses to entry and to an edit all serialise
    through here, so a row cannot change shape depending on which call the
    client happened to make.
    """
    return {
        "id": row.pk,
        "date": row.date.isoformat(),
        "amount": str(row.amount.quantize(Decimal("0.01"))),
        "currency": row.currency,
        "direction": row.direction,
        "category_id": row.category_id,
        "category": row.category.name,
        "parent": row.category.parent.name if row.category.parent else "—",
        "note": row.note,
        "from_recurring": row.recurring_template_id is not None,
    }


def transactions_for_month(month: str) -> list[dict]:
    rows = (
        Transaction.objects.filter(
            date__gte=month_start(month), date__lte=month_end(month)
        )
        .select_related("category", "category__parent")
        .order_by("-date", "-id")
    )

    return [transaction_row(row) for row in rows]
