"""Dashboard, tasks, backup status and CSV export."""

from __future__ import annotations

import os
import time
from datetime import date
from decimal import Decimal

import pytest
from django.test import override_settings

from accounts.models import Account, AccountType, Balance, LiquidityTier
from cashflow.models import Category, Direction, Frequency, RecurringTemplate
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

    assert isinstance(body["cashflow"], list)
    assert "net_worth" not in str(body["cashflow"])


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
