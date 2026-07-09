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
- [ ] AWS account (free tier) — needed for S3 + Lambda in Phases 2 & 4
- [ ] Clay account — needed for Phase 7 enrichment
- [ ] n8n account (cloud, free tier) — needed for Phase 9 workflow assembly
- [ ] HubSpot developer account + sandbox + Private App token — needed for Phase 6/9
- [ ] Gemini API key(s) — needed for Phase 5 (classification) and Phase 8 (outreach)
- [ ] Crunchbase API key — needed for Phase 1 (funding signal)
- [ ] Apify account — needed for Phase 1 (LinkedIn) and Phase 2 (G2)
- [ ] Docker Desktop installed and running — needed for local Postgres
- [ ] Copy `.env.example` to `.env` and fill in keys as each account is created

## Phase 1 — Branch A + B
- [ ] Crunchbase funding query (Series A/B, last 90 days, SaaS)
- [ ] Apify LinkedIn PM job scraper
- [ ] Standalone Python tests for both before n8n wiring

## Phase 2 — Branch C + S3 landing
- [ ] Apify G2 review scraper
- [ ] S3 bucket created, raw signal landing wired for all 3 branches

## Phase 3 — Postgres dedupe/merge
- [ ] `utils/db.py` connection helper
- [ ] `sql/queries.sql` dedup + reporting queries
- [ ] Merge/normalize/dedupe logic replacing `seen_companies.json`

## Phase 4 — Scoring on Lambda
- [ ] `python/scoring.py` + `tests/test_scoring.py`
- [ ] `api/main.py` FastAPI app
- [ ] Deployed to Lambda via Mangum + API Gateway

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
- [ ] `n8n/workflow.json` full assembly
- [ ] End-to-end live run

## Phase 10 — Polish + narrative prep
- [ ] `README.md`
- [ ] Interview talking-points doc
