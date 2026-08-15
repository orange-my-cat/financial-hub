"""Backup status — the control that closes RISK-02 in fact rather than in intent.

The application never performs a backup. That is the container entrypoint's job,
which runs before anything touches the schema (ADR-11). This service only *reads*
the folder, and its whole purpose is one sentence:

    **A silent backup failure is otherwise indistinguishable from success until
    the day it matters.**

So it compares the newest dump against the newest data modification and warns
when the dump is older. A backup that stopped running three months ago looks
exactly like one that ran this morning — unless something is looking.

Under the shared-instance decision this matters more than the HLD assumed.
`data-center` holds other tenants' databases, and nothing in this application can
prevent someone else's `docker compose down -v`. The dump is the only backstop
(BUILD_PLAN P-02), which promotes this panel from useful to load-bearing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.db import models


@dataclass(frozen=True)
class BackupStatus:
    #: Where dumps are written. Empty in development, which takes none.
    destination: str
    configured: bool
    newest_at: datetime | None
    newest_name: str | None
    size_bytes: int | None
    count: int
    #: The most recent change to any financial record.
    newest_data_at: datetime | None

    @property
    def is_stale(self) -> bool:
        """True where data has changed since the newest dump was written."""
        if self.newest_at is None or self.newest_data_at is None:
            return False
        return self.newest_data_at > self.newest_at

    @property
    def state(self) -> str:
        """The word, so meaning survives without the colour."""
        if not self.configured:
            return "Not configured"
        if self.newest_at is None:
            return "No backup found"
        if self.is_stale:
            return "Data changed since last backup"
        return "Current"

    @property
    def is_healthy(self) -> bool:
        return self.configured and self.newest_at is not None and not self.is_stale

    def as_dict(self) -> dict:
        return {
            "destination": self.destination,
            "configured": self.configured,
            "state": self.state,
            "healthy": self.is_healthy,
            "stale": self.is_stale,
            "newest_at": self.newest_at.isoformat() if self.newest_at else None,
            "newest_name": self.newest_name,
            "size_bytes": self.size_bytes,
            "count": self.count,
            "newest_data_at": self.newest_data_at.isoformat()
            if self.newest_data_at
            else None,
        }


def newest_data_change() -> datetime | None:
    """The most recent write to anything financial.

    Deliberately includes soft-deleted rows: deleting a year of balances is a
    data change that very much wants backing up before the next teardown.
    """
    from accounts.models import Account, Balance
    from cashflow.models import Category, RecurringTemplate, Transaction
    from core.models import Settings
    from fx.models import ExchangeRate
    from investments.models import Holding, InvestmentTransaction

    latest: datetime | None = None
    tracked = [
        Account,
        Balance,
        ExchangeRate,
        Category,
        Transaction,
        RecurringTemplate,
        Holding,
        InvestmentTransaction,
    ]

    for model in tracked:
        manager = getattr(model, "all_objects", model.objects)
        row = manager.aggregate(newest=models.Max("updated_at"))["newest"]
        if row is not None and (latest is None or row > latest):
            latest = row

    row = Settings.objects.aggregate(newest=models.Max("updated_at"))["newest"]
    if row is not None and (latest is None or row > latest):
        latest = row

    return latest


def backup_status() -> BackupStatus:
    destination = (settings.BACKUP_DIR or "").strip()
    newest_data_at = newest_data_change()

    if not destination:
        # Development takes no dumps. Saying so beats reporting a false green.
        return BackupStatus(
            destination="",
            configured=False,
            newest_at=None,
            newest_name=None,
            size_bytes=None,
            count=0,
            newest_data_at=newest_data_at,
        )

    folder = Path(destination)
    dumps = sorted(folder.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []

    if not dumps:
        return BackupStatus(
            destination=destination,
            configured=True,
            newest_at=None,
            newest_name=None,
            size_bytes=None,
            count=0,
            newest_data_at=newest_data_at,
        )

    newest = dumps[0]
    stat = newest.stat()
    return BackupStatus(
        destination=destination,
        configured=True,
        newest_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        newest_name=newest.name,
        size_bytes=stat.st_size,
        count=len(dumps),
        newest_data_at=newest_data_at,
    )
