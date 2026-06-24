"""Central configuration — all tunable parameters in one place.

Credentials and mode come from the environment (.env, never committed).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ── Mode ──
# Start in dry-run: detect events and draft posts, but DO NOT publish. Flip to "live" only
# after reviewing the generated copy.
PULSE_MODE = os.environ.get("PULSE_MODE", "dryrun").lower()  # "dryrun" | "live"

# ── Bluesky (atproto) ──
BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "")

# ── Claude (post copy only — never the detector) ──
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
WRITER_MODEL = "claude-haiku-4-5-20251001"  # cheap; this is a language task, low volume

# ── Persistence ──
DB_PATH = os.environ.get("PULSE_DB_PATH", "prediction_pulse.db")

# ── Detector thresholds (starting points — tune from real data) ──
MIN_ODDS_MOVE = 0.10          # post when an event's probability moves >= 10 points
MIN_VOLUME_SPIKE = 3.0        # ... or volume spikes >= 3x its recent average

# ── Cadence ──
MAX_POSTS_PER_DAY = 8         # rate cap so the feed stays signal, not spam
