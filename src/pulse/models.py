"""Normalized data models — the platform-agnostic seam the detector reads.

Every venue's poller normalizes its raw data into a `Snapshot`; the detector and store
depend only on these types, never on Kalshi/Polymarket/exchange-specific shapes. This is
what lets new venues slot in by adding an adapter, with no detector changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> datetime:
    """Timezone-aware UTC now — all timestamps in this system are aware UTC."""
    return datetime.now(timezone.utc)


class ValueKind(str, Enum):
    """What a snapshot's `value` represents. str-mixin so it stores/serializes as its name."""

    PROBABILITY = "PROBABILITY"  # value in [0, 1] (Kalshi, Polymarket)
    PRICE = "PRICE"  # positive price (NYSE, crypto) — used by later venues


@dataclass(frozen=True)
class MarketMeta:
    """Descriptive market context, carried through to the writer/dashboard."""

    title: str | None = None
    status: str | None = None  # "active" | "settled" | ...
    resolution_date: str | None = None  # ISO date/datetime string
    category: str | None = None
    extra: dict = field(default_factory=dict)  # free-form catch-all for venue specifics


@dataclass(frozen=True)
class Snapshot:
    """One normalized reading of a market at a point in time."""

    venue: str
    market_id: str
    ts: datetime  # aware UTC
    value: float  # PROBABILITY: [0,1]; PRICE: positive
    value_kind: ValueKind
    volume: float = 0.0  # CUMULATIVE traded volume at ts
    meta: MarketMeta | None = None


@dataclass(frozen=True)
class Event:
    """A detected, newsworthy occurrence — the detector's output unit."""

    rule: str
    venue: str
    market_id: str
    ts: datetime  # the triggering snapshot's ts
    value_kind: ValueKind
    from_value: float | None
    to_value: float | None
    magnitude: float
    direction: str | None  # "up" | "down" | None
    headline: str  # human-readable, writer/dashboard-ready
    dedup_key: str  # rule-owned stable idempotency key
    meta: MarketMeta | None = None
    context: dict = field(default_factory=dict)  # rule-specific extras
