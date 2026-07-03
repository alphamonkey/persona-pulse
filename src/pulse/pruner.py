"""Retention cycle: drop snapshots older than the horizon, then reclaim the freed space.

Peer to `poller.py` — a thin `prune_once` + a schedulable `PruneJob`. `market_snapshots` otherwise
grows monotonically; this bounds it. Run as a daily one-shot (systemd timer), not in-process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from pulse import config
from pulse.models import _now
from pulse.store.db import Database

log = logging.getLogger("pulse")


@dataclass
class PruneReport:
    deleted: int = 0
    retention_days: int = 0


def prune_once(
    db: Database, *, now: datetime | None = None,
    retention_days: int = config.SNAPSHOT_RETENTION_DAYS,
) -> PruneReport:
    now = now or _now()
    before = now - timedelta(days=retention_days)
    deleted = db.prune_snapshots(before)
    db.reclaim()
    return PruneReport(deleted=deleted, retention_days=retention_days)


class PruneJob:
    """The prune cycle as a schedulable Job (report logging in one place)."""

    name = "prune"

    def __init__(self, db: Database, retention_days: int = config.SNAPSHOT_RETENTION_DAYS) -> None:
        self._db = db
        self._retention_days = retention_days

    def run(self) -> PruneReport:
        report = prune_once(self._db, retention_days=self._retention_days)
        log.info(
            "prune complete: deleted %d snapshots older than %d days",
            report.deleted, report.retention_days,
        )
        return report
