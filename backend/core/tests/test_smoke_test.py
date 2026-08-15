"""The smoke test command (§11.5).

Four of the six assertions can be exercised now. The fifth — a known net worth
figure computing to the same number — arrives at Stage 2, and is asserted here
to be present and skipped rather than quietly absent.
"""

from __future__ import annotations

import io
import os
import time

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings

pytestmark = pytest.mark.django_db


def _run(**options) -> str:
    out = io.StringIO()
    call_command("smoke_test", stdout=out, stderr=out, skip_http=True, **options)
    return out.getvalue()


def test_it_passes_against_a_healthy_test_database():
    output = _run()

    assert "FAIL" not in output
    assert "All checks passed." in output


def test_it_reports_the_database_it_actually_connected_to():
    """P-04 — asked of the server, not read back from configuration.

    The expected name is taken from the live connection rather than written in,
    because the suite runs against `data-center-test` by default and against
    the throwaway tmpfs instance when that is faster.
    """
    output = _run()

    assert "database is the expected one" in output
    assert connection.settings_dict["NAME"] in output


def test_it_fails_when_connected_to_an_unexpected_database():
    with override_settings(EXPECTED_DATABASE_NAMES={"some_other_database"}):
        with pytest.raises(CommandError, match="database is the expected one"):
            _run()


def test_it_fails_when_the_settings_declare_no_expected_database():
    with override_settings(EXPECTED_DATABASE_NAMES=set()):
        with pytest.raises(CommandError):
            _run()


def test_migrations_are_reported_current():
    assert "migrations current" in _run()


def test_backup_check_is_skipped_when_no_directory_is_configured():
    """Development takes no dumps, and saying so beats passing vacuously."""
    output = _run()

    assert "SKIP" in output
    assert "BACKUP_DIR is not configured" in output


def test_backup_check_passes_on_a_recent_dump(tmp_path):
    (tmp_path / "financial_hub-20260815T090000Z.dump").write_bytes(b"x" * 2048)

    with override_settings(BACKUP_DIR=str(tmp_path), BACKUP_MAX_AGE_HOURS=24):
        output = _run()

    assert "recent backup" in output
    assert "1 retained" in output
    assert "FAIL" not in output


def test_backup_check_fails_on_a_stale_dump(tmp_path):
    dump = tmp_path / "financial_hub-20260101T090000Z.dump"
    dump.write_bytes(b"x")
    two_days_ago = time.time() - (48 * 3600)
    os.utime(dump, (two_days_ago, two_days_ago))

    with override_settings(BACKUP_DIR=str(tmp_path), BACKUP_MAX_AGE_HOURS=24):
        with pytest.raises(CommandError, match="recent backup"):
            _run()


def test_backup_check_fails_when_the_folder_holds_no_dumps(tmp_path):
    """A silent backup failure is otherwise indistinguishable from success."""
    with override_settings(BACKUP_DIR=str(tmp_path)):
        with pytest.raises(CommandError, match="recent backup"):
            _run()


def test_backup_check_fails_when_the_folder_is_missing(tmp_path):
    with override_settings(BACKUP_DIR=str(tmp_path / "not-mounted")):
        with pytest.raises(CommandError, match="recent backup"):
            _run()


def test_the_net_worth_assertion_is_skipped_until_a_month_has_been_closed():
    """A figure asserted before one exists would be asserting nothing."""
    output = _run()

    assert "known net worth unchanged" in output
    assert "after the first close" in output


def test_the_net_worth_assertion_passes_against_the_recorded_figure():
    from decimal import Decimal

    from accounts.models import Account, AccountType, Balance, LiquidityTier

    account = Account.objects.create(
        name="Everyday",
        account_type=AccountType.CURRENT,
        liquidity_tier=LiquidityTier.INSTANT,
        currency="USD",
        opened_month="2026-01",
    )
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("12500.00"))

    with override_settings(
        SMOKE_TEST_MONTH="2026-07",
        SMOKE_TEST_NET_WORTH="12500.00",
        SMOKE_TEST_CURRENCY="USD",
    ):
        output = _run()

    assert "12500.00 USD" in output
    assert "FAIL" not in output


def test_the_net_worth_assertion_fails_when_a_historic_figure_moves():
    """The failure this command exists to catch: a migration or a dependency
    upgrade that silently changed a number that should never change again."""
    from decimal import Decimal

    from accounts.models import Account, AccountType, Balance, LiquidityTier

    account = Account.objects.create(
        name="Everyday",
        account_type=AccountType.CURRENT,
        liquidity_tier=LiquidityTier.INSTANT,
        currency="USD",
        opened_month="2026-01",
    )
    Balance.objects.create(account=account, month="2026-07", amount=Decimal("9999.00"))

    with override_settings(
        SMOKE_TEST_MONTH="2026-07",
        SMOKE_TEST_NET_WORTH="12500.00",
        SMOKE_TEST_CURRENCY="USD",
    ):
        with pytest.raises(CommandError, match="known net worth unchanged"):
            _run()


def test_the_http_check_fails_against_an_unreachable_application():
    out = io.StringIO()
    with pytest.raises(CommandError, match="application responds"):
        call_command(
            "smoke_test",
            stdout=out,
            stderr=out,
            url="http://127.0.0.1:1/api/health/",
        )
