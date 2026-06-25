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
