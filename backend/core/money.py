"""Money — an amount inseparable from its currency, with no cross-currency arithmetic.

The back-end half of ADR-02. Money is exact decimal and never a float, carried at
full precision throughout and rounded once, at display, half-up.

Two rules are enforced here rather than trusted:

**Adding two currencies is refused**, not coerced. ``AUD 100 + USD 100`` has no
meaning, and a system that quietly picks one is a system that produces a wrong
net worth silently. Crossing currencies goes through the translation service and
nowhere else.

**Rounding happens once.** Every intermediate stays at full precision. Rounding
each addend and then summing produces a total that disagrees with the same
figures added by hand, which is the class of defect quality attribute 2 exists
to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from core.currencies import BASE_CURRENCY, is_known

#: Display scale. Storage keeps NUMERIC(19,4); this is the rounding applied once
#: at the boundary, not to anything held in between.
DISPLAY_PLACES = 2

_DISPLAY_EXPONENT = Decimal(1).scaleb(-DISPLAY_PLACES)


class CurrencyMismatch(TypeError):
    """Two different currencies were combined without translating first."""

    def __init__(self, left: str, right: str) -> None:
        super().__init__(
            f"Refusing to combine {left} and {right}. Crossing currencies goes "
            f"through the translation service, which records the rate it used, "
            f"its as-at date and its provenance — none of which survives a bare "
            f"addition."
        )


@dataclass(frozen=True, order=False)
class Money:
    """An exact amount in one currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(
                f"Money takes a Decimal, not {type(self.amount).__name__}. A float "
                f"cannot represent 0.10 exactly and has no place in this system."
            )
        if not is_known(self.currency):
            raise ValueError(f"{self.currency!r} is not a currency this system knows.")

    # -- construction ------------------------------------------------------

    @classmethod
    def zero(cls, currency: str = BASE_CURRENCY) -> Money:
        return cls(Decimal(0), currency)

    @classmethod
    def parse(cls, amount: str, currency: str) -> Money:
        """From the string form money travels in over the API (ADR-12)."""
        return cls(Decimal(amount), currency)

    # -- arithmetic, within one currency only ------------------------------

    def _guard(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"Expected Money, got {type(other).__name__}.")
        if self.currency != other.currency:
            raise CurrencyMismatch(self.currency, other.currency)

    def __add__(self, other: Money) -> Money:
        self._guard(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._guard(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        """Scale by a dimensionless factor — a quantity, a percentage, a sign.

        Deliberately not defined for ``Money * Money``: multiplying two amounts
        produces squared currency, which is not a thing.
        """
        if isinstance(factor, Money):
            raise TypeError(
                "Multiplying two Money values is not meaningful. Scale by a "
                "Decimal quantity instead."
            )
        if not isinstance(factor, (Decimal, int)):
            raise TypeError(
                f"Scale Money by a Decimal or int, not {type(factor).__name__}."
            )
        return Money(self.amount * Decimal(factor), self.currency)

    __rmul__ = __mul__

    # -- comparison, within one currency only ------------------------------

    def __lt__(self, other: Money) -> bool:
        self._guard(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._guard(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._guard(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._guard(other)
        return self.amount >= other.amount

    # -- inspection --------------------------------------------------------

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def rounded(self, places: int = DISPLAY_PLACES) -> Decimal:
        """Half-up to `places`. Call this once, at the display boundary.

        Half-up rather than Python's default banker's rounding: the user checks
        these figures against a spreadsheet and a bank statement, both of which
        round half away from zero.
        """
        exponent = Decimal(1).scaleb(-places) if places != DISPLAY_PLACES else _DISPLAY_EXPONENT
        return self.amount.quantize(exponent, rounding=ROUND_HALF_UP)

    def api(self, places: int = DISPLAY_PLACES) -> dict[str, str]:
        """The shape money crosses the API in: a string and a code (ADR-12)."""
        return {"amount": str(self.rounded(places)), "currency": self.currency}

    def __str__(self) -> str:
        return f"{self.rounded()} {self.currency}"

    def __repr__(self) -> str:
        return f"Money({self.amount!r}, {self.currency!r})"


def total(amounts: list[Money], currency: str | None = None) -> Money:
    """Sum at full precision, refusing to cross currencies.

    `currency` gives an empty list an answer: a total of nothing is zero in the
    currency that was asked for, not an error and not an assumption.
    """
    if not amounts:
        if currency is None:
            raise ValueError(
                "Summing an empty list needs a currency — a total of nothing is "
                "zero in some currency, and guessing which is how a report ends "
                "up denominated in the wrong one."
            )
        return Money.zero(currency)

    running = amounts[0]
    if currency is not None and running.currency != currency:
        raise CurrencyMismatch(currency, running.currency)
    for item in amounts[1:]:
        running = running + item
    return running
