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
from accounts.services.dormant import roll_dormant_balances
from accounts.services.net_worth import NetWorthService
from core.months import month_of, sequence
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


def test_setting_an_account_dormant_stores_its_balance_for_every_month_since():
    """The carry-forward is a stored fact, not only a reading rule.

    It was in-memory only: net worth found the last figure and used it, and the
    months in between held nothing. A dormant account is one nobody touches, so
    each of those months holds the same figure — and now says so in the
    database (`accounts.services.dormant`).
    """
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))

    lifecycle.set_dormant(account)

    stored = dict(account.balances.values_list("month", "amount"))
    for month in sequence("2026-05", month_of(date.today())):
        assert stored[month] == Decimal("1000"), month

    # Nothing ahead of today: "the balance has not changed" is a statement about
    # the past, and writing it forward would be a forecast.
    assert max(stored) == month_of(date.today())


def test_a_dormant_balance_is_an_ordinary_balance_once_stored():
    """So net worth reads it as entered rather than as carried — there is
    nothing left to carry for a month that has the figure itself."""
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))
    lifecycle.set_dormant(account)

    result = NetWorthService(staleness_days=7).for_month("2026-07", "USD")

    assert result.total.amount == Decimal("1000")
    contribution = result.contributions[0]
    assert contribution.is_carried is False
    assert contribution.source_month == "2026-07"


def test_a_dormant_account_still_carries_forward_where_no_row_was_stored():
    """The reading rule is still the one that makes net worth right (BR-03).

    Rows are stored for the months up to today, and nothing is stored beyond
    them — a month ahead of the roll, or one read before a roll has reached it,
    has no row at all. Net worth carries the last known figure into it exactly as
    it did before any of this, which is why the rule stays.
    """
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))
    lifecycle.set_dormant(account)
    account.balances.filter(month="2026-07").delete()

    result = NetWorthService(staleness_days=7).for_month("2026-07", "USD")

    assert result.total.amount == Decimal("1000")
    contribution = result.contributions[0]
    assert contribution.is_carried is True
    assert contribution.source_month == "2026-06"


def test_rolling_a_dormant_account_twice_writes_nothing_the_second_time():
    """Idempotent, which is what makes it safe on a read path."""
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))
    lifecycle.set_dormant(account)
    before = account.balances.count()

    assert roll_dormant_balances(month_of(date.today())) == ()
    assert account.balances.count() == before


def test_the_roll_never_writes_a_month_that_has_not_arrived():
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))
    lifecycle.set_dormant(account)

    written = roll_dormant_balances("2027-06", today=date(2026, 7, 15))

    assert [row.month for row in written] == []
    assert account.balances.filter(month__gt=month_of(date.today())).count() == 0


def test_the_roll_writes_nothing_before_the_first_recorded_figure():
    """An account is required only from the later of its opening and its first
    recorded balance (ADR-04), and there is nothing to carry into a month that
    precedes every figure there is."""
    account = make_account(opened="2026-01")
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))
    lifecycle.set_dormant(account)

    assert roll_dormant_balances("2026-03", today=date(2026, 3, 20)) == ()
    assert account.balances.filter(month__lt="2026-05").count() == 0


def test_the_roll_leaves_an_open_account_alone():
    """An Open account's missing month is outstanding work, and a figure written
    into it would hide that (BR-04)."""
    account = make_account()
    Balance.objects.create(account=account, month="2026-05", amount=Decimal("1000"))

    assert roll_dormant_balances(month_of(date.today())) == ()
    assert account.balances.count() == 1


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
# The month in progress is valued at today
# ---------------------------------------------------------------------------


def test_the_month_in_progress_is_translated_at_today_not_at_its_month_end():
    """A rate entered this morning is exact this morning, not carried and stale.

    Valuing the running month at a month-end that has not arrived would date
    every quote forward by the days left in it, so the headline would carry a
    staleness warning counting time that has not passed. Asserted as an
    invariant against today rather than a fixed date, so it keeps meaning
    something on every day this suite is run.
    """
    from core.months import month_of

    today = date.today()
    current = month_of(today)

    aud = make_account(name="CommBank", currency="AUD")
    Balance.objects.create(account=aud, month=current, amount=Decimal("5000"))
    ExchangeRate.objects.create(currency="AUD", rate_date=today, rate=Decimal("0.66"))

    result = NetWorthService(staleness_days=7).for_month(current, "USD")

    assert result.any_stale is False
    assert result.oldest_as_at == today
    assert result.contributions[0].quote.provenance == "exact"


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


def test_a_stale_carried_rate_does_not_make_a_month_complete():
    """Beyond the staleness threshold, a carry is not fit to close a month on.

    31 days back, against a threshold of 7. Reports still translate on it and
    say so; the month stays Incomplete and names the currency.
    """
    aud = make_account(name="CommBank", currency="AUD")
    Balance.objects.create(account=aud, month="2026-07", amount=Decimal("1"))
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 6, 30), rate=Decimal("0.66")
    )

    completeness = NetWorthService(staleness_days=7).completeness_for("2026-07")

    assert str(completeness.state) == "Incomplete"
    assert completeness.outstanding_currencies == ("AUD",)


def test_a_fresh_carried_rate_completes_a_month_that_has_ended():
    """The weekend month-end case, which has no close to enter.

    31 May 2026 was a Sunday. The market was shut and the provider published
    nothing, so under a rule requiring the as-at date itself the month could
    never be closed however diligent the user. Friday's rate is two days old
    against a threshold of seven, and closes it.
    """
    aud = make_account(name="CommBank", currency="AUD", opened="2026-05")
    Balance.objects.create(account=aud, month="2026-05", amount=Decimal("1"))
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 5, 29), rate=Decimal("0.66")
    )

    completeness = NetWorthService(staleness_days=7).completeness_for(
        "2026-05", today=date(2026, 8, 23)
    )

    assert str(completeness.state) == "Complete"
    assert completeness.outstanding_currencies == ()


def test_a_fresh_carry_is_not_written_into_the_rate_table():
    """Complete is reached without fabricating a rate, so provenance survives.

    The point of deciding this in completeness rather than materialising the
    carry into `fx`: a row stored on the as-at date would read as `exact` and
    the report would stop disclosing what it was translated on.
    """
    aud = make_account(name="CommBank", currency="AUD", opened="2026-05")
    Balance.objects.create(account=aud, month="2026-05", amount=Decimal("1"))
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 5, 29), rate=Decimal("0.66")
    )

    service = NetWorthService(staleness_days=7)
    assert str(service.completeness_for("2026-05", today=date(2026, 8, 23)).state) == "Complete"

    assert not ExchangeRate.objects.filter(rate_date=date(2026, 5, 31)).exists()
    leg = service.resolver.leg("AUD", date(2026, 5, 31))
    assert str(leg.provenance) == "carried"
    assert leg.as_at == date(2026, 5, 29)


def test_a_rate_exactly_at_the_staleness_threshold_still_completes():
    """The boundary belongs to `is_stale`, which breaches strictly greater."""
    aud = make_account(name="CommBank", currency="AUD", opened="2026-05")
    Balance.objects.create(account=aud, month="2026-05", amount=Decimal("1"))
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 5, 24), rate=Decimal("0.66")
    )

    completeness = NetWorthService(staleness_days=7).completeness_for(
        "2026-05", today=date(2026, 8, 23)
    )

    assert str(completeness.state) == "Complete"


def test_the_month_in_progress_still_requires_its_as_at_rate():
    """A running month must not read Complete on a rate from days ago.

    Its as-at date is today and moves daily, so the figures it would be closing
    on are not the ones it will finally close on.
    """
    aud = make_account(name="CommBank", currency="AUD", opened="2026-08")
    Balance.objects.create(account=aud, month="2026-08", amount=Decimal("1"))
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 8, 21), rate=Decimal("0.66")
    )

    service = NetWorthService(staleness_days=7)
    today = date(2026, 8, 23)

    running = service.completeness_for("2026-08", today=today)
    assert str(running.state) == "Incomplete"
    assert running.outstanding_currencies == ("AUD",)

    # The balances are in; only the as-at rate is not. That distinction is what
    # `all_balances_recorded` exists to state while a month runs.
    assert running.all_balances_recorded

    # Entered on the day it is asked about, it completes.
    ExchangeRate.objects.create(
        currency="AUD", rate_date=today, rate=Decimal("0.66")
    )
    assert str(service.completeness_for("2026-08", today=today).state) == "Complete"
