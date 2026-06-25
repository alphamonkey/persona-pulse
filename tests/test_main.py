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
