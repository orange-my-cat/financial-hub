"""The month's cash flow as one figure per line, in the reporting currency.

Distinct from :mod:`cashflow.services.reporting`, and deliberately so. The
category report answers *what was spent on* — a question that is only meaningful
in the currency the money was spent in, which is why nothing there is translated.
This answers *how the month went overall*, and that question has no per-currency
answer at all: three net figures in three currencies do not tell a person whether
they saved anything.

The BRD sanctions the translation — "FX applies to balances and cash flow only"
(A36); only investment performance is barred from it (BR-18). The translation
still goes through the one translation service, like every other crossing in the
system, so the rate, its as-at date and its provenance travel with the total.

**One rate, at month-end.** Every transaction in the month is translated at the
month-end rate rather than at its own date's rate — the same instant net worth
uses, so the two panels on the dashboard are denominated consistently. Choosing
the date is the report's job, not the arithmetic's (§5.2.1).

**A missing rate excludes the whole currency, and never zeroes it** (FR-46). A
month of MYR spending with no USD/MYR rate is withheld from income, expense and
net alike — dropping it from expense while keeping it in income would invent a
savings rate that no arrangement of the facts supports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from core.money import Money
from core.months import as_at_of, month_end, month_start, previous
from core.services.movement import movement
from core.services.rate_lookup import RateQuote
from core.services.translation import TranslationService
from cashflow.models import Direction, Transaction

TENTHS = Decimal("0.1")


@dataclass(frozen=True)
class CurrencyLeg:
    """One entered currency's contribution, before and after translation."""

    currency: str
    income: Decimal
    expense: Decimal

    #: Full precision, or **None** where no rate exists for the month-end.
    income_translated: Decimal | None
    expense_translated: Decimal | None
    quote: RateQuote | None
    exclusion_reason: str | None

    @property
    def is_excluded(self) -> bool:
        """All of the currency, or none of it.

        Both directions share one month-end quote, so in practice they succeed
        or fail together; the check is written over both so that a partial
        translation could never contribute half a currency to a net figure.
        """
        return self.income_translated is None or self.expense_translated is None


@dataclass(frozen=True)
class CashFlowSummary:
    """A month's income, expense, net and savings rate in one currency."""

    month: str
    currency: str
    legs: tuple[CurrencyLeg, ...]

    @property
    def included(self) -> tuple[CurrencyLeg, ...]:
        return tuple(leg for leg in self.legs if not leg.is_excluded)

    @property
    def exclusions(self) -> tuple[CurrencyLeg, ...]:
        return tuple(leg for leg in self.legs if leg.is_excluded)

    @property
    def has_activity(self) -> bool:
        """Whether the month has anything to report.

        A month with no transactions has no cash flow, which is not the same as
        a month that broke even. The distinction is the one FR-46 draws for a
        missing rate and BR-04 draws for a missing balance.
        """
        return bool(self.legs)

    @property
    def income(self) -> Money:
        return Money(sum((leg.income_translated for leg in self.included), Decimal(0)), self.currency)

    @property
    def expense(self) -> Money:
        return Money(
            sum((leg.expense_translated for leg in self.included), Decimal(0)), self.currency
        )

    @property
    def net(self) -> Money:
        return self.income - self.expense

    @property
    def savings_rate(self) -> Decimal | None:
        """Net as a percentage of income.

        **None where income is zero**, because a month that earned nothing did
        not save 0% of it — the ratio has no denominator. Zero would read as a
        month of spending everything, which is a different and untrue statement.
        """
        income = self.income.amount
        if income <= 0:
            return None
        return (self.net.amount / income * 100).quantize(TENTHS)

    @property
    def any_stale(self) -> bool:
        return any(leg.quote.is_stale for leg in self.included if leg.quote)

    @property
    def oldest_as_at(self) -> date | None:
        dates = [leg.quote.as_at for leg in self.included if leg.quote and leg.quote.legs]
        return min(dates) if dates else None

    def rate_provenance(self) -> list[dict]:
        return sorted(
            (
                {
                    "currency": leg.currency,
                    "pair": leg.quote.pair,
                    "as_at": leg.quote.as_at.isoformat(),
                    "provenance": str(leg.quote.provenance),
                    "stale": leg.quote.is_stale,
                }
                for leg in self.included
                if leg.quote and leg.quote.legs
            ),
            key=lambda row: row["currency"],
        )

    def exclusion_notices(self) -> list[dict]:
        return [
            {"currency": leg.currency, "reason": leg.exclusion_reason or ""}
            for leg in self.exclusions
        ]

    def as_dict(self) -> dict:
        return {
            "month": self.month,
            "currency": self.currency,
            "reportable": self.has_activity,
            "income": self.income.api() if self.has_activity else None,
            "expense": self.expense.api() if self.has_activity else None,
            "net": self.net.api() if self.has_activity else None,
            "savings_rate": str(self.savings_rate) if self.savings_rate is not None else None,
            "exclusions": self.exclusion_notices(),
            "rate_provenance": self.rate_provenance(),
            # Silent when every contributing rate is fresh, as on net worth.
            "as_at": self.oldest_as_at.isoformat()
            if (self.oldest_as_at and self.any_stale)
            else None,
            "any_stale": self.any_stale,
        }


def monthly_summary(
    month: str,
    reporting_currency: str,
    translation: TranslationService | None = None,
) -> CashFlowSummary:
    """Income, expense, net and savings rate for one month, in one currency."""
    if translation is None:
        translation = TranslationService.from_settings()

    # Valued as at today while the month is still running, as net worth is
    # (core.months.as_at_of). The transaction window below is the month itself
    # and stays month-end to month-end: which transactions belong to a month is
    # a different question from the date their currency is translated at.
    as_at = as_at_of(month)

    rows = (
        Transaction.objects.filter(
            date__gte=month_start(month), date__lte=month_end(month)
        )
        .values("currency", "direction")
        .annotate(total=Sum("amount"))
        .order_by("currency")
    )

    entered: dict[str, dict[str, Decimal]] = {}
    for row in rows:
        leg = entered.setdefault(row["currency"], {"income": Decimal(0), "expense": Decimal(0)})
        key = "income" if row["direction"] == Direction.INCOME else "expense"
        leg[key] += row["total"] or Decimal(0)

    legs: list[CurrencyLeg] = []
    for currency in sorted(entered):
        income = entered[currency]["income"]
        expense = entered[currency]["expense"]

        # One quote per currency, applied to both directions. Translating each
        # separately would be the same rate fetched twice and, on a carried
        # quote, two chances for them to disagree.
        income_result = translation.translate(Money(income, currency), reporting_currency, as_at)
        expense_result = translation.translate(Money(expense, currency), reporting_currency, as_at)

        legs.append(
            CurrencyLeg(
                currency=currency,
                income=income,
                expense=expense,
                income_translated=income_result.amount,
                expense_translated=expense_result.amount,
                quote=income_result.quote,
                exclusion_reason=income_result.exclusion_reason,
            )
        )

    return CashFlowSummary(
        month=month, currency=reporting_currency, legs=tuple(legs)
    )


def summary_with_change(
    month: str,
    reporting_currency: str,
    translation: TranslationService | None = None,
) -> dict:
    """The month's four figures, each with its movement on the month before.

    The savings rate moves in **percentage points, and carries no percentage of
    its own**: the change in a rate is already a proportion, and expressing it
    as a proportion of a proportion is a figure nobody can check by hand.
    """
    if translation is None:
        translation = TranslationService.from_settings()

    current = monthly_summary(month, reporting_currency, translation)
    prior_month = previous(month)
    prior = monthly_summary(prior_month, reporting_currency, translation)

    rate_change = None
    if current.savings_rate is not None and prior.savings_rate is not None:
        rate_change = current.savings_rate - prior.savings_rate

    return {
        **current.as_dict(),
        "previous_month": prior_month,
        "change": {
            "income": movement(current.income.amount, prior.income.amount),
            "expense": movement(current.expense.amount, prior.expense.amount),
            "net": movement(current.net.amount, prior.net.amount),
            # Points, not a percentage. And absent where either month has no
            # rate at all, because a change needs two figures to be a change.
            "savings_rate": {
                "change": str(rate_change) if rate_change is not None else None,
                "change_percent": None,
            },
        },
    }


def summary_trend(
    months: list[str],
    reporting_currency: str,
    translation: TranslationService | None = None,
) -> list[dict]:
    """The same four figures over a range, for the dashboard's chart.

    **A month with no transactions is plotted as zero, not as a gap** — the one
    place in this system where absence and zero coincide, for the reason
    :func:`cashflow.services.reporting.category_trend` gives: a month with no
    spending genuinely spent nothing, unlike a month with no balances, which
    does not have a net worth at all rather than one of zero.

    The savings rate is the exception within the exception. It stays **null**
    for a month that earned nothing, because the ratio has no denominator no
    matter how the month is otherwise described.

    One translation service across the range, so the rate lookups are cached
    across months exactly as they are for the net worth trend.
    """
    if translation is None:
        translation = TranslationService.from_settings()

    points: list[dict] = []
    for month in months:
        summary = monthly_summary(month, reporting_currency, translation)
        points.append(
            {
                "month": month,
                "income": str(summary.income.rounded()),
                "expense": str(summary.expense.rounded()),
                "net": str(summary.net.rounded()),
                "savings_rate": str(summary.savings_rate)
                if summary.savings_rate is not None
                else None,
            }
        )
    return points
