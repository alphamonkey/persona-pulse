# Kalshi Poller / Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `pulse poll` — one cycle that fetches live Kalshi public market data, normalizes it into `Snapshot`s, stores them, and runs the detector (dryrun: logs events, no publish).

**Architecture:** Kalshi-specific I/O and mapping live behind a tiny venue-agnostic `SnapshotSource` seam, so `poll_once(source, db)` is generic and future venues are just new sources. A `KalshiClient` (httpx, no auth) fetches; a pure `market_to_snapshot` normalizes; `KalshiSource` composes them with the category-allowlist + volume-floor filter.

**Tech Stack:** Python 3.13, httpx (sync `Client` + `MockTransport` for tests), SQLite (existing store), pytest.

## Global Constraints

- Python `>=3.13`. **No new dependencies** — use only existing ones (`httpx`, `python-dotenv`, `anthropic`, `atproto`). Specifically **do NOT add `kalshi_python_sync`**.
- **Read-only public Kalshi data only**: no auth header, no credentials, no orders/portfolio surface.
- **Real data only — never fabricate numbers.**
- **TDD always**; clean architecture / strong separation of concerns; avoid race conditions.
- **No agriculture/food topics** — enforced by the category allowlist (those categories are never in `PULSE_CATEGORIES`).
- `PULSE_MODE=dryrun`: never publish (no publish code in this chunk regardless).
- Never commit `.env` or `*.db` (already covered by `.gitignore`).
- Mirror kalshi-edge idioms where clean (the `*_dollars`-then-integer-cents quote fallback).
- Existing interfaces this plan builds on (do not change):
  - `pulse.models`: `Snapshot(venue, market_id, ts, value, value_kind, volume=0.0, meta=None)`, `MarketMeta(title=None, status=None, resolution_date=None, category=None, extra={})`, `ValueKind.PROBABILITY`, `Event`, `_now() -> datetime`.
  - `pulse.store.db.Database`: `.connect()`, `.close()`, `.insert_snapshot(snap) -> bool`, `.distinct_markets(venue)`, `.get_recent_snapshots(...)`.
  - `pulse.detector.engine.run_detection(db, venue, market_ids=None) -> list[Event]`.

---

## File structure

- Create `src/pulse/venue/__init__.py` — empty package marker.
- Create `src/pulse/venue/base.py` — `SnapshotSource` Protocol (the seam).
- Create `src/pulse/venue/kalshi.py` — `KalshiClient`, pure `market_to_snapshot`, `KalshiSource`.
- Create `src/pulse/poller.py` — `PollReport`, `poll_once(source, db)`.
- Create `src/pulse/main.py` — `cli()` with the `poll` subcommand.
- Modify `src/pulse/config.py` — Kalshi host, universe + HTTP constants.
- Tests: `tests/test_venue_base.py`, `tests/test_normalize.py`, `tests/test_kalshi_client.py`, `tests/test_kalshi_source.py`, `tests/test_poller.py`, `tests/test_main.py`.

---

## Task 1: Config additions + `SnapshotSource` seam

**Files:**
- Modify: `src/pulse/config.py` (append after the existing detector constants)
- Create: `src/pulse/venue/__init__.py`
- Create: `src/pulse/venue/base.py`
- Test: `tests/test_venue_base.py`

**Interfaces:**
- Produces: `config.KALSHI_API_HOST: str`, `config.PULSE_CATEGORIES: tuple[str,...]`, `config.MIN_MARKET_VOLUME_24H: float`, `config.HTTP_TIMEOUT_SECONDS: float`, `config.HTTP_MAX_RETRIES: int`; `pulse.venue.base.SnapshotSource` (runtime-checkable Protocol with `venue: str` and `fetch_snapshots(now: datetime) -> list[Snapshot]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_venue_base.py
from datetime import datetime, timezone

from pulse import config
from pulse.venue.base import SnapshotSource


def test_config_universe_constants_are_sane():
    assert config.KALSHI_API_HOST.startswith("https://")
    assert len(config.PULSE_CATEGORIES) > 0
    # The forbidden topics must never be in the allowlist.
    lowered = {c.lower() for c in config.PULSE_CATEGORIES}
    assert not any("food" in c or "agricult" in c for c in lowered)
    assert config.MIN_MARKET_VOLUME_24H > 0
    assert config.HTTP_MAX_RETRIES >= 0


def test_snapshot_source_is_runtime_checkable():
    class Dummy:
        venue = "dummy"

        def fetch_snapshots(self, now):
            return []

    assert isinstance(Dummy(), SnapshotSource)
    assert not isinstance(object(), SnapshotSource)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_venue_base.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pulse.venue'`.

- [ ] **Step 3: Add config constants**

Append to `src/pulse/config.py`:

```python
# ── Kalshi public API (read-only; no auth) ──
KALSHI_API_HOST = "https://api.elections.kalshi.com/trade-api/v2"

# ── Poller universe (allowlist + liquidity floor; tune from data) ──
# NB: agriculture/food categories are intentionally excluded per project rules.
PULSE_CATEGORIES = (
    "Politics",
    "Economics",
    "Companies",
    "Financials",
    "Science and Technology",
)
MIN_MARKET_VOLUME_24H = 1000.0   # contracts traded in the last 24h

# ── HTTP client resilience ──
HTTP_TIMEOUT_SECONDS = 10.0
HTTP_MAX_RETRIES = 3
```

- [ ] **Step 4: Create the package marker and Protocol**

```python
# src/pulse/venue/__init__.py
"""Venue adapters — each normalizes a platform's data into the shared Snapshot seam."""
```

```python
# src/pulse/venue/base.py
"""The venue-agnostic seam: a source yields normalized Snapshots for one venue."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pulse.models import Snapshot


@runtime_checkable
class SnapshotSource(Protocol):
    venue: str

    def fetch_snapshots(self, now: datetime) -> list[Snapshot]:
        """Return current normalized snapshots for this venue, timestamped `now`."""
        ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_venue_base.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/pulse/config.py src/pulse/venue/__init__.py src/pulse/venue/base.py tests/test_venue_base.py
git commit -m "feat(venue): add poller config + SnapshotSource seam"
```

---

## Task 2: Pure normalizer `market_to_snapshot`

**Files:**
- Create: `src/pulse/venue/kalshi.py` (the pure mapper + its private helpers only — client/source come in later tasks)
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `pulse.models.{Snapshot, MarketMeta, ValueKind}`.
- Produces: `market_to_snapshot(raw: dict, category: str | None, now: datetime) -> Snapshot | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_normalize.py
from datetime import datetime, timezone

from pulse.models import ValueKind
from pulse.venue.kalshi import market_to_snapshot

_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _raw(**over):
    base = {
        "ticker": "KXPRES-2028-DEM",
        "title": "Will a Democrat win in 2028?",
        "status": "active",
        "close_time": "2028-11-07T00:00:00Z",
        "last_price": 62,            # cents
        "yes_bid": 60,
        "yes_ask": 64,
        "volume": 12345,
        "volume_24h": 999,
        "event_ticker": "KXPRES-2028",
        "series_ticker": "KXPRES",
    }
    base.update(over)
    return base


def test_uses_last_price_in_cents():
    snap = market_to_snapshot(_raw(), category="Politics", now=_NOW)
    assert snap is not None
    assert snap.venue == "kalshi"
    assert snap.market_id == "KXPRES-2028-DEM"
    assert abs(snap.value - 0.62) < 1e-9
    assert snap.value_kind is ValueKind.PROBABILITY
    assert snap.volume == 12345
    assert snap.ts == _NOW


def test_prefers_dollars_field_over_cents():
    snap = market_to_snapshot(_raw(last_price_dollars=0.41), category="Politics", now=_NOW)
    assert abs(snap.value - 0.41) < 1e-9


def test_falls_back_to_mid_when_no_last_price():
    snap = market_to_snapshot(_raw(last_price=0), category="Politics", now=_NOW)
    assert abs(snap.value - 0.62) < 1e-9  # (60 + 64) / 2 / 100


def test_skips_when_unpriceable():
    raw = _raw(last_price=0, yes_bid=0, yes_ask=0)
    assert market_to_snapshot(raw, category="Politics", now=_NOW) is None


def test_skips_when_no_ticker():
    raw = _raw()
    del raw["ticker"]
    assert market_to_snapshot(raw, category="Politics", now=_NOW) is None


def test_maps_meta_fields():
    snap = market_to_snapshot(_raw(), category="Politics", now=_NOW)
    assert snap.meta.title == "Will a Democrat win in 2028?"
    assert snap.meta.status == "active"
    assert snap.meta.resolution_date == "2028-11-07T00:00:00Z"
    assert snap.meta.category == "Politics"
    assert snap.meta.extra["event_ticker"] == "KXPRES-2028"
    assert snap.meta.extra["series_ticker"] == "KXPRES"
    assert snap.meta.extra["volume_24h"] == 999
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_normalize.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pulse.venue.kalshi'`.

- [ ] **Step 3: Write the normalizer**

```python
# src/pulse/venue/kalshi.py
"""Kalshi public-data adapter: HTTP client, pure normalizer, and SnapshotSource.

Read-only and unauthenticated — only public market/event endpoints. The normalizer maps
a raw Kalshi market dict into the shared Snapshot seam; it is pure and the most-tested part.
"""

from __future__ import annotations

from datetime import datetime

from pulse.models import MarketMeta, Snapshot, ValueKind

VENUE = "kalshi"


def _price(raw: dict, cents_key: str, dollars_key: str) -> float | None:
    """A price in [0,1] from a `*_dollars` field (preferred) or integer-cents, else None."""
    d = raw.get(dollars_key)
    if d is not None:
        try:
            return float(d)
        except (TypeError, ValueError):
            pass
    c = raw.get(cents_key)
    if c is not None:
        try:
            return int(c) / 100.0
        except (TypeError, ValueError):
            pass
    return None


def _derive_value(raw: dict) -> float | None:
    """last_price if it traded; else the bid/ask midpoint; else None (unpriceable)."""
    last = _price(raw, "last_price", "last_price_dollars")
    if last is not None and last > 0:
        return last
    bid = _price(raw, "yes_bid", "yes_bid_dollars")
    ask = _price(raw, "yes_ask", "yes_ask_dollars")
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
        if mid > 0:
            return mid
    return None


def market_to_snapshot(raw: dict, category: str | None, now: datetime) -> Snapshot | None:
    """Map a raw Kalshi market dict to a normalized Snapshot, or None if unpriceable."""
    ticker = raw.get("ticker")
    if not ticker:
        return None
    value = _derive_value(raw)
    if value is None:
        return None
    meta = MarketMeta(
        title=raw.get("title"),
        status=raw.get("status"),
        resolution_date=raw.get("close_time"),
        category=category,
        extra={
            "event_ticker": raw.get("event_ticker"),
            "series_ticker": raw.get("series_ticker"),
            "volume_24h": raw.get("volume_24h"),
        },
    )
    return Snapshot(
        venue=VENUE,
        market_id=ticker,
        ts=now,
        value=value,
        value_kind=ValueKind.PROBABILITY,
        volume=float(raw.get("volume") or 0.0),
        meta=meta,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_normalize.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/pulse/venue/kalshi.py tests/test_normalize.py
git commit -m "feat(venue): pure Kalshi market->Snapshot normalizer"
```

---

## Task 3: `KalshiClient` (httpx, pagination, retries, no auth)

**Files:**
- Modify: `src/pulse/venue/kalshi.py` (add imports + `KalshiClient`)
- Test: `tests/test_kalshi_client.py`

**Interfaces:**
- Consumes: `config.{KALSHI_API_HOST, HTTP_TIMEOUT_SECONDS, HTTP_MAX_RETRIES}`.
- Produces: `KalshiClient(host=..., *, client=None, timeout=..., max_retries=..., sleep=time.sleep)` with `.iter_open_events(limit=200) -> Iterator[dict]` (follows the cursor) and `.close()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_client.py
import httpx
import pytest

from pulse.venue.kalshi import KalshiClient


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://example.test/v2")
    return KalshiClient(client=http, sleep=lambda _s: None)


def test_iter_open_events_follows_cursor():
    pages = {
        None: {"events": [{"event_ticker": "A"}], "cursor": "next"},
        "next": {"events": [{"event_ticker": "B"}], "cursor": ""},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in {k.lower() for k in request.headers}
        assert request.url.path.endswith("/events")
        assert request.url.params.get("status") == "open"
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=pages[cursor])

    events = list(_client(handler).iter_open_events())
    assert [e["event_ticker"] for e in events] == ["A", "B"]


def test_retries_then_succeeds_on_503():
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"events": [], "cursor": ""})

    list(_client(handler).iter_open_events())
    assert state["calls"] == 3


def test_raises_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(httpx.HTTPStatusError):
        list(_client(handler).iter_open_events())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_kalshi_client.py -q`
Expected: FAIL — `ImportError: cannot import name 'KalshiClient'`.

- [ ] **Step 3: Add the client**

Add imports at the top of `src/pulse/venue/kalshi.py` (below the existing `from datetime import datetime`):

```python
import time
from collections.abc import Callable, Iterator

import httpx

from pulse.config import HTTP_MAX_RETRIES, HTTP_TIMEOUT_SECONDS, KALSHI_API_HOST
```

Add the class (after the normalizer):

```python
_RETRY_STATUS = {429, 500, 502, 503, 504}


class KalshiClient:
    """Thin read-only wrapper over Kalshi's public REST API. No auth, no trading surface."""

    def __init__(
        self,
        host: str = KALSHI_API_HOST,
        *,
        client: httpx.Client | None = None,
        timeout: float = HTTP_TIMEOUT_SECONDS,
        max_retries: int = HTTP_MAX_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(base_url=host.rstrip("/"), timeout=timeout)
        self._max_retries = max_retries
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict) -> dict:
        attempt = 0
        while True:
            resp = self._client.get(path, params=params)
            if resp.status_code in _RETRY_STATUS and attempt < self._max_retries:
                attempt += 1
                self._sleep(min(0.1 * 2 ** attempt, 5.0))
                continue
            resp.raise_for_status()
            return resp.json()

    def iter_open_events(self, *, limit: int = 200) -> Iterator[dict]:
        """Yield open events with nested markets, following the pagination cursor."""
        cursor = None
        while True:
            params = {"status": "open", "with_nested_markets": "true", "limit": limit}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/events", params)
            yield from data.get("events", [])
            cursor = data.get("cursor")
            if not cursor:
                break
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kalshi_client.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/pulse/venue/kalshi.py tests/test_kalshi_client.py
git commit -m "feat(venue): KalshiClient httpx wrapper with pagination + retries"
```

---

## Task 4: `KalshiSource` (filter + normalize composition)

**Files:**
- Modify: `src/pulse/venue/kalshi.py` (add `KalshiSource`)
- Test: `tests/test_kalshi_source.py`

**Interfaces:**
- Consumes: `KalshiClient.iter_open_events()`, `market_to_snapshot(...)`, `config.{PULSE_CATEGORIES, MIN_MARKET_VOLUME_24H}`.
- Produces: `KalshiSource(client, *, categories=PULSE_CATEGORIES, min_volume_24h=MIN_MARKET_VOLUME_24H)` with class/inst attr `venue = "kalshi"` and `fetch_snapshots(now) -> list[Snapshot]`. Satisfies `SnapshotSource`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_source.py
from datetime import datetime, timezone

from pulse.venue.base import SnapshotSource
from pulse.venue.kalshi import KalshiSource

_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, events):
        self._events = events

    def iter_open_events(self, *, limit=200):
        yield from self._events


def _market(ticker, **over):
    m = {"ticker": ticker, "status": "active", "last_price": 50,
         "volume": 100, "volume_24h": 5000}
    m.update(over)
    return m


def _event(category, markets, event_ticker="E1"):
    return {"event_ticker": event_ticker, "category": category, "markets": markets}


def test_keeps_only_allowlisted_categories():
    events = [
        _event("Politics", [_market("A")]),
        _event("Weather", [_market("B")]),
    ]
    src = KalshiSource(FakeClient(events), categories={"Politics"}, min_volume_24h=0)
    ids = {s.market_id for s in src.fetch_snapshots(_NOW)}
    assert ids == {"A"}


def test_applies_volume_floor():
    events = [_event("Politics", [_market("A", volume_24h=10), _market("B", volume_24h=9000)])]
    src = KalshiSource(FakeClient(events), categories={"Politics"}, min_volume_24h=1000)
    ids = {s.market_id for s in src.fetch_snapshots(_NOW)}
    assert ids == {"B"}


def test_skips_non_active_and_unpriceable():
    events = [_event("Politics", [
        _market("A", status="finalized"),
        _market("B", last_price=0, yes_bid=0, yes_ask=0),
        _market("C"),
    ])]
    src = KalshiSource(FakeClient(events), categories={"Politics"}, min_volume_24h=0)
    ids = {s.market_id for s in src.fetch_snapshots(_NOW)}
    assert ids == {"C"}


def test_is_a_snapshot_source_with_venue():
    src = KalshiSource(FakeClient([]))
    assert src.venue == "kalshi"
    assert isinstance(src, SnapshotSource)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_kalshi_source.py -q`
Expected: FAIL — `ImportError: cannot import name 'KalshiSource'`.

- [ ] **Step 3: Add the source**

Add to `src/pulse/venue/kalshi.py` (import the universe constants by extending the existing config import line to include `MIN_MARKET_VOLUME_24H, PULSE_CATEGORIES`):

```python
class KalshiSource:
    """Composes the client + normalizer, applying the category allowlist + volume floor."""

    venue = VENUE

    def __init__(
        self,
        client: KalshiClient,
        *,
        categories=PULSE_CATEGORIES,
        min_volume_24h: float = MIN_MARKET_VOLUME_24H,
    ) -> None:
        self._client = client
        self._categories = set(categories)
        self._min_volume_24h = min_volume_24h

    def fetch_snapshots(self, now: datetime) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for event in self._client.iter_open_events():
            category = event.get("category")
            if category not in self._categories:
                continue
            for market in event.get("markets") or []:
                if market.get("status") != "active":
                    continue
                if float(market.get("volume_24h") or 0.0) < self._min_volume_24h:
                    continue
                raw = {
                    **market,
                    "event_ticker": event.get("event_ticker"),
                    "series_ticker": event.get("series_ticker"),
                }
                snap = market_to_snapshot(raw, category, now)
                if snap is not None:
                    snapshots.append(snap)
        return snapshots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kalshi_source.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/pulse/venue/kalshi.py tests/test_kalshi_source.py
git commit -m "feat(venue): KalshiSource filtering + normalization composition"
```

---

## Task 5: `poll_once` orchestrator + `PollReport`

**Files:**
- Create: `src/pulse/poller.py`
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: `SnapshotSource` (any), `Database`, `run_detection`, `pulse.models._now`.
- Produces: `PollReport(markets_seen: int, snapshots_stored: int, events: list[Event])`; `poll_once(source, db, *, now=None) -> PollReport`.

Note: per-market "unpriceable" skips are handled inside the source (those markets simply aren't returned); `PollReport` therefore reports `markets_seen` (snapshots the source produced) and `snapshots_stored` (newly inserted, post-idempotency) rather than a separate skip count.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poller.py
from datetime import datetime, timedelta, timezone

import pytest

from pulse.models import Snapshot, ValueKind
from pulse.poller import PollReport, poll_once
from pulse.store.db import Database

_T = datetime(2026, 6, 24, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


class FakeSource:
    """A SnapshotSource that returns a fixed list regardless of `now`."""

    venue = "kalshi"

    def __init__(self, snapshots):
        self._snapshots = snapshots

    def fetch_snapshots(self, now):
        return self._snapshots


def _snap(ts, value):
    return Snapshot("kalshi", "A", ts, value, ValueKind.PROBABILITY)


def test_poll_once_stores_snapshots_and_detects(db):
    # Two readings of market A: +15pts, crosses no milestone -> one odds_swing.
    source = FakeSource([_snap(_T, 0.55), _snap(_T + timedelta(minutes=10), 0.70)])
    report = poll_once(source, db)
    assert isinstance(report, PollReport)
    assert report.markets_seen == 2
    assert report.snapshots_stored == 2
    assert [e.rule for e in report.events] == ["odds_swing"]


def test_poll_once_is_idempotent_on_repeat(db):
    snaps = [_snap(_T, 0.55), _snap(_T + timedelta(minutes=10), 0.70)]
    poll_once(FakeSource(snaps), db)
    report = poll_once(FakeSource(snaps), db)  # identical data again
    assert report.snapshots_stored == 0   # nothing new ingested
    assert report.events == []            # dedup backstop -> no re-fire
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_poller.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pulse.poller'`.

- [ ] **Step 3: Write the orchestrator**

```python
# src/pulse/poller.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_poller.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/pulse/poller.py tests/test_poller.py
git commit -m "feat: venue-agnostic poll_once orchestrator + PollReport"
```

---

## Task 6: CLI `pulse poll`

**Files:**
- Create: `src/pulse/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `config`, `Database`, `KalshiClient`, `KalshiSource`, `poll_once`, `PollReport`.
- Produces: `cli(argv=None)` exposing the `poll` subcommand (entry point `pulse = pulse.main:cli`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from pulse import main
from pulse.poller import PollReport


def test_poll_command_runs_pipeline(monkeypatch):
    calls = {}

    class FakeDB:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            calls["connected"] = True

        def close(self):
            calls["closed"] = True

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def close(self):
            calls["client_closed"] = True

    def fake_poll_once(source, db, **k):
        calls["venue"] = source.venue
        return PollReport(markets_seen=2, snapshots_stored=2, events=[])

    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "KalshiClient", FakeClient)
    monkeypatch.setattr(main, "poll_once", fake_poll_once)

    main.cli(["poll"])

    assert calls["connected"] is True
    assert calls["venue"] == "kalshi"
    assert calls["client_closed"] is True
    assert calls["closed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_main.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pulse.main'`.

- [ ] **Step 3: Write the CLI**

```python
# src/pulse/main.py
"""CLI entry point. `pulse poll` runs one detect cycle against live Kalshi data (dryrun)."""

from __future__ import annotations

import argparse
import logging

from pulse import config
from pulse.poller import poll_once
from pulse.store.db import Database
from pulse.venue.kalshi import KalshiClient, KalshiSource

log = logging.getLogger("pulse")


def _run_poll() -> None:
    db = Database(config.DB_PATH)
    db.connect()
    try:
        client = KalshiClient()
        try:
            report = poll_once(KalshiSource(client), db)
        finally:
            client.close()
    finally:
        db.close()
    log.info(
        "poll complete (mode=%s): %d markets, %d new snapshots, %d events",
        config.PULSE_MODE, report.markets_seen, report.snapshots_stored, len(report.events),
    )
    for ev in report.events:
        log.info("  [%s] %s", ev.rule, ev.headline)


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pulse")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("poll", help="Fetch Kalshi data, store snapshots, run detection (no publish).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "poll":
        _run_poll()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_main.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the FULL suite**

Run: `.venv/bin/pytest -q`
Expected: PASS (all chunk-1 and chunk-2 tests green, no warnings).

- [ ] **Step 6: Commit**

```bash
git add src/pulse/main.py tests/test_main.py
git commit -m "feat: pulse poll CLI wiring the one-shot cycle"
```

---

## End-to-end verification (after Task 6)

Confirm the slice works against real Kalshi public data, in dryrun, no publish:

```bash
PULSE_MODE=dryrun .venv/bin/pulse poll
```

Expected: log line `poll complete (mode=dryrun): N markets, M new snapshots, K events`, possibly followed by `[rule] headline` lines. Then verify rows landed:

```bash
.venv/bin/python -c "from pulse.store.db import Database; from pulse import config; \
db=Database.connect_readonly(config.DB_PATH); \
print('snapshots:', db.conn.execute('SELECT COUNT(*) FROM market_snapshots').fetchone()[0]); \
print('posted:', db.conn.execute('SELECT COUNT(*) FROM posted_events').fetchone()[0])"
```

Expected: a non-zero snapshot count. (If the live category strings differ from `PULSE_CATEGORIES`, the count is 0 — adjust the allowlist to match Kalshi's actual `category` values and re-run. This is the one impl-time value to verify against the live API.)

---

## Self-review notes

- **Spec coverage:** client (T3), normalizer (T2), source/filter (T4), poll_once+report (T5), CLI (T6), config (T1), `SnapshotSource` seam (T1), error handling/retries (T3), testing-at-boundaries (MockTransport in T3, fake source/client in T4–T6). Covered.
- **Deviation from spec:** `PollReport` drops the `skipped` field — unpriceable skips are an internal concern of the source (it returns only usable snapshots) and surfacing them would require widening the `SnapshotSource` seam beyond `list[Snapshot]`. Documented in Task 5. If a skip metric is wanted later, add structured logging inside `KalshiSource`.
- **Type consistency:** `market_to_snapshot(raw, category, now)`, `KalshiClient.iter_open_events()`, `KalshiSource.fetch_snapshots(now)`, `poll_once(source, db)`, `PollReport(markets_seen, snapshots_stored, events)` are used identically across tasks.
- **Live-API unknowns:** exact Kalshi `category` strings and the market `status` value for tradeable markets ("active" assumed) are verified in the end-to-end step; everything else is exercised by unit tests with canned data.
```
