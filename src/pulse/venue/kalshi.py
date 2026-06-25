"""Kalshi public-data adapter: HTTP client, pure normalizer, and SnapshotSource.

Read-only and unauthenticated — only public market/event endpoints. The normalizer maps
a raw Kalshi market dict into the shared Snapshot seam; it is pure and the most-tested part.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import datetime

import httpx

from pulse.config import HTTP_MAX_RETRIES, HTTP_TIMEOUT_SECONDS, KALSHI_API_HOST
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
