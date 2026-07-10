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

## Phase 3 — Postgres (Supabase) dedupe/merge
- [ ] `utils/db.py` connection helper (works against Supabase's hosted Postgres, same as any Postgres connection string)
- [ ] `sql/schema.sql` run against Supabase (via SQL Editor in dashboard, or `psql`/connection string) — add `competitor_intel` table for Branch C
- [ ] `sql/queries.sql` dedup + reporting queries
- [ ] Merge/normalize/dedupe logic replacing `seen_companies.json`

## Phase 4 — Scoring API
- [ ] `python/scoring.py` + `tests/test_scoring.py`
- [ ] `api/main.py` FastAPI app, run locally via `uvicorn`

## Phase 5 — Gemini classification
- [ ] `python/classify.py` + `tests/test_classify.py`
- [ ] Wired into pipeline via n8n HTTP node

## Phase 6 — HubSpot dedupe check
- [ ] `utils/hubspot.py` company search
- [ ] Skip-if-recently-contacted logic

## Phase 7 — Clay enrichment
- [ ] Clay table built (waterfall enrichment)
- [ ] `python/enrichment.py` webhook integration
- [ ] `tests/test_enrichment.py`

## Phase 8 — Gemini outreach generation
- [ ] `python/outreach.py` signal-specific prompts (TIMING/INTENT/BOTH)

## Phase 9 — Output fan-out + full assembly
- [ ] `utils/sheets.py`, `utils/discord.py`
- [ ] User builds the n8n workflow in the UI (Claude guides node-by-node); optional exported `n8n/workflow.json` snapshot
- [ ] End-to-end live run

## Phase 10 — Polish + narrative prep
- [ ] `README.md`
- [ ] Interview talking-points doc
