"""The prune cycle as a `prune_once` function + `PruneJob` (mirrors poller.py)."""

from datetime import datetime, timedelta, timezone

from pulse.pruner import PruneJob, prune_once

_T = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)


class FakeDB:
    def __init__(self):
        self.cutoff = None
        self.reclaimed = False

    def prune_snapshots(self, before):
        self.cutoff = before
        return 42

    def reclaim(self):
        self.reclaimed = True


def test_prune_once_cutoff_is_now_minus_retention():
    db = FakeDB()
    report = prune_once(db, now=_T, retention_days=7)
    assert db.cutoff == _T - timedelta(days=7)
    assert report.deleted == 42
    assert db.reclaimed is True


def test_prune_job_runs_and_reports():
    db = FakeDB()
    report = PruneJob(db, retention_days=7).run()
    assert PruneJob.name == "prune"
    assert report.deleted == 42
    assert db.reclaimed is True
