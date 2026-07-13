# Creative Signal Capture Approaches

> Direct response to the SDR feedback: "hiring signals and funding signals aren't creative — that's a basic approach." This doc proposes genuinely differentiated signal ideas, ranked by how novel + how buildable they are. Review-only — nothing here is committed to build.

## Why the critique is fair

Funding events and hiring volume are exactly what ZoomInfo, Apollo, and every other off-the-shelf sales intelligence tool already sells. Building our own version of that isn't "in-house tooling that beats the expensive platforms" — it's rebuilding the same basic layer those platforms already commoditized. The actually differentiated part of this project so far is **Branch C** (G2 competitor-review mining) — nobody's selling that as a packaged product. The ideas below try to find more of that: signals that are genuinely hard to buy off the shelf, not just free versions of what's already for sale.

---

## Tier 1 — Most novel, most worth reviewing seriously

### 1. Buying-intent language mining inside job descriptions (not just tool-name counting)
**What:** Instead of just counting PM job postings or scanning for 4 hardcoded competitor names, run every PM/Product-Ops job description through an LLM classifier looking for literal buying-intent phrasing: "will own/evaluate/select our product management tool stack," "no formalized roadmap process yet," "define our PM tooling as we scale."
**Why creative:** This turns a "basic" data source (job postings — data we already collect) into a genuinely sharp signal by mining what the posting actually SAYS, not just that it exists. A company hiring a PM says nothing about buying intent; a company whose job posting literally says "select our new PM tool" is telling you the sale is already happening.
**Buildable:** Yes, immediately — same Branch B data we already have, one new Gemini classification pass over text we already pull.

### 2. Employee review mining for internal product-process dysfunction (Glassdoor/Comparably)
**What:** Scan employee reviews (not customer reviews — Glassdoor/Comparably, from the company's own staff) for language like "no clear roadmap," "prioritization is political," "product and engineering don't talk," "tools don't talk to each other."
**Why creative:** Every competitor in this space (including our own Branch C) mines CUSTOMER opinions of tools. Nobody's mining a prospect's own EMPLOYEES complaining about internal product-process dysfunction. This is a genuinely different data category — pain signal from inside the building, not from a review site about a competitor product.
**Buildable:** Needs a new scraper (Glassdoor/Comparably don't have friendly official APIs — similar ToS posture to the G2 situation already navigated once). Real, but not free-and-easy.

### 3. Public "we switched roadmap tools" case-study / blog mining
**What:** LLM-powered web search for a company's own public blog/case-study content describing a tool migration — "how we moved from spreadsheets to [tool]," "why we switched our roadmap process." Some companies genuinely publish this.
**Why creative:** Extremely high-confidence when found (a company publicly narrating its own tool-switching story is about as strong a signal as exists), and it's a genuinely creative use of an LLM's search+synthesis ability rather than a fixed-schema API call.
**Buildable:** Yes, cheaply — a scheduled LLM web-search pass per target company, no new paid data source needed. Hit rate will be low (most companies don't publish this), but each hit is gold.

### 4. Product Hunt launch monitoring
**What:** Product Hunt has a public API. A prospect launching a new product there is a direct, freely-scrapable version of the Trigger-Bot's "new product launch" trigger — one of the two High-signal triggers flagged as "no current source" in the trigger analysis.
**Why creative:** Nobody in the basic funding/hiring category is watching this. Directly maps to real buying psychology (new product = need for fast feedback synthesis + roadmap alignment on it).
**Buildable:** Yes, free public API, straightforward.

### 5. Leadership-page diffing (new CPO/VP Product detection without LinkedIn)
**What:** Periodically snapshot a target company's own public "Leadership"/"About" page HTML and diff it over time. A new name appearing under a Product-leadership title is a real, ToS-safe proxy for "new decision-maker hire" — one of the trigger analysis's top High-signal triggers, currently flagged as needing risky LinkedIn-style tracking.
**Why creative:** Solves a real gap (new-exec detection) entirely through public company websites instead of the LinkedIn scraping risk this project has twice already chosen to avoid (ADR-009/010). Nobody's doing this because it's slightly more engineering work than an API call, not because it's technically hard.
**Buildable:** Yes — needs simple periodic scraping + diffing infrastructure, no new paid API.

---

## Tier 2 — Genuinely useful, more niche or harder to scale

### 6. Conference speaker/sponsor list scraping
**What:** Scrape public speaker/sponsor pages from PM-specific conferences (Mind the Product, ProductCon, etc.) — no ToS issue since these are public marketing pages, not gated attendee lists.
**Why creative:** Reveals which companies are investing seriously in product-practice maturity — a real, non-obvious signal none of our current branches touch.
**Limitation:** Low volume, seasonal (tied to conference calendars), and only reveals companies aggressive enough to sponsor/speak, not the median prospect.

### 7. Domain/subdomain / certificate-transparency monitoring
**What:** Watch certificate-transparency logs for a target company registering a new subdomain like `roadmap.company.com` or `feedback.company.com` — could indicate they're standing up (or migrating to) a new tool.
**Why creative:** Extremely unusual signal source, near-zero false-positive rate when it actually fires.
**Limitation:** Very rare hits — likely too sparse to be a primary signal, more of a curiosity/bonus check.

### 8. M&A + product-launch press monitoring via GDELT (fully free global news index)
**What:** Fills the trigger analysis's other flagged High-signal gap ("Merger or Acquisition," "New Product Launch at the prospect") using a genuinely free, no-signup-friction global news database.
**Why creative:** Not creative in method (it's a news feed), but creative in that it's free where most people assume you need a paid news API (NewsAPI, Meltwater, etc.) to do this.
**Buildable:** Yes, GDELT's project data is public and free.

### 9. G2/Capterra review company-size-segment refinement
**What:** Some reviews carry a company-size-segment tag even without a full company name — could refine `competitor_intel`'s aggregate corpus by segment (e.g., "enterprise switch-signal rate" vs. "SMB switch-signal rate") without needing full per-company attribution.
**Why creative:** Squeezes more value out of a source we already have, rather than adding something new — cheap and low-risk.

---

## Ranked recommendation (for discussion, not a decision)

If choosing where to invest next, in order of **novelty-to-effort ratio**:

1. Buying-intent language mining (#1) — reuses existing data, one new Gemini pass, immediately differentiated
2. Leadership-page diffing (#5) — solves a real trigger-analysis gap, no risky data source
3. Product Hunt monitoring (#4) — free, direct, easy
4. Public tool-migration blog mining (#3) — cheap to try, high value per hit even if rare
5. Employee review mining (#2) — most novel of all, but the highest lift (new scraper, similar ToS posture navigated once already for G2)
6. GDELT press monitoring (#8) — fills real trigger gaps, straightforward but less "creative" in method
7. Conference lists (#6), domain monitoring (#7), review segment refinement (#9) — lower priority, niche/bonus value
