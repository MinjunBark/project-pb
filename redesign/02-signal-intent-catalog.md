# Signal Intent Catalog — Everything Capturable From Company Intelligence

> Purpose: a comprehensive brainstorm of every kind of signal a company's public/semi-public footprint can reveal — not a build plan. Review this and decide what's worth building; nothing here is committed. Organized by intelligence category. Each entry is tagged with status.

**Status key:** 🟢 Already built · 🟡 Buildable now with data we already collect · 🔵 Buildable with a new (free/cheap) source · 🔴 Needs a paid/harder source · ⚫ Not applicable to this architecture

---

## A. Financial / Funding Intelligence

| Signal | Status | Notes |
|---|---|---|
| SEC Form D filings (private funding rounds) | 🟢 | Branch A |
| SEC 10-K / 10-Q text mining (public companies) | 🔴 | "Risk factors" sections sometimes explicitly name process/tooling gaps. Heavier NLP lift than Form D. |
| S-1 filings (pre-IPO) | 🔴 | "Use of proceeds" sections sometimes name tooling/process investment plans directly. Rare event, small addressable set. |
| M&A press release monitoring | 🔵 | Free news APIs (GDELT, NewsAPI free tier) can catch this. |
| IPO tracking / watchlist | 🔴 | Needs a small curated watchlist, not a broad scan — low volume, high value per hit. |

## B. Hiring / People Intelligence

| Signal | Status | Notes |
|---|---|---|
| Job board postings (volume, recency) | 🟢 | Branch B (Adzuna + Greenhouse/Lever) |
| Job description tool-name mentions | 🟢 | ADR-013, currently limited to 4 competitor names |
| Job description tech-stack mentions (broader) | 🟡 | Same scan, wider vocabulary (Jira, Salesforce, Slack, etc.) |
| Job description **buying-intent language** ("will own/select/evaluate our PM tool stack") | 🟡 | Same data source, different extraction — mining the TEXT for intent phrasing, not just tool names. See creative doc. |
| Decision-maker-level job title filtering (CPO/VP Product openings specifically) | 🟡 | Same Branch B data, needs title parsing refinement |
| New decision-maker HIRE detection (not just open req) | 🔵 | Company "Leadership"/"About" page diffing — see creative doc |
| Exec moves to a new org (people-tracking) | 🔴 | LinkedIn-style — same ToS-risk category already avoided (ADR-009/010) |
| Employee review mining (Glassdoor/Comparably) for internal process dysfunction | 🔵 | Genuinely novel — see creative doc |
| Company careers-page open-req volume trend (own site, not board APIs) | 🔵 | Simple periodic scrape of a company's own careers page |

## C. Technology / Stack Intelligence

| Signal | Status | Notes |
|---|---|---|
| Job-description competitor tool mentions | 🟢 | ADR-013 |
| Public website tech fingerprinting (BuiltWith/Wappalyzer-style) | 🔴 | Only catches customer-facing tech, not internal PM tooling — limited direct relevance |
| Public API/integration docs revealing internal tool choices | 🔵 | e.g., a company's own public "we built a Zapier connector to Aha!" post — rare, high-confidence |
| Public engineering/product blog posts about tool migrations | 🔵 | See creative doc — LLM-searchable, rare but very high value |

## D. Intent / Review Intelligence

| Signal | Status | Notes |
|---|---|---|
| G2 competitor reviews (aggregate corpus + switch signals) | 🟢 | Branch C |
| Capterra / TrustRadius / GetApp reviews | 🔵 | Same pattern as G2, broadens coverage beyond one review site |
| Reddit (r/ProductManagement etc.) | 🔴 | Dropped earlier for noise (ADR-006) — could revisit with LLM-based classification instead of keyword matching |
| Twitter/X public complaints about specific tools | 🔴 | API cost/access has historically been a barrier |
| Public "we switched from X to Y" case-study blog posts | 🔵 | Rare, but extremely high-confidence when found — genuinely creative, LLM-search-driven |

## E. Company / Product Event Intelligence

| Signal | Status | Notes |
|---|---|---|
| Press release / news monitoring (funding, launches, M&A) | 🔵 | GDELT (fully free) or NewsAPI free tier |
| Product Hunt launches | 🔵 | Free public API, direct "new product launch" signal — see creative doc |
| Conference speaker/sponsor lists (Mind the Product, ProductCon, etc.) | 🔵 | Public marketing pages, no ToS issue — see creative doc |
| Webinar/podcast guest appearances by PM leaders | 🔴 | Harder to systematize broadly; good for one-off personalization, not scoring |

## F. Organizational / Structural Intelligence

| Signal | Status | Notes |
|---|---|---|
| LinkedIn company page public follower/headcount trend | 🔴 | Aggregate/public, but still LinkedIn — same caution zone as ADR-009/010 |
| Domain/subdomain / certificate-transparency monitoring (e.g. a new `roadmap.company.com` appearing) | 🔵 | Very creative, very rare hits, near-zero false positive rate when it hits — see creative doc |

## G. Firmographic / Demographic Intelligence

| Signal | Status | Notes |
|---|---|---|
| Employee count, SaaS classification (Clay enrichment) | 🟡 | Built, tested, not live-wired (ADR-014) — needs a second Clay enrichment pass |
| G2/Capterra review company-size segment tags | 🔵 | Some reviews carry a size-segment tag even without a company name — could refine the aggregate corpus by segment |

---

## Summary counts

- 🟢 Already built: 6
- 🟡 Buildable now, no new source needed: 5
- 🔵 Buildable with a new free/cheap source: 10
- 🔴 Needs a paid/harder source or carries real risk: 8
- ⚫ Not applicable to this architecture: 3 (see trigger prompt output — past-customer data, first-party pricing-page analytics, contract-renewal dates)

**The honest takeaway:** roughly a third of everything worth capturing is already built. Another third is sitting in data we already collect, just not extracted yet (this is the cheapest possible expansion — no new integrations, just better parsing of Branch B/C output). The last third needs either a new free source (very doable) or carries real cost/risk tradeoffs worth discussing explicitly before building.
