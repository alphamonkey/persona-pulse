"""Retention: prune old market_snapshots + reclaim on-disk space.

`market_snapshots` grows monotonically (no retention) — this bounds it by dropping rows older than a
cutoff, and reclaims freed pages via incremental auto_vacuum. Cutoff comparison is on the ISO-8601 UTC
`ts` text, which sorts chronologically.
"""

from datetime import datetime, timedelta, timezone

import pytest

from pulse.models import Snapshot, ValueKind
from pulse.store.db import Database

_T = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def _snap(ts, market_id="KXTEST", value=0.5):
    return Snapshot(
        venue="kalshi", market_id=market_id, ts=ts, value=value,
        value_kind=ValueKind.PROBABILITY, volume=0.0, meta=None,
    )


# ── prune_snapshots ──

def test_prune_drops_only_rows_older_than_cutoff(db):
    db.insert_snapshot(_snap(_T - timedelta(days=10)))  # old
    db.insert_snapshot(_snap(_T - timedelta(days=8)))   # old
    db.insert_snapshot(_snap(_T - timedelta(days=1)))   # keep
    db.insert_snapshot(_snap(_T))                        # keep
    deleted = db.prune_snapshots(_T - timedelta(days=7))
    assert deleted == 2
    kept = db.get_recent_snapshots("kalshi", "KXTEST")
    assert [s.ts for s in kept] == [_T - timedelta(days=1), _T]


def test_prune_cutoff_is_exclusive(db):
    # a row exactly at the cutoff is KEPT (strictly-older is dropped)
    db.insert_snapshot(_snap(_T - timedelta(days=7)))
    assert db.prune_snapshots(_T - timedelta(days=7)) == 0
    assert len(db.get_recent_snapshots("kalshi", "KXTEST")) == 1


def test_prune_empty_db_returns_zero(db):
    assert db.prune_snapshots(_T) == 0


def test_prune_preserves_detector_lookback(db):
    # Detector needs at most the last ~6h / 64 snaps per market; a 7-day prune must never touch them.
    for mins in (0, 60, 180, 360):  # within the last 6h
        db.insert_snapshot(_snap(_T - timedelta(minutes=mins)))
    db.insert_snapshot(_snap(_T - timedelta(days=30)))  # ancient
    db.prune_snapshots(_T - timedelta(days=7))
    kept = db.get_recent_snapshots("kalshi", "KXTEST")
    assert len(kept) == 4  # all recent survive, only the 30-day row went


# ── reclaim / auto_vacuum ──

def test_fresh_db_is_incremental_auto_vacuum(db):
    # 2 == SQLITE_AUTO_VACUUM_INCREMENTAL — new DBs are born reclaimable.
    assert db.conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2


def test_reclaim_runs_clean(db):
    db.insert_snapshot(_snap(_T - timedelta(days=30)))
    db.prune_snapshots(_T - timedelta(days=7))
    db.reclaim()  # must not raise (incremental_vacuum + wal truncate checkpoint)


def test_vacuum_runs_clean(db):
    db.insert_snapshot(_snap(_T))
    db.vacuum()  # one-time converter must not raise
