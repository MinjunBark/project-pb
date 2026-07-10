# Build Progress

> Owns: current status only. Detailed reasoning lives in DECISIONS.md, bugs live in ISSUES.md, checklists live in TASKS.md, plain-language code walkthroughs live in CODE_GUIDE.md. Update this file at the end of every phase — do not let it go stale.

## Status
**Current phase:** Phase 2 complete — ready for Phase 3 (Postgres schema, now live on Supabase)
**Last updated:** 2026-07-09

## Phase Log

| Phase | Description | Status | Date completed |
|---|---|---|---|
| 0 | Accounts + repo scaffold | Done | 2026-07-08 |
| 1 | Branch A/B — SEC EDGAR funding + PM hiring signals | Done, fully live-verified | 2026-07-09 |
| 2 | Branch C — G2 intent signal + local landing | Done | 2026-07-09 |
| 3 | Postgres dedupe/merge (SQL layer) | Not started | — |
| 4 | ICP scoring API (local FastAPI) | Not started | — |
| 5 | Gemini classification | Not started | — |
| 6 | HubSpot dedupe check | Not started | — |
| 7 | Clay enrichment | Not started | — |
| 8 | Gemini outreach generation | Not started | — |
| 9 | Output fan-out + full n8n assembly | Not started | — |
| 10 | Polish + narrative prep | Not started | — |

## Phase 0 Detail — COMPLETE
Scaffolded: `.gitignore`, `.env.example`, `requirements.txt`, `sql/schema.sql`, `docs/` tracking files.
Clay, n8n, HubSpot (regular CRM account, Private App token), Gemini (2 keys), Apify accounts all confirmed ready, `.env` filled in. Clay webhook, Google Sheets, and Discord vars intentionally left blank until their respective phases.

**Reversed 2026-07-09 (ADR-004):** Postgres moved from local Docker to Supabase (free tier, no credit card, hosted table editor) — `docker-compose.yml` removed, no longer using Docker Desktop for this project.

**Two architecture reversals during Phase 0 (both in `docs/DECISIONS.md`):**
- **ADR-003 (AWS):** Dropped to narrative-only. AWS required completing billing registration for IAM access even under free tier; user opted out of attaching a card. Local raw-signal landing + a locally-run FastAPI scoring service replace S3 + Lambda in the build.
- **ADR-008 (Crunchbase → SEC EDGAR):** User's Crunchbase account is Basic tier with no API access (Crunchbase's API went Enterprise-only in 2026). Replaced with SEC EDGAR Form D filings — free, public, no API key needed at all.

**Clarified during Phase 0 (ADR-007):** Claude authors and pytest-covers Python logic; the user builds the actual n8n workflow by hand in the n8n UI — this was a correction from an earlier assumption that Claude would author/push the workflow JSON directly.

## Phase 1 Detail
**Branch A (SEC EDGAR funding signal) — DONE.** `python/funding_edgar.py` implements the two-step flow (search `efts.sec.gov` for Form D filings matching an ICP keyword, then fetch each filing's `primary_doc.xml` for the offering amount/industry). 12 pytest cases (`tests/test_funding_edgar.py`), all passing, plus a live smoke test against the real API. Two real bugs found and fixed during build — see `docs/ISSUES.md`: (1) unfiltered date-range queries return mostly investment funds, not operating companies — fixed with a required keyword + name-heuristic filter; (2) some filings report offering amount as the literal string `"Indefinite"`, which crashed a naive `int()` cast — fixed with a safe parse helper.
**Branch B — REBUILT 2026-07-09 (ADR-010), fully live-verified.** The original LinkedIn-actor version (`python/hiring_apify.py`) was replaced after the user questioned its safety posture and requested genuinely free/official alternatives. Two-layer design, both layers real, tested, and live-verified:
- **Layer 1 — Adzuna** (`python/hiring_adzuna.py`, 4 tests): broad discovery via Adzuna's official free job-search API. Live-verified: a real 30-day "Product Manager" search returned 28 real companies.
- **Layer 2 — Greenhouse/Lever** (`python/hiring_ats_lookup.py`, 7 tests): per-company deepening, trying each candidate's guessed board token against both platforms' public read-only APIs. Live-verified against real GitLab data (5 real open PM postings).
- **Orchestrator** (`python/hiring_signals.py`, 2 tests): ties the two layers together, preferring Layer 2's richer data when it resolves, falling back to Layer 1's data when it doesn't. Full-chain live run measured Layer 2's real hit rate: **~7% (2/28)** — logged in `docs/ISSUES.md` and `docs/DECISIONS.md` (ADR-010) as a measured number, not an assumption.

One real bug caught and fixed during live testing — see `docs/ISSUES.md`: an ambiguous first read of Lever's error response (only checked body, not status code) was resolved by re-testing with both together, confirming Lever 404s cleanly like Greenhouse does.

## Phase 2 Detail
**Branch C (G2 intent signal) — code done, not yet live-tested.** `python/intent_g2.py`, 5 pytest cases, all mocked (no live Apify call by Claude, per ADR-009). Before building, checked whether official alternatives existed: G2's own Developer API and MCP server (both confirmed vendor-scoped — ADR-011, empirically proven via a real test call returning zero owned products), Capterra (no self-serve API), Reddit and Hacker News (HN empirically tested live and found too noisy/low-volume for our 4 named competitors). Settled on the Apify actor `automation-lab/g2-scraper` (ADR-012) — no login bypass, no proxy required, minimal PII, as conservative as G2 scraping gets.

**Real structural finding reshaped this branch's design:** G2 reviews don't include the reviewer's company name (anonymous by design), so most reviews can't attach to a specific company the way Branch A/B do. Reframed around the user's own articulation of G2's actual value — competitive-intelligence content for messaging, not strict per-company attribution. Two-part output: (1) best-effort company attribution deferred to Phase 5's Gemini classification, (2) an aggregated per-competitor pain-point corpus (negative-review counts, representative "reason for switching" quotes) that directly feeds Phase 8's outreach generation.

**G2 slugs confirmed (2026-07-09):** verified all 4 against real G2 URLs — 2 of the original guesses were wrong (`"aha"` not `"aha-roadmaps"`; `"craft-io-craft-io"` not `"craftio"`, a real G2 URL quirk from a historical name collision). Code updated, tests still pass. User still needs to run the first live Apify test themselves (ADR-009).

**Local raw-signal landing built:** `python/raw_landing.py` (4 tests) replaces the S3 landing zone from the original blueprint (ADR-003) — saves each branch's raw output as a timestamped JSON file in `data/raw/` before Phase 3's merge/dedupe touches it, so a bug in merge logic doesn't require re-hitting rate-limited APIs to recover. Live end-to-end tested with real Branch A data (8 companies landed and reloaded, verified identical).

**First live G2 test run completed by the user (2026-07-10):** 60 real reviews across all 4 competitors (15 each), ~$0.31 total. Caught and fixed a real bug from the actual data: `switchedFromOtherProduct` is a `"yes"`/`"no"`/`"unknown"` flag, not a product name, and a truthy-string bug (`bool("no")` is `True` in Python) meant 42 of 60 reviews were incorrectly counted as switch signals instead of the real 13. Fixed, re-validated against the full real dataset, and a regression test added. 37/37 tests passing.

**Phase 2 is COMPLETE.** Postgres is now live on Supabase (see Phase 0 detail above) — ready to start Phase 3.
