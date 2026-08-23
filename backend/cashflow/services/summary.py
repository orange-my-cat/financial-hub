"""The month's cash flow as one figure per line, in the reporting currency.

Distinct from :mod:`cashflow.services.reporting`, and deliberately so. The
category report answers *what was spent on* — a question that is only meaningful
in the currency the money was spent in, which is why nothing there is translated.
This answers *how the month went overall*, and that question has no per-currency
answer at all: three net figures in three currencies do not tell a person whether
they saved anything.

:func:`category_flow` is the same translation applied one category at a time —
the combined breakdown a single diagram can be drawn from. It lives here rather
than beside the category report because what defines it is the translation, and
the translated figures are defined here.

The BRD sanctions the translation — "FX applies to balances and cash flow only"
(A36); only investment performance is barred from it (BR-18). The translation
still goes through the one translation service, like every other crossing in the
system, so the rate, its as-at date and its provenance travel with the total.

**Each transaction at the rate on its own date.** A payment made on the 3rd was
worth what it was worth on the 3rd, and a month is the sum of what happened in
it rather than one conversion applied to a heap. This is where cash flow parts
company with net worth, and the difference is in what the two things are: a
balance is an as-at figure and takes the month-end rate, while a flow is an
event and takes its own day's. Choosing the date is still the report's job and
not the arithmetic's (§5.2.1) — it is chosen here, once, in
:func:`restate_month`, and every cash flow figure in the system is built from
what that returns.

The consequence is deliberate and worth stating plainly: **the month's income,
expense and net are sums of individually translated transactions**, so they
cannot be reproduced by translating the month's entered totals at any single
rate. That is the price of the column on the transactions table adding up to
the figure on the dashboard, which was the alternative price.

**A missing rate excludes, and never zeroes** (FR-46). At a rate per day the
unit of exclusion is the transaction and no longer the whole currency: a MYR
payment dated before the first USD/MYR rate on record is withheld from income,
expense and net alike, while its neighbours a fortnight later are counted
normally. Every response says how many rows this happened to and why. Both
directions are withheld together for the row concerned — dropping it from
expense while keeping it in income would invent a savings rate that no
arrangement of the facts supports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.money import Money
from core.months import month_end, month_start, previous
from core.services.movement import movement
from core.services.rate_lookup import RateQuote
from core.services.translation import TranslationService
from cashflow.models import Direction, Transaction
from cashflow.services import reporting

TENTHS = Decimal("0.1")


@dataclass(frozen=True)
class Restatement:
    """One transaction's amount in the reporting currency, and what qualifies it.

    Carried beside the transaction rather than in place of it. The entered
    amount is the fact; this is what that amount was worth, on the day it
    happened, in the currency the reports are being read in.

    `amount` is **None**, never zero, where no rate exists on or before the
    transaction's date — the FR-46 case, one row at a time.
    """

    #: Full precision. Rounded once, at display.
    amount: Decimal | None
    quote: RateQuote | None
    exclusion_reason: str | None

    @property
    def is_translatable(self) -> bool:
        return self.amount is not None

    def as_dict(self, currency: str) -> dict:
        return {
            "amount": Money(self.amount, currency).api() if self.amount is not None else None,
            # The rate this one row was translated at, which is not the rate
            # its neighbours were. Absent where the row is already in the
            # reporting currency and no rate was involved at all.
            "rate": {
                "pair": self.quote.pair,
                "as_at": self.quote.as_at.isoformat(),
                "provenance": str(self.quote.provenance),
                "stale": self.quote.is_stale,
            }
            if self.quote and self.quote.legs
            else None,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(frozen=True)
class CurrencyLeg:
    """One entered currency's contribution, before and after translation.

    A currency is no longer translated as a lump, so a leg is a roll-up of its
    rows rather than a pair of converted totals: the translated figures below
    are sums of what each transaction came to at its own date's rate, and the
    rows that had no rate are absent from them rather than present as zero.
    """

    currency: str
    #: As entered. Every row, including any that could not be translated.
    income: Decimal
    expense: Decimal

    #: Full precision, summed from the rows that had a rate.
    income_translated: Decimal
    expense_translated: Decimal

    translated_count: int
    excluded_count: int

    #: The distinct quotes actually used, oldest first. Empty where the entered
    #: currency is the reporting one and no rate was involved.
    quotes: tuple[RateQuote, ...]
    #: From the most recent row that could not be translated, which is the one
    #: that says how far the gap in the rate table reaches.
    exclusion_reason: str | None

    @property
    def is_excluded(self) -> bool:
        """Whether **nothing** in this currency could be translated.

        Distinct from :attr:`excluded_count`, which a currency can carry while
        still contributing: at a rate per day, part of a month's MYR can be
        older than the first MYR rate on record and the rest of it not.
        """
        return self.translated_count == 0


@dataclass(frozen=True)
class CashFlowSummary:
    """A month's income, expense, net and savings rate in one currency."""

    month: str
    currency: str
    legs: tuple[CurrencyLeg, ...]

    @property
    def included(self) -> tuple[CurrencyLeg, ...]:
        """Currencies that contributed something. Partly is enough."""
        return tuple(leg for leg in self.legs if not leg.is_excluded)

    @property
    def exclusions(self) -> tuple[CurrencyLeg, ...]:
        """Currencies that lost **any** row for want of a rate.

        A leg can appear here and in :attr:`included` at once, and that is the
        honest answer where it is true: some of the month's MYR was translated
        and some of it was not, and stating only one of those would be a
        smaller lie in either direction.
        """
        return tuple(leg for leg in self.legs if leg.excluded_count)

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
        """Summed from rows already translated one at a time, at full precision.

        Over every leg rather than the included ones: a leg that translated
        nothing contributes nothing to these, which is the same statement made
        without a filter that could fall out of step with the one above.
        """
        return Money(
            sum((leg.income_translated for leg in self.legs), Decimal(0)), self.currency
        )

    @property
    def expense(self) -> Money:
        return Money(
            sum((leg.expense_translated for leg in self.legs), Decimal(0)), self.currency
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
        return any(quote.is_stale for leg in self.legs for quote in leg.quotes)

    @property
    def oldest_as_at(self) -> date | None:
        dates = [quote.as_at for leg in self.legs for quote in leg.quotes]
        return min(dates) if dates else None

    def rate_provenance(self) -> list[dict]:
        """One row per currency, as the design handoff specifies (§2).

        A month translated at a rate a day now uses many rates per currency, and
        listing every one of them would answer a question nobody asked with
        thirty rows. What a reader of a *total* needs is how old the oldest
        contributing rate was and whether anything in the figure is stale, so
        that is what this states — the row's own rate travels with the row, on
        the transactions table, where a per-row fact belongs.
        """
        rows = []
        for leg in self.legs:
            if not leg.quotes:
                continue
            oldest = min(leg.quotes, key=lambda quote: quote.as_at)
            rows.append(
                {
                    "currency": leg.currency,
                    "pair": oldest.pair,
                    "as_at": oldest.as_at.isoformat(),
                    "provenance": str(oldest.provenance),
                    # Any of them, not merely the oldest: staleness qualifies
                    # the total, and one stale contributor is enough to.
                    "stale": any(quote.is_stale for quote in leg.quotes),
                }
            )
        return sorted(rows, key=lambda row: row["currency"])

    def exclusion_notices(self) -> list[dict]:
        """What was left out, per currency, and how much of it.

        The count is the point at a rate a day: "excludes MYR" once meant the
        whole month's MYR and now means somewhere between one row and all of
        them, and a reader cannot tell which without being told.
        """
        return [
            {
                "currency": leg.currency,
                "count": leg.excluded_count,
                "reason": leg.exclusion_reason or "",
            }
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


def restate_month(
    month: str,
    reporting_currency: str,
    translation: TranslationService | None = None,
) -> list[tuple[Transaction, Restatement]]:
    """Every transaction in the month, each at the rate on its own date.

    **The one place a cash flow figure crosses a currency.** The month's totals,
    the category breakdown and the column on the transactions table are all
    roll-ups of what this returns, which is what stops the three of them
    disagreeing about what a month came to — and what lets a reader add the
    column down and land on the total (§5.2.1, "one definition per
    calculation").

    Newest first, the order the transactions table reads in. Callers that group
    do not care, and the one that lists is spared a re-sort.

    The window is the month itself and stays month-end to month-end: which
    transactions belong to a month is a different question from the date each
    one's currency is translated at.
    """
    if translation is None:
        translation = TranslationService.from_settings()

    rows = list(
        Transaction.objects.filter(
            date__gte=month_start(month), date__lte=month_end(month)
        )
        .select_related("category", "category__parent")
        .order_by("-date", "-id")
    )

    # A rate a day is a lookup a day, and a twenty-four month trend asks for
    # eight hundred of them. Warmed in one query per currency; every leg this
    # fills is the leg the resolver would have found on its own.
    translation.warm(
        {row.currency for row in rows} | {reporting_currency},
        {row.date for row in rows},
    )

    restated = []
    for row in rows:
        result = translation.translate(
            Money(row.amount, row.currency), reporting_currency, row.date
        )
        restated.append(
            (
                row,
                Restatement(
                    amount=result.amount,
                    quote=result.quote,
                    exclusion_reason=result.exclusion_reason,
                ),
            )
        )

    return restated


def _summarise(
    month: str,
    reporting_currency: str,
    restated: list[tuple[Transaction, Restatement]],
) -> CashFlowSummary:
    """Roll restated transactions up into one currency's legs.

    Separate from :func:`monthly_summary` only so that a caller already holding
    the restated rows — the breakdown, the transactions table — can have the
    month's totals without translating everything a second time.
    """
    legs: dict[str, dict] = {}

    for row, restatement in restated:
        leg = legs.setdefault(
            row.currency,
            {
                "income": Decimal(0),
                "expense": Decimal(0),
                "income_translated": Decimal(0),
                "expense_translated": Decimal(0),
                "translated_count": 0,
                "excluded_count": 0,
                "quotes": {},
                "exclusion_reason": None,
            },
        )

        direction = "income" if row.direction == Direction.INCOME else "expense"
        leg[direction] += row.amount

        if restatement.is_translatable:
            leg[f"{direction}_translated"] += restatement.amount
            leg["translated_count"] += 1
            if restatement.quote and restatement.quote.legs:
                # Keyed by date, so a month that used the 3rd's rate on nine
                # transactions counts that rate once.
                leg["quotes"][restatement.quote.as_at] = restatement.quote
        else:
            leg["excluded_count"] += 1
            # The first one seen, and the rows arrive newest first: the most
            # recent date without a rate is the one that says how far the gap
            # in the rate table reaches forward.
            if leg["exclusion_reason"] is None:
                leg["exclusion_reason"] = restatement.exclusion_reason

    return CashFlowSummary(
        month=month,
        currency=reporting_currency,
        legs=tuple(
            CurrencyLeg(
                currency=currency,
                income=leg["income"],
                expense=leg["expense"],
                income_translated=leg["income_translated"],
                expense_translated=leg["expense_translated"],
                translated_count=leg["translated_count"],
                excluded_count=leg["excluded_count"],
                quotes=tuple(quote for _, quote in sorted(leg["quotes"].items())),
                exclusion_reason=leg["exclusion_reason"],
            )
            for currency, leg in sorted(legs.items())
        ),
    )


def monthly_summary(
    month: str,
    reporting_currency: str,
    translation: TranslationService | None = None,
) -> CashFlowSummary:
    """Income, expense, net and savings rate for one month, in one currency.

    Every figure is a sum of transactions translated one at a time, at the rate
    on each one's own date. There is no single rate that reproduces these totals
    from the month's entered figures, and that is the point rather than a
    shortcoming — see the note at the top of this module.
    """
    return _summarise(
        month, reporting_currency, restate_month(month, reporting_currency, translation)
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


def transaction_list(
    month: str,
    reporting_currency: str,
    translation: TranslationService | None = None,
) -> dict:
    """The month's transactions, each restated in the reporting currency.

    A column beside each row, not a combination — the transaction keeps the
    currency it was entered in, and the figure next to it says what that amount
    was worth on the day it happened. Because the month's totals are sums of
    these same restated rows, the column adds down to the net figure the
    dashboard states rather than to something near it.

    It lives here and not beside :func:`cashflow.services.reporting.transactions_for_month`
    because what defines it is the translation. The untranslated list stays
    where it is and is what the CSV export writes — the export states amounts as
    entered and says so.

    **A row with no rate on or before its own date withholds the column, and
    never shows a zero** (FR-46). It keeps its own-currency figure and its place
    in the list, its neighbours are unaffected, and the response says how many
    rows this happened to and why.
    """
    restated = restate_month(month, reporting_currency, translation)
    totals = _summarise(month, reporting_currency, restated)

    return {
        "month": month,
        "currency": reporting_currency,
        "rows": [
            reporting.transaction_row(
                row, restatement=restatement.as_dict(reporting_currency)
            )
            for row, restatement in restated
        ],
        "exclusions": totals.exclusion_notices(),
        "rate_provenance": totals.rate_provenance(),
        # Silent when every contributing rate is fresh, as everywhere else.
        "as_at": totals.oldest_as_at.isoformat()
        if (totals.oldest_as_at and totals.any_stale)
        else None,
        "any_stale": totals.any_stale,
    }


@dataclass(frozen=True)
class FlowCategory:
    """One category's month, after translation into the reporting currency."""

    category_id: int
    category: str
    parent: str
    direction: str
    #: Full precision. Rounded once, at display.
    total: Decimal
    count: int

    def as_dict(self, currency: str) -> dict:
        return {
            "category_id": self.category_id,
            "category": self.category,
            "parent": self.parent,
            "direction": self.direction,
            "total": Money(self.total, currency).api(),
            "count": self.count,
        }


def category_flow(
    month: str,
    reporting_currency: str,
    translation: TranslationService | None = None,
) -> dict:
    """Every category the month touched, combined into one currency.

    The companion to :func:`cashflow.services.reporting.category_report`, and
    its opposite in exactly one respect. That report is per currency and never
    translated, because *what was spent on* is a question about money as it was
    spent — a month's groceries in MYR and its rent in AUD are two facts. This
    answers a question the split cannot: *where did the month go*, for a life
    lived in more than one currency, where three lists side by side are not
    something a person can read as one month.

    Combining is the translation the BRD sanctions — "FX applies to balances and
    cash flow only" (A36). Only investment performance is barred from it
    (BR-18). It goes through the one translation service like every other
    crossing, so the rate, its as-at date and its provenance travel with the
    figures.

    **The totals here are :func:`monthly_summary`'s totals, broken apart.** Both
    are roll-ups of the same restated transactions — the same list, cut by
    category here and by direction there — so the diagram and the dashboard's
    four figures cannot disagree, and the rate each transaction is translated at
    is chosen in one place (§5.2.1).

    **A row with no rate on its own date is excluded** (FR-46). It is absent
    from its category's total rather than present at zero, and the omission is
    stated in the response beside the figures it changes. Its category does not
    vanish with it: a category with one untranslatable row and nine ordinary
    ones is still drawn, from the nine.

    Categories merge across currencies: groceries bought in MYR and groceries
    bought in AUD are one category and one row, which is the point of
    combining them.
    """
    restated = restate_month(month, reporting_currency, translation)
    summary = _summarise(month, reporting_currency, restated)

    merged: dict[int, dict] = {}
    for row, restatement in restated:
        if not restatement.is_translatable:
            continue

        entry = merged.setdefault(
            row.category_id,
            {
                "category": row.category.name,
                "parent": row.category.parent.name if row.category.parent else "—",
                "direction": row.direction,
                "total": Decimal(0),
                "count": 0,
            },
        )
        entry["total"] += restatement.amount
        entry["count"] += 1

    children = sorted(
        (
            FlowCategory(
                category_id=category_id,
                category=entry["category"],
                parent=entry["parent"],
                direction=entry["direction"],
                total=entry["total"],
                count=entry["count"],
            )
            for category_id, entry in merged.items()
        ),
        key=lambda child: (child.direction, child.parent, child.category),
    )

    # Rolled up here rather than in the browser, for the reason ADR-02 gives:
    # a parent total added client-side would be added in floats, and would stop
    # agreeing with the children printed under it.
    rollup: dict[tuple[str, str], dict] = {}
    for child in children:
        entry = rollup.setdefault(
            (child.direction, child.parent),
            {
                "parent": child.parent,
                "direction": child.direction,
                "total": Decimal(0),
                "count": 0,
            },
        )
        entry["total"] += child.total
        entry["count"] += child.count

    parents = [
        {
            "parent": entry["parent"],
            "direction": entry["direction"],
            "total": Money(entry["total"], reporting_currency).api(),
            "count": entry["count"],
        }
        for entry in sorted(
            rollup.values(), key=lambda row: (row["direction"], row["parent"])
        )
    ]

    return {
        "month": month,
        "currency": reporting_currency,
        # A month with nothing left to draw. Not the same as a month that broke
        # even, and not the same as a month excluded entirely — the exclusions
        # below say which of the two this is.
        "reportable": bool(children),
        "income": summary.income.api(),
        "expense": summary.expense.api(),
        "net": summary.net.api(),
        "parents": parents,
        "children": [child.as_dict(reporting_currency) for child in children],
        "exclusions": summary.exclusion_notices(),
        "rate_provenance": summary.rate_provenance(),
        # Silent when every contributing rate is fresh, as on net worth.
        "as_at": summary.oldest_as_at.isoformat()
        if (summary.oldest_as_at and summary.any_stale)
        else None,
        "any_stale": summary.any_stale,
    }
