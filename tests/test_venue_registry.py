"""Source registry: [pipeline.poll] sources resolve by name to SnapshotSource builders."""

from __future__ import annotations

import pytest

from pulse.venue.kalshi import KalshiClient, KalshiSource
from pulse.venue.registry import make_source
from pulse.venue.trending import BlueskyTrendSource


@pytest.fixture
def client():
    c = KalshiClient()
    yield c
    c.close()


def test_kalshi_source(client):
    assert isinstance(make_source("kalshi", client), KalshiSource)


def test_trend_source(client):
    assert isinstance(make_source("trend", client), BlueskyTrendSource)


def test_unknown_source_names_the_known_ones(client):
    with pytest.raises(ValueError, match="rss.*kalshi.*trend"):
        make_source("rss", client)
