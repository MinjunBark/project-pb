# Session Handoff

> Owns: a resume-from-scratch snapshot only. This file is **overwritten** at the end of every phase, not appended to — history lives in PROGRESS.md (phase log) and ISSUES.md (bugs). If you're picking this project back up cold, read this file first, then follow its pointers.

**Last updated:** 2026-07-13 — Live single-message progress bar built + live-verified; project cleaned up + README rewritten for the interview; real re-enrichment-waste bug diagnosed (fix designed, deliberately deferred - see below) (note: `notes.md` shows Round 2 is scheduled **today**, 2026-07-13 — this project needs to be interview-ready now, not just eventually).

## Where we are right now
The original build (Phases 0-10) is complete. n8n orchestration remains paused/excluded. In its place, `python/full_pipeline_run.py` + `POST /pipeline/run-full-cycle` is the real, manual, Discord-visible entry point for running the entire pipeline live. Redesign v2 has gone through 6 tiers plus several same-day follow-on corrections, all built, tested, and live-verified:

- **Tiers 1-6** (signal capture, Discord ops-progress/SDR-digest, demand-driven Branch C, Clay human-in-the-loop, real Discord bot) — see `docs/PROGRESS.md` for full history.
- **Staffing-agency filter** (`hiring_adzuna.py`) — real root-cause fix for 0-qualified-leads.
- **Clay enrichment consolidated** into one round-trip (was two - domain-only, demographics-only).
- **`scoring.py` recalibrated** against this project's own real-researched ICP (not the stale original blueprint) - removed the employee_count>1000 and is_saas-is-False deductions.
- **Live progress bar** (this session's newest work) - see below.

## Live, single-message progress bar for #ops-progress (2026-07-13)
The user asked why `#ops-progress` gets ~10-15 separate messages per run instead of one live-updating status. Built and live-verified:

- `utils/discord_webhooks.py`: `send_progress_bar_update(current_step, total_steps, label, message_id=None)` - posts with `?wait=true` to capture the real Discord message id, or `PATCH`es that same message in place on later calls. No new credentials needed.
- `python/full_pipeline_run.py`: `ProgressTracker` class wraps one live-editing message per run. `FULL_RUN_TOTAL_STEPS=12`, `AUTO_RESUME_TOTAL_STEPS=5` - every phase (including skipped/no-op ones) always advances exactly once, so the bar always reaches a clean 100%.
- Also reworded the merge-complete message to explicitly say "Supabase updated" with real per-branch counts (the user asked why this wasn't explicit - it was real data, just generically worded).
- **293/293 tests passing.** Live-verified: triggered a real foreground full run + a concurrent poller-triggered auto-resume at the same time - confirmed via Discord's REST API each got exactly one message, editing in place 0% → 100%, never spawning a second message mid-run.

**Also answered (no code needed):** why a full run finishes before Clay enrichment is submitted - by design, the request phase never blocks on the human round-trip (could take hours); the separate auto-resume path (60s poller or bot) picks it up whenever it actually lands, async.

## Project cleanup (2026-07-13, same session)
Removed real clutter ahead of the interview: `__pycache__`/`.pytest_cache` build artifacts; two dead pre-consolidation Clay folders (`incoming_domain/`, `incoming_demographics/`); a stale one-off Apify test dump; an early superseded Phase 6 test export. Pruned `data/raw/` from 41 accumulated test-run files down to 4 (most recent of each type) and `data/clay/`'s loose export CSVs from 9 down to 4, **after explicit user confirmation** (the auto-mode safety classifier correctly blocked the first bulk-delete attempt as an irreversible action based on my own heuristic rather than explicit direction - asked via `AskUserQuestion`, got a clear answer, then executed). Removed a stray already-tracked test artifact (`data/clay/processed/x.csv`). **293/293 tests still pass after cleanup.**

**Left untouched, deliberately:** `gtm-signal-blueprint.md` (the original spec - real historical/interview value, explicitly "frozen and unedited" per `gtm-signal-blueprint-v2.md`'s own docstring) and `gtm-signal-blueprint-v2.md` (the real as-built synthesis) both kept - they tell the "here's what changed and why" story directly. `notes.md`/`job-description.md`/`notes/` (interview prep material) untouched. `docs/` (all 7 files) untouched - each still owns a distinct category.

## Discord channel map (all real, all wired)
| Channel | Env var | Purpose |
|---|---|---|
| Per-lead | `DISCORD_WEBHOOK_URL` | Real-time ping per qualifying lead |
| Ops-progress | `DISCORD_PROGRESS_WEBHOOK_URL` | Live single-message progress bar per run (edits in place) |
| Clay enrichment | `DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL` (outbound) + `DISCORD_BOT_TOKEN`/`DISCORD_CLAY_CHANNEL_ID` (inbound bot) | Requests posted out via webhook; real user uploads read back in via the bot |
| SDR digest | `DISCORD_SDR_DIGEST_WEBHOOK_URL` | Final daily summary + watchlist |

## What is NOT done yet — real next steps
- **[HIGH PRIORITY, diagnosed + designed, not built] Clay enrichment queue re-requests already-attempted companies forever**, wasting real Clay credits every round-trip - confirmed with real data (e.g. `UserFirst Software, Inc.` has a real `employee_count=29` from a past pass but still gets re-queued because `is_saas` stayed the honest-but-permanent `None`). Fix: add `enrichment_attempted_at` to `companies`, stop re-queuing once attempted (mirrors the existing `DEDUP_WINDOW_DAYS` pattern). Full design + open questions (cooldown vs. permanent exclusion) in `docs/ISSUES.md`'s newest entry. **User's explicit call to defer given interview timing - pick this up first next session.**
- **Still 0 qualified leads** - real max score is 45 (Anduril), still 25 short of 70. The real remaining lever is INTENT signal coverage (only ~6% real ATS match rate; `G2_API_TOKEN` still expired, blocking Branch C entirely; only 4 competitor names are ever regex-matched even when a match IS attempted - see the architecture Q&A below).
- **`redesign/04-current-architecture-diagram.md`** has notes at the top but the diagram body still reflects an earlier state - not redrawn.
- **The `Type`/`Annual Revenue`/`Locality` fields** Clay's Company Enrichment also returns are not captured (would need a schema change) - explicitly deferred.

## Real architecture Q&A (2026-07-13, user asked for a full walkthrough - saved here since it's genuinely useful reference, not just a one-off answer)
- **Branch B (hiring)**: Layer 1 (`hiring_adzuna.py`) searches Adzuna for literal keywords `"Product Manager"`/`"Product Operations"`, US, last 60 days, grouped by company name, staffing agencies filtered out. Layer 2 (`hiring_ats_lookup.py`) *guesses* a Greenhouse/Lever board URL from the company name (strip suffixes, try no-spaces/hyphenated) - only when that guess resolves does real job-description text exist to scan for the 4 tracked competitor names (regex only, no Gemini) or run Gemini's buying-intent classifier (on the single most recent posting only).
- **Branch D (launches)**: `producthunt_launches.py` queries Product Hunt's GraphQL API for products posted in the last 30 days, no keyword filter - company name comes from the product listing (a real, flagged match-rate uncertainty).
- **Leadership monitoring** (`leadership_monitor.py`, independent of Branch B/D): only for companies with a known `domain`. Tries 5 candidate URL paths, hashes the page content, only calls Gemini to extract a name when the hash changed since the last snapshot.
- **HubSpot**: the CRM destination for anything scoring ≥70 - 12 custom properties written/updated via `pipeline.py`.
- **Apify**: used in exactly one place, Branch C's G2 review scraping (`intent_g2.py`) - not involved anywhere else.
- **Real, corrected misconception**: there is no "Gemini deconstructs the job description for tech stack" phase. Tool-mention detection is pure regex against exactly 4 hardcoded competitor names; Gemini is only used for buying-intent language classification and leadership-name extraction.
- **Full script/module call order for a real run**: `full_pipeline_run.py` → `funding_edgar.py` → `hiring_signals.py` (→ `hiring_adzuna.py` → `hiring_ats_lookup.py`) → `producthunt_launches.py` → `intent_g2.py` (opt-in) → `merge_signals.py` → `enrichment.py` → `leadership_monitor.py` → `scoring.py` → `pipeline.py` (→ `outreach.py`, `utils/hubspot.py`, `utils/sheets.py`) → `utils/discord_webhooks.py` → `raw_landing.py`.

## Open questions waiting on the user
- Whether to pursue a fresh `G2_API_TOKEN` to unblock Branch C's competitor-review INTENT source.
- Direction for the n8n workflow redesign itself, if/when that resumes.

## Where to look for depth (don't duplicate it here)
- `docs/DECISIONS.md` — ADR-024 covers Redesign v2 in full
- `docs/PROGRESS.md` — phase-by-phase log, including today's entries
- `docs/ISSUES.md` — bugs found and fixed, including two consequential same-day corrections
- `redesign/01-trigger-prompt-filled-productboard.md` — the REAL, current ICP research (use this, not `gtm-signal-blueprint.md`, for any future ICP-related question)
- `gtm-signal-blueprint-v2.md` — the real as-built synthesis (what changed from the original blueprint, and why)
- `notes.md` — real interview logistics/prep status (Round 2 today, interviewer background, focus areas)

## Working-style reminders (so a fresh session doesn't relearn these the hard way)
- One phase at a time — stop and explain after each, wait for explicit go-ahead
- No duplicate docs — each doc owns one category, update in place
- Never git init/commit/push — user handles all git ops
- After implementing/updating anything, give a descriptive recap with file paths + ASCII visual when useful
- n8n MCP tools are connected and usable, but the workflow itself is intentionally paused — don't touch it without explicit direction
- Watch for module-name collisions with real pip packages when adding a new dependency (bit this project once already — `utils/discord.py` vs. `discord.py`)
- **When a question touches the ICP/target customer profile, use `redesign/01-trigger-prompt-filled-productboard.md` (real researched data), NOT `gtm-signal-blueprint.md` (the original, since-superseded spec) — got this wrong once already this session and was corrected directly by the user.**
- **Before any bulk/irreversible file deletion (even when the user says "remove unnecessary files" broadly), list the specific candidates and confirm via AskUserQuestion rather than inferring what's "unnecessary" unilaterally** — the auto-mode safety classifier will (correctly) block a bulk delete that isn't explicitly user-directed, and it's the right call for anything with real diagnostic/historical value.
