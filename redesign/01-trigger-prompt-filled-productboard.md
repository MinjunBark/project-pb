# Trigger-Bot Prompt — Filled Out for Productboard

> Source template: `notes/GTM signal engine prompt....md`. This is that template completed with real, researched answers (not assumptions), plus the full assistant output it produced. Research sources are listed at the bottom.

---

## USER — filled fields (about the PRODUCT)

### 🟢 LEVEL 1 — LIGHTNING
- **Product one-liner:** Productboard is an agentic product management platform that turns customer feedback, feature requests, and market signals into evidence-based roadmaps — helping PM teams prioritize the right work and align stakeholders around it.
- **Public URL:** https://www.productboard.com/

### 🟡 LEVEL 2 — STANDARD
- **Primary industries you sell to:** Enterprise and high-growth companies across software, enterprise tech, industrial, and consumer sectors. Named customers: Autodesk, Salesforce, Zoom, Ubisoft, Medtronic, OutSystems — real ICP skews larger/more enterprise than the original project blueprint assumed (50-500 employees, Series A-C).
- **Buyer job titles / personas:** CPO / VP Product / Head of Product, Product Managers, Product Operations, sometimes co-buying with Engineering leadership.
- **Tech your product integrates with:** Feedback sources — Zendesk, Slack, Intercom, G2 Reviews, Google Play, App Store, Zapier, Microsoft Teams, FullStory, Gong, Grain, Gainsight PX/CS, SatisMeter, Survicate. Dev planning — Jira, Azure DevOps, Trello, GitHub, Shortcut. Customer data — Salesforce. Design — Miro, Figma, Mural. Analytics — Amplitude, Mixpanel.
- **Main competitors:** Aha! ($59/user/month), Jira Product Discovery ($10/creator/month, built by Atlassian specifically to compete with Productboard), ProductPlan, Craft.io.

### 🔴 LEVEL 3 — DEEP DIVE
- **Top 3 pains solved:** (1) Customer feedback is scattered across many channels with no synthesis. (2) Roadmap prioritization decisions get made on gut feel/internal politics instead of evidence. (3) Disconnect between strategy/roadmap and what engineering actually ships.
- **Triggers we already track (pre-existing system):** Funding events (SEC EDGAR Form D), PM hiring volume (Adzuna + Greenhouse/Lever), competitor review/switch-signal data (G2 via Apify).
- **Recent news about the company:** $125M Series D, Feb 2022, led by Dragoneer + Tiger Global, valuation $1.725B — no new round found through mid-2026. Productboard Spark (AI agent for PMs) launched Jan 27, 2026, 4 major feature updates shipped through April 2026.
- **Deal size / pricing model:** Subscription-based, free trial + enterprise tier, no public per-seat pricing disclosed (unlike Aha!/Jira Product Discovery, which do publish pricing).

---

## ASSISTANT — full output

*(Detail tier detected: Level 3 — Deep Dive)*

### 🔥 High-Signal Triggers

**New Funding Round**
- *Why Relevant* – Fresh capital creates a spend mandate and a product org about to scale faster than its current tooling can keep up with.
- *How to Use* – Already built: Branch A (SEC EDGAR Form D). Prioritize companies within 90 days of a raise.

**Merger or Acquisition**
- *Why Relevant* – Combined product orgs inherit two roadmap tools, two feedback pipelines, two sources of truth — a forced consolidation moment.
- *How to Use* – Not currently tracked. Needs M&A news monitoring (a free news/press API) filtered to relevant industries.

**Runs a Stack Productboard Integrates With**
- *Why Relevant* – A prospect already on Jira, Salesforce, or Slack removes nearly all deployment friction — the sale becomes "add," not "replace everything."
- *How to Use* – Extend the existing job-description scan (ADR-013) beyond the 4 competitor names to also flag Jira, Salesforce, Slack, GitHub, Amplitude mentions.

**Competitor Contract Near Renewal (Review-Based)**
- *Why Relevant* – A company publicly airing frustration with Aha!/JPD/ProductPlan/Craft.io is mid-evaluation and open to a switch pitch right now.
- *How to Use* – Already built: Branch C (G2 review scraping + switch-signal corpus).

**New Decision-Maker Hire (CPO / VP Product / Head of Product)**
- *Why Relevant* – New product leaders re-evaluate their tool stack in the first 90 days — a clean-slate mandate with real budget authority.
- *How to Use* – Not currently tracked. Filter Branch B's existing job-posting pull for decision-maker-level titles specifically — data we already collect, just not parsed this way.

**Department Build-Out / Many Open PM Reqs**
- *Why Relevant* – Rapid PM headcount growth is a direct proxy for scaling pains that outstrip ad hoc spreadsheet/doc-based roadmapping.
- *How to Use* – Already built: Branch B (Adzuna + Greenhouse/Lever).

**Open Decision-Maker Role**
- *Why Relevant* – An open Head of Product / VP Product req is itself a signal — engaging before that hire lands lets you help shape their tool decision.
- *How to Use* – Same data source as Branch B; needs title-level filtering to separate "open CPO/VP Product role" from general PM postings.

**Active RFP / Large Project**
- *Why Relevant* – An open RFP means the buying cycle is already live — as hot as a signal gets.
- *How to Use* – No current source; RFPs for PM tooling are rarely public. Aspirational, not near-term buildable.

### ⚡ Medium-Signal Triggers

**IPO**
- *Why Relevant* – Cash infusion plus new public-company reporting rigor around roadmaps and stakeholder communication.
- *How to Use* – No current source; would need a small tracked watchlist of IPO-track companies, not a broad scan.

**Positive 10-K / Earnings Beat**
- *Why Relevant* – Bigger budgets follow a strong quarter, especially at Productboard's real named customers (larger, often public-adjacent firms).
- *How to Use* – No current source; SEC 10-K text-mining is plausible but heavier than the Form D search already built.

**High YoY Growth**
- *Why Relevant* – Fast-growing companies feel scaling pains fastest — the exact inflection point the ICP describes.
- *How to Use* – Not directly tracked; already partially captured indirectly via the funding + hiring overlap.

**Uses an Expensive Enterprise Tool**
- *Why Relevant* – Proves budget authority and willingness to pay for premium tooling.
- *How to Use* – Could piggyback on the same job-description tech-stack scan proposed above.

**Exec Moves to a New Org**
- *Why Relevant* – A former Productboard-friendly champion landing at a new company is a high-trust, shorter-cycle opportunity.
- *How to Use* – No current source (LinkedIn-style people-tracking — same ToS-risk category already avoided, ADR-009/010).

**Attending a Niche PM Conference**
- *Why Relevant* – Attendance at something like Mind the Product or ProductCon signals active investment in leveling up product practice.
- *How to Use* – No current source; conference attendee lists are usually gated, though speaker/sponsor lists often aren't (see creative approaches doc).

**New Product Launch (at the prospect)**
- *Why Relevant* – A company shipping a new product line needs fresh feedback synthesis and roadmap alignment for it — directly on-thesis.
- *How to Use* – No current source; needs press/launch monitoring (see creative approaches doc — Product Hunt is a strong free option).

**Strategic Partnership / Channel Deal**
- *Why Relevant* – A partnership can create ecosystem pressure to adopt tools the partner (or Productboard) already integrates with.
- *How to Use* – No current source; situational, hard to systematize broadly.

**Positive Press / Major Award**
- *Why Relevant* – Budget-friendly momentum; also decent personalization material.
- *How to Use* – Best used as outreach-copy color, not a hard qualifying signal.

**Promotion / Lateral Exec Move**
- *Why Relevant* – Creates a vacancy to monitor and a new decision-maker with fresh priorities.
- *How to Use* – No current source.

**Roadmap / Feature Upgrade (at the prospect)**
- *Why Relevant* – Weaker version of "new product launch" — still signals implementation need, just less acute.
- *How to Use* – No current source.

### 💤 Low-Signal / Monitor Triggers

**Recently Adopted New Tech**
- *Why NOT Highly Relevant* – Too generic on its own; doesn't specify whether the new tech is roadmap-adjacent at all.
- *Next Step* – Only useful combined with the specific-stack trigger above, not standalone.

**New Regulation Deadline**
- *Why NOT Highly Relevant* – Productboard isn't compliance-driven software the way security/fintech tooling is.
- *Next Step* – Deprioritize; only relevant for a regulation-heavy vertical, not the current ICP.

**Industry Disruption Event**
- *Why NOT Highly Relevant* – Too indirect for a roadmap/PM tool; maps better to security/resilience-category products.
- *Next Step* – Deprioritize.

**Facility Expansion**
- *Why NOT Highly Relevant* – A weak proxy for headcount growth when a direct, stronger hiring signal (Branch B) already exists.
- *Next Step* – Skip; redundant.

**Facility Relocation**
- *Why NOT Highly Relevant* – Same reasoning — weak/indirect, redundant with hiring data.
- *Next Step* – Skip.

### ⚑ Negative Triggers (Risk)

**No Funding ≥ 18 Months**
- *Risk* – Likely budget freeze; low willingness/ability to buy new tooling.
- *Pivot Tip* – Deprioritize; already implicitly handled by the funding-recency scoring window.

**Divestiture**
- *Risk* – Active cost-cutting mode, bad timing for a new tool pitch.
- *Pivot Tip* – Deprioritize; no current source to detect this anyway.

**Flat / Negative Growth**
- *Risk* – Efficiency-only budget mindset; a full-platform pitch won't land.
- *Pivot Tip* – Reframe as a consolidation/ROI pitch if pursued at all.

**Added a Competitor Tool < 90 Days Ago**
- *Risk* – Just signed elsewhere; a switch pitch this early gets ignored.
- *Pivot Tip* – Wait out a cool-off window before re-engaging.

**Dropped Complementary Tech**
- *Risk* – Ambiguous — could indicate churn risk or an unrelated tool swap.
- *Pivot Tip* – Too weak/ambiguous to act on without more context; skip.

**Layoffs**
- *Risk* – Contracting budget, harder sell overall.
- *Pivot Tip* – Only actionable via a specific ROI/consolidation angle, not a growth pitch.

**PR Crisis**
- *Risk* – Weak product-fit for a "reputation-save" pivot — Productboard doesn't solve PR/comms problems directly.
- *Pivot Tip* – Skip this trigger for this specific product.

### ⚖ Neutral Personalization Nuggets

- Awards — quick, low-effort compliment-opener.
- Podcasts — reference a recent appearance to show real research.
- Articles — cite something specific an exec actually said or wrote.
- Viral LinkedIn posts — timely, shows attentiveness.
- Alumni ties — soft trust-builder, not a qualifying signal.

### 🚫 Not Applicable Triggers

**Past Customer/User of Product Now at Target Company**
- *Reason* – Requires Productboard's own internal CRM/win-loss data, which an externally-facing signal-scraping architecture has no access to.

**Repeated Pricing / Demo Page Hits**
- *Reason* – First-party website analytics on Productboard's OWN site — a fundamentally different data category (who's already looking at us, not who we should look at). Out of scope for this external-signal-collection architecture.

**Competitor Contract Renewal (as a Procurement-Date Trigger)**
- *Reason* – Distinct from the review-based version above. Actual contract renewal dates are almost never public — no realistic free/legal data source exists.

---

## Research sources used to fill this out
- [Productboard homepage](https://www.productboard.com/)
- [Productboard integrations page](https://www.productboard.com/integrations/)
- [Productboard Series D announcement](https://www.productboard.com/blog/series-d-announcement/)
- [Productboard $125M Series D — PR Newswire](https://www.prnewswire.com/news-releases/productboard-raises-125m-in-series-d-funding-to-scale-its-leading-product-management-platform-to-help-companies-build-the-right-digital-products-301472997.html)
- [Introducing Productboard Spark](https://www.productboard.com/blog/introducing-spark-agentic-product-system/)
- [Productboard Spark support docs](https://support.productboard.com/hc/en-us/articles/44571897288723-Productboard-Spark)
- [Aha! vs Productboard vs Craft.io](https://www.spotsaas.com/compare/aha--vs-productboard-vs-craft-io)
- [Jira Product Discovery vs Productboard — Atlassian](https://www.atlassian.com/software/jira/product-discovery/comparison/jira-product-discovery-vs-productboard)
- [Best Productboard Alternatives — craft.io](https://craft.io/alternatives/productboard-alternatives/)
