"""Completeness — four states, and ADR-04's later-of rule.

The rule that earns the most from being tested is the second half of ADR-04: an
account is required only from the *later* of its opening date and the first month
a balance was actually recorded. Without it, back-filling a lossy spreadsheet
would indict every month since the account was opened.
"""

from __future__ import annotations

import pytest

from core.services.completeness import (
    AccountHistory,
    CompletenessState,
    month_completeness,
    recorded_from,
    required_currencies,
)

pytestmark = pytest.mark.invariant


def account(
    account_id=1,
    name="Savings",
    currency="USD",
    opened="2024-01",
    first_recorded="2024-01",
    closed=None,
) -> AccountHistory:
    return AccountHistory(
        account_id=account_id,
        name=name,
        currency=currency,
        opened_month=opened,
        first_recorded_month=first_recorded,
        closed_month=closed,
    )


# ---------------------------------------------------------------------------
# ADR-04 — required from the later of opening and first recorded balance
# ---------------------------------------------------------------------------


def test_an_account_is_required_from_its_first_recorded_month_not_its_opening():
    """Opened in 2012, first recorded in 2019 — 2015 is not a failure."""
    a = account(opened="2012-03", first_recorded="2019-01")

    assert a.required_from == "2019-01"
    assert a.is_required_for("2015-06") is False
    assert a.is_required_for("2019-01") is True
    assert a.is_required_for("2020-01") is True


def test_an_account_is_required_from_its_opening_when_that_is_the_later_date():
    """A balance back-dated before the account existed does not pull it earlier."""
    a = account(opened="2020-06", first_recorded="2019-01")

    assert a.required_from == "2020-06"
    assert a.is_required_for("2019-06") is False
    assert a.is_required_for("2020-06") is True


def test_an_account_with_no_recorded_balance_is_required_for_no_month():
    a = account(first_recorded=None)

    assert a.required_from is None
    assert a.is_required_for("2024-01") is False
    assert a.is_required_for("2030-01") is False


def test_a_closed_account_stops_being_required_after_its_closing_month():
    a = account(opened="2024-01", first_recorded="2024-01", closed="2024-06")

    assert a.is_required_for("2024-06") is True
    assert a.is_required_for("2024-07") is False


# ---------------------------------------------------------------------------
# The four states
# ---------------------------------------------------------------------------


def test_outside_range_when_nothing_was_ever_required():
    result = month_completeness("2020-01", [account(first_recorded="2024-01")])

    assert result.state is CompletenessState.OUTSIDE_RANGE
    assert result.balances_expected == 0


def test_outside_range_when_there_are_no_accounts_at_all():
    """First run. The spine shows this, and it is not a fault."""
    assert month_completeness("2026-08", []).state is CompletenessState.OUTSIDE_RANGE


def test_missing_when_the_month_is_in_range_and_nothing_is_entered():
    result = month_completeness("2024-05", [account()])

    assert result.state is CompletenessState.MISSING
    assert result.balances_expected == 1
    assert result.balances_recorded == 0
    assert result.outstanding_accounts == ("Savings",)


def test_complete_when_every_balance_and_rate_is_present():
    accounts = [
        account(account_id=1, name="Savings", currency="USD"),
        account(account_id=2, name="CommBank", currency="AUD"),
    ]

    result = month_completeness(
        "2024-05", accounts, balances_recorded_for=[1, 2], rates_recorded_for=["AUD"]
    )

    assert result.state is CompletenessState.COMPLETE
    assert result.is_complete
    assert result.outstanding_accounts == ()
    assert result.outstanding_currencies == ()


def test_incomplete_when_some_are_entered_and_some_absent():
    accounts = [
        account(account_id=1, name="Savings"),
        account(account_id=2, name="CommBank", currency="AUD"),
    ]

    result = month_completeness("2024-05", accounts, balances_recorded_for=[1])

    assert result.state is CompletenessState.INCOMPLETE
    assert result.balances_recorded == 1
    assert result.balances_expected == 2
    assert result.outstanding_accounts == ("CommBank",)
    assert result.outstanding_currencies == ("AUD",)


def test_a_month_is_incomplete_when_only_a_rate_is_outstanding():
    """Twenty balances typed and one rate forgotten is not Complete."""
    accounts = [account(account_id=1, currency="AUD")]

    result = month_completeness("2024-05", accounts, balances_recorded_for=[1])

    assert result.state is CompletenessState.INCOMPLETE
    assert result.rates_expected == 1
    assert result.rates_recorded == 0


def test_a_month_with_only_rates_entered_is_incomplete_not_missing():
    accounts = [account(account_id=1, currency="AUD")]

    result = month_completeness("2024-05", accounts, rates_recorded_for=["AUD"])

    assert result.state is CompletenessState.INCOMPLETE


# ---------------------------------------------------------------------------
# Required currencies
# ---------------------------------------------------------------------------


def test_the_base_currency_never_requires_a_rate():
    accounts = [account(currency="USD")]

    assert required_currencies(accounts, "2024-05") == ()


def test_each_foreign_currency_requires_one_rate_however_many_accounts_hold_it():
    accounts = [
        account(account_id=1, currency="AUD"),
        account(account_id=2, currency="AUD"),
        account(account_id=3, currency="MYR"),
    ]

    assert required_currencies(accounts, "2024-05") == ("AUD", "MYR")


def test_a_currency_is_not_required_before_its_account_is():
    accounts = [account(currency="AUD", first_recorded="2025-01")]

    assert required_currencies(accounts, "2024-05") == ()
    assert required_currencies(accounts, "2025-01") == ("AUD",)


# ---------------------------------------------------------------------------
# Where the spine starts
# ---------------------------------------------------------------------------


def test_recorded_from_is_the_earliest_month_any_account_recorded():
    accounts = [
        account(account_id=1, opened="2020-01", first_recorded="2022-06"),
        account(account_id=2, opened="2019-01", first_recorded="2021-03"),
    ]

    assert recorded_from(accounts) == "2021-03"


def test_recorded_from_is_none_when_nothing_has_been_recorded():
    assert recorded_from([]) is None
    assert recorded_from([account(first_recorded=None)]) is None


def test_a_malformed_month_is_refused():
    with pytest.raises(ValueError, match="not a reporting month"):
        month_completeness("2026-13", [])
