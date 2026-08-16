"""The Month Close view — a purpose-built query, not a resource (ADR-12).

This screen is the one SC-01 lives or dies on, and its shape is dictated by one
sentence in the handoff: *the prior balance sits immediately left of the input —
that adjacency is the point of the screen*. So the query returns the prior
month's figure alongside each row rather than making the browser fetch a second
month and join them.

This query used to carry a second section: the rates for the month, quoted
against the reporting currency and typed on the screen beside the balances.
Rates are loaded from the provider now (`manage.py load_rates`), so the payload
is balances alone and the whole re-basing apparatus that served those rows is
gone with it.

The reporting currency therefore no longer changes anything this query returns.
It is still accepted, because the completeness figure below is computed against
it and because dropping a parameter from a live endpoint's signature buys
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.currencies import BASE_CURRENCY, definition
from core.months import as_at_of, previous
from core.services.completeness import MonthCompleteness
from core.services.movement import movement
from accounts.models import Account, AccountStatus, Balance
from accounts.services.net_worth import NetWorthService


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
        # The movement on the month before, from the one place that defines it.
        # Both halves null where either month has no figure, the percentage
        # alone null against a zero prior month — see core.services.movement.
        moved = movement(self.current, self.prior)

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
            "change": moved["change"],
            "change_percent": moved["change_percent"],
        }


@dataclass(frozen=True)
class MonthClose:
    month: str
    as_at: str
    #: The reporting currency the completeness figure is computed against.
    #: Balances are unaffected and stay in each account's own currency.
    currency: str
    completeness: MonthCompleteness
    rows: tuple[BalanceRow, ...]

    def as_dict(self) -> dict:
        return {
            "month": self.month,
            "as_at": self.as_at,
            "currency": self.currency,
            "completeness": self.completeness.as_dict(),
            "rows": [row.as_dict() for row in self.rows],
        }


def month_close(
    month: str,
    *,
    staleness_days: int,
    reporting_currency: str = BASE_CURRENCY,
) -> MonthClose:
    basis = reporting_currency
    definition(basis)
    # Never a future date. A month still running is valued at today, not at a
    # month-end that has not arrived — see core.months.as_at_of.
    as_at = as_at_of(month)
    prior_month = previous(month)

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

    return MonthClose(
        month=month,
        as_at=as_at.isoformat(),
        currency=basis,
        completeness=NetWorthService(staleness_days=staleness_days).completeness_for(month),
        rows=rows,
    )
