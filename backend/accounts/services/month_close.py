"""The Month Close view — a purpose-built query, not a resource (ADR-12).

This screen is the one SC-01 lives or dies on, and its shape is dictated by one
sentence in the handoff: *the prior balance sits immediately left of the input —
that adjacency is the point of the screen*. So the query returns the prior
month's figure alongside each row rather than making the browser fetch a second
month and join them.

Rates come first in the payload for the same reason they come first on screen:
the whole pass runs in one tab order, and stopping midway to go and find a rate
is exactly the friction that ends a close.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.currencies import definition, format_rate, pair_label
from core.months import month_end, previous
from core.services.completeness import MonthCompleteness
from core.services.rate_lookup import RateResolver
from accounts.models import Account, AccountStatus, Balance
from accounts.services.net_worth import NetWorthService


@dataclass(frozen=True)
class RateRow:
    currency: str
    pair: str
    quote_label: str
    example: str
    #: What is recorded for this month-end, if anything.
    rate: Decimal | None
    is_recorded: bool
    #: What a translation would use today — carried, if nothing was entered.
    effective_rate: Decimal | None
    effective_as_at: str | None
    provenance: str | None
    is_stale: bool

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "pair": self.pair,
            "quote_label": self.quote_label,
            "example": self.example,
            "rate": format_rate(self.rate) if self.rate is not None else None,
            "recorded": self.is_recorded,
            "effective_rate": format_rate(self.effective_rate)
            if self.effective_rate is not None
            else None,
            "effective_as_at": self.effective_as_at,
            "provenance": self.provenance,
            "stale": self.is_stale,
        }


@dataclass(frozen=True)
class BalanceRow:
    account_id: int
    name: str
    account_type: str
    liquidity_tier: str
    currency: str
    status: str
    is_liability: bool
    prior: Decimal | None
    prior_month: str
    current: Decimal | None

    @property
    def is_saved(self) -> bool:
        return self.current is not None

    def as_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "name": self.name,
            "type": self.account_type,
            "liquidity_tier": self.liquidity_tier,
            "currency": self.currency,
            "status": self.status,
            "is_liability": self.is_liability,
            "prior": str(self.prior) if self.prior is not None else None,
            "prior_month": self.prior_month,
            "current": str(self.current) if self.current is not None else None,
            "saved": self.is_saved,
        }


@dataclass(frozen=True)
class MonthClose:
    month: str
    as_at: str
    completeness: MonthCompleteness
    rates: tuple[RateRow, ...]
    rows: tuple[BalanceRow, ...]

    def as_dict(self) -> dict:
        return {
            "month": self.month,
            "as_at": self.as_at,
            "completeness": self.completeness.as_dict(),
            "rates": [rate.as_dict() for rate in self.rates],
            "rows": [row.as_dict() for row in self.rows],
        }


def month_close(month: str, *, staleness_days: int) -> MonthClose:
    from fx.models import ExchangeRate

    as_at = month_end(month)
    prior_month = previous(month)
    resolver = RateResolver(staleness_days=staleness_days)

    # -- accounts ---------------------------------------------------------
    # Dormant accounts appear so their status is visible and they can be
    # updated if the user wants to, but they are not counted as outstanding
    # (BR-03). Closed accounts are gone from months after closure.
    accounts = [
        account
        for account in Account.objects.exclude(status=AccountStatus.CLOSED)
        if account.is_active_at(month)
    ]
    closed_but_historic = [
        account
        for account in Account.objects.filter(status=AccountStatus.CLOSED)
        if account.is_active_at(month)
    ]
    accounts = sorted(accounts + closed_but_historic, key=lambda a: a.name.lower())

    account_ids = [account.pk for account in accounts]
    current = {
        row.account_id: row.amount
        for row in Balance.objects.filter(account_id__in=account_ids, month=month)
    }
    prior = {
        row.account_id: row.amount
        for row in Balance.objects.filter(account_id__in=account_ids, month=prior_month)
    }

    rows = tuple(
        BalanceRow(
            account_id=account.pk,
            name=account.name,
            account_type=account.account_type,
            liquidity_tier=account.liquidity_tier,
            currency=account.currency,
            status=account.status,
            is_liability=account.is_liability,
            prior=prior.get(account.pk),
            prior_month=prior_month,
            current=current.get(account.pk),
        )
        for account in accounts
    )

    # -- rates ------------------------------------------------------------
    # Only the currencies actually in use this month. A rate for a currency no
    # account holds is one more thing to type for nothing.
    required = sorted({account.currency for account in accounts if account.currency != "USD"})

    recorded = {
        row.currency: row.rate
        for row in ExchangeRate.objects.filter(rate_date=as_at, currency__in=required)
    }

    rates: list[RateRow] = []
    for code in required:
        leg = resolver.leg(code, as_at)
        rates.append(
            RateRow(
                currency=code,
                pair=pair_label(code),
                quote_label=definition(code).quote_label,
                example=definition(code).example,
                rate=recorded.get(code),
                is_recorded=code in recorded,
                effective_rate=leg.quoted_rate if leg else None,
                effective_as_at=leg.as_at.isoformat() if leg else None,
                provenance=str(leg.provenance) if leg else None,
                is_stale=leg.is_stale if leg else False,
            )
        )

    return MonthClose(
        month=month,
        as_at=as_at.isoformat(),
        completeness=NetWorthService(staleness_days=staleness_days).completeness_for(month),
        rates=tuple(rates),
        rows=rows,
    )
