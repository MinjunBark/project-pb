# Session Handoff

> Owns: a resume-from-scratch snapshot only. This file is **overwritten** at the end of every phase, not appended to — history lives in PROGRESS.md (phase log) and ISSUES.md (bugs). If you're picking this project back up cold, read this file first, then follow its pointers.

**Last updated:** 2026-07-13 — Redesign v2, Tier 6 built, tested, AND live-verified with a real human Discord upload: a real bot watching `#clay-enrichment` for the enriched CSV attachment, no local file-drop step required.

## Where we are right now
The original build (Phases 0-10) is complete. n8n orchestration remains paused/excluded (real SDR feedback that funding+hiring alone is "the basic approach"). In its place, `python/full_pipeline_run.py` + `POST /pipeline/run-full-cycle` is the real, manual, Discord-visible entry point for running the entire pipeline live. Redesign v2 has now gone through 6 tiers, all built, tested, and live-verified against real Supabase/Discord/external APIs:

- **Tier 1** — 3 new signal-capture features: buying-intent language mining, leadership-page diffing, Product Hunt launch monitoring (Branch D).
- **Outreach-copy gap fix** — the 3 new signal types now actually reach generated outreach copy, not just scoring.
- **Tier 2** — Discord ops-progress + SDR-digest channels, `full_pipeline_run.py` orchestrator, `POST /pipeline/run-full-cycle`.
- **Tier 3** — Branch C made demand-driven by Branch B's real findings; SDR digest gained a "watchlist" + a real run-query log; Google Sheet link bug fixed.
- **Tier 4** — Clay demographic enrichment pass (`employee_count`/`is_saas`).
- **Tier 5** — local-folder auto-pickup + 60s background poller: drop an enriched CSV in `data/clay/incoming_*/` and the pipeline auto-resumes.
- **Tier 6 (this session)** — a real Discord bot, so the "submit it" step is a genuine Discord attachment upload, not a local file drop. See below.

## Tier 5→6 bridge: two real bugs the user caught live, fixed same-session
1. **Crash-loop bug** in `import_enriched_companies()` — Clay's waterfall mismatched 3 different companies to the same placeholder domain (`google.com`); the resulting `UniqueViolation` was uncaught, killing the whole import and leaving the file stuck retrying forever every 60s (visible in the user's Discord screenshot as the identical error 3x). Fixed: catch `psycopg2.errors.UniqueViolation` per-row, `conn.rollback()`, skip just that row.
2. **Design pushback** — the user expected "submit it on the Discord channel" to mean a literal attachment upload, not a local file drop (a webhook can only post *out*, never read back). Explained the real constraint, user chose to build a real bot → Tier 6.

## Tier 6: real Discord bot for Clay enrichment upload (2026-07-13)

**What was built:**
- `python/enrichment.py` — `_detect_enrichment_kind(header)` (content-based: recognizes a demographics file via `EMPLOYEE_COUNT_COLUMNS`/`INDUSTRY_COLUMNS`, a domain file via a `Domain`/`domain` column, `None` if neither) + `save_incoming_enrichment_file(kind, filename, content)` (writes into the same Tier 5 known-folder, microsecond-timestamp-prefixed).
- New `utils/discord_bot.py` — a real `discord.Client` (new `discord.py==2.4.0` dependency) watching `DISCORD_CLAY_CHANNEL_ID` for CSV attachments. All real logic in `handle_upload()` (plain async function, no discord.py types in its signature — testable without mocking `Client`/`Message`). Saves the file, replies immediately, calls `resume_after_enrichment()` right away (not waiting for the next poll tick), posts a second reply once done. `create_bot_task()` returns `None` gracefully if `DISCORD_BOT_TOKEN`/`DISCORD_CLAY_CHANNEL_ID` aren't set.
- `api/main.py` — bot launched from the same `@app.on_event("startup")` handler the Tier 5 poller uses. One process, both mechanisms.

**Two real bugs hit and fixed during setup itself (not the feature logic):**
1. **Naming collision**: this project's own `utils/discord.py` (Phase 9 webhook helper) has the exact same importable name as the pip `discord.py` library. Since every entry point puts `utils/` at the front of `sys.path`, `import discord` inside the bot grabbed our own module instead of the SDK — crashed with `AttributeError: module 'discord' has no attribute 'Intents'`. **Fixed by renaming** `utils/discord.py` → `utils/discord_webhooks.py` (and `tests/test_discord.py` → `tests/test_discord_webhooks.py`), updating 4 call sites to `import discord_webhooks as discord` — every existing `discord.send_*()` call is unchanged.
2. **Local machine SSL cert issue** (not a code bug): first bot connection attempt failed with `SSLCertVerificationError` — this Python.org install had never run its bundled `Install Certificates.command`. Ran it once; resolved.

**281/281 tests passing** (14 new since Tier 5: `test_enrichment.py` +6, `test_discord_bot.py` new file with 6 tests — no `pytest-asyncio` added, uses plain `asyncio.run()` from sync test functions).

**Live-verified with a real human upload, not simulated:** the user dragged their own real, already-enriched domain CSV directly into `#clay-enrichment`. Confirmed via the bot's own message history (read over the REST API): replied "✅ Got it..." in under a second, then correctly took ~5.5 minutes for a genuine leadership-check pass across all 112 domain-having companies (jumped from 22 once domains got backfilled) before posting "🔄 Pipeline auto-resumed: 0 qualified lead(s) out of 114 companies evaluated" — matching an earlier equivalent poller-triggered run's timing almost exactly. SDR digest posted to `#sdr-digest` at the same moment. Zero manual file handling.

## Discord channel map (all real, all wired)
| Channel | Env var | Purpose |
|---|---|---|
| Per-lead | `DISCORD_WEBHOOK_URL` | Real-time ping per qualifying lead |
| Ops-progress | `DISCORD_PROGRESS_WEBHOOK_URL` | Phase-by-phase status during a run |
| Clay enrichment | `DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL` (outbound) + `DISCORD_BOT_TOKEN`/`DISCORD_CLAY_CHANNEL_ID` (inbound bot) | Requests posted out via webhook; real user uploads read back in via the bot |
| SDR digest | `DISCORD_SDR_DIGEST_WEBHOOK_URL` | Final daily summary + watchlist |

## What is NOT done yet — real next steps
- **The demographics import is still only lightly verified** — real column-name assumptions (`EMPLOYEE_COUNT_COLUMNS`/`INDUSTRY_COLUMNS`) confirmed against one real user-driven test row, not a full real Clay-table export yet.
- **2 companies permanently can't get a domain** via the current queue (both Chrome-extension-style Product Hunt launches mismatched to `google.com` by Clay's waterfall, correctly skipped rather than corrupting the unique constraint) — a real, accepted data-quality limit, not a bug.
- **111 companies now queued for demographics** (jumped up once domains got backfilled — many more companies now qualify for that pass) — will keep resurfacing in `#clay-enrichment` until done.
- **G2_API_TOKEN is expired** (real `401 Bad Credentials` confirmed live) — blocks discovering brand-new competitor names for Branch C. Documented as a real follow-on.
- **The n8n workflow itself remains untouched and paused.**
- **`redesign/04-current-architecture-diagram.md`** has Tier 5/6 notes at the top but the diagram body itself still reflects an earlier state.

## Open questions waiting on the user
- Whether/when to do a real full Clay-table export+enrich+import round-trip for the demographics queue (111 companies) via the new bot.
- Whether to pursue a fresh `G2_API_TOKEN` to unblock Branch C's new-competitor discovery.
- Direction for the n8n workflow redesign itself, if/when that resumes.

## Where to look for depth (don't duplicate it here)
- `docs/DECISIONS.md` — ADR-024 covers Redesign v2 in full
- `docs/PROGRESS.md` — phase-by-phase log, including today's Tier 5/6 entries
- `docs/ISSUES.md` — bugs found and fixed
- `redesign/` — the research trail behind Redesign v2
- `~/.claude/plans/let-s-continue-with-your-reflective-sifakis.md` — the approved implementation plan for Tier 6

## Working-style reminders (so a fresh session doesn't relearn these the hard way)
- One phase at a time — stop and explain after each, wait for explicit go-ahead
- No duplicate docs — each doc owns one category, update in place
- Never git init/commit/push — user handles all git ops
- After implementing/updating anything, give a descriptive recap with file paths + ASCII visual when useful
- n8n MCP tools are connected and usable, but the workflow itself is intentionally paused — don't touch it without explicit direction
- Watch for module-name collisions with real pip packages when adding a new dependency (bit this project once already — `utils/discord.py` vs. `discord.py`)
