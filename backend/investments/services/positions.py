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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.money import Money, trim
from core.months import as_at_of
from core.services.exceptions import BusinessRuleError, NotFoundError
from core.services.translation import TranslationService
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


# ---------------------------------------------------------------------------
# Currently held, estimated — a departure, and a knowing one
# ---------------------------------------------------------------------------
# The BRD and HLD exclude market prices and therefore unrealised gain: a figure
# the system cannot source is a figure it should not state. This summary
# estimates a value anyway, at the Product Owner's explicit instruction, from the
# last price each holding was transacted at (see replay.PriceObservation).
#
# Three things keep it honest, and none of them is decoration:
#
#   * Every figure derived from it carries the word **estimated**, and the date
#     of the oldest price it rests on travels with it. A holding bought in 2019
#     and untouched since is "valued" at its 2019 price, and the panel says so.
#   * **Absent is never zero.** A held holding with no price on record is named
#     and left out of the estimate rather than valued at nothing, and the value
#     and the gain are computed over the same set of holdings so the two figures
#     always reconcile with each other (FR-46, applied to a price).
#   * It combines across currencies through the one translation service, which
#     is a departure from BR-18 the Product Owner chose explicitly. A currency
#     with no rate is excluded and named, exactly as on net worth.


@dataclass(frozen=True)
class HeldSummary:
    """Everything currently held, as three figures and their qualifications."""

    currency: str
    #: Holdings with units still open, contributing to the figures below.
    holdings: int
    #: Every held, translatable holding. A fact, not an estimate.
    cost_basis: Money
    #: The priced subset only. None where nothing could be estimated at all.
    estimated_value: Money | None
    estimated_gain: Money | None
    #: The cost basis of that same priced subset, so a reader can see what the
    #: gain was measured against when the two sets differ.
    priced_cost_basis: Money | None
    #: The oldest price the estimate rests on — how out of date it might be.
    priced_from: date | None
    #: Held holdings with no price on record, named rather than valued at zero.
    unpriced: tuple[str, ...]
    exclusions: tuple[dict, ...]
    rate_provenance: tuple[dict, ...]
    as_at: date | None
    any_stale: bool

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "holdings": self.holdings,
            "cost_basis": self.cost_basis.api(),
            "estimated_value": self.estimated_value.api() if self.estimated_value else None,
            "estimated_gain": self.estimated_gain.api() if self.estimated_gain else None,
            "priced_cost_basis": (
                self.priced_cost_basis.api() if self.priced_cost_basis else None
            ),
            "priced_from": self.priced_from.isoformat() if self.priced_from else None,
            "unpriced": list(self.unpriced),
            "exclusions": list(self.exclusions),
            "rate_provenance": list(self.rate_provenance),
            "as_at": self.as_at.isoformat() if self.as_at else None,
            "any_stale": self.any_stale,
        }


def held_summary(
    reporting_currency: str,
    translation: TranslationService | None = None,
    *,
    on_date: date | None = None,
) -> HeldSummary:
    """Cost basis, estimated value and estimated gain for everything still held.

    `on_date` is the date the exchange rates are read at — today by default,
    because this is a statement about what is held now rather than about a
    reporting month. The caller supplies it; the arithmetic does not choose
    (§5.2.1).
    """
    if translation is None:
        translation = TranslationService.from_settings()
    as_at = on_date or date.today()

    cost = Decimal(0)
    priced_cost = Decimal(0)
    value = Decimal(0)
    anything_priced = False

    holdings = 0
    unpriced: list[str] = []
    exclusions: list[dict] = []
    provenance: dict[str, dict] = {}
    price_dates: list[date] = []
    oldest_rate: date | None = None
    any_stale = False

    for position in positions():
        holding, result = position.holding, position.result

        # Currently held only. A holding sold down to nothing has a realised gain
        # and a place on the Investments screen, but nothing left to value.
        if result.total_quantity == 0:
            continue

        basis = translation.translate(
            Money(result.total_cost_basis, holding.currency), reporting_currency, as_at
        )
        if not basis.is_translatable:
            # No rate, so nothing about this holding can join a combined figure.
            exclusions.append(
                {
                    "holding": holding.name,
                    "currency": holding.currency,
                    "reason": basis.exclusion_reason or "",
                }
            )
            continue

        holdings += 1
        cost += basis.amount

        quote = basis.quote
        if quote is not None and quote.legs:
            provenance.setdefault(
                holding.currency,
                {
                    "currency": holding.currency,
                    "pair": quote.pair,
                    "as_at": quote.as_at.isoformat(),
                    "provenance": str(quote.provenance),
                    "stale": quote.is_stale,
                },
            )
            oldest_rate = quote.as_at if oldest_rate is None else min(oldest_rate, quote.as_at)
            any_stale = any_stale or quote.is_stale

        estimate = result.estimated_value
        if estimate is None:
            unpriced.append(holding.name)
            continue

        # Value and gain are measured over the same holdings, so the gain is
        # always the difference between the two figures shown beside it.
        translated = translation.translate(
            Money(estimate, holding.currency), reporting_currency, as_at
        )
        if not translated.is_translatable:  # pragma: no cover - basis would have failed first
            unpriced.append(holding.name)
            continue

        anything_priced = True
        value += translated.amount
        priced_cost += basis.amount
        if result.last_price is not None:
            price_dates.append(result.last_price.on_date)

    return HeldSummary(
        currency=reporting_currency,
        holdings=holdings,
        cost_basis=Money(cost, reporting_currency),
        estimated_value=Money(value, reporting_currency) if anything_priced else None,
        estimated_gain=Money(value - priced_cost, reporting_currency) if anything_priced else None,
        priced_cost_basis=Money(priced_cost, reporting_currency) if anything_priced else None,
        priced_from=min(price_dates) if price_dates else None,
        unpriced=tuple(sorted(unpriced)),
        exclusions=tuple(exclusions),
        rate_provenance=tuple(sorted(provenance.values(), key=lambda row: row["currency"])),
        as_at=oldest_rate,
        any_stale=any_stale,
    )


def held_trend(
    months: Sequence[str],
    reporting_currency: str,
    translation: TranslationService | None = None,
) -> list[dict]:
    """Cost basis and estimated value at each month's end, oldest first.

    **Each point is the position as at that month**, not today's position plotted
    backwards: the transactions are filtered to the month's as-at date and
    replayed, so a holding sold in June contributes to May and to nothing after
    it, and a holding bought in July appears in July. The last price is whatever
    had been recorded by that date for the same reason — a price typed in August
    is not what the holding was worth in March.

    Zero rather than absent for a month with no position: unlike a net worth month
    with no balances, this is derived from transactions rather than entered, so
    "no transactions yet" genuinely means nothing was held (the same coincidence
    of absence and zero as a quiet cash flow month).

    `estimated_value` is null only where something *was* held and none of it could
    be estimated — no price recorded by that date, or no rate. The line breaks
    there rather than dropping to zero, because an estimate that does not exist is
    not a value of nothing.
    """
    if translation is None:
        translation = TranslationService.from_settings()

    # Fetched once and replayed per month in memory. The alternative — a query per
    # holding per month — is 24 times the database work for the same answer.
    holdings = list(Holding.objects.select_related("account").prefetch_related("transactions"))

    rows: list[dict] = []

    for month in months:
        as_at = as_at_of(month)
        cost = Decimal(0)
        value = Decimal(0)
        held = 0
        priced = 0

        for holding in holdings:
            rows_to = [t for t in holding.transactions.all() if t.date <= as_at]
            if not rows_to:
                continue

            result = replay(to_replay(rows_to))
            if result.total_quantity == 0:
                continue

            basis = translation.translate(
                Money(result.total_cost_basis, holding.currency), reporting_currency, as_at
            )
            if not basis.is_translatable:
                continue

            held += 1
            cost += basis.amount

            estimate = result.estimated_value
            if estimate is None:
                continue
            translated = translation.translate(
                Money(estimate, holding.currency), reporting_currency, as_at
            )
            if translated.is_translatable:
                priced += 1
                value += translated.amount

        rows.append(
            {
                "month": month,
                "cost_basis": str(cost.quantize(CENTS)),
                "estimated_value": str(value.quantize(CENTS)) if (priced or not held) else None,
            }
        )

    return rows


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
