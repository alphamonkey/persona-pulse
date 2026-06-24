"""Tests for the pure detection rules. No DB, no network — fixture snapshot series only."""

from datetime import datetime, timedelta, timezone

from pulse.detector import rules
from pulse.detector.registry import REGISTRY
from pulse.models import Snapshot, ValueKind

_T = datetime(2026, 6, 24, 0, 0, 0, tzinfo=timezone.utc)


def _series(values, volumes=None, kind=ValueKind.PROBABILITY, step_seconds=600, start=_T):
    """Build an ascending snapshot series for one market."""
    volumes = volumes if volumes is not None else [0.0] * len(values)
    return [
        Snapshot(
            venue="kalshi",
            market_id="KXTEST",
            ts=start + timedelta(seconds=step_seconds * i),
            value=v,
            value_kind=kind,
            volume=vol,
        )
        for i, (v, vol) in enumerate(zip(values, volumes))
    ]


# ── registry ──

def test_registry_has_all_four_rules():
    names = {spec.name for spec in REGISTRY}
    assert names == {"odds_swing", "volume_spike", "milestone", "new_market"}


def test_volume_spike_applies_to_both_kinds():
    spec = next(s for s in REGISTRY if s.name == "volume_spike")
    assert spec.applies_to == frozenset({ValueKind.PROBABILITY, ValueKind.PRICE})


def test_odds_swing_is_probability_only():
    spec = next(s for s in REGISTRY if s.name == "odds_swing")
    assert spec.applies_to == frozenset({ValueKind.PROBABILITY})


# ── odds_swing ──

def test_odds_swing_fires_at_exact_threshold():
    ev = rules.odds_swing(_series([0.40, 0.50]))
    assert ev is not None
    assert ev.rule == "odds_swing"
    assert ev.direction == "up"
    assert ev.from_value == 0.40 and ev.to_value == 0.50
    assert abs(ev.magnitude - 0.10) < 1e-9
    assert ev.dedup_key == "odds_swing:kalshi:KXTEST:2026-06-24"


def test_odds_swing_does_not_fire_below_threshold():
    assert rules.odds_swing(_series([0.40, 0.49])) is None


def test_odds_swing_direction_down():
    ev = rules.odds_swing(_series([0.60, 0.45]))
    assert ev is not None and ev.direction == "down"


def test_odds_swing_persistent_condition_fires_once():
    # Already swung by t1; t2 stays elevated -> must NOT re-fire (edge-triggered).
    assert rules.odds_swing(_series([0.40, 0.55, 0.56])) is None


def test_odds_swing_needs_two_snapshots():
    assert rules.odds_swing(_series([0.40])) is None


def test_odds_swing_ignores_move_outside_lookback_window():
    # The only other point is 7h before now -> outside the 6h window -> no in-window move.
    far = _series([0.40], step_seconds=0)
    now = _series([0.50], start=_T + timedelta(hours=7))
    assert rules.odds_swing(far + now) is None


# ── volume_spike ──

def test_volume_spike_fires_on_three_x_interval():
    vols = [0, 10, 20, 30, 40, 50, 60, 230]  # 7 deltas of 10, then 170
    ev = rules.volume_spike(_series([0.5] * 8, volumes=vols))
    assert ev is not None
    assert ev.rule == "volume_spike"
    assert ev.magnitude >= 3.0  # ratio
    assert ev.dedup_key.startswith("volume_spike:kalshi:KXTEST:")


def test_volume_spike_persistent_fires_once():
    vols = [0, 10, 20, 30, 40, 50, 60, 230, 400]  # two consecutive 170 deltas
    assert rules.volume_spike(_series([0.5] * 9, volumes=vols)) is None


def test_volume_spike_needs_enough_history():
    assert rules.volume_spike(_series([0.5] * 4, volumes=[0, 10, 20, 30])) is None


def test_volume_spike_zero_baseline_does_not_fire():
    vols = [0, 0, 0, 0, 0, 0, 100]  # baseline 0 -> undefined multiple
    assert rules.volume_spike(_series([0.5] * 7, volumes=vols)) is None


def test_volume_spike_clamps_negative_delta_reset():
    # A cumulative reset (decrease) must not crash or produce a phantom spike.
    vols = [0, 10, 20, 30, 40, 50, 5, 15]
    assert rules.volume_spike(_series([0.5] * 8, volumes=vols)) is None


# ── milestone ──

def test_milestone_crosses_fifty_up():
    ev = rules.milestone(_series([0.45, 0.55]))
    assert ev is not None
    assert ev.magnitude == 0.50 and ev.direction == "up"
    assert ev.dedup_key == "milestone:kalshi:KXTEST:0.5:up:2026-06-24"


def test_milestone_crosses_fifty_down():
    ev = rules.milestone(_series([0.55, 0.45]))
    assert ev is not None and ev.direction == "down" and ev.magnitude == 0.50


def test_milestone_no_cross():
    assert rules.milestone(_series([0.55, 0.60])) is None


def test_milestone_multi_level_jump_picks_most_significant_up():
    ev = rules.milestone(_series([0.20, 0.85]))  # crosses .25, .5, .75
    assert ev is not None and ev.magnitude == 0.75 and ev.direction == "up"


def test_milestone_multi_level_jump_picks_lowest_down():
    ev = rules.milestone(_series([0.85, 0.20]))  # crosses .75, .5, .25
    assert ev is not None and ev.magnitude == 0.25 and ev.direction == "down"


def test_milestone_landing_exactly_on_level_counts_up():
    ev = rules.milestone(_series([0.45, 0.50]))
    assert ev is not None and ev.magnitude == 0.50 and ev.direction == "up"


def test_milestone_needs_two_snapshots():
    assert rules.milestone(_series([0.45])) is None


# ── new_market ──

def test_new_market_fires_on_debut_above_floor():
    ev = rules.new_market(_series([0.5], volumes=[150]))
    assert ev is not None
    assert ev.rule == "new_market"
    assert ev.dedup_key == "new_market:kalshi:KXTEST"


def test_new_market_waits_until_volume_crosses_floor():
    assert rules.new_market(_series([0.5, 0.5], volumes=[50, 60])) is None
    ev = rules.new_market(_series([0.5, 0.5], volumes=[50, 150]))
    assert ev is not None


def test_new_market_does_not_fire_for_established_market():
    # More snapshots than the debut window -> not new, even with high volume.
    ev = rules.new_market(_series([0.5] * 7, volumes=[200] * 7))
    assert ev is None
