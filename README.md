# GTM Signal Engine

A signal-driven lead qualification pipeline: it watches for companies that just raised funding **and** are hiring Product Managers **and/or** are showing intent by griping about a named competitor on G2 — scores the overlap, and for anything that clears the bar, automatically writes a CRM record, generates signal-specific outreach copy, and notifies the team.

Built as a hands-on portfolio project mapping to a GTM/Growth Engineer job description's actual stack: **n8n, Clay, HubSpot, Postgres, Python, REST APIs, and an AI-enabled GTM workflow.**

## Why this exists

Most "lead scoring" demos hardcode a static ICP (industry, headcount, title). This one is signal-driven: it only prioritizes companies where multiple *independent, time-sensitive* things are true at once — right after a funding event, while actively hiring, ideally while complaining about a specific competitor by name. That overlap is a much stronger buying-window signal than any static firmographic list, and scoring it honestly (see `docs/DECISIONS.md`, ADR-014) means most days it correctly finds **zero** qualifying leads — which is a feature of a strict multi-signal model, not a bug (see `docs/ISSUES.md`, "A live Branch B run + full re-score found zero real qualifying companies").

## Architecture

```
                    ┌─────────────────┐         ┌──────────────────────┐
   Daily 08:00 UTC  │ Branch A: SEC    │         │ Branch B: Adzuna +   │
   ────────────────▶│ EDGAR Form D     │         │ Greenhouse/Lever     │
                     │ (funding signal) │         │ (hiring signal)      │
                     └────────┬─────────┘         └───────────┬──────────┘
                              │                                │
                              └──────────────┬─────────────────┘
                                              ▼
                                     ┌─────────────────┐
                                     │  Merge/Dedupe    │
                                     │  (Postgres/      │
                                     │   Supabase)       │
                                     └────────┬─────────┘
                                              ▼
                                     ┌─────────────────────────┐
                                     │  Score every company     │
                                     │  (TIMING + INTENT +      │
                                     │   demographic buckets)   │
                                     └────────┬─────────────────┘
                                              │  score >= 70?
                                              ▼
                          ┌───────────────────────────────────┐
                          │  Dedupe (Postgres window + HubSpot)│
                          │  → Gemini outreach generation      │
                          │  → HubSpot company write            │
                          │  → Google Sheet row                 │
                          │  → Discord notification              │
                          └───────────────────────────────────┘

   Weekly Mon 08:00 UTC  ┌──────────────────┐      ┌─────────────────┐
   ─────────────────────▶│ Branch C: G2      │─────▶│ Merge (recompute │
   (real Apify cost)      │ competitor        │      │ competitor_intel │
                          │ review scraping   │      │ from full history)│
                          └──────────────────┘      └─────────────────┘
```

**Orchestration is n8n** (`GTM Signal Engine` workflow, n8n.cloud) calling a thin FastAPI service (`api/main.py`) that wraps already-tested Python — n8n orchestrates the sequence, it does not reimplement any scoring/outreach/merge logic itself (see ADR-022/023 in `docs/DECISIONS.md`).

## Signal branches

| Branch | Source | Signal | Cost |
|---|---|---|---|
| A | SEC EDGAR Form D filings | Funding event (TIMING) | Free, no key |
| B | Adzuna + Greenhouse/Lever | PM hiring activity (TIMING) | Free, no key |
| C | G2 reviews (Apify) | Competitor pain points (INTENT) | Real cost per call — runs weekly, not daily |

## Scoring

`python/scoring.py` — weighted TIMING + INTENT + demographic buckets, a bonus for hitting both TIMING and INTENT on the same company, threshold **>= 70** to qualify. Every score returns a `score_breakdown` so the reasoning is inspectable, not a black box. Full rationale for every scoring decision: `docs/DECISIONS.md` ADR-014.

## Output fan-out (what happens when something qualifies)

All in `python/pipeline.py`'s `process_qualified_lead()`:
1. Dedup check (Postgres recency window, then HubSpot "recently contacted")
2. Gemini-generated outreach copy (email x2 subject lines, body, LinkedIn message, call script, priority summary) — pulls real G2 pain-point quotes into the copy when the lead's current tool is known
3. HubSpot company create/update (12 custom properties, created programmatically)
4. Google Sheet row (CRM-style tracking sheet)
5. Discord notification (color-coded by signal type: green=BOTH, yellow=TIMING, blue=INTENT)

## Repo layout

```
api/main.py           FastAPI service — the surface n8n actually calls
python/                One module per pipeline stage (funding_edgar, hiring_signals,
                        intent_g2, merge_signals, scoring, classify, outreach, pipeline)
utils/                 Shared clients (db, gemini, hubspot, sheets, discord)
sql/                   schema.sql (Postgres/Supabase schema) + queries.sql (reporting)
tests/                 167 pytest cases, one file per module
docs/                  DECISIONS.md (ADRs), ISSUES.md (bugs + fixes), PROGRESS.md
                        (phase log), TASKS.md (checklist), CODE_GUIDE.md (plain-language
                        walkthrough), HANDOFF.md (resume-from-scratch snapshot),
                        INTERVIEW_TALKING_POINTS.md
gtm-signal-blueprint.md      Original spec (frozen, unedited — the plan as first written)
gtm-signal-blueprint-v2.md   Final as-built architecture (what actually got built, and why it differs)
```

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env    # fill in real keys — see comments in the file for what's free vs. paid
python3 -m pytest       # 167 tests, all mocked, no real API calls
uvicorn api.main:app --reload --port 8000
```

Health check: `curl http://localhost:8000/health`

To let n8n.cloud reach a local `api/main.py`, tunnel it publicly (e.g. `ngrok http 8000`) and wire the tunnel URL into the n8n workflow's HTTP Request nodes — `localhost` is not reachable from n8n.cloud. See `docs/HANDOFF.md` for the current live tunnel setup and its known fragility (free-tier ngrok URLs aren't stable across restarts).

## Documentation map

Start with `docs/HANDOFF.md` if resuming work cold. For the "why," not just the "what": `docs/DECISIONS.md` (23 ADRs) and `docs/ISSUES.md` (every real bug hit and how it was found/fixed) are the actual interview material — most of what's interesting about this build is in the tradeoffs and dead ends recorded there, not the final code.
