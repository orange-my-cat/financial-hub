"""The development data seeder.

Tested for the two properties that make it safe to run against a database
someone has been typing real figures into: it writes only where nothing is
recorded, and it refuses to run anywhere but development.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from accounts.models import Account, AccountType, Balance, LiquidityTier
from cashflow.models import Category, Transaction
from core.months import month_of, previous, shift

pytestmark = pytest.mark.django_db


@pytest.fixture
def anchored(db):
    """One account with one real balance, in the last month that has ended.

    Relative to today, so the seeded window is the one a real run would use on
    any day this suite happens to run.
    """
    account = Account.objects.create(
        name="Everyday",
        account_type=AccountType.SAVINGS,
        liquidity_tier=LiquidityTier.INSTANT,
        currency="USD",
        opened_month=previous(month_of(date.today())),
    )
    Balance.objects.create(
        account=account, month=previous(month_of(date.today())), amount=Decimal("10000")
    )
    return account


def _seed(**options) -> str:
    out = StringIO()
    call_command("seed_history", stdout=out, **options)
    return out.getvalue()


def test_it_walks_back_from_the_anchor_and_leaves_it_alone(anchored):
    """The recorded figure is the starting point, and it is not rewritten."""
    last_closed = previous(month_of(date.today()))

    _seed(months=3, seed=1)

    months = list(
        Balance.objects.filter(account=anchored).order_by("month").values_list("month", flat=True)
    )
    assert months == [shift(last_closed, -2), previous(last_closed), last_closed]

    # The anchor is untouched, and the earlier months are figures of their own —
    # not the same number three times.
    balances = dict(
        Balance.objects.filter(account=anchored).values_list("month", "amount")
    )
    assert balances[last_closed] == Decimal("10000.0000")
    assert len(set(balances.values())) == 3


def test_savings_were_smaller_a_year_ago(anchored):
    """The drift is a tendency, not a rule applied to every step: a savings
    account that was dipped into rises going backwards, which is why the jitter
    is allowed to outweigh one month of drift. Over a year it cannot, and the
    seed pins the figures so this asserts a shape rather than a coin toss."""
    last_closed = previous(month_of(date.today()))

    _seed(months=13, seed=1)

    balances = dict(
        Balance.objects.filter(account=anchored).values_list("month", "amount")
    )
    assert balances[shift(last_closed, -12)] < Decimal("8500")
    assert balances[last_closed] == Decimal("10000.0000")


def test_it_moves_the_opening_month_back_so_the_history_is_admissible(anchored):
    """A balance cannot precede the opening month, so the seed widens it."""
    _seed(months=4, seed=1)

    anchored.refresh_from_db()
    assert anchored.opened_month == shift(previous(month_of(date.today())), -3)


def test_a_month_holding_a_transaction_is_left_entirely_alone(anchored):
    """One real transaction means someone started that month by hand. Adding
    forty invented ones to it would make the real one unfindable."""
    last_closed = previous(month_of(date.today()))
    groceries = Category.objects.get(name="Groceries", parent__isnull=False)
    Transaction.objects.create(
        date=date(int(last_closed[:4]), int(last_closed[5:]), 2),
        amount=Decimal("40"),
        currency="USD",
        direction=groceries.direction,
        category=groceries,
    )

    report = _seed(months=2, seed=1)

    assert Transaction.objects.filter(date__year=int(last_closed[:4]), date__month=int(last_closed[5:])).count() == 1
    assert f"left alone" in report and last_closed in report
    # The month before it, which held nothing, is seeded.
    assert Transaction.objects.count() > 1


def test_running_it_twice_writes_nothing_the_second_time(anchored):
    _seed(months=6, seed=1)
    balances, transactions = Balance.objects.count(), Transaction.objects.count()

    _seed(months=6, seed=1)

    assert Balance.objects.count() == balances
    assert Transaction.objects.count() == transactions


def test_the_same_seed_gives_the_same_figures(anchored):
    _seed(months=6, seed=99)
    first = list(Balance.objects.order_by("month").values_list("month", "amount"))

    Balance.objects.filter(month__lt=previous(month_of(date.today()))).delete()
    _seed(months=6, seed=99)

    assert list(Balance.objects.order_by("month").values_list("month", "amount")) == first


def test_a_dry_run_writes_nothing(anchored):
    report = _seed(months=6, seed=1, dry_run=True)

    assert "Nothing was saved" in report
    assert Balance.objects.count() == 1
    assert Transaction.objects.count() == 0


def test_it_refuses_a_database_that_is_not_development(anchored):
    """P-04. `manage.py` can be pointed at production with one variable, and this
    command writes fabricated financial figures."""
    with patch.dict(connection.settings_dict, {"NAME": "financial_hub", "PORT": "5432"}):
        with pytest.raises(CommandError) as refusal:
            _seed(months=2, seed=1)

    assert "financial_hub" in str(refusal.value)
    assert Balance.objects.count() == 1


def test_it_says_so_rather_than_inventing_a_rate(db):
    """A missing rate excludes and states the omission (FR-46). The seeder holds
    the same line: it names the uncovered months and prints the command that
    fills them from the provider."""
    account = Account.objects.create(
        name="CommBank",
        account_type=AccountType.SAVINGS,
        liquidity_tier=LiquidityTier.SHORT,
        currency="AUD",
        opened_month=previous(month_of(date.today())),
    )
    Balance.objects.create(
        account=account, month=previous(month_of(date.today())), amount=Decimal("500")
    )

    report = _seed(months=3, seed=1, dry_run=True)

    assert "No month-end rate" in report
    assert "load_rates" in report


def test_an_account_with_no_balance_is_reported_not_guessed_at(anchored):
    """Nothing to anchor on is nothing to walk back from."""
    Account.objects.create(
        name="Brand New",
        account_type=AccountType.CURRENT,
        liquidity_tier=LiquidityTier.INSTANT,
        currency="USD",
        opened_month=month_of(date.today()),
    )

    report = _seed(months=3, seed=1, dry_run=True)

    assert "no anchor" in report and "Brand New" in report
