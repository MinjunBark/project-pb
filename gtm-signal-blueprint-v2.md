# GTM Signal Engine — v2: As-Built Architecture

> `gtm-signal-blueprint.md` is the original spec, frozen and unedited — the plan as first written. This file is the single caught-up reference: what actually got built, what changed from the original plan, and why. It doesn't replace the ADR trail in `docs/DECISIONS.md` — that's still the full reasoning for every individual decision. This is the synthesized end state.

## What stayed the same

The core thesis from the original blueprint held all the way through: a static demographic ICP is weak, and the real signal is the *overlap* between independent, time-sensitive behaviors — a funding event, active PM hiring, and/or public frustration with a named competitor. The scoring model still requires that overlap to qualify (threshold 70, and no single signal type can reach it alone). The output still fans out to HubSpot + a tracking layer + a notification channel. Productboard's real ICP (B2B SaaS, 50-500 employees, Series A-C) is still the target profile, even though the demographic bucket that would enforce it isn't live-wired yet (see below).

## What changed, and why

| Blueprint (v1) | As-built (v2) | Why (ADR) |
|---|---|---|
| Crunchbase for funding data | SEC EDGAR Form D filings | Crunchbase API went Enterprise-only | ADR-008 |
| Apify LinkedIn Jobs Scraper | Adzuna (broad) + Greenhouse/Lever (per-company) | ToS/safety concerns, rebuilt on official free APIs | ADR-010 |
| G2 + Reddit for intent signal | G2 only | Reddit dropped — noisy/low-volume for the 4 tracked competitor names | ADR-006 |
| S3 raw landing zone + Lambda scoring API | Local `data/raw/` landing + local FastAPI (`uvicorn`) | AWS required billing registration even for free tier | ADR-003 |
| Local Docker Postgres | Supabase (hosted Postgres, free, no card) | Restores hosted-cloud story without AWS's billing wall | ADR-004 |
| Direct Hunter.io/Apollo enrichment | Clay waterfall enrichment, CSV round-trip | Named in the JD; live webhook trigger is paid-tier, so batch CSV instead | ADR-002, ADR-017 |
| G2 review → per-company attribution assumed | G2 reviews are anonymous by design; reframed as an aggregate competitive-intel corpus + best-effort attribution | Structural discovery once real data arrived | ADR-012 |
| Demographic scoring live from day one | Demographic bucket (`employee_count`/`is_saas`) built and tested, deliberately not wired until Clay backfills those fields | "Score once" — avoid the same `icp_score` meaning two different things before/after enrichment | ADR-014 |
| n8n workflow: user builds by hand in the UI, Claude guides node-by-node | n8n workflow: Claude builds directly via n8n's official MCP server | User explicitly reversed the original hands-on-practice rationale once the MCP server made direct build-and-run possible | ADR-007 → ADR-023 |
| n8n calls raw external APIs directly per node | n8n calls a thin FastAPI wrapper (`api/main.py`) around already-tested Python; doesn't reimplement branch/merge/scoring/outreach logic | Avoids silently re-introducing every bug already fixed in the tested Python (US-filter, truthy-string fix, model-deprecation-proofing, etc.) | ADR-022 |

## Final architecture

```
                                    n8n.cloud: "GTM Signal Engine" workflow
                                    (2 schedule triggers, 10 nodes total)

  Daily 08:00 UTC ─┬─▶ POST /branch-a/run  (SEC EDGAR, free)
                    ├─▶ POST /branch-b/run  (Adzuna + Greenhouse/Lever, free)
                    ├─▶ POST /merge/run     (dedupe into Supabase)
                    └─▶ POST /pipeline/run-all
                             │
                             ▼  (per company, inside Python — invisible to n8n)
                        score_company() → threshold check
                             │ qualifies (>=70)
                             ▼
                        dedup window check (Postgres) → HubSpot dedupe check
                             │ not recently contacted
                             ▼
                        Gemini outreach generation (pulls real G2 pain quotes)
                             │
                        ┌────┴────┬──────────────┬─────────────┐
                        ▼          ▼              ▼             ▼
                   leads table  HubSpot        Google Sheet   Discord
                   (Postgres)   company         (CRM-style     (color-coded
                                create/update    tracking row)  notification)

  Weekly Mon 08:00 UTC ─┬─▶ POST /branch-c/run  (G2 via Apify — real cost, ADR-009)
                         └─▶ POST /merge/run     (recomputes competitor_intel
                                                   from full g2_reviews history,
                                                   not a wholesale overwrite — ADR-021)
```

**Deployment reality:** `api/main.py` runs locally (`uvicorn`), tunneled publicly via ngrok so n8n.cloud can reach it. This is explicitly a portfolio-appropriate choice, not a production one — see `docs/HANDOFF.md` for the current tunnel URL and its known fragility (free-tier ngrok isn't stable across restarts).

## Scoring model (unchanged in shape, calibrated against real data)

- **TIMING** (max 50): funding recency + PM posting count + a Product-Ops-specific-title bonus (excludes titles that also say "manager," to avoid double-counting one posting under two bonuses)
- **INTENT** (max ~25): banded off `current_tool_mentioned` (job-description competitor scan, ADR-013) × that competitor's real switch-signal severity in `competitor_intel` — Aha!'s real 21.7% switch rate anchors the "high" band
- **BOTH-signal bonus** (+10): only applies once a company already has non-zero TIMING *and* non-zero INTENT — structurally prevents a single-signal company from ever crossing 70
- **Demographic** (max 25, built but not live-wired): employee_count/is_saas fit, pending a second Clay enrichment pass

Full formula and every calibration decision: `docs/DECISIONS.md` ADR-014.

## What's real vs. narrative-only

| Component | Status |
|---|---|
| SEC EDGAR (Branch A) | Real, live-verified, runs daily via n8n |
| Adzuna + Greenhouse/Lever (Branch B) | Real, live-verified, runs daily via n8n |
| G2 via Apify (Branch C) | Real, code live-tested manually; not yet triggered through n8n itself (real per-call cost) |
| Postgres/Supabase | Real, hosted, live |
| Clay enrichment | Real, CSV round-trip, live-verified (domain only) |
| HubSpot | Real CRM writes, live-verified, 12 custom properties created programmatically |
| Gemini (classification + outreach) | Real, live-verified |
| Google Sheets | Real, live-verified |
| Discord | Real, live-verified |
| n8n orchestration | Real, live, activated on a real schedule |
| AWS (S3 + Lambda) | Narrative-only — see ADR-003 |
| Salesforce / Marketo | Narrative-only — see ADR-005 |

## Test coverage

167 pytest cases across every Python module, all mocked (no real API calls in CI). Real behavior additionally confirmed via live testing wherever free/safe to do so (EDGAR, Adzuna, Greenhouse/Lever, Gemini, HubSpot sandbox, Google Sheets, Discord, the full n8n workflow) — see `docs/ISSUES.md` for every real bug that live testing caught which mocked tests alone would have missed.
