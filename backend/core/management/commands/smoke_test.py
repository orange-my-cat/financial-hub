"""The post-deployment smoke test — one command (§11.5).

    python manage.py smoke_test

Five assertions are specified. Four exist now; the fifth is the one that earns
the command its place and it cannot be written until Stage 2:

    1. the application responds
    2. the database is reachable
    3. it is the *right* database                       (BUILD_PLAN P-04)
    4. migrations are current
    5. the last dump is recent
    6. a known net worth figure computes to the same number   ← Stage 2

Assertion 6 is the valuable one: it catches a migration or a dependency upgrade
that silently altered a figure, which is the worst failure mode available to a
system whose second-ranked quality attribute is that historic figures reproduce.
No amount of unit testing detects that after the fact. It is scaffolded here as
a skipped check so that adding it at Stage 2 is filling in a body rather than
remembering a requirement.

Assertion 3 is the tripwire under P-04. `config.settings.dev` already refuses to
start against the production database, but that guard reads configuration. This
one asks the server it actually connected to what its name is.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Check:
    name: str
    status: str
    detail: str


def _allowed_host() -> str | None:
    """The first host name the application will admit, or None if it admits any.

    Development lists `localhost` and a wildcard is possible under DEBUG; in
    either case the loopback request needs no help and the header is left
    alone.
    """
    for host in settings.ALLOWED_HOSTS:
        if host in ("*", ".localhost"):
            return None
        return host.lstrip(".")
    return None


class Command(BaseCommand):
    help = "Assert that this deployment is answering, connected, migrated and backed up."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--url",
            default="http://127.0.0.1:8000/api/health/",
            help="Health endpoint to poll. Default is the container's own port.",
        )
        parser.add_argument(
            "--skip-http",
            action="store_true",
            help="Skip the HTTP check, for running against a stopped application.",
        )

    def handle(self, *args, **options) -> None:
        checks: list[Check] = [
            self._check_http(options["url"], skip=options["skip_http"]),
            self._check_database(),
            self._check_database_identity(),
            self._check_migrations(),
            self._check_backup_age(),
            self._check_known_net_worth(),
        ]

        width = max(len(check.name) for check in checks)
        for check in checks:
            style = {
                PASS: self.style.SUCCESS,
                FAIL: self.style.ERROR,
                SKIP: self.style.WARNING,
            }[check.status]
            self.stdout.write(
                f"{style(check.status.ljust(4))}  {check.name.ljust(width)}  {check.detail}"
            )

        failures = [check for check in checks if check.status == FAIL]
        if failures:
            raise CommandError(
                f"{len(failures)} of {len(checks)} checks failed: "
                + ", ".join(check.name for check in failures)
            )
        self.stdout.write(self.style.SUCCESS("\nAll checks passed."))

    # -- 1 -----------------------------------------------------------------
    def _check_http(self, url: str, *, skip: bool) -> Check:
        name = "application responds"
        if skip:
            return Check(name, SKIP, "--skip-http")
        # Connect to the loopback address, but present the name the application
        # answers to. In production ALLOWED_HOSTS is exactly
        # `financial-hub.localhost`, so a request carrying a `127.0.0.1` Host
        # header is refused with a 400 before it reaches a view — the check
        # would report the application down while it was serving perfectly well
        # through nginx. Widening ALLOWED_HOSTS to satisfy a self-test would be
        # the wrong repair.
        request = urllib.request.Request(url)  # noqa: S310
        host = _allowed_host()
        if host:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
                if response.status == 200:
                    return Check(name, PASS, f"200 from {url}")
                return Check(name, FAIL, f"{response.status} from {url}")
        except (urllib.error.URLError, OSError) as exc:
            return Check(name, FAIL, f"{url} unreachable: {exc}")

    # -- 2 -----------------------------------------------------------------
    def _check_database(self) -> Check:
        name = "database reachable"
        try:
            connection.ensure_connection()
        except Exception as exc:  # noqa: BLE001 - the message is the whole point
            return Check(name, FAIL, str(exc).strip().splitlines()[0])
        settings_dict = connection.settings_dict
        return Check(
            name,
            PASS,
            f"{settings_dict['HOST']}:{settings_dict['PORT']}",
        )

    # -- 3 -----------------------------------------------------------------
    def _check_database_identity(self) -> Check:
        """P-04. Ask the server which database this actually is."""
        name = "database is the expected one"
        expected = getattr(settings, "EXPECTED_DATABASE_NAMES", None)
        if not expected:
            return Check(name, FAIL, "EXPECTED_DATABASE_NAMES is not defined by these settings")
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database()")
                actual = cursor.fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            return Check(name, FAIL, str(exc).strip().splitlines()[0])

        if actual not in expected:
            return Check(
                name,
                FAIL,
                f"connected to '{actual}', expected one of "
                f"{', '.join(sorted(expected))} — see BUILD_PLAN P-04",
            )
        return Check(name, PASS, f"'{actual}'")

    # -- 4 -----------------------------------------------------------------
    def _check_migrations(self) -> Check:
        name = "migrations current"
        try:
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except Exception as exc:  # noqa: BLE001
            return Check(name, FAIL, str(exc).strip().splitlines()[0])
        if plan:
            pending = ", ".join(f"{migration.app_label}.{migration.name}" for migration, _ in plan)
            return Check(name, FAIL, f"{len(plan)} unapplied: {pending}")
        return Check(name, PASS, "nothing unapplied")

    # -- 5 -----------------------------------------------------------------
    def _check_backup_age(self) -> Check:
        name = "recent backup"
        backup_dir = (settings.BACKUP_DIR or "").strip()
        if not backup_dir:
            # Development takes no dumps. Saying so is the honest answer;
            # passing would make the check meaningless in the one environment
            # where it matters.
            return Check(name, SKIP, "BACKUP_DIR is not configured (development)")

        directory = Path(backup_dir)
        if not directory.is_dir():
            return Check(name, FAIL, f"{directory} does not exist")

        dumps = sorted(directory.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not dumps:
            return Check(name, FAIL, f"no dump files in {directory}")

        newest = dumps[0]
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            newest.stat().st_mtime, tz=timezone.utc
        )
        limit = timedelta(hours=settings.BACKUP_MAX_AGE_HOURS)
        size_mb = newest.stat().st_size / (1024 * 1024)
        detail = f"{newest.name}, {size_mb:.1f} MB, {age.total_seconds() / 3600:.1f}h old"

        if age > limit:
            return Check(
                name, FAIL, f"{detail} — older than {settings.BACKUP_MAX_AGE_HOURS}h"
            )
        return Check(name, PASS, f"{detail} ({len(dumps)} retained)")

    # -- 6 -----------------------------------------------------------------
    def _check_known_net_worth(self) -> Check:
        """The assertion this command exists for.

        Recomputes a fixed historic month and compares it against the figure
        recorded when that month was closed. A difference means a migration or a
        dependency upgrade silently changed a number that should never change
        again — the worst failure mode available to a system whose second-ranked
        quality attribute is that historic figures reproduce, and one that no
        amount of unit testing detects after the fact.

        Configured rather than hard-coded, because the figure cannot exist until
        a month has actually been closed. Until then it says so, rather than
        passing vacuously.
        """
        name = "known net worth unchanged"

        month = (settings.SMOKE_TEST_MONTH or "").strip()
        expected_raw = (settings.SMOKE_TEST_NET_WORTH or "").strip()

        if not month or not expected_raw:
            return Check(
                name,
                SKIP,
                "set SMOKE_TEST_MONTH and SMOKE_TEST_NET_WORTH after the first close",
            )

        try:
            from accounts.services.net_worth import NetWorthService

            expected = Decimal(expected_raw)
            actual = NetWorthService().for_month(
                month, settings.SMOKE_TEST_CURRENCY
            ).total.rounded()
        except Exception as exc:  # noqa: BLE001 - the message is the whole point
            return Check(name, FAIL, str(exc).strip().splitlines()[0])

        if actual != expected:
            return Check(
                name,
                FAIL,
                f"{month} recomputes to {actual} {settings.SMOKE_TEST_CURRENCY}, "
                f"expected {expected}. A historic figure has moved.",
            )
        return Check(name, PASS, f"{month} = {actual} {settings.SMOKE_TEST_CURRENCY}")
