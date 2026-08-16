"""Dashboard, tasks, backup status and CSV export."""

from __future__ import annotations

import os
import time
from datetime import date
from decimal import Decimal

import pytest
from django.test import override_settings

from accounts.models import Account, AccountType, Balance, LiquidityTier
from cashflow.models import (
    Category,
    Direction,
    Frequency,
    RecurringTemplate,
    Transaction,
)
from cashflow.services.summary import (
    monthly_summary,
    summary_trend,
    summary_with_change,
)
from core.services.backup_status import backup_status
from core.services.export import investments_csv, net_worth_csv
from core.services.tasks import outstanding_tasks
from fx.models import ExchangeRate
from investments.models import Holding
from investments.services.positions import record

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in(client, django_user_model):
    user = django_user_model.objects.create_user(username="owner", password="pw-long-enough")
    client.force_login(user)
    return client


@pytest.fixture
def portfolio(db):
    usd = Account.objects.create(
        name="Everyday", account_type=AccountType.CURRENT,
        liquidity_tier=LiquidityTier.INSTANT, currency="USD", opened_month="2026-01",
    )
    aud = Account.objects.create(
        name="CommBank", account_type=AccountType.SAVINGS,
        liquidity_tier=LiquidityTier.SHORT, currency="AUD", opened_month="2026-01",
    )
    Balance.objects.create(account=usd, month="2026-07", amount=Decimal("10000"))
    Balance.objects.create(account=aud, month="2026-07", amount=Decimal("50000"))
    ExchangeRate.objects.create(currency="AUD", rate_date=date(2026, 7, 31), rate=Decimal("0.66"))
    return {"usd": usd, "aud": aud}


# ---------------------------------------------------------------------------
# Backup status — the control that closes RISK-02 in fact
# ---------------------------------------------------------------------------


def test_backup_status_says_so_when_nothing_is_configured():
    status = backup_status()

    assert status.configured is False
    assert status.state == "Not configured"
    # Not a false green.
    assert status.is_healthy is False


def test_backup_status_reports_no_backup_found(tmp_path):
    with override_settings(BACKUP_DIR=str(tmp_path)):
        status = backup_status()

    assert status.state == "No backup found"
    assert status.is_healthy is False


def test_a_backup_newer_than_the_data_is_healthy(tmp_path, portfolio):
    dump = tmp_path / "financial_hub-20260801T000000Z.dump"
    dump.write_bytes(b"x" * 1024)
    future = time.time() + 3600
    os.utime(dump, (future, future))

    with override_settings(BACKUP_DIR=str(tmp_path)):
        status = backup_status()

    assert status.is_stale is False
    assert status.state == "Current"
    assert status.is_healthy is True
    assert status.count == 1


def test_a_backup_older_than_the_data_warns(tmp_path, portfolio):
    """A silent backup failure is otherwise indistinguishable from success."""
    dump = tmp_path / "financial_hub-20200101T000000Z.dump"
    dump.write_bytes(b"x")
    old = time.time() - (365 * 24 * 3600)
    os.utime(dump, (old, old))

    with override_settings(BACKUP_DIR=str(tmp_path)):
        status = backup_status()

    assert status.is_stale is True
    assert status.state == "Data changed since last backup"
    assert status.is_healthy is False


# ---------------------------------------------------------------------------
# Outstanding tasks — the product's conscience
# ---------------------------------------------------------------------------


def test_a_complete_month_raises_no_tasks(portfolio):
    """Silence is the signal (design state S3)."""
    assert outstanding_tasks("2026-07") == []


def test_a_missing_balance_raises_a_task(portfolio):
    Balance.objects.filter(account=portfolio["usd"], month="2026-07").delete()
    Balance.objects.create(account=portfolio["usd"], month="2026-06", amount=Decimal("9000"))

    tasks = {task.kind: task for task in outstanding_tasks("2026-07")}

    assert tasks["balances"].count == 1
    assert "understating" in tasks["balances"].message
    assert tasks["balances"].route == "/month-close"


def test_the_month_before_is_checked_too(portfolio):
    """A close that never finished is invisible until someone hunts the spine.

    The USD account records May, so June is required of it (ADR-04: an account
    is required from the later of opening and its first recorded balance) — and
    June is exactly the month it never got. The AUD account closes June
    normally, and July is complete, so June's hole is the only task raised.
    """
    Balance.objects.create(account=portfolio["usd"], month="2026-05", amount=Decimal("1"))
    Balance.objects.create(account=portfolio["aud"], month="2026-06", amount=Decimal("1"))
    ExchangeRate.objects.create(
        currency="AUD", rate_date=date(2026, 6, 30), rate=Decimal("0.66")
    )

    tasks = {task.kind: task for task in outstanding_tasks("2026-07")}

    assert "balances" not in tasks
    assert tasks["balances_previous"].count == 1
    # The month is named, so two rows asking for balances are never confused.
    assert "2026-06" in tasks["balances_previous"].message
    assert "never closed" in tasks["balances_previous"].message
    assert tasks["balances_previous"].route == "/month-close"


def test_a_month_that_required_nothing_stays_silent(portfolio):
    """June predates every first balance, so it is Outside Range, not a fault.

    The fixture records balances for July only, which is the shape of a new
    install — and a conscience panel that opens by apologising for the month
    before the data starts is a panel that gets ignored.
    """
    assert outstanding_tasks("2026-07") == []


def test_a_missing_rate_is_a_breach_because_the_account_is_excluded(portfolio):
    ExchangeRate.objects.all().delete()

    tasks = {task.kind: task for task in outstanding_tasks("2026-07")}

    assert tasks["rates_missing"].is_breach is True
    assert "never counted as zero" in tasks["rates_missing"].message


def test_a_stale_rate_is_a_task_but_not_a_breach(portfolio):
    ExchangeRate.objects.all().delete()
    ExchangeRate.objects.create(currency="AUD", rate_date=date(2026, 1, 1), rate=Decimal("0.66"))
    ExchangeRate.objects.create(currency="MYR", rate_date=date(2026, 7, 31), rate=Decimal("4.2"))

    tasks = {task.kind: task for task in outstanding_tasks("2026-07")}

    assert tasks["rates_stale"].is_breach is False
    assert "still compute" in tasks["rates_stale"].message


def test_a_rate_entered_today_raises_no_task_in_the_month_still_running(portfolio):
    """Outstanding is judged as at today, never at a month-end still to come.

    Judging the running month at its month-end would age every rate by the days
    left in it — a rate entered this morning reported as a fortnight old, and
    breaching the threshold on time that has not passed. It would also put this
    panel in contradiction with the FX screen, which asks the same question as
    of today. Asserted as an invariant against today, so it keeps meaning
    something on every day this suite is run.
    """
    from core.months import month_of

    today = date.today()
    ExchangeRate.objects.create(currency="AUD", rate_date=today, rate=Decimal("0.66"))

    tasks = {task.kind: task for task in outstanding_tasks(month_of(today))}

    assert "rates_stale" not in tasks
    assert "rates_missing" not in tasks


def test_a_task_for_a_finished_month_still_names_its_month_end(portfolio):
    """Only the month in progress moves. A month that has ended has one date."""
    ExchangeRate.objects.all().delete()

    tasks = {task.kind: task for task in outstanding_tasks("2026-07")}

    assert "2026-07 month-end" in tasks["rates_missing"].message


def test_an_outstanding_recurring_proposal_raises_a_task(portfolio):
    RecurringTemplate.objects.create(
        name="Rent", amount=Decimal("2200"), currency="AUD", direction=Direction.EXPENSE,
        category=Category.objects.get(name="Rent", parent__isnull=False),
        frequency=Frequency.MONTHLY, start_month="2026-07",
    )

    tasks = {task.kind: task for task in outstanding_tasks("2026-07")}

    assert tasks["recurring"].count == 1
    assert "Nothing is posted until confirmed" in tasks["recurring"].message


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_the_dashboard_carries_everything_that_qualifies_its_total(signed_in, portfolio):
    body = signed_in.get("/api/dashboard/?month=2026-07&currency=USD").json()["data"]

    assert body["net_worth"]["total"]["amount"] == "43000.00"
    assert body["completeness"]["state"] == "Complete"
    assert body["exclusions"] == []
    assert body["rate_provenance"][0]["currency"] == "AUD"
    assert body["backup"]["state"] == "Not configured"


def test_the_dashboard_is_silent_about_rates_when_nothing_is_stale(signed_in, portfolio):
    body = signed_in.get("/api/dashboard/?month=2026-07").json()["data"]

    assert body["net_worth"]["any_stale"] is False
    assert body["net_worth"]["as_at"] is None
    assert body["tasks"] == []


def test_the_dashboard_trend_is_twenty_four_months(signed_in, portfolio):
    body = signed_in.get("/api/dashboard/?month=2026-07").json()["data"]

    assert len(body["trend"]) == 24
    assert body["trend"][-1]["month"] == "2026-07"
    # Months before any balance existed carry no figure.
    assert body["trend"][0]["total"] is None


def test_the_dashboard_never_adds_cashflow_to_net_worth(signed_in, portfolio):
    """BR-12 — they are separate keys and there is no combined figure."""
    body = signed_in.get("/api/dashboard/?month=2026-07").json()["data"]

    assert isinstance(body["cashflow"], dict)
    assert "net_worth" not in str(body["cashflow"])


# ---------------------------------------------------------------------------
# The dashboard's cash flow summary — the reporting currency, not a breakdown
# ---------------------------------------------------------------------------


@pytest.fixture
def spending(db):
    """Income and expense in two currencies, one of which needs a rate."""
    income = Category.objects.create(name="Salary", direction=Direction.INCOME)
    expense = Category.objects.create(name="Groceries", direction=Direction.EXPENSE)

    Transaction.objects.create(
        date=date(2026, 7, 10), amount=Decimal("8000"), currency="USD",
        direction=Direction.INCOME, category=income,
    )
    Transaction.objects.create(
        date=date(2026, 7, 12), amount=Decimal("2000"), currency="USD",
        direction=Direction.EXPENSE, category=expense,
    )
    Transaction.objects.create(
        date=date(2026, 7, 20), amount=Decimal("1000"), currency="AUD",
        direction=Direction.EXPENSE, category=expense,
    )
    return {"income": income, "expense": expense}


def test_the_summary_states_one_figure_per_line_in_the_reporting_currency(
    signed_in, portfolio, spending
):
    """AUD 1,000 at 0.66 is USD 660, added to the USD 2,000 already spent."""
    flow = signed_in.get("/api/dashboard/?month=2026-07&currency=USD").json()["data"][
        "cashflow"
    ]

    assert flow["income"] == {"amount": "8000.00", "currency": "USD"}
    assert flow["expense"] == {"amount": "2660.00", "currency": "USD"}
    assert flow["net"] == {"amount": "5340.00", "currency": "USD"}
    # There is no per-currency breakdown on this screen any more.
    assert "currencies" not in flow


def test_the_summary_obeys_the_reporting_currency(signed_in, portfolio, spending):
    flow = signed_in.get("/api/dashboard/?month=2026-07&currency=AUD").json()["data"][
        "cashflow"
    ]

    assert flow["currency"] == "AUD"
    assert flow["net"]["currency"] == "AUD"


def test_the_savings_rate_is_net_over_income(portfolio, spending):
    summary = monthly_summary("2026-07", "USD")

    # 5340 / 8000.
    assert summary.savings_rate == Decimal("66.8")


def test_a_month_with_no_income_has_no_savings_rate(portfolio, spending):
    """No denominator is not a rate of zero."""
    Transaction.objects.filter(direction=Direction.INCOME).delete()

    summary = monthly_summary("2026-07", "USD")

    assert summary.savings_rate is None
    assert summary.net.amount < 0


def test_a_currency_with_no_rate_is_excluded_and_never_zeroed(portfolio, spending):
    """FR-46, applied to a whole currency rather than one account."""
    ExchangeRate.objects.filter(currency="AUD").delete()

    summary = monthly_summary("2026-07", "USD")

    # The AUD 1,000 of spending is withheld, not counted as nothing.
    assert summary.expense.amount == Decimal("2000")
    assert [row["currency"] for row in summary.exclusion_notices()] == ["AUD"]
    assert "AUD" in summary.exclusion_notices()[0]["reason"]


def test_a_month_with_no_transactions_is_not_a_month_that_broke_even(portfolio):
    summary = monthly_summary("2026-07", "USD")

    assert summary.has_activity is False
    assert summary.as_dict()["net"] is None


def test_each_figure_carries_its_movement_on_the_month_before(portfolio, spending):
    """June earned 4,000 and spent 1,000; July earned 8,000 and spent 2,660."""
    Transaction.objects.create(
        date=date(2026, 6, 10), amount=Decimal("4000"), currency="USD",
        direction=Direction.INCOME, category=spending["income"],
    )
    Transaction.objects.create(
        date=date(2026, 6, 12), amount=Decimal("1000"), currency="USD",
        direction=Direction.EXPENSE, category=spending["expense"],
    )

    body = summary_with_change("2026-07", "USD")

    assert body["previous_month"] == "2026-06"
    assert body["change"]["income"] == {"change": "4000.00", "change_percent": "100.0"}
    assert body["change"]["expense"] == {"change": "1660.00", "change_percent": "166.0"}
    # 5340 - 3000.
    assert body["change"]["net"]["change"] == "2340.00"
    # 66.8% against 75.0% — points, and never a percentage of a percentage.
    assert body["change"]["savings_rate"] == {"change": "-8.2", "change_percent": None}


def test_a_rise_from_a_month_of_nothing_has_no_proportion(portfolio, spending):
    """The absolute change is real; the percentage has no denominator."""
    body = summary_with_change("2026-07", "USD")

    assert body["change"]["income"]["change"] == "8000.00"
    assert body["change"]["income"]["change_percent"] is None
    # Neither month has both figures, so the rate has no movement at all.
    assert body["change"]["savings_rate"]["change"] is None


def test_the_two_trends_share_one_window(signed_in, portfolio, spending):
    """The dashboard's three plots sit on one x axis, so one month sits at one
    horizontal position in all of them. Two windows would put a bar and a point
    at the same place on screen while meaning two different months."""
    body = signed_in.get("/api/dashboard/?month=2026-07").json()["data"]

    months = [point["month"] for point in body["cashflow_trend"]]

    assert months == [point["month"] for point in body["trend"]]
    assert len(months) == 24
    assert months[-1] == "2026-07"
    assert months[0] == "2024-08"


def test_a_quiet_month_in_the_trend_is_zero_not_a_gap(portfolio, spending):
    """The one place absence and zero coincide — a quiet month spent nothing.

    Unlike the net worth trend, where a month with no balances has no figure at
    all rather than one of zero.
    """
    trend = {point["month"]: point for point in summary_trend(["2026-06", "2026-07"], "USD")}

    assert trend["2026-06"]["income"] == "0.00"
    assert trend["2026-06"]["expense"] == "0.00"
    # But the rate has no denominator, so it stays absent.
    assert trend["2026-06"]["savings_rate"] is None
    assert trend["2026-07"]["savings_rate"] == "66.8"


def test_the_dashboard_requires_a_session(client):
    assert client.get("/api/dashboard/").status_code == 403


# ---------------------------------------------------------------------------
# The spine
# ---------------------------------------------------------------------------


def test_the_spine_runs_from_the_first_recorded_month(signed_in, portfolio):
    body = signed_in.get("/api/spine/?through=2026-09").json()["data"]

    assert [row["month"] for row in body] == ["2026-09", "2026-08", "2026-07"]
    assert body[-1]["state"] == "Complete"


def test_an_empty_system_shows_the_current_month_as_outside_range(signed_in):
    """State S1, first run."""
    body = signed_in.get("/api/spine/?through=2026-09").json()["data"]

    assert body == [{"month": "2026-09", "state": "Outside Range"}]


def test_the_spine_extends_before_the_first_recorded_month(signed_in, portfolio):
    """Earlier months are Outside Range — shown, never invented."""
    body = signed_in.get("/api/spine/?through=2026-09&extend=12").json()["data"]

    assert [row["month"] for row in body][:4] == [
        "2026-09",
        "2026-08",
        "2026-07",
        "2026-06",
    ]
    assert body[-1]["month"] == "2025-07"
    assert {row["state"] for row in body[3:]} == {"Outside Range"}


def test_an_empty_system_extends_from_the_current_month(signed_in):
    body = signed_in.get("/api/spine/?through=2026-09&extend=2").json()["data"]

    assert [row["month"] for row in body] == ["2026-09", "2026-08", "2026-07"]


def test_the_extension_is_capped_and_says_so(signed_in, portfolio):
    payload = signed_in.get("/api/spine/?through=2026-09&extend=600").json()

    assert payload["extendable"] is False
    assert payload["data"][-1]["month"] == "2016-07"
    assert signed_in.get("/api/spine/?through=2026-09").json()["extendable"] is True


def test_a_nonsense_extension_is_ignored_rather_than_failing(signed_in, portfolio):
    body = signed_in.get("/api/spine/?through=2026-09&extend=nope").json()["data"]

    assert [row["month"] for row in body] == ["2026-09", "2026-08", "2026-07"]


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def test_the_net_worth_export_carries_its_qualifications(portfolio):
    csv_body = net_worth_csv("2026-07", "USD")

    assert "Completeness,Complete" in csv_body
    assert "Balances recorded,2 of 2" in csv_body
    assert "Net worth,43000.00,USD" in csv_body


def test_the_export_states_an_exclusion_rather_than_dropping_it(portfolio):
    ExchangeRate.objects.all().delete()

    csv_body = net_worth_csv("2026-07", "USD")

    assert "Excluded,CommBank" in csv_body
    # The account keeps its own-currency figure in the row.
    assert "50000.00" in csv_body


def test_every_net_of_tax_figure_in_the_export_is_labelled_indicative(portfolio):
    holding = Holding.objects.create(
        name="Acme", currency="USD", account=portfolio["usd"],
        estimated_tax_percent=Decimal("20"),
    )
    record(holding, action="Buy", on_date=date(2026, 1, 1), quantity=Decimal("100"), unit_price=Decimal("10"))
    record(holding, action="Sell", on_date=date(2026, 2, 1), quantity=Decimal("100"), unit_price=Decimal("20"))

    csv_body = investments_csv()

    assert "INDICATIVE — a percentage you supplied, not a tax calculation" in csv_body
    assert "Unrealised gain does not exist in this system" in csv_body


def test_export_endpoints_return_a_csv_attachment(signed_in, portfolio):
    response = signed_in.get("/api/export/net-worth/?month=2026-07&currency=USD")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    assert "net-worth-2026-07-USD.csv" in response["Content-Disposition"]


@pytest.mark.parametrize(
    "report", ["net-worth", "net-worth-trend", "cashflow", "investments", "fx"]
)
def test_every_report_exports(signed_in, portfolio, report):
    response = signed_in.get(f"/api/export/{report}/?month=2026-07")

    assert response.status_code == 200
    assert response.content


def test_an_unknown_report_is_a_404(signed_in):
    assert signed_in.get("/api/export/nonsense/").status_code == 404


def test_export_requires_a_session(client):
    assert client.get("/api/export/net-worth/").status_code == 403


def test_no_task_is_raised_for_a_currency_no_account_holds(portfolio):
    """Found by the tests: rate tasks fired for every quoted pair, so MYR
    nagged even though nothing was held in it. A conscience panel that cries
    wolf is one that gets ignored."""
    tasks = outstanding_tasks("2026-07")

    assert [task.kind for task in tasks] == []
    # MYR has no rate on record at all, and correctly says nothing about it.
    assert not ExchangeRate.objects.filter(currency="MYR").exists()


def test_a_task_appears_as_soon_as_an_account_holds_that_currency(portfolio):
    myr = Account.objects.create(
        name="Maybank", account_type=AccountType.CURRENT,
        liquidity_tier=LiquidityTier.INSTANT, currency="MYR", opened_month="2026-01",
    )
    Balance.objects.create(account=myr, month="2026-07", amount=Decimal("100000"))

    tasks = {task.kind: task for task in outstanding_tasks("2026-07")}

    assert "rates_missing" in tasks
    assert "USD/MYR" in tasks["rates_missing"].message
