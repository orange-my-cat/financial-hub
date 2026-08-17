"""Net worth — the single implementation of BR-04.

    Net worth for a reporting month is the sum of all asset balances minus the
    sum of all liability balances, each translated to the reporting currency at
    that month-end's rate, for every account Open or Dormant as at that
    month-end.

Everything else in this system that shows a net worth figure — the dashboard,
the trend, every slice, the CSV export, the smoke test — comes through here.
There is exactly one definition, so a screen and a report cannot disagree
(§5.2.2).

"That month-end" means the month's as-at date, which for the month still in
progress is today rather than a month-end that has not arrived (see
`core.months.as_at_of`). For every month that has ended the two are the same
date, so the rule reads as written everywhere except the month being closed.

Four rules meet in this function, and each is easy to get subtly wrong:

**The sign is the account's, not the balance's** (BR-06). Liabilities are typed
positive and subtracted here. A credit card in credit is a negative on a
liability account, and correctly increases net worth.

**Dormant accounts carry forward** (BR-03, BR-04). Their last known balance is
included and flagged stale. Open accounts do not carry forward — a missing
balance makes the month Incomplete and is simply absent from the total, which
BR-04 states explicitly.

**A missing rate excludes; it never zeroes** (FR-46). The account keeps its
own-currency figure and its place in the output; only the translated column
withholds a number.

**Nothing computed is stored** (ADR-05). This runs on every read, which is what
makes unrestricted historic editing free rather than dangerous.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.money import Money
from core.months import as_at_of
from core.services.completeness import (
    AccountHistory,
    MonthCompleteness,
    month_completeness,
)
from core.services.rate_lookup import RateQuote, RateResolver
from core.services.translation import TranslationService
from accounts.models import Account, AccountStatus, Balance


@dataclass(frozen=True)
class Contribution:
    """One account's part in one month's net worth."""

    account_id: int
    name: str
    account_type: str
    liquidity_tier: str
    status: str
    currency: str
    is_liability: bool

    #: As entered, in the account's own currency — positive even for a liability.
    entered: Money
    #: The month the figure was actually recorded for. Differs from the
    #: reporting month when a dormant account has carried forward.
    source_month: str
    is_carried: bool

    #: Signed and translated, at full precision. None where no rate exists.
    translated: Decimal | None
    quote: RateQuote | None
    exclusion_reason: str | None

    @property
    def is_excluded(self) -> bool:
        return self.translated is None

    @property
    def signed_entered(self) -> Money:
        return self.entered * (-1 if self.is_liability else 1)

    def as_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "name": self.name,
            "type": self.account_type,
            "liquidity_tier": self.liquidity_tier,
            "status": self.status,
            "currency": self.currency,
            "is_liability": self.is_liability,
            "entered": self.entered.api(),
            "source_month": self.source_month,
            "carried": self.is_carried,
            "translated": str(self.translated.quantize(Decimal("0.01")))
            if self.translated is not None
            else None,
            "as_at": self.quote.as_at.isoformat() if self.quote else None,
            "provenance": str(self.quote.provenance) if self.quote else None,
            "stale": self.quote.is_stale if self.quote else False,
            "excluded": self.is_excluded,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(frozen=True)
class NetWorth:
    month: str
    currency: str
    total: Money
    contributions: tuple[Contribution, ...]
    completeness: MonthCompleteness

    @property
    def is_reportable(self) -> bool:
        """Whether this month has a net worth at all.

        A month before any account recorded a balance does not have a net worth
        of zero — it does not have one. The distinction is the same one FR-46
        draws for a missing rate, one level up: absent is not nothing, and a
        chart that plots it as zero draws a cliff that never happened.
        """
        return bool(self.contributions)

    @property
    def included(self) -> tuple[Contribution, ...]:
        return tuple(c for c in self.contributions if not c.is_excluded)

    @property
    def exclusions(self) -> tuple[Contribution, ...]:
        return tuple(c for c in self.contributions if c.is_excluded)

    @property
    def oldest_as_at(self) -> date | None:
        """The oldest contributing rate date (ADR-09).

        A total may depend on three rates with three different as-at dates, so
        "the as-at date" has no single answer. The oldest is the one shown, and
        only when something is stale — a headline driven by one stale minor
        currency is the safe direction of error.
        """
        dates = [c.quote.as_at for c in self.included if c.quote and c.quote.legs]
        return min(dates) if dates else None

    @property
    def any_stale(self) -> bool:
        return any(c.quote.is_stale for c in self.included if c.quote)

    @property
    def has_carried_balances(self) -> bool:
        return any(c.is_carried for c in self.included)

    def rate_provenance(self) -> list[dict]:
        """Per-currency detail, for the expandable as-at strip."""
        seen: dict[str, dict] = {}
        for contribution in self.included:
            quote = contribution.quote
            if quote is None or not quote.legs:
                continue
            if contribution.currency in seen:
                continue
            seen[contribution.currency] = {
                "currency": contribution.currency,
                "pair": quote.pair,
                "as_at": quote.as_at.isoformat(),
                "provenance": str(quote.provenance),
                "stale": quote.is_stale,
            }
        return sorted(seen.values(), key=lambda row: row["currency"])

    def exclusion_notices(self) -> list[dict]:
        return [
            {"account": c.name, "currency": c.currency, "reason": c.exclusion_reason or ""}
            for c in self.exclusions
        ]


class NetWorthService:
    """One instance per request. The resolver's cache lives for its lifetime."""

    def __init__(
        self,
        translation: TranslationService | None = None,
        *,
        staleness_days: int | None = None,
    ) -> None:
        if translation is None:
            translation = (
                TranslationService(staleness_days=staleness_days)
                if staleness_days is not None
                else TranslationService.from_settings()
            )
        self.translation = translation

    @property
    def resolver(self) -> RateResolver:
        return self.translation.resolver

    # -- inputs ------------------------------------------------------------

    def _accounts_for(self, month: str) -> list[Account]:
        return [
            account
            for account in Account.objects.all()
            if account.is_active_at(month)
        ]

    def _balance_for(
        self, account: Account, month: str
    ) -> tuple[Balance | None, bool]:
        """The balance to use, and whether it was carried forward.

        A Dormant account uses its last known balance where the month has none —
        that is the whole point of the status. An Open account does not: a
        missing balance makes the month Incomplete and the account simply does
        not appear in the total (BR-04).
        """
        exact = account.balances.filter(month=month).first()
        if exact is not None:
            return exact, False

        if account.status == AccountStatus.DORMANT:
            carried = account.balances.filter(month__lt=month).order_by("-month").first()
            if carried is not None:
                return carried, True

        return None, False

    # -- the definition ----------------------------------------------------

    def for_month(self, month: str, reporting_currency: str) -> NetWorth:
        # The date the month is valued at — its month-end, or today while it is
        # still running (core.months.as_at_of). Translating the month in
        # progress at a month-end that has not arrived would date every quote
        # forward: a rate entered on the 16th reads as carried and n days stale
        # on the 16th, and the staleness warning under the headline would be
        # counting days that have not happened. Month Close already records
        # against this date, and completeness already reads it.
        as_at = as_at_of(month)
        accounts = self._accounts_for(month)

        contributions: list[Contribution] = []
        running = Decimal(0)

        for account in accounts:
            balance, carried = self._balance_for(account, month)
            if balance is None:
                continue

            entered = Money(balance.amount, account.currency)
            # The sign is applied before translation, not after. Same answer
            # either way, but doing it here keeps "signed" and "translated"
            # from being two places a sign could be forgotten.
            signed = entered * account.sign

            result = self.translation.translate(signed, reporting_currency, as_at)

            if result.is_translatable:
                # Full precision. Rounded once, at the end.
                running += result.amount

            contributions.append(
                Contribution(
                    account_id=account.pk,
                    name=account.name,
                    account_type=account.account_type,
                    liquidity_tier=account.liquidity_tier,
                    status=account.status,
                    currency=account.currency,
                    is_liability=account.is_liability,
                    entered=entered,
                    source_month=balance.month,
                    is_carried=carried,
                    translated=result.amount,
                    quote=result.quote,
                    exclusion_reason=result.exclusion_reason,
                )
            )

        return NetWorth(
            month=month,
            currency=reporting_currency,
            total=Money(running, reporting_currency),
            contributions=tuple(contributions),
            completeness=self.completeness_for(month),
        )

    # -- completeness ------------------------------------------------------

    def account_histories(self) -> list[AccountHistory]:
        """Translate accounts into what the completeness service understands."""
        histories: list[AccountHistory] = []
        for account in Account.objects.all():
            first = account.balances.order_by("month").values_list("month", flat=True).first()
            histories.append(
                AccountHistory(
                    account_id=account.pk,
                    name=account.name,
                    currency=account.currency,
                    opened_month=account.opened_month,
                    first_recorded_month=first,
                    closed_month=account.closed_month,
                )
            )
        return histories

    def completeness_for(
        self, month: str, *, today: date | None = None
    ) -> MonthCompleteness:
        """The state of one month.

        `today` is what "now" means when deciding the month's as-at date, and
        exists so a caller reasoning about a month other than the real current one
        can be tested deterministically. It changes nothing for a month that has
        ended, which has one as-at date whatever day it is read on.
        """
        histories = self.account_histories()

        recorded_balances = set(
            Balance.objects.filter(month=month).values_list("account_id", flat=True)
        )

        # A rate counts only when it was entered on the month's as-at date
        # itself. A carried rate keeps reports working but does not make the
        # month complete — nobody entered it (ADR-08).
        #
        # As-at rather than month-end because Month Close now records against
        # the as-at date, and the readout sits directly above the rows it
        # describes: a screen that says "0 of 1 rates" beside a row marked saved
        # is worse than either statement alone. For every month that has ended
        # the two dates are the same, so this changes nothing but the month in
        # progress.
        from fx.models import ExchangeRate

        recorded_rates = set(
            ExchangeRate.objects.filter(rate_date=as_at_of(month, today=today)).values_list(
                "currency", flat=True
            )
        )

        # Dormant accounts are excluded from the requirement (BR-03): their last
        # known balance carries forward, so nothing is outstanding for them.
        dormant = set(
            Account.objects.filter(status=AccountStatus.DORMANT).values_list("pk", flat=True)
        )
        histories = [h for h in histories if h.account_id not in dormant]

        return month_completeness(
            month,
            histories,
            balances_recorded_for=recorded_balances,
            rates_recorded_for=recorded_rates,
        )

    # -- ranges ------------------------------------------------------------

    def trend(self, months: list[str], reporting_currency: str) -> list[NetWorth]:
        """A series. One resolver, so the rate lookups are cached across months."""
        return [self.for_month(month, reporting_currency) for month in months]
