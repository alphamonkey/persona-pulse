"""The deterministic detection rules — pure functions over a snapshot series.

Each rule takes an ASCENDING series of snapshots for ONE market (homogeneous value_kind,
`series[-1]` is "now") and returns an `Event` or `None`. Rules are EDGE-TRIGGERED: they
fire only on the transition INTO a condition, so a condition that persists across polling
cycles does not re-fire. Each rule owns the `dedup_key` that the store uses as an
idempotency backstop.

Pure: no DB, no network, no wall-clock reads. Only `pulse.models` and `pulse.config`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from pulse.config import (
    MILESTONE_LEVELS,
    MIN_ODDS_MOVE,
    MIN_VOLUME_SPIKE,
    NEW_MARKET_DEBUT_WINDOW,
    NEW_MARKET_MIN_VOLUME,
    ODDS_SWING_LOOKBACK_SECONDS,
    VOLUME_SPIKE_BASELINE_N,
)
from pulse.detector.registry import rule
from pulse.models import Event, Snapshot, ValueKind


def _label(snap: Snapshot) -> str:
    if snap.meta is not None and snap.meta.title:
        return snap.meta.title
    return snap.market_id


def _date(snap: Snapshot) -> str:
    return snap.ts.date().isoformat()


def _event(rule_name, snap, *, from_value, to_value, magnitude, direction, headline,
           dedup_key, context) -> Event:
    return Event(
        rule=rule_name,
        venue=snap.venue,
        market_id=snap.market_id,
        ts=snap.ts,
        value_kind=snap.value_kind,
        from_value=from_value,
        to_value=to_value,
        magnitude=magnitude,
        direction=direction,
        headline=headline,
        dedup_key=dedup_key,
        context=context,
        meta=snap.meta,
    )


# ── odds_swing ──

def _swing_state(series: Sequence[Snapshot]) -> tuple[bool, float, float]:
    """(triggered, ref_value, now_value): ref is the value at the start of the lookback window."""
    now = series[-1]
    cutoff = now.ts - timedelta(seconds=ODDS_SWING_LOOKBACK_SECONDS)
    in_window = [s for s in series if s.ts >= cutoff]
    ref = in_window[0].value  # ascending -> oldest within window
    # epsilon so an exact-threshold move isn't excluded by float subtraction noise
    return abs(now.value - ref) >= MIN_ODDS_MOVE - 1e-9, ref, now.value


@rule("odds_swing", applies_to={ValueKind.PROBABILITY})
def odds_swing(series: Sequence[Snapshot]) -> Event | None:
    if len(series) < 2:
        return None
    trig_now, ref, now_v = _swing_state(series)
    if not trig_now:
        return None
    if _swing_state(series[:-1])[0]:  # condition already held last cycle -> not a new swing
        return None
    now = series[-1]
    direction = "up" if now_v >= ref else "down"
    magnitude = abs(now_v - ref)
    pts = round(magnitude * 100)
    sign = "+" if direction == "up" else "-"
    headline = f"{_label(now)}: odds {ref:.0%} -> {now_v:.0%} ({sign}{pts}pts)"
    return _event(
        "odds_swing", now, from_value=ref, to_value=now_v, magnitude=magnitude,
        direction=direction, headline=headline,
        dedup_key=f"odds_swing:{now.venue}:{now.market_id}:{_date(now)}",
        context={"lookback_seconds": ODDS_SWING_LOOKBACK_SECONDS},
    )


# ── volume_spike ──

def _spike_state(series: Sequence[Snapshot]) -> tuple[bool, float, float] | None:
    """(triggered, current_interval, baseline_avg) or None if insufficient history."""
    deltas = [max(0.0, series[i].volume - series[i - 1].volume) for i in range(1, len(series))]
    if len(deltas) < VOLUME_SPIKE_BASELINE_N + 1:
        return None
    current = deltas[-1]
    baseline_deltas = deltas[-(VOLUME_SPIKE_BASELINE_N + 1):-1]
    baseline = sum(baseline_deltas) / len(baseline_deltas)
    if baseline <= 0:
        return False, current, baseline
    return current >= MIN_VOLUME_SPIKE * baseline, current, baseline


@rule("volume_spike", applies_to={ValueKind.PROBABILITY, ValueKind.PRICE})
def volume_spike(series: Sequence[Snapshot]) -> Event | None:
    state = _spike_state(series)
    if state is None or not state[0]:
        return None
    prev = _spike_state(series[:-1])
    if prev is not None and prev[0]:  # spike already detected last cycle
        return None
    _, current, baseline = state
    ratio = current / baseline
    now = series[-1]
    headline = f"{_label(now)}: volume {ratio:.1f}x its recent average"
    return _event(
        "volume_spike", now, from_value=baseline, to_value=current, magnitude=ratio,
        direction="up", headline=headline,
        dedup_key=f"volume_spike:{now.venue}:{now.market_id}:{_date(now)}",
        context={"interval_volume": current, "baseline_avg": baseline},
    )


# ── milestone ──

@rule("milestone", applies_to={ValueKind.PROBABILITY})
def milestone(series: Sequence[Snapshot]) -> Event | None:
    if len(series) < 2:
        return None
    prev_v = series[-2].value
    now = series[-1]
    now_v = now.value
    crossed_up = [lvl for lvl in MILESTONE_LEVELS if prev_v < lvl <= now_v]
    crossed_down = [lvl for lvl in MILESTONE_LEVELS if prev_v > lvl >= now_v]
    if crossed_up:
        level, direction = max(crossed_up), "up"
    elif crossed_down:
        level, direction = min(crossed_down), "down"
    else:
        return None
    headline = f"{_label(now)}: crossed {level:.0%} ({direction})"
    return _event(
        "milestone", now, from_value=prev_v, to_value=now_v, magnitude=level,
        direction=direction, headline=headline,
        dedup_key=f"milestone:{now.venue}:{now.market_id}:{level}:{direction}:{_date(now)}",
        context={"level": level, "all_crossed": crossed_up or crossed_down},
    )


# ── new_market ──

@rule("new_market", applies_to={ValueKind.PROBABILITY})
def new_market(series: Sequence[Snapshot]) -> Event | None:
    if len(series) > NEW_MARKET_DEBUT_WINDOW:  # established market — never "new"
        return None
    now = series[-1]
    if now.volume < NEW_MARKET_MIN_VOLUME:
        return None
    first_cross = len(series) == 1 or series[-2].volume < NEW_MARKET_MIN_VOLUME
    if not first_cross:
        return None
    headline = f"New market {_label(now)}: {now.value:.0%}, volume {now.volume:.0f}"
    return _event(
        "new_market", now, from_value=None, to_value=now.value, magnitude=now.volume,
        direction=None, headline=headline,
        dedup_key=f"new_market:{now.venue}:{now.market_id}",
        context={"debut_volume": now.volume},
    )
