"""Account and Balance rules — BR-01 to BR-08.

The database-level ones are tested by writing around the service, because that
is the only way to find out whether they are actually in the database (§9.1).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from accounts.models import (
    Account,
    AccountStatus,
    AccountType,
    Balance,
    LiquidityTier,
)
from accounts.services import lifecycle
from accounts.services.net_worth import NetWorthService
from core.services.advisories import AdvisoryKind
from core.services.exceptions import BusinessRuleError, ConflictError
from fx.models import ExchangeRate

pytestmark = pytest.mark.django_db


def make_account(
    name="Savings",
    account_type=AccountType.SAVINGS,
    tier=LiquidityTier.SHORT,
    currency="USD",
    opened="2026-01",
    **kwargs,
) -> Account:
    return Account.objects.create(
        name=name,
        account_type=account_type,
        liquidity_tier=tier,
        currency=currency,
        opened_month=opened,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# BR-06 — the sign belongs to the account
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("account_type", "liability"),
    [
        (AccountType.CURRENT, False),
        (AccountType.SAVINGS, False),
        (AccountType.INVESTMENT, False),
        (AccountType.PENSION, False),
        (AccountType.PROPERTY, False),
        (AccountType.PHYSICAL, False),
        (AccountType.CREDIT_CARD, True),
        (AccountType.LOAN, True),
        (AccountType.OTHER_LIABILITY, True),
    ],
)
def test_every_one_of_the_nine_types_knows_its_side(account_type, liability):
    account = make_account(account_type=account_type)

    assert account.is_liability is liability
    assert account.sign == (-1 if liability else 1)


def test_a_credit_card_in_credit_increases_net_worth():
    """Entered as a negative on a liability account (BR-06)."""
    account = make_account(account_type=AccountType.CREDIT_CARD, currency="USD")
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("-500.00"))

    result = NetWorthService(staleness_days=7).for_month("2026-07", "USD")

    assert result.total.amount == Decimal("500.00")


# ---------------------------------------------------------------------------
# BR-08 — one currency, fixed once balances exist
# ---------------------------------------------------------------------------


def test_the_service_refuses_a_currency_change_once_balances_exist():
    account = make_account(currency="AUD")
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("1"))

    with pytest.raises(BusinessRuleError, match="requires a new account"):
        lifecycle.change_currency(account, "USD")


def test_the_currency_can_change_while_the_account_has_no_balances():
    account = make_account(currency="AUD")

    lifecycle.change_currency(account, "MYR")

    account.refresh_from_db()
    assert account.currency == "MYR"


def test_the_database_refuses_a_currency_change_written_around_the_service():
    """The trigger. This is the path the Django admin would take."""
    account = make_account(currency="AUD")
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("1"))

    # The trigger raises with ERRCODE check_violation, which Django surfaces as
    # IntegrityError — the same class the unique and check constraints use.
    with pytest.raises(IntegrityError, match="BR-08"):
        with transaction.atomic():
            Account.objects.filter(pk=account.pk).update(currency="USD")


def test_a_soft_deleted_balance_does_not_freeze_the_currency():
    """A balance the application treats as never having existed must not
    permanently fix the currency of an account whose history was removed."""
    account = make_account(currency="AUD")
    balance = Balance.objects.create(account=account, month="2026-07", amount=Decimal("1"))
    balance.delete()

    lifecycle.change_currency(account, "USD")

    account.refresh_from_db()
    assert account.currency == "USD"


# ---------------------------------------------------------------------------
# One balance per account per month
# ---------------------------------------------------------------------------


def test_entering_a_second_balance_for_a_month_replaces_the_first():
    account = make_account()
    lifecycle.upsert_balance(account, "2026-07", Decimal("100"))
    lifecycle.upsert_balance(account, "2026-07", Decimal("200"))

    assert account.balances.count() == 1
    assert account.balances.get().amount == Decimal("200")


def test_the_database_refuses_a_duplicate_balance():
    account = make_account()
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("1"))

    with pytest.raises(IntegrityError):
        Balance.objects.create(account=account, month="2026-07", amount=Decimal("2"))


def test_the_same_month_can_be_entered_again_after_a_delete():
    account = make_account()
    lifecycle.upsert_balance(account, "2026-07", Decimal("100"))
    lifecycle.delete_balance(account, "2026-07")

    lifecycle.upsert_balance(account, "2026-07", Decimal("300"))

    assert account.balances.count() == 1


def test_a_balance_before_the_opening_month_is_refused():
    account = make_account(opened="2026-06")

    with pytest.raises(BusinessRuleError, match="opened in 2026-06"):
        lifecycle.upsert_balance(account, "2026-05", Decimal("1"))


def test_a_malformed_month_is_refused_by_the_database():
    account = make_account()

    with pytest.raises(IntegrityError):
        Balance.objects.create(account=account, month="2026-13", amount=Decimal("1"))


# ---------------------------------------------------------------------------
# BR-03 / BR-04 — dormancy, closure and who counts
# ---------------------------------------------------------------------------


def test_a_dormant_account_carries_its_last_balance_forward_and_flags_it():
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))
    lifecycle.set_dormant(account)

    result = NetWorthService(staleness_days=7).for_month("2026-07", "USD")

    assert result.total.amount == Decimal("1000")
    contribution = result.contributions[0]
    assert contribution.is_carried is True
    assert contribution.source_month == "2026-05"


def test_an_open_account_does_not_carry_forward():
    """A missing balance makes the month Incomplete and is simply absent from
    the total — BR-04 says so explicitly."""
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))

    result = NetWorthService(staleness_days=7).for_month("2026-07", "USD")

    assert result.total.amount == Decimal("0")
    assert result.contributions == ()


def test_a_dormant_account_is_not_outstanding_for_completeness():
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))
    lifecycle.set_dormant(account)

    completeness = NetWorthService(staleness_days=7).completeness_for("2026-07")

    assert completeness.outstanding_accounts == ()


def test_a_closed_account_stays_in_its_historic_months():
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))
    lifecycle.close(account, "2026-06")

    assert NetWorthService(staleness_days=7).for_month("2026-05", "USD").total.amount == Decimal("1000")
    assert NetWorthService(staleness_days=7).for_month("2026-07", "USD").contributions == ()


def test_an_account_is_absent_from_months_before_it_opened():
    account = make_account(opened="2026-06")
    Balance.objects.create(account=account, month="2026-06", amount=Decimal("1000"))

    assert account.is_active_at("2026-05") is False
    assert NetWorthService(staleness_days=7).for_month("2026-05", "USD").contributions == ()


# ---------------------------------------------------------------------------
# FR-46 — a missing rate excludes, never zeroes
# ---------------------------------------------------------------------------


def test_an_account_with_no_rate_is_excluded_and_keeps_its_own_figure():
    usd = make_account(name="Everyday", currency="USD")
    aud = make_account(name="CommBank", currency="AUD")
    Balance.objects.create(account=usd, month="2026-07", amount=Decimal("1000"))
    Balance.objects.create(account=aud, month="2026-07", amount=Decimal("5000"))

    result = NetWorthService(staleness_days=7).for_month("2026-07", "USD")

    assert result.total.amount == Decimal("1000")
    excluded = result.exclusions[0]
    assert excluded.name == "CommBank"
    assert excluded.translated is None
    # Its own-currency figure survives, and its place in the table with it.
    assert excluded.entered.amount == Decimal("5000")
    assert "AUD/USD" in excluded.exclusion_reason


def test_the_exclusion_is_stated_on_the_aggregate():
    aud = make_account(name="CommBank", currency="AUD")
    Balance.objects.create(account=aud, month="2026-07", amount=Decimal("5000"))

    notices = NetWorthService(staleness_days=7).for_month("2026-07", "USD").exclusion_notices()

    assert notices[0]["account"] == "CommBank"
    assert "no AUD/USD rate exists" in notices[0]["reason"]


# ---------------------------------------------------------------------------
# BR-07 — reclassification restates history
# ---------------------------------------------------------------------------


def test_crossing_the_asset_liability_boundary_advises_and_still_saves():
    account = make_account(account_type=AccountType.SAVINGS)
    for month in ("2026-05", "2026-06", "2026-07"):
        Balance.objects.create(account=account, month=month, amount=Decimal("100"))

    result = lifecycle.reclassify(
        account, account_type=AccountType.LOAN, liquidity_tier=LiquidityTier.LOCKED
    )

    assert len(result.advisories) == 1
    advisory = result.advisories[0]
    assert advisory.kind is AdvisoryKind.HISTORIC_RESTATEMENT
    assert advisory.detail["months_affected"] == 3
    assert advisory.detail["crosses_asset_liability_boundary"] is True
    assert "reverses the sign" in advisory.message
    # Saved either way. That is what makes it an advisory.
    account.refresh_from_db()
    assert account.account_type == AccountType.LOAN


def test_reclassification_restates_historic_net_worth():
    account = make_account(account_type=AccountType.SAVINGS)
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("100"))
    assert NetWorthService(staleness_days=7).for_month("2026-07", "USD").total.amount == Decimal("100")

    lifecycle.reclassify(
        account, account_type=AccountType.LOAN, liquidity_tier=LiquidityTier.LOCKED
    )

    assert NetWorthService(staleness_days=7).for_month("2026-07", "USD").total.amount == Decimal("-100")


def test_a_reclassification_within_one_side_says_net_worth_is_unchanged():
    account = make_account(account_type=AccountType.SAVINGS)
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("100"))

    advisory = lifecycle.reclassify(
        account, account_type=AccountType.CURRENT, liquidity_tier=LiquidityTier.INSTANT
    ).advisories[0]

    assert advisory.detail["crosses_asset_liability_boundary"] is False
    assert "Net worth is unchanged" in advisory.message


def test_reclassifying_an_account_with_no_history_advises_nothing():
    """Saying "0 months restated" trains the user to dismiss without reading."""
    account = make_account()

    result = lifecycle.reclassify(
        account, account_type=AccountType.LOAN, liquidity_tier=LiquidityTier.LOCKED
    )

    assert result.advisories == ()


# ---------------------------------------------------------------------------
# ADR-14 — deletion narrowed to accounts with no history
# ---------------------------------------------------------------------------


def test_an_account_with_no_balances_can_be_deleted():
    account = make_account()

    lifecycle.delete_account(account)

    assert Account.objects.count() == 0
    # Still soft, so even this is recoverable.
    assert Account.all_objects.count() == 1


def test_an_account_with_history_cannot_be_deleted():
    account = make_account()
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("1"))

    with pytest.raises(BusinessRuleError, match="closed, never deleted"):
        lifecycle.delete_account(account)


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------


def test_closing_before_the_opening_month_is_refused():
    account = make_account(opened="2026-06")

    with pytest.raises(BusinessRuleError, match="cannot close"):
        lifecycle.close(account, "2026-05")


def test_closing_before_a_recorded_balance_is_refused():
    account = make_account()
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("1"))

    with pytest.raises(ConflictError, match="after the closing month"):
        lifecycle.close(account, "2026-06")


def test_the_database_refuses_a_closed_account_with_no_closing_month():
    account = make_account()

    with pytest.raises(IntegrityError):
        Account.objects.filter(pk=account.pk).update(status=AccountStatus.CLOSED)


def test_a_dormant_account_needs_something_to_carry_forward():
    account = make_account()

    with pytest.raises(BusinessRuleError, match="no recorded balance"):
        lifecycle.set_dormant(account)


def test_a_closed_account_cannot_be_made_dormant():
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1"))
    lifecycle.close(account, "2026-06")

    with pytest.raises(BusinessRuleError, match="is closed"):
        lifecycle.set_dormant(account)


def test_reopening_clears_the_closing_month():
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1"))
    lifecycle.close(account, "2026-06")

    lifecycle.reopen(account)

    account.refresh_from_db()
    assert account.status == AccountStatus.OPEN
    assert account.closed_month is None


# ---------------------------------------------------------------------------
# Completeness through the real models
# ---------------------------------------------------------------------------


def test_a_month_is_complete_when_every_balance_and_rate_is_present():
    usd = make_account(name="Everyday", currency="USD")
    aud = make_account(name="CommBank", currency="AUD")
    Balance.objects.create(account=usd, month="2026-07", amount=Decimal("1"))
    Balance.objects.create(account=aud, month="2026-07", amount=Decimal("1"))
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 7, 31), rate=Decimal("0.66")
    )

    completeness = NetWorthService(staleness_days=7).completeness_for("2026-07")

    assert str(completeness.state) == "Complete"


def test_a_carried_rate_does_not_make_a_month_complete():
    """Nobody entered it. Reports still work; the month is still Incomplete."""
    aud = make_account(name="CommBank", currency="AUD")
    Balance.objects.create(account=aud, month="2026-07", amount=Decimal("1"))
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 6, 30), rate=Decimal("0.66")
    )

    completeness = NetWorthService(staleness_days=7).completeness_for("2026-07")

    assert str(completeness.state) == "Incomplete"
    assert completeness.outstanding_currencies == ("AUD",)
