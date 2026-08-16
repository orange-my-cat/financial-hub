"""AS-03 — the hand-worked three-currency net worth scenario.

This is the actual control on correctness. Coverage measures lines executed, not
arithmetic proven, and the risk here is not a coding error: it is the code
faithfully implementing a misunderstanding, which no amount of self-consistent
testing detects. Only a human checking a worked example against their own
arithmetic catches that (ADR-17).

So the figures below are worked out longhand first, in the comments, and the
code is asserted against them — not the other way round.

===========================================================================
THE SCENARIO — net worth for July 2026, reported in USD
===========================================================================

Rates. AUD is quoted USD per 1 AUD; MYR is quoted MYR per 1 USD.

    30 Jun 2026    USD/MYR   4.2000            (entered)
    31 Jul 2026    AUD/USD   0.6600            (entered)

    There is NO MYR rate for 31 Jul, so it CARRIES FORWARD from 30 Jun —
    31 days old. That is the carried rate the scenario is built around.

Accounts and their 31 Jul 2026 balances, as entered:

  #  Account            Type              Cur    Entered        A/L
  1  Everyday           Current/Checking  USD     12,500.00     asset
  2  CommBank Saver     Savings/Deposit   AUD     40,000.00     asset
  3  Maybank Current    Current/Checking  MYR    100,000.00     asset
  4  Amex               Credit Card       USD      3,250.00     LIABILITY
  5  Home loan          Loan/Mortgage     AUD    250,000.00     LIABILITY

Working, in USD, at full precision:

  1  Everyday        +12,500.00  x 1                 =  +12,500.0000
  2  CommBank        +40,000.00  x 0.66              =  +26,400.0000
  3  Maybank        +100,000.00  / 4.20              =  +23,809.5238095238...
  4  Amex        (-)  -3,250.00  x 1                 =   -3,250.0000
  5  Home loan   (-)-250,000.00  x 0.66              = -165,000.0000

  Sum, full precision:
      12,500
    + 26,400                    =  38,900
    + 23,809.523809523809...    =  62,709.523809523809...
    -  3,250                    =  59,459.523809523809...
    - 165,000                   = -105,540.476190476190...

  NET WORTH = -105,540.476190476190...  →  rounded once, half-up: -105,540.48

Two things this pins down that a simpler scenario would not:

  * The MYR figure is non-terminating (100,000 / 4.2 = 23,809.5238095...).
    Rounding it to 23,809.52 before summing gives -105,540.48 as well — but
    rounding the AUD legs early would not always agree, and the discipline is
    what is being tested, not the coincidence.
  * Net worth is NEGATIVE. A mortgage larger than the assets is entirely
    ordinary, and a sign error anywhere would be obvious against this figure.

The as-at date shown is the OLDEST contributing: 30 Jun 2026, from the carried
MYR rate — not 31 Jul, even though two of the three currencies are current.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from accounts.models import Account, AccountType, Balance, LiquidityTier
from accounts.services.net_worth import NetWorthService
from accounts.services.slices import SliceDimension, gross_assets, slice_net_worth
from fx.models import ExchangeRate

pytestmark = [pytest.mark.django_db, pytest.mark.invariant]

MONTH = "2026-07"

#: Worked by hand above. If this number changes, either the arithmetic changed
#: or something is wrong; there is no third possibility.
EXPECTED_NET_WORTH = Decimal("-105540.48")

#: The same five lines, summed the way the working above does. Written as an
#: expression rather than a literal on purpose: the exact value is
#: -105540.4761904761904761904762, which is Decimal's 28-significant-digit
#: rounding of a non-terminating quotient — a figure nobody can transcribe
#: reliably, and one where a typo would look like a real defect.
EXPECTED_FULL_PRECISION = (
    Decimal("12500")
    + Decimal("26400")
    + Decimal("100000") / Decimal("4.20")
    - Decimal("3250")
    - Decimal("165000")
)


@pytest.fixture
def scenario(db):
    ExchangeRate.objects.create(
        currency="MYR", rate_date=date(2026, 6, 30), rate=Decimal("4.2000")
    )
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 7, 31), rate=Decimal("0.6600")
    )

    rows = [
        ("Everyday", AccountType.CURRENT, LiquidityTier.INSTANT, "USD", "12500.00"),
        ("CommBank Saver", AccountType.SAVINGS, LiquidityTier.SHORT, "AUD", "40000.00"),
        ("Maybank Current", AccountType.CURRENT, LiquidityTier.INSTANT, "MYR", "100000.00"),
        ("Amex", AccountType.CREDIT_CARD, LiquidityTier.INSTANT, "USD", "3250.00"),
        ("Home loan", AccountType.LOAN, LiquidityTier.LOCKED, "AUD", "250000.00"),
    ]

    for name, account_type, tier, currency, amount in rows:
        account = Account.objects.create(
            name=name,
            account_type=account_type,
            liquidity_tier=tier,
            currency=currency,
            opened_month="2026-01",
        )
        Balance.objects.create(account=account, month=MONTH, amount=Decimal(amount))


def test_the_hand_worked_figure(scenario):
    """The one assertion this whole file exists for."""
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")

    assert result.total.rounded() == EXPECTED_NET_WORTH


def test_full_precision_is_carried_and_rounded_exactly_once(scenario):
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")

    assert result.total.amount == EXPECTED_FULL_PRECISION
    assert result.total.amount != EXPECTED_NET_WORTH


def test_each_contribution_matches_the_worked_line(scenario):
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    by_name = {c.name: c for c in result.contributions}

    assert by_name["Everyday"].translated == Decimal("12500.00")
    assert by_name["CommBank Saver"].translated == Decimal("26400.0000")
    assert by_name["Maybank Current"].translated == Decimal("100000.00") / Decimal("4.20")
    # Liabilities entered positive, subtracted by the system (BR-06).
    assert by_name["Amex"].entered.amount == Decimal("3250.00")
    assert by_name["Amex"].translated == Decimal("-3250.00")
    assert by_name["Home loan"].entered.amount == Decimal("250000.00")
    assert by_name["Home loan"].translated == Decimal("-165000.0000")


def test_the_headline_as_at_date_is_the_oldest_contributing_rate(scenario):
    """30 Jun, from the carried MYR rate — not 31 Jul (ADR-09)."""
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")

    assert result.oldest_as_at == date(2026, 6, 30)
    assert result.any_stale is True


def test_the_per_currency_detail_names_the_carried_rate(scenario):
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    provenance = {row["currency"]: row for row in result.rate_provenance()}

    assert provenance["AUD"]["provenance"] == "exact"
    assert provenance["AUD"]["stale"] is False
    assert provenance["MYR"]["provenance"] == "carried"
    assert provenance["MYR"]["as_at"] == "2026-06-30"
    assert provenance["MYR"]["stale"] is True
    # USD contributes no rate at all — the base against itself is never entered.
    assert "USD" not in provenance


def test_nothing_is_stale_when_every_rate_is_current(scenario):
    """Silence is the signal (design state S3)."""
    ExchangeRate.objects.create(
        currency="MYR", rate_date=date(2026, 7, 31), rate=Decimal("4.2000")
    )

    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")

    assert result.any_stale is False
    assert result.total.rounded() == EXPECTED_NET_WORTH


def test_every_slice_totals_to_the_same_figure(scenario):
    """By construction, and checked anyway — construction arguments have been
    wrong before."""
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")

    for dimension in SliceDimension:
        rows = slice_net_worth(result, dimension)
        assert sum(row.amount for row in rows) == result.total.amount, dimension


def test_the_by_type_slice_labels_liabilities(scenario):
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    rows = {row.key: row for row in slice_net_worth(result, SliceDimension.TYPE)}

    assert rows["Credit Card"].is_liability is True
    assert rows["Loan/Mortgage"].is_liability is True
    assert rows["Savings/Deposit"].is_liability is False
    assert rows["Credit Card"].amount == Decimal("-3250.00")


def test_the_by_currency_slice(scenario):
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    rows = {row.key: row for row in slice_net_worth(result, SliceDimension.CURRENCY)}

    # USD: 12,500 - 3,250 = 9,250
    assert rows["USD"].amount == Decimal("9250.00")
    # AUD: 26,400 - 165,000 = -138,600
    assert rows["AUD"].amount == Decimal("-138600.0000")
    assert rows["MYR"].amount == Decimal("100000.00") / Decimal("4.20")


#: The three asset legs only: 12,500 + 26,400 + 23,809.5238...
#: The two debts are what the column measures, so they are not in it.
EXPECTED_GROSS_ASSETS = Decimal("62709.52")


def test_gross_assets_are_what_is_owned_before_anything_owed(scenario):
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")

    assert gross_assets(result).quantize(Decimal("0.01")) == EXPECTED_GROSS_ASSETS


def test_the_asset_rows_compose_to_the_whole_of_what_is_owned(scenario):
    """Assets make 100% of assets — the composition the column exists for.

    Within the tenth each row is rounded to: the amounts sum exactly because
    they are full precision, the shares are rounded for display first, and
    asserting exactness here would be asserting that rounding does not round.
    """
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    rows = {row.key: row for row in slice_net_worth(result, SliceDimension.TYPE)}

    # Both current accounts, two currencies: (12,500 + 23,809.52) / 62,709.52.
    assert rows["Current/Checking"].percent_of_gross == Decimal("57.9")
    assert rows["Savings/Deposit"].percent_of_gross == Decimal("42.1")

    owned = sum(
        row.percent_of_gross for row in rows.values() if not row.is_liability
    )
    assert abs(owned - 100) <= Decimal("0.5")


def test_a_debt_is_read_against_what_stands_behind_it_and_may_exceed_it(scenario):
    """-263.1%, and that figure is the point rather than a defect.

    The mortgage is 165,000 against 62,709.52 of assets. Stated as a share of
    net worth it would be -156% of a household worth less than nothing; stated
    against what is owned it says plainly that the debt is two and a half times
    everything behind it.
    """
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    rows = {row.key: row for row in slice_net_worth(result, SliceDimension.TYPE)}

    assert rows["Loan/Mortgage"].percent_of_gross == Decimal("-263.1")
    assert rows["Credit Card"].percent_of_gross == Decimal("-5.2")


def test_a_row_holding_both_sides_states_the_net_of_them(scenario):
    """The USD row holds a current account and a credit card; AUD a saver and a
    mortgage. Each states what that currency is worth on balance."""
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    rows = {row.key: row for row in slice_net_worth(result, SliceDimension.CURRENCY)}

    # 9,250 / 62,709.52; -138,600 / 62,709.52; 23,809.52 / 62,709.52.
    assert rows["USD"].percent_of_gross == Decimal("14.8")
    assert rows["AUD"].percent_of_gross == Decimal("-221.0")
    assert rows["MYR"].percent_of_gross == Decimal("38.0")


def test_a_balance_sheet_of_nothing_leaves_the_share_absent_rather_than_zero(scenario):
    """A proportion of nothing is not a figure — the amount beside it is."""
    result = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    flat = replace(
        result,
        contributions=tuple(
            replace(c, translated=Decimal(0)) for c in result.contributions
        ),
    )

    rows = slice_net_worth(flat, SliceDimension.CURRENCY)

    assert rows
    assert all(row.percent_of_gross is None for row in rows)


def test_reporting_in_aud_gives_a_consistent_answer(scenario):
    """Changing the reporting currency changes display only (BR-10).

    Net worth in AUD is the USD figure divided by 0.66 — checked here because
    the by-currency route through triangulation is the one that would drift if
    a reciprocal were taken twice.
    """
    in_usd = NetWorthService(staleness_days=7).for_month(MONTH, "USD")
    in_aud = NetWorthService(staleness_days=7).for_month(MONTH, "AUD")

    assert in_aud.total.rounded() == (
        in_usd.total.amount / Decimal("0.66")
    ).quantize(Decimal("0.01"))
