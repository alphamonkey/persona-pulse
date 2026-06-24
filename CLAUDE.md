# CLAUDE.md — prediction-pulse

> Handoff brief for this project. This repo was scaffolded from the `kalshi-edge` session;
> it is a SEPARATE project. Start by brainstorming/confirming the open items below, then
> build with TDD.

## What it is
A faceless, data-driven finance/markets content bot. A **deterministic pipeline** detects
"interesting" prediction-market events; **Claude writes** a punchy, accurate post; it
publishes to **Bluesky first** (free, full read+write API so traction is measurable),
architected for easy cross-posting (X free tier, Threads/Mastodon) later. **MVP goal:**
validate that data-driven prediction-market content gets organic pull — measure engagement,
iterate. Monetization (affiliate / sponsor / newsletter funnel) is deferred until traction.

## Why this shape
- **Moat = data + distribution, not generation.** Prediction-market odds are newsy/shareable
  and not saturated; leverages the operator's finance edge; uses free Kalshi public data
  (read-only — no trading-strategy exposure).
- Mirrors `kalshi-edge` discipline: **deterministic core; LLM only for the judgment/language
  task**; cheap; measure-before-scale (a content "shadow phase").

## Architecture (MVP) — `src/pulse/`
- **detector/** — deterministic rules over free data (Kalshi public API; later Polymarket /
  sports odds): big odds swings, volume spikes, round-number milestones, notable new markets. Pure, TDD.
- **writer/** — Claude (cheap model) turns a detected event + context into a post; optional odds chart.
- **publish/** — pluggable publishers; **Bluesky** first (atproto app-password API); one
  interface so X / Threads / Mastodon drop in. **Idempotent** — never double-post the same event.
- **store/** — SQLite + WAL: posted-events log (idempotency) + engagement metrics for the feedback loop.
- **scheduler/** — cadence (a few posts/day + a daily digest); systemd, like kalshi-edge.
- **dashboard/** (optional) — reuse kalshi-edge's FastAPI + static pattern.

## Reuse from kalshi-edge (`/home/pi/Projects/kalshi-edge`)
`KalshiREST` public-data client (`src/edge/venue/rest.py`); Python 3.13 + `virtualenv`;
SQLite+WAL idempotency patterns (`src/edge/core/db.py`); systemd deploy (`deploy/`);
dashboard pattern (`src/edge/server/`). **Copy what helps, don't couple** — separate repo.

## Conventions
- **Never commit `.env`** (Bluesky app password, Anthropic key) or `*.db`.
- **Real data only — never fabricate numbers.** Finance content: avoid "financial advice";
  include light "not advice" framing. No agriculture / food topics.
- **Start in `PULSE_MODE=dryrun`** (detect + write, do NOT publish); flip to `live` only after
  reviewing generated posts.
- **TDD**: tests-first on the detector (pure) and the idempotent store; mock Bluesky/Claude
  at their boundaries.

## Open items to resolve first (brainstorm before building)
1. Content angle — **recommended: prediction-market moves**; confirm or broaden.
2. Brand / handle; posting cadence; which cross-post targets after Bluesky.
3. Create a Bluesky account + App Password; private GitHub repo (gh is authed as `alphamonkey`).

## Setup
```bash
virtualenv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env   # fill in Bluesky + Anthropic
.venv/bin/pytest
```
