"""Turning stored transactions into computed state, and back into a payload.

This module is the only bridge between the database and the replay engine. The
engine itself knows nothing about Django, and everything it needs arrives as
plain values — which is what lets the arithmetic be tested in milliseconds
against figures worked by hand.

Realised gains are grouped by **holding currency and never summed across
currencies** (BR-18). Estimated tax is a user-typed percentage applied to gains
only, and every net figure it produces is labelled indicative (BR-21, OI-05).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.money import trim
from core.services.exceptions import BusinessRuleError, NotFoundError
from investments.models import Holding, InvestmentTransaction
from investments.replay import Action, ReplayResult, ReplayTransaction, replay

CENTS = Decimal("0.01")


def to_replay(rows) -> list[ReplayTransaction]:
    return [
        ReplayTransaction(
            id=row.pk,
            action=Action(row.action),
            on_date=row.date,
            sequence=row.sequence,
            quantity=row.quantity,
            unit_price=row.unit_price,
            fees=row.fees,
            split_ratio=row.split_ratio,
            cash_amount=row.cash_amount,
        )
        for row in rows
    ]


def replay_holding(holding: Holding) -> ReplayResult:
    """Every figure this system shows for a holding comes through here."""
    return replay(to_replay(holding.transactions.all()))


def get_holding(pk: int) -> Holding:
    holding = Holding.objects.filter(pk=pk).first()
    if holding is None:
        raise NotFoundError(f"No holding with id {pk}.", code="holding_not_found")
    return holding


# ---------------------------------------------------------------------------
# Tax — indicative, and only ever on gains
# ---------------------------------------------------------------------------


def net_of_tax(gain: Decimal, percent: Decimal | None) -> tuple[Decimal, bool]:
    """Apply the user's percentage to a gain. Returns (net, was_applied).

    Not applied to losses (OI-05): losses are shown gross. Applying a percentage
    to a loss would imply a refund the system knows nothing about, and the
    system knows nothing about tax at all.
    """
    if percent is None or gain <= 0:
        return gain, False
    return gain - (gain * percent / 100), True


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldingPosition:
    holding: Holding
    result: ReplayResult

    def as_dict(self) -> dict:
        return {
            "id": self.holding.pk,
            "name": self.holding.name,
            "symbol": self.holding.symbol,
            "instrument_type": self.holding.instrument_type,
            "currency": self.holding.currency,
            "account_id": self.holding.account_id,
            "account": self.holding.account.name,
            "estimated_tax_percent": (
                trim(self.holding.estimated_tax_percent)
                if self.holding.estimated_tax_percent is not None
                else None
            ),
            "total_quantity": str(self.result.total_quantity),
            "total_cost_basis": str(self.result.total_cost_basis.quantize(CENTS)),
            "lot_count": len(self.result.lots),
            "distributions": str(self.result.total_distributions.quantize(CENTS)),
            # Flagged, never blocking. Figures still display and entry still works.
            "consistent": self.result.is_consistent,
            "inconsistencies": [
                {
                    "transaction_id": problem.transaction_id,
                    "date": problem.on_date.isoformat(),
                    "requested": str(problem.requested),
                    "available": str(problem.available),
                    "message": problem.message,
                }
                for problem in self.result.inconsistencies
            ],
            # The open FIFO queue, which is what makes cost basis legible.
            "lots": [
                {
                    "transaction_id": lot.transaction_id,
                    "acquired": lot.acquired.isoformat(),
                    "remaining_quantity": str(lot.remaining_quantity),
                    "unit_cost": str(lot.unit_cost.quantize(Decimal("0.00000001"))),
                    "remaining_cost": str(lot.remaining_cost.quantize(CENTS)),
                    "from_reinvestment": lot.from_reinvestment,
                }
                for lot in self.result.lots
            ],
        }


def positions() -> list[HoldingPosition]:
    holdings = Holding.objects.select_related("account").prefetch_related("transactions")
    return [HoldingPosition(holding=holding, result=replay_holding(holding)) for holding in holdings]


def realised_gains_by_currency(year: int | None = None) -> list[dict]:
    """Grouped by currency, and never summed across them (BR-18).

    A total across currencies would require translation, and translating
    performance conflates market movement with currency movement — producing a
    figure that answers neither question. There is deliberately no grand total
    in this payload.
    """
    blocks: dict[str, dict] = {}

    for position in positions():
        holding = position.holding
        block = blocks.setdefault(
            holding.currency,
            {
                "currency": holding.currency,
                "sales": [],
                "gross": Decimal(0),
                "net": Decimal(0),
                "tax_applied": False,
            },
        )

        for disposal in position.result.disposals:
            if year is not None and disposal.on_date.year != year:
                continue

            net, applied = net_of_tax(
                disposal.realised_gain, holding.estimated_tax_percent
            )
            block["gross"] += disposal.realised_gain
            block["net"] += net
            block["tax_applied"] = block["tax_applied"] or applied

            block["sales"].append(
                {
                    "transaction_id": disposal.transaction_id,
                    "date": disposal.on_date.isoformat(),
                    "holding": holding.name,
                    "holding_id": holding.pk,
                    "quantity": str(disposal.quantity),
                    "proceeds": str(disposal.proceeds.quantize(CENTS)),
                    "fees": str(disposal.fees.quantize(CENTS)),
                    "net_proceeds": str(disposal.net_proceeds.quantize(CENTS)),
                    "cost_basis": str(disposal.cost_basis.quantize(CENTS)),
                    "realised_gain": str(disposal.realised_gain.quantize(CENTS)),
                    "estimated_tax_percent": (
                        trim(holding.estimated_tax_percent)
                        if holding.estimated_tax_percent is not None
                        else None
                    ),
                    "net_realised_gain": str(net.quantize(CENTS)),
                    # Losses are shown gross; no percentage is applied to them.
                    "tax_applied": applied,
                    "is_loss": disposal.is_loss,
                }
            )

    return [
        {
            **block,
            "gross": str(block["gross"].quantize(CENTS)),
            "net": str(block["net"].quantize(CENTS)),
            "sales": sorted(block["sales"], key=lambda row: row["date"], reverse=True),
        }
        for block in sorted(blocks.values(), key=lambda row: row["currency"])
        if block["sales"]
    ]


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def units_available(holding: Holding, on_date, exclude_id: int | None = None) -> Decimal:
    rows = holding.transactions.filter(date__lte=on_date)
    if exclude_id is not None:
        rows = rows.exclude(pk=exclude_id)
    return replay(to_replay(rows)).total_quantity


def record(
    holding: Holding,
    *,
    action: str,
    on_date,
    quantity: Decimal = Decimal(0),
    unit_price: Decimal = Decimal(0),
    fees: Decimal = Decimal(0),
    split_ratio: Decimal = Decimal(0),
    cash_amount: Decimal = Decimal(0),
    note: str = "",
) -> InvestmentTransaction:
    parsed = Action(action)

    if parsed is Action.SELL:
        # FR-33 — an over-sale is rejected AT THE POINT OF ENTRY. This is the
        # one refusal in this module. A sale invalidated later by a historic
        # edit is flagged instead, never blocked (ADR-07).
        available = units_available(holding, on_date)
        if quantity > available:
            raise BusinessRuleError(
                f"{holding.name} held {trim(available)} units on "
                f"{on_date:%d %b %Y}; this sale disposes of {trim(quantity)}.",
                code="oversale",
                field="quantity",
            )

    if parsed is Action.SPLIT and split_ratio <= 0:
        raise BusinessRuleError(
            "A split needs a ratio — 2 for a 2:1 split, 0.1 for a 1:10 consolidation.",
            code="split_ratio_required",
            field="split_ratio",
        )

    if parsed in (Action.BUY, Action.SELL, Action.REINVESTMENT) and quantity <= 0:
        raise BusinessRuleError(
            "Enter a quantity greater than zero.",
            code="quantity_required",
            field="quantity",
        )

    # Same-day ordering: new transactions land after existing ones on that date.
    sequence = (
        holding.transactions.filter(date=on_date)
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )

    return InvestmentTransaction.objects.create(
        holding=holding,
        action=parsed.value,
        date=on_date,
        sequence=(sequence + 1) if sequence is not None else 0,
        quantity=quantity,
        unit_price=unit_price,
        fees=fees,
        split_ratio=split_ratio,
        cash_amount=cash_amount,
        note=note,
    )
