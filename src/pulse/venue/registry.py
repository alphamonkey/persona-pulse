"""Source registry: resolve a [pipeline.poll] source name to a SnapshotSource.

The groundwork for "get *something* to post about": a new content source (news, RSS, another
venue) is one builder registered here — the poll job, store, and detector are unchanged as long
as it yields normalized Snapshots.
"""

from __future__ import annotations

from pulse import config
from pulse.venue.base import ContentSource, SnapshotContentSource, SnapshotSource
from pulse.venue.kalshi import KalshiClient, KalshiSource
from pulse.venue.trending import BlueskyTrendClient, BlueskyTrendSource


def _kalshi(client: KalshiClient) -> SnapshotSource:
    return KalshiSource(client)


def _trend(client: KalshiClient) -> SnapshotSource:
    return BlueskyTrendSource(
        BlueskyTrendClient(config.bluesky_handle(), config.bluesky_app_password()), client)


_BUILDERS = {
    "kalshi": _kalshi,  # broad category-allowlist poll
    "trend": _trend,    # Bluesky-trend-selected markets
}


def make_source(name: str, kalshi_client: KalshiClient) -> ContentSource:
    try:
        builder = _BUILDERS[name]
    except KeyError:
        known = ", ".join(sorted(_BUILDERS))
        raise ValueError(f"unknown snapshot source {name!r} (known: {known})") from None
    return SnapshotContentSource(builder(kalshi_client))
