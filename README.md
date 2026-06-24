# prediction-pulse

A faceless, data-driven **prediction-market content engine**. A deterministic pipeline
detects interesting prediction-market events (odds swings, volume spikes, milestones, notable
new markets) from free data, Claude writes a punchy + accurate post, and it publishes to
**Bluesky** (with a pluggable interface for cross-posting to X / Threads / Mastodon later).

The point isn't generating text — anyone can do that. It's owning a **data → insight**
pipeline in a niche where the data is genuinely shareable, and measuring what travels before
spending on scale or chasing monetization.

Status: **scaffold only.** See `CLAUDE.md` for the design brief and the open items to resolve
first.

## Setup
```bash
virtualenv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env   # fill in Bluesky app password + Anthropic key
.venv/bin/pytest
```

Starts in `PULSE_MODE=dryrun` — it will detect events and draft posts but not publish.
