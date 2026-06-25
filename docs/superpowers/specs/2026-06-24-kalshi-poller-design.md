# Kalshi Poller / Adapter — Design

**Date:** 2026-06-24
**Status:** Approved (pending spec review)
**Chunk:** 2 of the prediction-pulse pipeline (follows the detector core).

## Context

The detector core (chunk 1) is pure and reads normalized `Snapshot`s from a WAL store, but
nothing yet *feeds* it real data. This chunk builds the piece that fetches live Kalshi public
market data, normalizes it into `Snapshot`s, stores them, and runs detection — a runnable
end-to-end slice in `PULSE_MODE=dryrun` (no publishing).

It is **read-only, unauthenticated public data only** (no trading exposure). kalshi-edge's
`KalshiREST` is deliberately *not* reused: it is built on the `kalshi_python_sync` SDK with
PEM/RSA auth and a full trading surface, and requires credentials — the wrong shape here. We
reuse its *idioms* (one isolated venue module, thin typed wrapper, `_quote` dollars/cents
fallback) on top of `httpx` (already a dependency).

## Goal / outcome

`pulse poll` performs one cycle: fetch active Kalshi markets in allowlisted categories above a
volume floor → normalize → store snapshots → run the detector → log a report. Detected events are
logged only (dryrun); publishing is a later chunk.

## Architecture & module layout

Kalshi-specific code stays behind a tiny venue-agnostic seam so future venues (Polymarket, NYSE,
crypto) are just new sources — consistent with the project's normalized-`Snapshot` architecture.

```
src/pulse/venue/
  base.py      # SnapshotSource Protocol: `venue: str`; `fetch_snapshots(now) -> list[Snapshot]`
  kalshi.py    # KalshiClient (httpx I/O) + market_to_snapshot (pure) + KalshiSource
src/pulse/poller.py   # poll_once(source, db) -> PollReport   (venue-agnostic orchestrator)
src/pulse/main.py     # cli(): `pulse poll` one-shot (pyproject already maps pulse = pulse.main:cli)
```

- **`SnapshotSource`** (Protocol, `venue/base.py`): `venue: str`, `fetch_snapshots(now: datetime)
  -> list[Snapshot]`. The single seam `poll_once` depends on.
- **`KalshiClient`** (`venue/kalshi.py`): wraps `httpx.Client`, base
  `https://api.elections.kalshi.com/trade-api/v2`, **no auth header**. Cursor pagination, request
  timeout, bounded exponential-backoff retry on HTTP 429/5xx. Returns raw dicts. Only Kalshi I/O.
- **`market_to_snapshot(raw, category, now)`** (`venue/kalshi.py`, **pure**): Kalshi market dict →
  `Snapshot | None`. The heavily-tested mapping logic; folded into `kalshi.py` because it is
  Kalshi-specific (per approved decision).
- **`KalshiSource`** (`venue/kalshi.py`): implements `SnapshotSource`; composes client +
  `market_to_snapshot`; applies the category allowlist + volume floor; `venue = "kalshi"`.
- **`poll_once(source, db)`** (`poller.py`): venue-agnostic — `fetch_snapshots` → `insert_snapshot`
  (idempotent) → `run_detection(db, source.venue)` → return `PollReport`.

## Data flow (`pulse poll`)

1. `KalshiSource.fetch_snapshots(now)` pages `GET /events?status=open&with_nested_markets=true`.
   Keep events whose **`category` ∈ `PULSE_CATEGORIES`**; for each nested market that is **active**
   and has **`volume_24h ≥ MIN_MARKET_VOLUME_24H`**, call `market_to_snapshot`.
   (Category is not reliably present on the market object, so it is read from the event and
   filtered client-side — robust, at the cost of fetching all open events then trimming.)
2. `poll_once` inserts each `Snapshot` (dedup on `(venue, market_id, ts)`), then
   `run_detection(db, "kalshi")`.
3. dryrun: log the `PollReport` (markets seen / snapshots stored / events detected + headlines).
   No publish.

`PollReport` (dataclass): `markets_seen: int`, `snapshots_stored: int`, `skipped: int`,
`events: list[Event]`.

## Normalization rules (`market_to_snapshot`)

- **value**: `last_price/100` when `last_price > 0`; else midpoint `((yes_bid + yes_ask)/2)/100`
  when both sides present; else **return None (skip — unpriceable)**. A `_quote` helper prefers
  `*_dollars` fields and falls back to integer-cents, mirroring kalshi-edge.
- **value_kind**: `PROBABILITY`. **volume**: cumulative `volume` (contracts).
- **meta** (`MarketMeta`): `title`; `status`; `resolution_date` ← `close_time`; `category`
  (from the event); `extra` ← `{event_ticker, series_ticker, volume_24h}`.
- **ts**: the poll's `now` (aware UTC), passed in for determinism/testability.

## Error handling

- Per-request timeout; bounded exponential-backoff retry on 429/5xx. A persistent fetch failure
  raises, so the one-shot CLI exits non-zero and logs the cause.
- A single malformed or unpriceable market is skipped and counted (`PollReport.skipped`), never
  crashing the cycle.
- Public endpoints only — no credentials, nothing secret to leak.

## Config additions (`src/pulse/config.py`)

- `KALSHI_API_HOST = "https://api.elections.kalshi.com/trade-api/v2"`
- `PULSE_CATEGORIES` — allowlist (e.g. Politics, Economics, Companies, Financials,
  Science & Technology). Exact Kalshi category strings verified against the live API at impl.
- `MIN_MARKET_VOLUME_24H` — starting volume floor (tune from data).
- `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_RETRIES` — client resilience knobs.

## Testing (TDD; mock only at boundaries)

- **`tests/test_normalize.py`** (pure): last_price→value; mid fallback; skip when neither;
  cents vs `*_dollars`; volume + meta + `close_time`→`resolution_date` mapping; value_kind.
- **`tests/test_kalshi_client.py`**: `httpx.MockTransport` (real client code, fake network) —
  cursor pagination followed across pages; correct params/URL; **no Authorization header**;
  retry/backoff on 429/5xx; timeout surfaced.
- **`tests/test_poller.py`**: inject a fake `SnapshotSource` + real temp DB + real detector —
  `poll_once` stores snapshots, runs detection, returns an accurate report; idempotent re-poll
  (identical data → no new snapshots, no new events); filtering applied; unpriceable skipped.
- **`tests/test_main.py`** (light): `pulse poll` wiring builds the source + db, calls `poll_once`,
  logs the report.

**End-to-end verification:** unit suite green; then a real one-shot `pulse poll` against live
Kalshi public data in dryrun — confirm snapshots land in the DB and any detected events are logged,
with no publish attempted.

## Out of scope (later chunks)

Scheduler/cadence loop (systemd, intervals, signal handling); the writer + news/context; publish
to Bluesky; the dashboard. `poll_once` is the unit the future scheduler will call on a cadence.
