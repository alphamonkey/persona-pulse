"""The detection runner — the only place I/O meets the pure rules.

`run_detection` loads each market's recent snapshot history from the store, runs every
registered rule whose asset-class matches, and records newly-emitted events in the
idempotency log. The rules stay pure; the store enforces dedup as a race-safe backstop.
"""

from __future__ import annotations

from collections.abc import Iterable

# Importing rules populates the REGISTRY via the @rule decorators.
from pulse.detector import rules as _rules  # noqa: F401
from pulse.detector.registry import REGISTRY
from pulse.models import Event
from pulse.store.db import Database


def run_detection(
    db: Database,
    venue: str,
    market_ids: Iterable[str] | None = None,
) -> list[Event]:
    markets = list(market_ids) if market_ids is not None else db.distinct_markets(venue)
    emitted: list[Event] = []
    for mid in markets:
        series = db.get_recent_snapshots(venue, mid)
        if not series:
            continue
        kind = series[-1].value_kind
        for spec in REGISTRY:
            if kind not in spec.applies_to:
                continue
            event = spec.fn(series)  # PURE — no I/O inside
            if event is not None and db.record_posted(event):
                emitted.append(event)
    return emitted
