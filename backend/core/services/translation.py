"""Translation — the single path by which any amount changes currency.

One place, reached by net worth, every slice, every report and every export. A
screen that translated for itself would let the screen and the report disagree,
with no way to tell which was right (§5.2.2).

The service does not decide *which* date is appropriate — the caller supplies it,
because "the rate in effect at this month-end" is a decision belonging to the
report, not to the arithmetic (§5.2.1).

**A missing rate excludes; it never zeroes.** The result type has no amount at
all when the rate is unavailable, so a caller cannot accidentally add it to a
total. That is FR-46 made structural rather than remembered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.currencies import pair_label
from core.money import Money
from core.services.rate_lookup import DEFAULT_STALENESS_DAYS, RateQuote, RateResolver


@dataclass(frozen=True)
class Translation:
    """The outcome of translating one amount, with everything that qualifies it."""

    source: Money
    target_currency: str
    #: Full precision, or **None** where no rate exists on or before the date.
    #: None is not zero, and the type will not let it be mistaken for zero.
    amount: Decimal | None
    quote: RateQuote | None
    exclusion_reason: str | None = None

    @property
    def is_translatable(self) -> bool:
        return self.amount is not None

    @property
    def money(self) -> Money:
        """The translated amount.

        Raises where untranslatable, deliberately. A caller that has not checked
        :attr:`is_translatable` is a caller about to put an unknown into a total.
        """
        if self.amount is None:
            raise ValueError(
                f"{self.source.currency} could not be translated to "
                f"{self.target_currency}: {self.exclusion_reason}. This account is "
                f"excluded from the total and its balance is never treated as zero "
                f"(FR-46)."
            )
        return Money(self.amount, self.target_currency)

    @property
    def is_stale(self) -> bool:
        return self.quote.is_stale if self.quote else False

    @property
    def as_at(self) -> date | None:
        return self.quote.as_at if self.quote else None


class TranslationService:
    """The only cross-currency path in the system."""

    def __init__(self, resolver: RateResolver | None = None, *, staleness_days: int | None = None):
        if resolver is None:
            resolver = RateResolver(
                staleness_days=staleness_days
                if staleness_days is not None
                else DEFAULT_STALENESS_DAYS
            )
        self.resolver = resolver

    @classmethod
    def from_settings(cls) -> "TranslationService":
        """Configured from the user's thresholds, changeable without a deploy."""
        from core.models import Settings

        return cls(staleness_days=Settings.load().rate_staleness_days)

    def translate(self, amount: Money, to_currency: str, on_date: date) -> Translation:
        quote = self.resolver.quote(amount.currency, to_currency, on_date)

        if quote is None:
            return Translation(
                source=amount,
                target_currency=to_currency,
                amount=None,
                quote=None,
                exclusion_reason=(
                    f"no {pair_label(amount.currency)} rate exists on or before "
                    f"{on_date:%d %b %Y}"
                ),
            )

        return Translation(
            source=amount,
            target_currency=to_currency,
            # Full precision. Rounded once, at display.
            amount=amount.amount * quote.factor,
            quote=quote,
        )
