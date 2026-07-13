# Task Checklist

> Owns: per-phase checklists, checked off as completed. Status summary lives in PROGRESS.md — this file is the granular to-do list underneath it.

## Phase 0 — Accounts + Scaffold

**Scaffolding (done by Claude):**
- [x] `.gitignore`
- [x] `.env.example`
- [x] `requirements.txt`
- [x] ~~`docker-compose.yml`~~ — removed 2026-07-09, Postgres moved to Supabase (ADR-004)
- [x] `sql/schema.sql`
- [x] `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ISSUES.md`, `docs/TASKS.md`

**Accounts (user creates — Claude guides step-by-step, does not sign up on your behalf):**
- [x] AWS account — has console access, but AWS is now narrative-only (see ADR-003) since billing registration was required for IAM and user opted out
- [x] Clay account
- [x] n8n account (cloud)
- [x] HubSpot regular free CRM account (hubspot.com, NOT developers.hubspot.com) → Private App token obtained
- [x] Gemini API key(s)
- [x] Crunchbase account — Basic tier, no API access; replaced by SEC EDGAR (see ADR-008), no signup needed for EDGAR
- [x] Apify account
- [x] Adzuna account (`app_id`/`app_key`)
- [x] G2 developer portal account — investigated for Branch C, confirmed vendor-scoped/not usable (ADR-011)
- [x] Supabase account (free, no card) — replaces Docker Desktop for Postgres (ADR-004 reversal, 2026-07-09); connection live-verified via Session pooler after Direct connection hit an IPv6 DNS issue (see docs/ISSUES.md)
- [x] Copy `.env.example` to `.env` and fill in keys — Apify, Gemini (x2), HubSpot Private App token, Adzuna all set; Clay/Google Sheets/Discord/DATABASE_URL intentionally left until their phases

## Phase 1 — Branch A + B — COMPLETE
- [x] SEC EDGAR Form D query (`python/funding_edgar.py`) — search + fetch details + approximate stage from offering amount; 12 pytest cases; verified live against the real API
- [x] ~~Apify LinkedIn PM job scraper~~ — deleted, replaced per ADR-010 (safety concerns)
- [x] Adzuna broad hiring discovery (`python/hiring_adzuna.py`) — 4 pytest cases, mocked
- [x] Greenhouse/Lever per-company deepening (`python/hiring_ats_lookup.py`) — 7 pytest cases, mocked + live-verified against real GitLab data
- [x] Branch B orchestrator (`python/hiring_signals.py`) — 2 pytest cases
- [x] User signed up for Adzuna `app_id`/`app_key`; Layer 1 and full chain live-verified (28 real companies, ~7% Layer 2 hit rate measured)

## Phase 2 — Branch C + local landing — COMPLETE
- [x] Apify G2 review scraper (`python/intent_g2.py`) — 5 pytest cases, mocked (no live Apify call per ADR-009). Two-part design: best-effort per-company attribution (deferred to Phase 5 Gemini) + aggregated per-competitor pain-point corpus for Phase 8 outreach generation
- [x] G2 product slugs confirmed against real G2 URLs (2026-07-09) — 2 of 4 original guesses were wrong (`"aha"` not `"aha-roadmaps"`; `"craft-io-craft-io"` not `"craftio"`)
- [x] Deeper documentation pass (2026-07-10) caught real input/output field-name bugs before the first live run — fixed, see docs/ISSUES.md
- [x] User ran the first live Apify test (2026-07-10) — 60 real reviews across all 4 competitors, ~$0.31. Caught and fixed a second real bug from the actual data: a truthy-string bug incorrectly counting "no"/"unknown" as switch signals (42/60 instead of the real 13/60) — see docs/ISSUES.md
- [x] Local raw-signal landing (`python/raw_landing.py`) — 4 pytest cases + live end-to-end test with real Branch A data (8 real companies landed to `data/raw/` and reloaded, verified identical)

## Phase 3 — Postgres (Supabase) dedupe/merge — COMPLETE
- [x] Schema tension resolved: `domain` made nullable, `normalized_name` added as interim dedup key (Clay backfills domain in Phase 7) — confirmed as standard design, not a workaround
- [x] `sql/schema.sql` updated: `biz_location`, `current_tool_mentioned` columns added; new `competitor_intel` table for Branch C
- [x] `utils/db.py` connection helper — `get_connection()`, `normalize_company_name()`, `apply_schema()`, `upsert_company()`, `get_company_by_normalized_name()`; 10 pytest cases
- [x] Schema applied live to Supabase — all 4 tables confirmed (`companies`, `signals`, `leads`, `competitor_intel`)
- [x] Live dedup test passed — "Acme Corp" and "Acme, Inc." correctly resolved to the same row
- [x] US-only ICP filter added to Branch A (`is_us_location()` in `funding_edgar.py`) — live-verified, excludes real non-US filer (Pulsenmore Ltd./Israel)
- [x] ADR-013: job-description tool-mention scanning added to `hiring_ats_lookup.py` (`scan_for_competitor_tools()`) — connects Branch B to Branch C's G2 corpus per-company; live-verified against real GitLab job description text
- [x] `sql/queries.sql` dedup + reporting queries — dedup lookups, TIMING/INTENT/BOTH signal-type reporting, tool-mention-to-G2-corpus join, funnel counts, US-only sanity check
- [x] Merge/normalize/dedupe logic (`python/merge_signals.py`) tying Branch A + B + C output together into the live database, replacing `seen_companies.json` entirely — 8 new pytest cases (2 in test_db.py, 6 in test_merge_signals.py), all mocked

## Phase 4 — Scoring API — COMPLETE
- [x] `python/scoring.py` + `tests/test_scoring.py` — full blueprint formula adapted per ADR-014 (severity-banded INTENT, Product-Ops/manager-title split, demographic bucket written but not live-wired until Phase 7); 15 pytest cases, all mocked
- [x] `api/main.py` FastAPI app (`/score`, `/health`), run locally via `uvicorn` — 3 pytest cases (TestClient) + a real live `curl` smoke test against a running `uvicorn` instance, confirmed correct end-to-end output

## Phase 5 — Gemini classification
- [x] `utils/gemini.py` — dual-key + backoff Gemini client; 5 pytest cases
- [x] `python/classify.py` — G2 review company-attribution extraction (the deferred job from ADR-012); 6 pytest cases
- [x] `python/merge_signals.py` — added `merge_attributed_reviews()` so a successfully-attributed review flows into the normal per-company signal pipeline; 1 pytest case
- [x] Live test succeeded (Claude-run, per user decision) — first attempt hit `gemini-2.0-flash` deprecation (looked like quota exhaustion, wasn't); switched to the `gemini-flash-lite-latest` rolling alias after querying the live model list, then confirmed both the true-negative path (15 real G2 reviews, 0 attributed — expected, G2 is anonymous by design) and the true-positive path (synthetic text naming a company correctly extracted it). `GEMINI_API_KEY_2` is still invalid — not blocking, but the dual-key fallback has no real second key yet. Full writeup in `docs/ISSUES.md`.
- [ ] Wired into pipeline via n8n HTTP node (later, Phase 9)

## Phase 6 — Clay enrichment (reordered before HubSpot dedupe, ADR-016) — COMPLETE
- [x] Clay's live Webhook trigger found to be paid-only on the user's plan — switched to a CSV export/import round-trip instead (ADR-017)
- [x] `python/enrichment.py` — `get_companies_needing_domain()` + `export_companies_needing_domain()`, live-verified against the real Supabase database (22-row CSV correctly exported)
- [x] Live-verified `merge_signals.run_full_merge()` against real Supabase for the first time (previously untested) — caught and fixed a real bug in `raw_landing.py`'s "latest file" selection (see `docs/ISSUES.md`)
- [x] User set up a Clay Blank table, imported the exported CSV, ran waterfall enrichment (name → domain), exported the enriched result
- [x] `import_enriched_companies(csv_path)` — built against Clay's real column name (`"Domain"`, capital D); live-verified against the real Supabase database — all 22 companies updated with real domains, `get_companies_needing_domain()` confirms 0 remaining
- [x] `utils/db.py` — new `update_company_by_id()` (writes by id, not normalized_name — the correct match key for a round-tripped CSV)
- [x] `tests/test_enrichment.py` (5 cases) + `tests/test_db.py` (2 new cases), all mocked
- [x] Data-quality note logged (not a code bug): 2 of 22 real domains look like enrichment mismatches — see `docs/ISSUES.md`

## Phase 7 — HubSpot dedupe check (reordered after Clay enrichment, ADR-016) — COMPLETE
- [x] Verified the real HubSpot API shape live before coding (endpoint, filter operators, and the `notes_last_contacted` standard property — no custom property setup needed, contrary to the blueprint's assumption) — see ADR-018
- [x] `utils/hubspot.py` — `search_company_by_domain()`, `search_company_by_name()`, `find_existing_company()` (domain-first, name fallback), `check_dedupe_status()` (create/skip/update, 30-day inclusive window)
- [x] `tests/test_hubspot.py` — 10 pytest cases, mocked against the live-confirmed real shapes
- [x] Live-verified against the real HubSpot sandbox: all 22 real companies from Phase 6 correctly return `"create"`; the seed company (contacted 2 days ago) correctly returns `"skip"`; name-fallback path confirmed with a deliberately wrong domain

## Phase 8 — Gemini outreach generation — COMPLETE
- [x] `python/outreach.py` — signal-specific prompts (TIMING/INTENT/BOTH), plus a new `priority_summary` field (user-requested, ADR-019) for Phase 9's CRM-style sheet
- [x] Refactored `classify.py`'s JSON-fence parser into `utils/gemini.py` as shared `parse_json_response()` — second real call site, not premature abstraction
- [x] `tests/test_outreach.py` — 9 pytest cases, mocked
- [x] Live-verified against real data: TIMING angle tested against the real "InfraSight Software Corp" row (Phase 6); INTENT angle tested with realistic synthetic pain-point quotes (no real company has `current_tool_mentioned` set yet — needs a live Branch B run)

## Phase 9 — Output fan-out + full assembly — Python side COMPLETE
- [x] Google Sheets + Discord accounts set up by user; two real credential-handling incidents caught and resolved along the way (private key `@`-mention exposure, inline-comment `.env` corruption) — see `docs/ISSUES.md`
- [x] `utils/sheets.py` — CRM-style Sheet output (company info, funding, score, `priority_summary`, all outreach fields), sorted-by-score-ready
- [x] `utils/discord.py` — color-coded per-lead notifications (green=BOTH/yellow=TIMING/blue=INTENT)
- [x] `utils/hubspot.py` extended — `ensure_custom_properties_exist()` (12 custom properties, created live via API per user approval — real property-group prerequisite bug caught and fixed), `create_company()`, `update_company()`
- [x] `sql/schema.sql` — `leads.priority_summary` column added (`ALTER TABLE ADD COLUMN IF NOT EXISTS`), applied live
- [x] `utils/db.py` — new `insert_lead()`
- [x] `python/pipeline.py` — `process_qualified_lead()`, the full per-lead orchestrator (scoring → dedupe → outreach → leads table + HubSpot + Sheet + Discord)
- [x] 24 new pytest cases across `test_sheets.py`, `test_discord.py`, `test_pipeline.py`, `test_hubspot.py`, `test_db.py`
- [x] Full live end-to-end test run (user-approved, clearly-labeled TEST lead) — caught and fixed 2 real integration-ordering bugs (`hubspot_company_id` not written to `leads`; missing Sheet header row), re-verified clean on a second run
- [x] Full-pipeline live validation across 61 real companies (Branch A + live Branch B) — 0 qualified, confirmed as correct scoring-model behavior, not a bug (see `docs/ISSUES.md`)
- [x] Branch C rearchitected for periodic/incremental scheduling (ADR-021) — `g2_reviews` table + recomputed `competitor_intel`, live-verified against the real 60-review dataset (idempotent, correctly accumulates new reviews)
- [x] Dedup-window check — `db.has_recent_lead()` (wires up the already-present but unused `DEDUP_WINDOW_DAYS` env var) + `pipeline.process_qualified_lead()`'s new `"skipped_recently_processed"` short-circuit, placed before the HubSpot call and before outreach generation. 4 new pytest cases (2 `test_db.py`, 2 `test_pipeline.py`). Live-verified: re-running the existing test lead correctly skipped with zero Gemini/HubSpot calls.
- [x] `api/main.py` extended with `/branch-a/run`, `/branch-b/run`, `/branch-c/run`, `/merge/run`, `/pipeline/run-all` (ADR-022) — n8n calls these, doesn't reimplement logic itself. 3 new `utils/db.py` read helpers, 8 new/updated `test_api.py` cases. Real bug caught and fixed: `api/main.py` never called `load_dotenv()`, every endpoint 500'd under a fresh `uvicorn` process — fixed, see `docs/ISSUES.md`.
- [x] Live-verified with a real standalone `uvicorn` process: `/branch-a/run` (22 companies), `/branch-b/run` (40 companies, fresh live run), `/merge/run` (62 distinct companies), `/pipeline/run-all` (62 evaluated, all `not_qualified`). `/branch-c/run` confirmed via mocked test only — not live-called, real Apify cost per call (ADR-009).
- [x] n8n workflow built directly via n8n MCP (ADR-023 reversal) — "GTM Signal Engine" (workflow id `SsGnN1xKSHqz68c3`) on the user's n8n.cloud instance: daily trigger (Branch A -> Branch B -> merge -> pipeline/run-all) + separate weekly trigger (Branch C -> merge). Public reachability solved with an ngrok tunnel (`https://1d92-152-44-135-141.ngrok-free.app`) forwarding to a local `uvicorn api.main:app` on port 8000. Two real bugs caught and fixed live: a `setNodeParameter` path mistake left the old placeholder URL in place; 4 of 6 endpoints (`branch-a`, `branch-b`, `branch-c`, `pipeline/run-all`) 422'd because FastAPI requires a JSON body even with all-optional fields — fixed with `sendBody: true` + `jsonBody: "{}"`. Full live end-to-end test of the daily chain succeeded (22 Branch A + 40 Branch B = 62 merged, all `not_qualified` — consistent with the earlier direct-uvicorn test). **Workflow is now activated** (`active: true`) — daily cron fires 08:00 UTC, weekly (Branch C) fires Monday 08:00 UTC. Branch C has not yet been live-tested through n8n (real Apify cost, ADR-009) — first real run will be its own scheduled Monday firing unless tested sooner.

## Phase 10 — Polish + narrative prep — COMPLETE
- [x] `README.md` — real project overview, architecture diagram, repo layout, setup/run instructions, docs map (was a one-line placeholder before)
- [x] `docs/INTERVIEW_TALKING_POINTS.md` — synthesized "2-minute version" pulling the strongest material from `DECISIONS.md`/`ISSUES.md`: the 30-second pitch, architecture-decision walkthrough, real-bugs-not-hypotheticals section, the "zero qualified leads" story, honest limitations, "what would you do differently"
- [x] `gtm-signal-blueprint-v2.md` capturing the final as-built architecture — `gtm-signal-blueprint.md` itself stays frozen/unedited as the original spec. v2 includes a v1-vs-v2 diff table (with ADR references), the final architecture diagram, scoring model summary, and a real-vs-narrative-only component table
