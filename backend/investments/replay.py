"""The FIFO replay engine.

A pure function. Transactions in date order in; lot states, consumption, cost
basis, realised gains, the last price transacted at and any inconsistency out.
**No database writes, no stored lot state, no stored cost basis, no stored
realised gain** (ADR-06). This module
imports nothing from Django, and that is deliberate — the arithmetic that
matters most in this system should be testable without a database, in
milliseconds, against figures worked by hand.

Three consequences of replay-over-storage are worth stating, because each is a
class of bug that simply cannot occur here:

**A buy *is* a lot.** Its remaining quantity is output, not a column. Nothing can
drift between a lot table and the transactions that produced it, because there
is no lot table.

**A split is a transaction in the sequence, not an edit to lots.** A 2:1 split
dated March doubles a February lot and leaves an April lot alone — and that
falls out of replaying in order rather than being special-cased. Backdating a
split later needs no migration and corrects nothing, because nothing was ever
written down.

**An edit anywhere restates everything after it, for free.** Which is what makes
BR-23's unrestricted historic editing safe.

Precision: quantities and ratios carry ten places, unit prices eight, money
four. Nothing is rounded here at all — rounding happens once, at display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

ZERO = Decimal(0)


class Action(StrEnum):
    """Corporate actions are limited to fees, splits and reinvestment (BR-20).

    Mergers, spin-offs, rights issues and returns of capital are out of scope.
    They are rare, individually complex, and each behaves differently; a user
    representing one manually as a sale and a purchase gets figures that do not
    reflect the true event, and the system says so rather than pretending.
    """

    BUY = "Buy"
    SELL = "Sell"
    SPLIT = "Split"
    DISTRIBUTION = "Distribution"
    REINVESTMENT = "Reinvestment"


@dataclass(frozen=True)
class ReplayTransaction:
    """One transaction, as plain values.

    `sequence` breaks ties within a date. Two transactions on one day must
    replay in a defined order or the FIFO queue is non-deterministic — and a
    non-deterministic cost basis is worse than a wrong one, because it cannot be
    reproduced to be argued with.
    """

    id: int
    action: Action
    on_date: date
    sequence: int = 0

    #: Units bought, sold or reinvested.
    quantity: Decimal = ZERO
    #: Price per unit.
    unit_price: Decimal = ZERO
    #: Purchase fees join cost basis; sale fees come off proceeds (BR-16).
    fees: Decimal = ZERO
    #: For a split: new units per old unit. 2 for a 2:1 split, 0.1 for a 1:10
    #: consolidation.
    split_ratio: Decimal = ZERO
    #: For a distribution: the cash received.
    cash_amount: Decimal = ZERO


@dataclass
class _OpenLot:
    """Mutable during replay only. Never returned, never stored."""

    transaction_id: int
    acquired: date
    original_quantity: Decimal
    remaining_quantity: Decimal
    remaining_cost: Decimal
    from_reinvestment: bool


@dataclass(frozen=True)
class Lot:
    """An open lot, as replay found it."""

    transaction_id: int
    acquired: date
    remaining_quantity: Decimal
    remaining_cost: Decimal
    from_reinvestment: bool

    @property
    def unit_cost(self) -> Decimal:
        if self.remaining_quantity == 0:
            return ZERO
        return self.remaining_cost / self.remaining_quantity


@dataclass(frozen=True)
class Consumption:
    """One lot's contribution to one sale."""

    lot_transaction_id: int
    acquired: date
    quantity: Decimal
    cost_basis: Decimal


@dataclass(frozen=True)
class Disposal:
    """A sale, and what it cost.

    Realised gain is net proceeds minus the FIFO cost basis of the units sold,
    computed only at the moment of sale (BR-17). It may be negative, and is
    shown as such.
    """

    transaction_id: int
    on_date: date
    quantity: Decimal
    proceeds: Decimal
    fees: Decimal
    cost_basis: Decimal
    consumed: tuple[Consumption, ...]

    @property
    def net_proceeds(self) -> Decimal:
        """Sale fees are deducted from proceeds, never added to cost basis."""
        return self.proceeds - self.fees

    @property
    def realised_gain(self) -> Decimal:
        return self.net_proceeds - self.cost_basis

    @property
    def is_loss(self) -> bool:
        return self.realised_gain < 0


@dataclass(frozen=True)
class Distribution:
    transaction_id: int
    on_date: date
    cash_amount: Decimal


@dataclass(frozen=True)
class PriceObservation:
    """The most recent price this holding was actually transacted at.

    **A departure, and a knowing one.** The BRD and HLD exclude market prices and
    therefore unrealised gain, on the grounds that a figure the system cannot
    source is a figure it should not state. The dashboard's holdings panel now
    estimates a value from this observation at the Product Owner's explicit
    instruction. It is not a market price: it is the last price *the user typed*,
    on the date they typed it, which is why both travel together and why every
    figure derived from it is labelled an estimate and dated.

    `split_adjusted` records that a split fell after the observation, so the price
    has been divided by the ratio to be expressed per post-split unit. Without
    that, a 2:1 split would double an estimated value on the strength of an
    arithmetic error: twice the units at the pre-split price.
    """

    transaction_id: int
    on_date: date
    action: Action
    #: Per unit, expressed in today's unit terms — see `split_adjusted`.
    unit_price: Decimal
    split_adjusted: bool = False


@dataclass(frozen=True)
class Inconsistency:
    """A sale that cannot be satisfied by the lots preceding it.

    FR-33 rejects an over-sale *at the point of entry*. This is the other case:
    a sale that was valid when entered and was later invalidated by a historic
    edit — a backdated buy removed, a quantity corrected downward. ADR-07 says
    flag, never block. The figures still display and entry still works; the
    holding simply says what is wrong, specifically, and the flag clears itself
    when the underlying data is corrected.
    """

    transaction_id: int
    on_date: date
    requested: Decimal
    available: Decimal

    @property
    def shortfall(self) -> Decimal:
        return self.requested - self.available

    @property
    def message(self) -> str:
        return (
            f"The sale on {self.on_date:%d %b %Y} disposes of {self.requested} units "
            f"but only {self.available} were held at that date — a shortfall of "
            f"{self.shortfall}. A later edit has invalidated it. The figures below "
            f"still compute from what is recorded; correcting the earlier entry "
            f"clears this."
        )


@dataclass(frozen=True)
class ReplayResult:
    lots: tuple[Lot, ...]
    disposals: tuple[Disposal, ...]
    distributions: tuple[Distribution, ...]
    inconsistencies: tuple[Inconsistency, ...] = field(default_factory=tuple)
    #: The last transacted price, or None where nothing priced has been recorded.
    last_price: PriceObservation | None = None

    @property
    def is_consistent(self) -> bool:
        return not self.inconsistencies

    @property
    def total_quantity(self) -> Decimal:
        return sum((lot.remaining_quantity for lot in self.lots), ZERO)

    @property
    def total_cost_basis(self) -> Decimal:
        return sum((lot.remaining_cost for lot in self.lots), ZERO)

    @property
    def realised_gain(self) -> Decimal:
        """Across this holding only. Never summed across currencies (BR-18)."""
        return sum((disposal.realised_gain for disposal in self.disposals), ZERO)

    @property
    def total_distributions(self) -> Decimal:
        return sum((row.cash_amount for row in self.distributions), ZERO)

    def disposals_in_year(self, year: int) -> tuple[Disposal, ...]:
        return tuple(d for d in self.disposals if d.on_date.year == year)

    # -- estimation, on the last price typed rather than a market price -------
    #
    # See PriceObservation: these are a deliberate departure, they are estimates,
    # and they are None rather than zero wherever the estimate has no basis —
    # nothing held, or nothing ever priced. An absent estimate is not a value of
    # nothing, exactly as a missing rate is not a rate of zero (FR-46).

    @property
    def estimated_value(self) -> Decimal | None:
        """Units still held, at the last price they were transacted at."""
        if self.last_price is None or self.total_quantity == 0:
            return None
        return self.total_quantity * self.last_price.unit_price

    @property
    def estimated_gain(self) -> Decimal | None:
        """The estimate above, less what those units cost.

        This is the figure the BRD calls unrealised gain and declines to compute.
        It is here at the Product Owner's instruction, it is an estimate, and the
        word `estimated` travels with it everywhere it is rendered.
        """
        value = self.estimated_value
        if value is None:
            return None
        return value - self.total_cost_basis


def replay(transactions: list[ReplayTransaction]) -> ReplayResult:
    """Replay a holding's transactions and return its computed state.

    Pure: same input, same output, no side effects, no database.
    """
    ordered = sorted(transactions, key=lambda t: (t.on_date, t.sequence, t.id))

    open_lots: list[_OpenLot] = []
    disposals: list[Disposal] = []
    distributions: list[Distribution] = []
    inconsistencies: list[Inconsistency] = []
    last_price: PriceObservation | None = None

    for transaction in ordered:
        # The last price typed, tracked in the same pass and in the same order as
        # everything else here. In the sequence rather than derived afterwards
        # because a split has to be able to rescale it: doing this from outside
        # would mean sorting the transactions a second time and re-deriving the
        # ordering this loop already has.
        if transaction.unit_price > 0 and transaction.action in (
            Action.BUY,
            Action.SELL,
            Action.REINVESTMENT,
        ):
            last_price = PriceObservation(
                transaction_id=transaction.id,
                on_date=transaction.on_date,
                action=transaction.action,
                unit_price=transaction.unit_price,
            )

        if transaction.action in (Action.BUY, Action.REINVESTMENT):
            # Purchase fees form part of cost basis (BR-16). A reinvestment
            # creates a lot at the reinvestment price, dated to the
            # reinvestment — it is a purchase that happens to be funded by a
            # distribution (BR-20).
            cost = transaction.quantity * transaction.unit_price + transaction.fees
            open_lots.append(
                _OpenLot(
                    transaction_id=transaction.id,
                    acquired=transaction.on_date,
                    original_quantity=transaction.quantity,
                    remaining_quantity=transaction.quantity,
                    remaining_cost=cost,
                    from_reinvestment=transaction.action is Action.REINVESTMENT,
                )
            )

        elif transaction.action is Action.SELL:
            disposal, shortfall = _consume(open_lots, transaction)
            disposals.append(disposal)
            if shortfall is not None:
                inconsistencies.append(shortfall)

        elif transaction.action is Action.SPLIT:
            # Adjusts the quantity of every OPEN lot proportionally and leaves
            # each lot's total cost basis unchanged; unit cost changes
            # accordingly (BR-20). Lots acquired after this point are untouched,
            # which needs no special case because they do not exist yet.
            if transaction.split_ratio > 0:
                for lot in open_lots:
                    lot.remaining_quantity *= transaction.split_ratio
                    lot.original_quantity *= transaction.split_ratio

                # The last observed price is per *old* unit and every quantity has
                # just been restated in new ones. Rescaling it here is what keeps
                # an estimated value from doubling on a 2:1 split, which is the
                # same total holding at half the price per unit.
                if last_price is not None:
                    last_price = PriceObservation(
                        transaction_id=last_price.transaction_id,
                        on_date=last_price.on_date,
                        action=last_price.action,
                        unit_price=last_price.unit_price / transaction.split_ratio,
                        split_adjusted=True,
                    )

        elif transaction.action is Action.DISTRIBUTION:
            # Cash against the holding. Changes no lot and no cost basis.
            distributions.append(
                Distribution(
                    transaction_id=transaction.id,
                    on_date=transaction.on_date,
                    cash_amount=transaction.cash_amount,
                )
            )

    lots = tuple(
        Lot(
            transaction_id=lot.transaction_id,
            acquired=lot.acquired,
            remaining_quantity=lot.remaining_quantity,
            remaining_cost=lot.remaining_cost,
            from_reinvestment=lot.from_reinvestment,
        )
        for lot in open_lots
        if lot.remaining_quantity > 0
    )

    return ReplayResult(
        lots=lots,
        disposals=tuple(disposals),
        distributions=tuple(distributions),
        inconsistencies=tuple(inconsistencies),
        last_price=last_price,
    )


def _consume(
    open_lots: list[_OpenLot], sale: ReplayTransaction
) -> tuple[Disposal, Inconsistency | None]:
    """Take units from the oldest lots first.

    Cost is taken from the lot's *remaining* cost proportionally rather than
    from a stored unit cost, so a fully consumed lot contributes exactly what it
    cost — no rounding residue accumulates across a long queue.
    """
    outstanding = sale.quantity
    consumed: list[Consumption] = []
    cost_basis = ZERO
    available = sum((lot.remaining_quantity for lot in open_lots), ZERO)

    for lot in open_lots:
        if outstanding <= 0:
            break
        if lot.remaining_quantity <= 0:
            continue

        take = min(lot.remaining_quantity, outstanding)

        if take == lot.remaining_quantity:
            # The whole lot. Its remaining cost transfers exactly.
            portion = lot.remaining_cost
        else:
            portion = lot.remaining_cost * (take / lot.remaining_quantity)

        lot.remaining_quantity -= take
        lot.remaining_cost -= portion
        outstanding -= take
        cost_basis += portion

        consumed.append(
            Consumption(
                lot_transaction_id=lot.transaction_id,
                acquired=lot.acquired,
                quantity=take,
                cost_basis=portion,
            )
        )

    disposal = Disposal(
        transaction_id=sale.id,
        on_date=sale.on_date,
        quantity=sale.quantity,
        proceeds=sale.quantity * sale.unit_price,
        fees=sale.fees,
        cost_basis=cost_basis,
        consumed=tuple(consumed),
    )

    # Never raises. A sale invalidated by a later edit is flagged, not blocked.
    shortfall = (
        Inconsistency(
            transaction_id=sale.id,
            on_date=sale.on_date,
            requested=sale.quantity,
            available=available,
        )
        if outstanding > 0
        else None
    )
    return disposal, shortfall


def units_held_at(transactions: list[ReplayTransaction], on_date: date) -> Decimal:
    """Units held immediately before a prospective sale on `on_date`.

    Used to reject an over-sale at the point of entry (FR-33), which is the one
    place this system does refuse. Everything discovered later is flagged
    instead.
    """
    preceding = [t for t in transactions if t.on_date <= on_date]
    return replay(preceding).total_quantity
