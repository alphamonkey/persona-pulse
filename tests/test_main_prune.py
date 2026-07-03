"""`pulse prune` / `pulse vacuum` CLI wiring."""

from __future__ import annotations

from pulse import main


class FakeDB:
    last = None

    def __init__(self, *a, **k):
        FakeDB.last = self
        self.pruned_before = None
        self.vacuumed = False
        self.reclaimed = False

    def connect(self):
        pass

    def close(self):
        pass

    def prune_snapshots(self, before):
        self.pruned_before = before
        return 7

    def reclaim(self):
        self.reclaimed = True

    def vacuum(self):
        self.vacuumed = True


def test_prune_command_prunes_with_retention(monkeypatch):
    monkeypatch.setattr(main, "Database", FakeDB)
    main.cli(["prune", "--retention-days", "7"])
    assert FakeDB.last.pruned_before is not None
    assert FakeDB.last.reclaimed is True


def test_vacuum_command_calls_vacuum(monkeypatch):
    monkeypatch.setattr(main, "Database", FakeDB)
    main.cli(["vacuum"])
    assert FakeDB.last.vacuumed is True
