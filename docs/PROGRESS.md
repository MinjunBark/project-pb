# Build Progress

> Owns: current status only. Detailed reasoning lives in DECISIONS.md, bugs live in ISSUES.md, checklists live in TASKS.md. Update this file at the end of every phase — do not let it go stale.

## Status
**Current phase:** Phase 1 — Branch A done, Branch B (Apify LinkedIn) next
**Last updated:** 2026-07-09

## Phase Log

| Phase | Description | Status | Date completed |
|---|---|---|---|
| 0 | Accounts + repo scaffold | Done | 2026-07-08 |
| 1 | Branch A/B — SEC EDGAR funding + PM hiring signals | In progress (Branch A done) | — |
| 2 | Branch C — G2 intent signal + local landing | Not started | — |
| 3 | Postgres dedupe/merge (SQL layer) | Not started | — |
| 4 | ICP scoring API (local FastAPI) | Not started | — |
| 5 | Gemini classification | Not started | — |
| 6 | HubSpot dedupe check | Not started | — |
| 7 | Clay enrichment | Not started | — |
| 8 | Gemini outreach generation | Not started | — |
| 9 | Output fan-out + full n8n assembly | Not started | — |
| 10 | Polish + narrative prep | Not started | — |

## Phase 0 Detail — COMPLETE
Scaffolded: `.gitignore`, `.env.example`, `requirements.txt`, `docker-compose.yml`, `sql/schema.sql`, `docs/` tracking files.
Clay, n8n, HubSpot (regular CRM account, Private App token), Gemini (2 keys), Apify accounts + Docker Desktop all confirmed ready, `.env` filled in. Clay webhook, Google Sheets, and Discord vars intentionally left blank until their respective phases.

**Two architecture reversals during Phase 0 (both in `docs/DECISIONS.md`):**
- **ADR-003 (AWS):** Dropped to narrative-only. AWS required completing billing registration for IAM access even under free tier; user opted out of attaching a card. Local raw-signal landing + a locally-run FastAPI scoring service replace S3 + Lambda in the build.
- **ADR-008 (Crunchbase → SEC EDGAR):** User's Crunchbase account is Basic tier with no API access (Crunchbase's API went Enterprise-only in 2026). Replaced with SEC EDGAR Form D filings — free, public, no API key needed at all.

**Clarified during Phase 0 (ADR-007):** Claude authors and pytest-covers Python logic; the user builds the actual n8n workflow by hand in the n8n UI — this was a correction from an earlier assumption that Claude would author/push the workflow JSON directly.

## Phase 1 Detail
**Branch A (SEC EDGAR funding signal) — DONE.** `python/funding_edgar.py` implements the two-step flow (search `efts.sec.gov` for Form D filings matching an ICP keyword, then fetch each filing's `primary_doc.xml` for the offering amount/industry). 12 pytest cases (`tests/test_funding_edgar.py`), all passing, plus a live smoke test against the real API. Two real bugs found and fixed during build — see `docs/ISSUES.md`: (1) unfiltered date-range queries return mostly investment funds, not operating companies — fixed with a required keyword + name-heuristic filter; (2) some filings report offering amount as the literal string `"Indefinite"`, which crashed a naive `int()` cast — fixed with a safe parse helper.
**Branch B (Apify LinkedIn PM jobs) — not started.**
