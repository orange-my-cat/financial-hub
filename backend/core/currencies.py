"""The currencies in use, and how each one's USD rate is quoted.

This module is small and load-bearing. It encodes ADR-08's most easily
misunderstood decision: **rates are entered in market convention per pair**, and
the two pairs in use are quoted in opposite directions.

    AUD    0.6600    USD per 1 AUD     — what any rate site shows for AUD/USD
    MYR    4.2000    MYR per 1 USD     — what any rate site shows for USD/MYR

Forcing one internal direction was rejected as making the user invert in their
head before typing. Letting each *entry* declare its own direction was rejected
as inviting a silent inversion that misvalues an entire month. So direction is a
property of the **currency**, fixed here once, and never a property of a row a
person types.

A misplaced decimal or a wrong-way rate misstates every foreign balance for that
month, and nothing else in the system would catch it — which is why the
rate-variance advisory exists, and why this file is the one place the convention
is stated.

Adding a fourth currency (AS-05) is one entry here plus one stored pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

# The base currency and the stored currency of record. Fixed, not switchable: a
# switchable base makes "what did net worth do in the month I changed base
# currency" unanswerable (BR-10).
BASE_CURRENCY = "USD"

ONE = Decimal(1)


class QuoteConvention(StrEnum):
    """Which way round this currency's USD rate is quoted."""

    #: The rate is how many USD one unit of this currency buys — AUD at 0.66.
    USD_PER_UNIT = "usd_per_unit"
    #: The rate is how many units of this currency one USD buys — MYR at 4.20.
    UNITS_PER_USD = "units_per_usd"


@dataclass(frozen=True)
class CurrencyDefinition:
    code: str
    name: str
    convention: QuoteConvention
    #: Shown beside the entry field, so the direction is never in doubt.
    quote_label: str
    #: A plausible value, shown as placeholder text.
    example: str
    #: Whether net worth may be *stated* in this unit.
    #:
    #: The one distinction this module did not need until gold. A currency and a
    #: unit of account are not the same thing: XAU can denominate a balance —
    #: eight troy ounces in a safe is a balance like any other — but "net worth,
    #: in ounces" is a different claim, one whose denominator moves for reasons
    #: that have nothing to do with the finances being measured. It is excluded
    #: because it would be offered otherwise, not because it is unthinkable.
    can_report: bool = True

    @property
    def is_base(self) -> bool:
        return self.code == BASE_CURRENCY


CURRENCIES: dict[str, CurrencyDefinition] = {
    "USD": CurrencyDefinition(
        code="USD",
        name="United States Dollar",
        # Never used: the base against itself is always 1 and is never entered
        # (BR-09). The definition exists so USD is a currency like any other
        # everywhere else.
        convention=QuoteConvention.USD_PER_UNIT,
        quote_label="base currency",
        example="1.0000000000",
    ),
    "AUD": CurrencyDefinition(
        code="AUD",
        name="Australian Dollar",
        convention=QuoteConvention.USD_PER_UNIT,
        quote_label="USD per 1 AUD",
        example="0.6600",
    ),
    "MYR": CurrencyDefinition(
        code="MYR",
        name="Malaysian Ringgit",
        convention=QuoteConvention.UNITS_PER_USD,
        quote_label="MYR per 1 USD",
        example="4.2000",
    ),
    # Gold, by its ISO 4217 code, quoted the only way the market quotes it and
    # the only way the rate provider serves it: USD per troy ounce. `C:USDXAU`
    # does not exist, which is a useful check on the direction below.
    #
    # It is here as a currency rather than as a price because that is what makes
    # it obey every rule already written. A Physical Asset account denominated
    # in XAU holds a balance of ounces, entered and never derived (BR-01); it
    # translates through the one translation service like any foreign balance;
    # a month with no gold rate excludes that account and says so rather than
    # zeroing it (FR-46). None of that is a market-price feature, which the
    # design handoff excludes — it is the existing foreign-currency machinery,
    # pointed at a unit that happens to be metal.
    "XAU": CurrencyDefinition(
        code="XAU",
        name="Gold (Troy Ounce)",
        convention=QuoteConvention.USD_PER_UNIT,
        quote_label="USD per 1 XAU",
        example="4400.0000",
        # See CurrencyDefinition.can_report.
        can_report=False,
    ),
}

#: Every currency the system knows, base first.
CURRENCY_CODES: tuple[str, ...] = tuple(CURRENCIES)

#: The currencies a rate must be entered for. USD is excluded by BR-09.
QUOTED_CURRENCY_CODES: tuple[str, ...] = tuple(
    code for code in CURRENCIES if code != BASE_CURRENCY
)

#: The currencies net worth may be stated in. A strict subset, since gold.
REPORTING_CURRENCY_CODES: tuple[str, ...] = tuple(
    code for code, currency in CURRENCIES.items() if currency.can_report
)

#: Django model choices.
CURRENCY_CHOICES = [(code, CURRENCIES[code].name) for code in CURRENCIES]
QUOTED_CURRENCY_CHOICES = [
    (code, CURRENCIES[code].name) for code in QUOTED_CURRENCY_CODES
]
REPORTING_CURRENCY_CHOICES = [
    (code, CURRENCIES[code].name) for code in REPORTING_CURRENCY_CODES
]


def format_rate(value: Decimal) -> str:
    """A rate as a person would write it — `0.66`, not `0.6600000000`.

    Delegates to :func:`core.money.trim`, which is where this lives now: the
    same defect turned up in a rate advisory, a settings response and a tax
    percentage, and three copies of a fix is two too many.
    """
    from core.money import trim

    return trim(value)


def is_known(code: str) -> bool:
    return code in CURRENCIES


def definition(code: str) -> CurrencyDefinition:
    try:
        return CURRENCIES[code]
    except KeyError:
        raise ValueError(
            f"{code!r} is not a currency this system knows. "
            f"Known: {', '.join(CURRENCY_CODES)}."
        ) from None


def pair_label(code: str) -> str:
    """How the stored pair reads, in its own direction — `AUD/USD`, `USD/MYR`."""
    if code == BASE_CURRENCY:
        return f"{BASE_CURRENCY}/{BASE_CURRENCY}"
    if definition(code).convention is QuoteConvention.USD_PER_UNIT:
        return f"{code}/{BASE_CURRENCY}"
    return f"{BASE_CURRENCY}/{code}"


def usd_ratio(code: str, quoted_rate: Decimal) -> tuple[Decimal, Decimal]:
    """USD per one unit of `code`, as an unevaluated (numerator, denominator).

    The ratio is left undivided on purpose. Translating A to B is
    ``usd(A) / usd(B)``, and evaluating each side first performs two divisions
    where one will do — which matters because an inverse quote is
    non-terminating. `AUD → MYR` via two divisions gives 2.7719999…, and via one
    gives exactly 2.772, because the reciprocals cancel before any rounding
    happens.

    ADR-02 says full precision throughout, rounded once. This is what that costs
    in practice: carrying a fraction a few lines further than feels natural.
    """
    if code == BASE_CURRENCY:
        return ONE, ONE

    if quoted_rate <= 0:
        raise ValueError(
            f"A rate must be greater than zero; got {quoted_rate} for {code}."
        )

    if definition(code).convention is QuoteConvention.USD_PER_UNIT:
        return quoted_rate, ONE
    return ONE, quoted_rate


def usd_per_unit(code: str, quoted_rate: Decimal) -> Decimal:
    """Normalise a stored, market-convention rate to USD per one unit.

    This is the only place the two conventions are reconciled. Everything
    downstream — translation, triangulation, the trend chart — works in USD per
    unit and never has to ask which way a pair was quoted.

    No rounding happens here. The quotient of an inverse quote is very often
    non-terminating, and ADR-02 rounds once, at display.
    """
    if code == BASE_CURRENCY:
        return ONE

    if quoted_rate <= 0:
        raise ValueError(
            f"A rate must be greater than zero; got {quoted_rate} for {code}."
        )

    if definition(code).convention is QuoteConvention.USD_PER_UNIT:
        return quoted_rate
    return ONE / quoted_rate


# ---------------------------------------------------------------------------
# Storing a rate at the column's scale
# ---------------------------------------------------------------------------

#: The scale a stored rate is held at — NUMERIC(19,10), the rate column.
#:
#: ADR-02 rounds once, at display, and carries full precision until then. This
#: is the exception the rule allows for: a figure being *written* has no further
#: precision to carry, and something has to reconcile it with the column's ten
#: places. Rounding here rather than letting Postgres truncate on the way in is
#: what makes "once, half-up" a decision rather than an accident — see the rate
#: provider, where the wire genuinely delivers thirteen decimal places.
RATE_PLACES = Decimal("0.0000000001")


def quantize_rate(value: Decimal) -> Decimal:
    """To the stored rate scale, half-up — the rounding ADR-02 asks for."""
    return value.quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


