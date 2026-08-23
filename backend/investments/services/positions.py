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
from decimal import ROUND_HALF_UP, Decimal

from core.money import Money, trim
from core.months import as_at_of, month_end, month_of, previous, sequence
from core.services.exceptions import BusinessRuleError, NotFoundError
from core.services.movement import movement
from core.services.translation import TranslationService
from investments.models import Holding, InvestmentTransaction
from investments.replay import Action, Disposal, ReplayResult, ReplayTransaction, replay

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


#: The quantity field's own scale, NUMERIC(19,10).
UNITS = Decimal("0.0000000001")


def units_bought(spend: Decimal, unit_price: Decimal) -> Decimal:
    """Units, from what was spent and what a unit cost. The only place this
    division happens.

    Purchases and reinvestments are entered by dollar value, at the Product
    Owner's instruction, because that is what the paperwork states: a
    confirmation says what was paid and at what price, and a dividend
    reinvestment statement says what the distribution was worth. A unit count to
    ten decimal places is the *result* of the trade — nobody types
    `0.4588502067`.

    Rounded half-up at the field's own scale, the rule every figure in this
    system rounds by. The error that can leave in cost basis is the unit price
    times 5e-11 — a hundred-millionth of a cent on a $75 unit, against a cost
    basis quantized to cents long before anyone reads it.
    """
    return (spend / unit_price).quantize(UNITS, rounding=ROUND_HALF_UP)


def realised_percent(result: ReplayResult) -> Decimal | None:
    """Realised gain as a percentage of what the units sold had cost.

    Not a portfolio return, and not derivable into one: the denominator is the
    FIFO cost of units that have left (BR-17), so nothing here touches a market
    price or a unit still held. Summing it across holdings would be meaningless
    anyway — each is stated in its own currency (BR-18).

    None where nothing has been sold, or where the sold units cost nothing at
    all. A return on nothing is not a return of zero, exactly as a missing rate
    is not a rate of zero (FR-46).
    """
    cost = result.realised_cost_basis
    if not result.disposals or cost == 0:
        return None
    return (result.realised_gain / cost * 100).quantize(CENTS)


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldingPosition:
    holding: Holding
    result: ReplayResult

    def as_dict(self) -> dict:
        percent = realised_percent(self.result)
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
            # Closed gains only, on this holding, in this holding's currency.
            # Null rather than zero where nothing has been sold: a holding still
            # wholly held has realised nothing, which is not the same fact as
            # having sold at cost.
            "realised_gain": (
                str(self.result.realised_gain.quantize(CENTS))
                if self.result.disposals
                else None
            ),
            "realised_gain_percent": trim(percent) if percent is not None else None,
            "lot_count": len(self.result.lots),
            # What the register groups on, and what decides whether a holding
            # can be deleted rather than only left alone: a holding nothing was
            # ever recorded against has no history to preserve (ADR-14, exactly
            # as for an account). `lot_count` cannot answer this — it is zero for
            # an untraded holding and for a sold-out one, and those are not the
            # same thing.
            #
            # `len` over `count()` deliberately. The list path prefetches the
            # transactions in order to replay them, so on the register — the one
            # place this is read per holding — it costs nothing. `count()` would
            # ignore that cache and issue a query per row.
            #
            # Not prefetched in `get_holding`, and that is not an oversight: a
            # prefetch cache taken before `record()` would still be holding the
            # pre-insert list when the response is built, and the new
            # transaction would be missing from the position it returns.
            "transaction_count": len(self.holding.transactions.all()),
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


def disposal_row(holding: Holding, disposal: Disposal) -> dict:
    """One sale, as the API states it.

    The only definition of a sale's figures. The realised gains report and the
    holding's own transaction register both render from this, so the two cannot
    disagree about what a sale realised — which is the whole point of having one
    place where a calculation lives (§5.2.2).
    """
    net, applied = net_of_tax(disposal.realised_gain, holding.estimated_tax_percent)
    return {
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
        # Which lots the sale took its units from, oldest first. The open queue
        # says what remains; this says where a sale's cost basis came from, and
        # between them the two account for every unit ever bought.
        "consumed": [
            {
                "lot_transaction_id": taken.lot_transaction_id,
                "acquired": taken.acquired.isoformat(),
                "quantity": str(taken.quantity),
                "cost_basis": str(taken.cost_basis.quantize(CENTS)),
            }
            for taken in disposal.consumed
        ],
    }


def holding_history(rows: Sequence[InvestmentTransaction], *, today: date | None = None) -> list[dict]:
    """What was held at each month end, and what those units had cost.

    Newest month first, as the account history reads, and continuous: a holding
    has a cost basis every month from its first transaction to the present,
    including the zero months after it was sold out. Months before the first
    transaction are absent rather than zero — the holding did not exist to hold.

    **Not performance, and not convertible into it.** Both figures are facts
    about transactions: units surviving FIFO, and what those surviving units
    cost. No market price is read, because none is stored, so no month here
    carries a value or a return (BR-17, BR-18).

    Computed by replaying the transactions dated on or before each month end,
    which is the same engine every other figure on the page came through
    (ADR-06). Walking the months once with a running total would be quicker and
    would be a second definition of cost basis, free to drift from the first.
    Nothing is stored either way (ADR-05).
    """
    if not rows:
        return []

    first = month_of(min(row.date for row in rows))
    # To the present, not to the last transaction: units bought and left alone
    # are still held, and a line that stopped at the last trade would read as a
    # holding that ended.
    last = max(first, month_of(today or date.today()))

    history = [
        {
            "month": month,
            **_position_at(rows, month_end(month)),
        }
        for month in sequence(first, last)
    ]
    history.reverse()
    return history


def _position_at(rows: Sequence[InvestmentTransaction], on_date: date) -> dict:
    result = replay(to_replay([row for row in rows if row.date <= on_date]))
    return {
        "quantity": str(result.total_quantity),
        "cost_basis": str(result.total_cost_basis.quantize(CENTS)),
    }


def holding_detail(holding: Holding) -> dict:
    """A holding, its open lots, and every transaction with what replay made of it.

    The register is what this payload exists for. Each transaction carries the
    figure the engine derived from it — the cost a purchase added to basis, the
    proceeds and FIFO cost basis a sale realised, the lots that sale consumed —
    because the browser cannot work any of it out: money has no arithmetic there
    (ADR-12).

    Every key an action does not touch is null, and null means *not applicable*
    rather than zero. The one deliberate exception is a purchase sold down to
    nothing, whose remaining quantity is a genuine zero.

    A reinvestment populates two of them — `acquired` and `distributed` — because
    it is one event with two money effects (see `Action`). Every other action
    populates exactly one, and a split none.
    """
    # Read once and iterated twice — by the engine and by the register below.
    rows = list(holding.transactions.all())
    result = replay(to_replay(rows))

    acquisitions = {row.transaction_id: row for row in result.acquisitions}
    # The running unit total, which every row carries — see `UnitsHeld`. Keyed
    # here rather than zipped, because the register below reads newest first and
    # replay ran oldest first.
    running = {row.transaction_id: row for row in result.units_held}
    disposals = {row.transaction_id: row for row in result.disposals}
    distributions = {row.transaction_id: row for row in result.distributions}
    open_lots = {lot.transaction_id: lot for lot in result.lots}
    flagged = {problem.transaction_id for problem in result.inconsistencies}

    register: list[dict] = []
    for row in rows:
        entry = {
            "id": row.pk,
            "action": row.action,
            "date": row.date.isoformat(),
            "quantity": str(row.quantity),
            "unit_price": str(row.unit_price),
            "fees": str(row.fees),
            "split_ratio": str(row.split_ratio),
            "cash_amount": str(row.cash_amount),
            "note": row.note,
            # What was held once this row had replayed. Present on every action,
            # including a split, which changes it without buying anything.
            #
            # Quantized to the field's own ten places: a split multiplies every
            # open lot, and Decimal multiplication widens the scale as it goes,
            # so a running total past two splits would otherwise arrive with
            # thirty decimal places of nothing.
            "units_held": (
                str(running[row.pk].units_held.quantize(UNITS, rounding=ROUND_HALF_UP))
                if row.pk in running
                else "0"
            ),
            # What the engine made of it. One of these three per action — two for
            # a reinvestment, which received cash and bought units — and none for
            # a split, because a split moves no money.
            "acquired": None,
            "realised": None,
            "distributed": None,
            # Only a sale can be retroactively invalidated, and it is flagged
            # here as well as on the holding so the register names the row.
            "flagged": row.pk in flagged,
        }

        acquisition = acquisitions.get(row.pk)
        if acquisition is not None:
            lot = open_lots.get(row.pk)
            entry["acquired"] = {
                "cost": str(acquisition.cost.quantize(CENTS)),
                "from_reinvestment": acquisition.from_reinvestment,
                # A lot sold down to nothing is not absent, it is empty — and a
                # later split restates what remains, not what was bought.
                "remaining_quantity": str(lot.remaining_quantity) if lot else "0",
                "remaining_cost": str(lot.remaining_cost.quantize(CENTS)) if lot else "0.00",
            }

        disposal = disposals.get(row.pk)
        if disposal is not None:
            entry["realised"] = disposal_row(holding, disposal)

        distribution = distributions.get(row.pk)
        if distribution is not None:
            entry["distributed"] = str(distribution.cash_amount.quantize(CENTS))

        register.append(entry)

    return {
        **HoldingPosition(holding, result).as_dict(),
        # Month ends, for the plot beside the headline figure. Same rows, replayed
        # to each month end rather than to the present.
        "history": holding_history(rows),
        "transactions": register,
        # This holding's sales, newest first — the same rows the realised gains
        # report groups by currency, restricted to one holding and never summed
        # with another currency's (BR-18).
        "realised": {
            "gross": str(result.realised_gain.quantize(CENTS)),
            "sales": sorted(
                (disposal_row(holding, disposal) for disposal in result.disposals),
                key=lambda sale: sale["date"],
                reverse=True,
            ),
        },
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


def held_positions(through: date | None = None):
    """Every holding and its replayed state, optionally as at a past date.

    `through` filters the transactions before they are replayed, exactly as
    `held_trend` does per month: the position as at that date, not today's
    position dated backwards. A holding whose first purchase is later than
    `through` is not yielded at all — it was not held.
    """
    if through is None:
        for position in positions():
            yield position.holding, position.result
        return

    holdings = Holding.objects.select_related("account").prefetch_related("transactions")
    for holding in holdings:
        rows = [t for t in holding.transactions.all() if t.date <= through]
        if not rows:
            continue
        yield holding, replay(to_replay(rows))


def held_summary(
    reporting_currency: str,
    translation: TranslationService | None = None,
    *,
    on_date: date | None = None,
    through: date | None = None,
) -> HeldSummary:
    """Cost basis, estimated value and estimated gain for everything still held.

    `on_date` is the date the exchange rates are read at — today by default,
    because this is a statement about what is held now rather than about a
    reporting month. The caller supplies it; the arithmetic does not choose
    (§5.2.1).

    `through` rolls the whole summary back to a past date: transactions after it
    are not replayed and, unless `on_date` overrides it, the rates are read as at
    that date too. This is what the dashboard's month-on-month change subtracts
    from, and it is the same basis the holdings plot is drawn on, so the change
    stated beside a figure agrees with the line above it.
    """
    if translation is None:
        translation = TranslationService.from_settings()
    as_at = on_date or through or date.today()

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

    for holding, result in held_positions(through):
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


def held_summary_with_change(
    reporting_currency: str,
    translation: TranslationService | None = None,
    *,
    month: str,
    today: date | None = None,
) -> dict:
    """The three held figures **as at a month**, each with its movement on the
    month before it.

    The reported month, not today: on a dashboard reporting July, the position is
    July's and the change is July on June, so the panel covers the same period as
    the two above it and ends where the plot beside it ends. Both figures are
    month-end positions, so the change subtracts from the figure it sits under.

    Nulls carry the meaning `movement` gives them: no change at all where either
    month's figure does not exist, because an estimate nobody could make is not
    an estimate of nothing (FR-46).
    """
    if translation is None:
        translation = TranslationService.from_settings()

    now = today or date.today()
    prior_month = previous(month)
    current = held_summary(reporting_currency, translation, through=as_at_of(month, today=now))
    prior = held_summary(reporting_currency, translation, through=as_at_of(prior_month, today=now))

    def amount(money):
        return money.amount if money is not None else None

    return {
        **current.as_dict(),
        "month": month,
        "previous_month": prior_month,
        "change": {
            "cost_basis": movement(current.cost_basis.amount, prior.cost_basis.amount),
            "estimated_value": movement(
                amount(current.estimated_value), amount(prior.estimated_value)
            ),
            "estimated_gain": movement(
                amount(current.estimated_gain), amount(prior.estimated_gain)
            ),
        },
    }


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

            # The totals accumulate the unrounded figures and round once, so a
            # long block's total is not the sum of its displayed rows.
            net, applied = net_of_tax(
                disposal.realised_gain, holding.estimated_tax_percent
            )
            block["gross"] += disposal.realised_gain
            block["net"] += net
            block["tax_applied"] = block["tax_applied"] or applied

            block["sales"].append(disposal_row(holding, disposal))

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
# Creating and editing a holding
# ---------------------------------------------------------------------------


def assert_name_available(account_id: int, name: str, exclude_pk: int | None = None) -> None:
    """One holding name per account, stated as a refusal.

    The rule itself lives in the database — `investments_one_holding_per_name_per_account`,
    scoped to live rows — which is what makes it true rather than merely intended
    (§9.1). This is where it becomes a *message*: without it the constraint
    surfaces as an IntegrityError and a 500, and a rename that collides is
    ordinary user error, not a server fault.

    Filtered through the default manager, so a soft-deleted holding does not
    hold its name hostage — exactly the rows the constraint's condition covers.
    """
    clash = Holding.objects.filter(account_id=account_id, name=name)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)

    if clash.exists():
        raise BusinessRuleError(
            f"This account already has a holding called {name}. The same "
            "instrument at two brokers is two holdings; the same name twice in "
            "one account is not.",
            code="duplicate_holding_name",
            field="name",
        )


def create_holding(**fields) -> Holding:
    """A new holding. Refuses a name the account already uses."""
    assert_name_available(fields["account_id"], fields["name"])
    return Holding.objects.create(**fields)


def update_holding(holding: Holding, changes: dict) -> Holding:
    """A holding's editable facts: name, symbol, instrument type, tax percentage.

    **Not the account and not the currency**, and their absence is the rule
    rather than an oversight. A holding is scoped to one account as a one-way
    door — merging two brokers' queues later would need a decision about which
    lots came first that the data cannot answer (§13.4) — and the currency is
    the one every figure for this holding is stated in and never translated from
    (BR-18). The update serialiser has no field for either, so neither arrives
    here to be applied.

    Changing the tax percentage restates the net figure on every historic sale,
    including sales already reported. That is free, because nothing was stored
    (BR-21, ADR-05).
    """
    name = changes.get("name")
    if name is not None and name != holding.name:
        assert_name_available(holding.account_id, name, exclude_pk=holding.pk)

    for field, value in changes.items():
        setattr(holding, field, value)
    holding.save()
    return holding


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
    amount: Decimal = Decimal(0),
    note: str = "",
) -> InvestmentTransaction:
    """Write one transaction, or refuse it.

    `amount` is what a purchase paid, and it is not stored: it exists to derive
    the units, which are (see `units_bought`). A reinvestment derives its units
    from `cash_amount` instead, because that figure is a fact in its own right —
    the income the holding paid out — and not merely an input to a division.

    A quantity stated outright still wins, which is what keeps the engine's own
    vocabulary usable from a shell and a test: give it units, or give it the
    money and the price and it will work the units out.
    """
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

    # One action, two effects (see Action): a reinvestment is the distribution and
    # the purchase it funded, so neither half is optional. Without the cash the
    # holding's income is understated; without the units its cost basis is.
    if parsed is Action.REINVESTMENT and cash_amount <= 0:
        raise BusinessRuleError(
            "Enter the cash the distribution paid. A distribution taken as cash "
            "is not recorded against a holding — it reaches an account, and shows "
            "up in that account's balance at the next close.",
            code="cash_amount_required",
            field="cash_amount",
        )

    if parsed is Action.BUY and quantity > 0 and amount > 0:
        raise BusinessRuleError(
            "Enter what the purchase cost or how many units it bought, not both.",
            code="amount_and_quantity",
            field="amount",
        )

    # Entry is by dollar value for both acquiring actions: what was paid, and
    # what a unit cost. The units follow from those two and are stored; nothing
    # else about the row is derived.
    if parsed in (Action.BUY, Action.REINVESTMENT) and quantity <= 0:
        spend = amount if parsed is Action.BUY else cash_amount
        field = "amount" if parsed is Action.BUY else "cash_amount"

        if spend <= 0:
            raise BusinessRuleError(
                "Enter what was paid, greater than zero.",
                code="amount_required",
                field=field,
            )

        # Guarded rather than divided by: a price of zero is either a mistyped
        # row or a gift, and neither is a number of units this can work out.
        if unit_price <= 0:
            raise BusinessRuleError(
                "Enter the price a unit was bought at, greater than zero.",
                code="unit_price_required",
                field="unit_price",
            )

        quantity = units_bought(spend, unit_price)

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
