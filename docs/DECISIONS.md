# Architecture & Tool Decisions

> Owns: every notable tool/architecture choice, the alternatives considered, and why. This is the "why this tool and not another" material for interview prep — keep it accurate as decisions change, don't leave superseded entries in place.

## ADR-001: n8n as the sole orchestrator
**Decision:** Build the entire workflow in n8n. Do not build in Zapier or Salesforce Agentforce.
**Alternatives considered:**
- Zapier — weaker parallel branching, no merge-on-all-complete, gets expensive at this step volume, harder to run custom code steps.
- Salesforce Agentforce — not an orchestration/iPaaS tool; it's a framework for agents living natively inside a Salesforce org. We have no Salesforce org (HubSpot is the built CRM), so there's nothing to attach it to.
**Why n8n:** Full control over branching/data flow, self-hostable, handles HTTP nodes for every API in this stack, and is explicitly named in the actual job description.
**Status:** Decided.

## ADR-002: Clay replaces direct Hunter.io calls for enrichment
**Decision:** Contact enrichment (Phase 7) goes through a Clay table (waterfall enrichment + AI research agent columns), not a direct Hunter.io API call.
**Why:** Clay is explicitly named in the job description's "AI-enabled GTM stack" line and is absent from the original blueprint (0% represented). Industry sources (Clay's own 2026 GTM engineering writeup) name Clay + HubSpot/Salesforce + n8n as the emerging standard GTM engineer stack.
**Status:** Decided.

## ADR-003: AWS dropped to narrative-only (reversed 2026-07-08)
**Original decision:** Raw signals land in S3 before merge/dedupe; the ICP scoring endpoint deploys to AWS Lambda via Mangum + API Gateway.
**What changed:** AWS requires completing billing/payment registration before IAM access is usable, even for free-tier usage. Given the user's standing preference to avoid providing card details for this portfolio project, we reversed course.
**Decision now:** AWS is not built against at all — same treatment as Salesforce/Marketo (ADR-005). Raw signal "landing" happens locally (written to `data/` / a Postgres staging table instead of S3). The ICP scoring endpoint (`api/main.py`) runs as a locally-hosted FastAPI service (`uvicorn`), not Lambda — this still gives genuine hands-on REST API experience (the JD's "Python, SQL, REST" line), just self-hosted instead of serverless.
**Alternatives considered:** LocalStack (Docker-based AWS emulator, no account/card needed) — would have preserved real boto3 S3/Lambda-shaped code without billing. Not chosen because the marginal interview value (one more line item) wasn't worth the added tool/time given everything else already in scope (Clay, Postgres, n8n, HubSpot, SEC EDGAR).
**Talking point if asked about AWS:** "I scoped AWS (S3 landing zone + Lambda-hosted scoring API) into the design, but given this is a portfolio project I chose not to attach billing to a personal AWS account — I built the same scoring API as a local FastAPI service instead, which is a one-step deploy to Lambda via Mangum if it needed to move to production."
**Status:** Decided (reversed from original).

## ADR-004: Postgres (local via Docker) replaces the flat-file dedup store
**Decision:** `seen_companies.json` is replaced by a real Postgres database (`companies`, `signals`, `leads` tables — see `sql/schema.sql`), run locally via `docker-compose.yml` rather than AWS RDS.
**Alternatives considered:** AWS RDS — more "real" cloud footprint to reference, but costs money/time and needs VPC/security group setup for no added learning value in a 5-day build.
**Why:** Gives genuine hands-on SQL (the JD's "Python, SQL, REST" line) without burning build time on AWS networking that doesn't teach anything new beyond what Lambda/S3 already cover.
**Status:** Decided.

## ADR-005: HubSpot is the only built CRM; Salesforce/Marketo are narrative-only
**Decision:** All real CRM writes go to a HubSpot account. Salesforce and Marketo are not built against — they're prepared talking points about how the same architecture would map to them (swap REST auth + object model).
**Why:** Could not confirm Productboard's actual internal CRM/MAP stack (their own product integrates with both HubSpot and Salesforce for customers, which says nothing about their internal GTM stack). The JD's "Salesforce, Marketo, HubSpot, etc." phrasing reads as generic "familiarity with concepts," not a confirmed stack reveal. HubSpot has the fastest free account to stand up in a 5-day window.
**Correction (2026-07-08):** Original guidance said "HubSpot developer sandbox," inherited from the initial blueprint's imprecise wording. Confirmed via HubSpot's own docs: **Private Apps (what we need for the API token) are not available in Developer accounts at all** — only in a regular HubSpot CRM account with Super Admin permissions. User's existing developer account (used for building/publishing marketplace apps, with "Legacy Apps"/"Projects"/"Development" nav) is unrelated and unused; a separate plain free HubSpot CRM signup (hubspot.com, not developers.hubspot.com) is what actually hosts the Private App token.
**Status:** Decided.

## ADR-006: Intent signal trimmed to G2 only (Reddit dropped)
**Decision:** Branch C (intent signal) scrapes G2 competitor reviews only. Reddit scraping (r/ProductManagement) from the original blueprint is dropped.
**Why:** G2 gives structured star ratings + review text that map directly to named competitors (Aha!, Jira PD, ProductPlan, Craft.io) — cleaner signal, one Apify actor to build/debug instead of two, within a tight time budget.
**Status:** Decided.

## ADR-007: Claude authors Python logic; user builds the n8n workflow itself
**Decision:** Claude Code writes and pytest-covers the underlying logic as standalone Python (scoring, classification, outreach generation, the locally-hosted scoring API). The user builds the actual n8n workflow — the HTTP Request nodes, Merge/Filter nodes, branching — by hand in the n8n UI, with Claude guiding node-by-node. Claude does not author `n8n/workflow.json` from scratch or push workflows via n8n's REST API.
**Alternatives considered:** Claude authors the full workflow JSON and pushes it to n8n via its REST API (n8n does expose one — `POST /workflows` etc. — no dedicated n8n MCP server was available in this session, but the plain REST API would have worked fine). Faster and fully version-controlled, but means Claude built the orchestration too.
**Why:** n8n is explicitly named in the JD and is exactly the kind of tool Darrell will probe hands-on ("walk me through the branching logic," "how'd you handle rate limits in that HTTP node"). Having Claude author the workflow blind would produce a working pipeline but not real n8n fluency — defeating the point of this build as learning, not just output. `n8n/workflow.json` in the repo is retained only as an optional exported snapshot of what the user built, for version history.
**Status:** Decided.

## ADR-008: SEC EDGAR Form D filings replace Crunchbase for the funding signal
**Decision:** Branch A (funding/timing signal) pulls from the SEC's EDGAR full-text search API for Form D filings, not the Crunchbase API.
**What changed:** User's Crunchbase account is Basic tier only, which has no API access (Crunchbase removed its free API tier — as of 2026 it's Enterprise-only, ~$588+/year).
**Why SEC EDGAR:** Form D is a mandatory SEC filing any US company makes when raising private capital (seed through late-stage) — it's a free, public, government database with **no API key or signup required at all**. It includes issuer name, total offering amount, and date of first sale in real time. It does not include an explicit "Series A/B" label the way Crunchbase does, so we approximate funding stage from the offering amount (e.g., roughly $2M–$15M ≈ seed/Series A range, $15M–$50M ≈ Series B range) — a heuristic, documented as such, not a fabrication.
**Talking point:** "Crunchbase's API went Enterprise-only in 2026, so I went to the primary source it's partly derived from anyway — SEC Form D filings directly from EDGAR, free and public. I had to approximate funding stage from offering amount since Form D doesn't label rounds, which is a real tradeoff I'd flag to a GTM team relying on this data."
**Implementation detail (confirmed against SEC's own API docs, 2026-07-09):** Two-step flow, not one call. (1) Query `efts.sec.gov/LATEST/search-index` full-text search with `forms=D` and a date range → candidate companies that filed. (2) For each hit, fetch that filing's `primary_doc.xml` via CIK + accession number → extract `TotalOfferingAmount` and `IndustryGroup`. Requires a descriptive `User-Agent` header (`EDGAR_USER_AGENT` in `.env`) or EDGAR returns 403; rate limit 10 req/sec, no API key.
**Known gap:** EDGAR returns company legal name, not a website domain, but our Postgres schema dedupes on `domain`. Resolved by deferring domain lookup to the Clay enrichment step (Phase 7) rather than adding another tool just for this.
**Status:** Decided.
