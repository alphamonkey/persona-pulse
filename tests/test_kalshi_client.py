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
