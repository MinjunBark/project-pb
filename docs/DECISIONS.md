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

## ADR-003: Add AWS (S3 + Lambda) — previously absent from the blueprint
**Decision:** Raw signals land in S3 before merge/dedupe (data lake / audit trail). The ICP scoring endpoint (`api/main.py`) deploys to AWS Lambda via Mangum + API Gateway, called from n8n via HTTP node.
**Why:** AWS familiarity is explicitly preferred in the job description and had zero footprint in the original blueprint. S3 landing also directly demonstrates the JD's "manage integrations and data quality to support language model inputs" responsibility.
**Status:** Decided.

## ADR-004: Postgres (local via Docker) replaces the flat-file dedup store
**Decision:** `seen_companies.json` is replaced by a real Postgres database (`companies`, `signals`, `leads` tables — see `sql/schema.sql`), run locally via `docker-compose.yml` rather than AWS RDS.
**Alternatives considered:** AWS RDS — more "real" cloud footprint to reference, but costs money/time and needs VPC/security group setup for no added learning value in a 5-day build.
**Why:** Gives genuine hands-on SQL (the JD's "Python, SQL, REST" line) without burning build time on AWS networking that doesn't teach anything new beyond what Lambda/S3 already cover.
**Status:** Decided.

## ADR-005: HubSpot is the only built CRM; Salesforce/Marketo are narrative-only
**Decision:** All real CRM writes go to a HubSpot developer sandbox. Salesforce and Marketo are not built against — they're prepared talking points about how the same architecture would map to them (swap REST auth + object model).
**Why:** Could not confirm Productboard's actual internal CRM/MAP stack (their own product integrates with both HubSpot and Salesforce for customers, which says nothing about their internal GTM stack). The JD's "Salesforce, Marketo, HubSpot, etc." phrasing reads as generic "familiarity with concepts," not a confirmed stack reveal. HubSpot has the fastest free developer sandbox to stand up in a 5-day window.
**Status:** Decided.

## ADR-006: Intent signal trimmed to G2 only (Reddit dropped)
**Decision:** Branch C (intent signal) scrapes G2 competitor reviews only. Reddit scraping (r/ProductManagement) from the original blueprint is dropped.
**Why:** G2 gives structured star ratings + review text that map directly to named competitors (Aha!, Jira PD, ProductPlan, Craft.io) — cleaner signal, one Apify actor to build/debug instead of two, within a tight time budget.
**Status:** Decided.
