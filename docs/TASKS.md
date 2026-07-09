# Task Checklist

> Owns: per-phase checklists, checked off as completed. Status summary lives in PROGRESS.md — this file is the granular to-do list underneath it.

## Phase 0 — Accounts + Scaffold

**Scaffolding (done by Claude):**
- [x] `.gitignore`
- [x] `.env.example`
- [x] `requirements.txt`
- [x] `docker-compose.yml`
- [x] `sql/schema.sql`
- [x] `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ISSUES.md`, `docs/TASKS.md`

**Accounts (user creates — Claude guides step-by-step, does not sign up on your behalf):**
- [x] AWS account — has console access, but AWS is now narrative-only (see ADR-003) since billing registration was required for IAM and user opted out
- [x] Clay account
- [x] n8n account (cloud)
- [ ] HubSpot regular free CRM account (hubspot.com, NOT developers.hubspot.com — Private Apps don't exist in Developer accounts at all) → Private App token from Settings → Integrations → Private Apps
- [x] Gemini API key(s)
- [x] Crunchbase account — Basic tier, no API access; replaced by SEC EDGAR (see ADR-008), no signup needed for EDGAR
- [x] Apify account
- [x] Docker Desktop installed
- [x] Copy `.env.example` to `.env` and fill in keys — Apify, Gemini (x2), HubSpot Private App token all set; Clay/Google Sheets/Discord intentionally left blank until their phases

## Phase 1 — Branch A + B
- [x] SEC EDGAR Form D query (`python/funding_edgar.py`) — search + fetch details + approximate stage from offering amount; 12 pytest cases; verified live against the real API
- [ ] Apify LinkedIn PM job scraper
- [ ] Standalone Python tests for both before n8n wiring

## Phase 2 — Branch C + local landing
- [ ] Apify G2 review scraper
- [ ] Local raw-signal landing (data/ or Postgres staging table) wired for all 3 branches

## Phase 3 — Postgres dedupe/merge
- [ ] `utils/db.py` connection helper
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
