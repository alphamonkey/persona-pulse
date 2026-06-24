"""Integration tests: the engine composes the store with the pure rules, end-to-end."""

from datetime import datetime, timedelta, timezone

import pytest

from pulse.detector.engine import run_detection
from pulse.models import Snapshot, ValueKind
from pulse.store.db import Database

_T = datetime(2026, 6, 24, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def _snap(market_id, i, value, volume=0.0, kind=ValueKind.PROBABILITY, venue="kalshi"):
    return Snapshot(
        venue=venue,
        market_id=market_id,
        ts=_T + timedelta(minutes=10 * i),
        value=value,
        value_kind=kind,
        volume=volume,
    )


def _seed_swing(db, market_id="A"):
    # +15pts and crosses no milestone level -> isolates odds_swing.
    db.insert_snapshot(_snap(market_id, 0, 0.55))
    db.insert_snapshot(_snap(market_id, 1, 0.70))


def test_run_detection_emits_event(db):
    _seed_swing(db)
    events = run_detection(db, "kalshi")
    assert [e.rule for e in events] == ["odds_swing"]
    assert events[0].market_id == "A"


def test_second_run_emits_nothing_due_to_dedup(db):
    _seed_swing(db)
    assert len(run_detection(db, "kalshi")) == 1
    assert run_detection(db, "kalshi") == []  # posted_events backstop


def test_new_triggering_snapshot_re_emits(db):
    _seed_swing(db)
    run_detection(db, "kalshi")
    # A genuinely new swing on a later day -> new dedup bucket -> fires again.
    db.insert_snapshot(
        Snapshot("kalshi", "A", _T + timedelta(days=1), 0.55, ValueKind.PROBABILITY)
    )
    db.insert_snapshot(
        Snapshot("kalshi", "A", _T + timedelta(days=1, minutes=10), 0.72, ValueKind.PROBABILITY)
    )
    events = run_detection(db, "kalshi")
    assert [e.rule for e in events] == ["odds_swing"]


def test_applies_to_filters_by_value_kind(db):
    # A PRICE market with a swing-sized move must NOT trigger the probability-only odds_swing,
    # but a volume spike (probability OR price) still can.
    vols = [0, 10, 20, 30, 40, 50, 60, 230]
    for i, vol in enumerate(vols):
        db.insert_snapshot(_snap("P", i, 100.0 + i, volume=vol, kind=ValueKind.PRICE))
    events = run_detection(db, "kalshi")
    assert [e.rule for e in events] == ["volume_spike"]


def test_scans_multiple_markets_when_market_ids_none(db):
    _seed_swing(db, "A")
    _seed_swing(db, "B")
    events = run_detection(db, "kalshi")
    assert {e.market_id for e in events} == {"A", "B"}


def test_explicit_market_ids_limits_scope(db):
    _seed_swing(db, "A")
    _seed_swing(db, "B")
    events = run_detection(db, "kalshi", market_ids=["A"])
    assert {e.market_id for e in events} == {"A"}
