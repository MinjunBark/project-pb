# GTM Signal Engine

A signal-driven lead qualification pipeline: it watches for companies that just raised funding **and/or** are hiring Product Managers **and/or** just launched a product **and/or** are showing intent by griping about a named competitor on G2 — scores the overlap, and for anything that clears the bar, automatically writes a CRM record, generates signal-specific outreach copy, and notifies the team. A human-in-the-loop Clay enrichment step (real domain/firmographic backfill, no live API on the free tier) runs fully asynchronously — request it, do the manual Clay work whenever, drop the file back into Discord, and the pipeline auto-resumes on its own with zero re-trigger.

Built as a hands-on portfolio project mapping to a GTM/Growth Engineer job description's actual stack: **Clay, HubSpot, Postgres/Supabase, Python, REST APIs, Discord, and an AI-enabled GTM workflow.**

## Why this exists

Most "lead scoring" demos hardcode a static ICP (industry, headcount, title). This one is signal-driven: it only prioritizes companies where multiple *independent, time-sensitive* things are true at once — right after a funding event, while actively hiring, ideally while complaining about a specific competitor by name. That overlap is a much stronger buying-window signal than any static firmographic list, and scoring it honestly (see `docs/DECISIONS.md`) means most days it correctly finds **zero** qualifying leads — a real, deliberate outcome of a strict multi-signal model, not a bug. When 0 qualified leads kept happening, the instinct to push back on that (rather than just accept it, or worse, lower the bar to fabricate a quota) led to real root-cause fixes documented in `docs/ISSUES.md` — a bad-data filter three layers upstream of scoring, and a scoring miscalibration against a stale ICP definition, both caught and fixed the same day they were found.

## Current architecture (as of the Redesign v2 rebuild)

n8n orchestration is **paused/excluded** — real SDR feedback that funding+hiring alone was "the basic approach" every off-the-shelf sales tool already does. In its place, the whole pipeline runs live, in-process, fully observable through Discord:

```
POST /pipeline/run-full-cycle
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│  Branch A: SEC EDGAR    Branch B: Adzuna +      Branch D: Product   │
│  Form D filings         Greenhouse/Lever         Hunt launches       │
│  (funding, TIMING)      (hiring, TIMING —        (TIMING)            │
│                         staffing-agency filtered)                    │
└──────────────────────────────┬────────────────────────────────────┘
                                ▼
                  Merge/Dedupe → Supabase (Postgres)
                                │
                                ▼
          Clay enrichment pickup + request (human-in-the-loop,
          fully async — see below)
                                │
                                ▼
          Leadership-page diffing (new decision-maker hire, TIMING)
                                │
                                ▼
          Score every company (TIMING + INTENT + DEMOGRAPHIC buckets)
                                │  score >= 70?
                                ▼
        Dedupe (Postgres window + HubSpot) → Gemini outreach copy
        → HubSpot company write → Google Sheet row → Discord notification

  Branch C (G2 competitor reviews, INTENT) — opt-in only, real Apify
  cost, demand-driven by what Branch B actually found mentioned this run
```

Every phase reports live to a single, edit-in-place Discord message (`#ops-progress`) — a real text progress bar, not a stream of separate messages. A separate `#sdr-digest` channel gets the final daily summary (qualified leads + a "top prospects to watch" list, so the digest never looks empty even at 0 qualified).

### Clay enrichment — fully async human-in-the-loop

Clay's free tier has no live webhook trigger, so domain/firmographic enrichment is a manual export→Clay→import round-trip — but the pipeline never blocks waiting for it. When enrichment is needed, it's requested via `#clay-enrichment` (a real CSV attached). The user does the manual Clay work on their own timeline, then drops the result back either as a local file **or a real Discord upload** — a real bot (`utils/discord_bot.py`) watches the channel and auto-detects it, same as a 60-second background poller as a fallback. Either path auto-imports the data and automatically re-runs scoring + the SDR digest, with zero manual re-trigger required.

## Signal branches

| Branch | Source | Signal | Cost |
|---|---|---|---|
| A | SEC EDGAR Form D filings | Funding event (TIMING) | Free, no key |
| B | Adzuna + Greenhouse/Lever | PM hiring activity (TIMING) + competitor-tool mentions/buying-intent language (INTENT) | Free, no key |
| C | G2 reviews (Apify) | Competitor pain points (INTENT) | Real cost per call — opt-in, demand-driven |
| D | Product Hunt | New product launches (TIMING) | Free, developer token |
| — | Company leadership pages | New decision-maker hire (TIMING) | Free (direct fetch + Gemini extraction) |

## Scoring

`python/scoring.py` — weighted TIMING (max 50) + INTENT (max 40) + DEMOGRAPHIC (max 10) buckets, a +10 bonus for hitting both TIMING and INTENT on the same company, deductions for existing customers or implausibly tiny companies, threshold **>= 70** to qualify. Every score returns a `score_breakdown` so the reasoning is inspectable, not a black box.

The DEMOGRAPHIC/DEDUCTIONS thresholds were recalibrated mid-build against this project's own real ICP research (`redesign/01-trigger-prompt-filled-productboard.md`) after the original assumed thresholds (50-500 employees, SaaS-only) turned out to penalize every one of Productboard's real named customers (Autodesk, Salesforce, Zoom, Ubisoft, Medtronic, OutSystems — 1,800 to 95,000 employees, spanning non-SaaS industries). Full story in `docs/ISSUES.md`.

## Output fan-out (what happens when something qualifies)

All in `python/pipeline.py`'s `process_qualified_lead()`:
1. Dedup check (Postgres recency window, then HubSpot "recently contacted")
2. Gemini-generated outreach copy (email x2 subject lines, body, LinkedIn message, call script, priority summary) — pulls real G2 pain-point quotes, buying-intent language, or leadership-hire/launch context into the copy depending on which real signals fired
3. HubSpot company create/update (12 custom properties, created programmatically)
4. Google Sheet row (CRM-style tracking sheet)
5. Discord notification (color-coded by signal type: green=BOTH, yellow=TIMING, blue=INTENT)

## Repo layout

```
api/main.py            FastAPI service — /pipeline/run-full-cycle, plus a background
                        asyncio poller and a real Discord bot launched at startup
python/                One module per pipeline stage: funding_edgar, hiring_adzuna,
                        hiring_ats_lookup, hiring_signals, producthunt_launches,
                        leadership_monitor, intent_g2, merge_signals, scoring,
                        classify, enrichment, outreach, pipeline, full_pipeline_run
utils/                 Shared clients — db, gemini, hubspot, sheets, discord_webhooks
                        (outbound notifications + the live progress bar), discord_bot
                        (inbound Clay-upload watcher)
sql/                   schema.sql (Postgres/Supabase schema) + queries.sql (reporting)
tests/                 293 pytest cases, one file per module
data/                  raw/ (landed signal snapshots), clay/ (enrichment round-trip
                        folders — incoming_enrichment/, processed/)
docs/                  DECISIONS.md (ADRs), ISSUES.md (real bugs + fixes), PROGRESS.md
                        (phase log), CODE_GUIDE.md (plain-language walkthrough),
                        HANDOFF.md (resume-from-scratch snapshot), INTERVIEW_TALKING_POINTS.md
redesign/               Research trail behind Redesign v2 — trigger-prompt ICP research,
                        signal catalog, creative signal approaches, architecture diagram
gtm-signal-blueprint.md       Original spec (frozen, unedited — the plan as first written)
gtm-signal-blueprint-v2.md    As-built synthesis (what changed from the original, and why)
```

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env    # fill in real keys — see comments in the file for what's free vs. paid
python3 -m pytest       # 293 tests, all mocked, no real API calls
uvicorn api.main:app --reload --port 8000
```

Health check: `curl http://localhost:8000/health`

Trigger a real full live run: `curl -X POST http://localhost:8000/pipeline/run-full-cycle -d '{}'` — watch `#ops-progress` in Discord for the live progress bar.

## Documentation map

Start with `docs/HANDOFF.md` if resuming work cold — it's overwritten at the end of every phase with an exact "resume from here" snapshot. For the "why," not just the "what": `docs/DECISIONS.md` (every ADR) and `docs/ISSUES.md` (every real bug hit, and how it was found/fixed — including two same-day catches: a crash-loop bug from a real Clay data mismatch, and a scoring miscalibration against a stale ICP definition that was corrected only after being called out directly) are the actual interview material — most of what's interesting about this build is in the tradeoffs and dead ends recorded there, not the final code.
