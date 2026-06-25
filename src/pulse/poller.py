"""Venue-agnostic poll cycle: fetch normalized snapshots, store them, run detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pulse.detector.engine import run_detection
from pulse.models import Event, _now
from pulse.store.db import Database
from pulse.venue.base import SnapshotSource


@dataclass
class PollReport:
    markets_seen: int = 0
    snapshots_stored: int = 0
    events: list[Event] = field(default_factory=list)


def poll_once(source: SnapshotSource, db: Database, *, now: datetime | None = None) -> PollReport:
    now = now or _now()
    snapshots = source.fetch_snapshots(now)
    stored = sum(int(db.insert_snapshot(s)) for s in snapshots)
    events = run_detection(db, source.venue)
    return PollReport(markets_seen=len(snapshots), snapshots_stored=stored, events=events)
