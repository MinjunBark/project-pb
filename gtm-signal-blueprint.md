# GTM Signal Engine — Productboard ICP
## Project Blueprint & Implementation Spec

> Transfer this file to a new repo directory. It contains everything needed to build from scratch.

---

## 1. Problem Statement

Productboard's GTM team needs a systematic way to identify companies that are actively experiencing the pain their product solves — before those companies start a formal vendor evaluation. Most outbound pipelines rely on static demographic lists (company size, industry, headcount). This project replaces that with a **live, multi-signal pipeline** that detects two types of high-intent behavior:

1. **Timing Signal** — Companies at the exact growth inflection where PM tooling becomes a business need
2. **Intent Signal** — Companies actively expressing frustration with competing tools

The output is a scored, enriched, outreach-ready lead list that pipes directly into HubSpot — the same workflow Productboard's GTM team would actually run.

---

## 2. What "High-Intent" Means in This Context

```
SIGNAL QUALITY SPECTRUM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOW INTENT                                        HIGH INTENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Demographic]     [Behavioral]     [Timing]     [Active Pain]
   Fit Only       Has PM team     Funding +      Competitor
  (company        (passive)       PM Hiring      Complaints
   size, SaaS)                   Velocity        (in-market)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  We skip this                    BUILD THIS     BUILD THIS
```

**Timing Signal (Option B):** Company raised Series A/B in last 90 days AND hired 2+ PMs in last 60 days AND has no Product Operations role yet. This is the inflection point — headcount growing, product team scaling, no infrastructure in place.

**Intent Signal (Option A):** Company's team publicly expressed frustration with a competing tool (Aha!, Jira Product Discovery, ProductPlan, Craft.io) via G2 review ≤3 stars or Reddit post requesting alternatives. These people are mid-evaluation cycle.

**Combined = highest priority:** A company hitting both signals is the highest-probability lead in the pipeline.

---

## 3. Productboard ICP Definition

Use this to filter and score all signals:

```
PRODUCTBOARD IDEAL CUSTOMER PROFILE
┌─────────────────────────────────────────────────────────────┐
│  Company Type:    B2B SaaS                                  │
│  Employee Range:  50 – 500                                  │
│  Funding Stage:   Series A, B, or C                         │
│  PM Team Size:    2+ product managers                       │
│  Growth Signal:   Actively hiring PMs or Product Ops        │
│  Pain Signal:     Frustrated with Aha!, Jira PD,            │
│                   ProductPlan, Craft.io, or spreadsheets    │
│  Exclusions:      Existing Productboard customers           │
│                   Non-SaaS companies                        │
│                   Seed stage or post-Series C               │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Full System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      GTM SIGNAL ENGINE                              │
│                 Orchestrated by n8n (daily schedule)                │
└─────────────────────────────────────────────────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
    ┌──────────────────┐ ┌───────────────────┐ ┌──────────────────┐
    │  SIGNAL SOURCE 1 │ │  SIGNAL SOURCE 2  │ │  SIGNAL SOURCE 3 │
    │  Crunchbase API  │ │  Apify → LinkedIn │ │  Apify → G2 +   │
    │  (Funding Events)│ │  (PM Job Posts)   │ │  Reddit Scraper  │
    └────────┬─────────┘ └────────┬──────────┘ └────────┬─────────┘
             │                    │                      │
             └──────────┬─────────┘                      │
                        ▼                                 │
              ┌──────────────────┐                        │
              │  MERGE + DEDUPE  │◄───────────────────────┘
              │  (n8n Merge +    │
              │  Code Node)      │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  SIGNAL CLASSIFY │
              │  Gemini API      │
              │  Sentiment +     │
              │  Category tag    │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  ICP SCORING     │
              │  Python logic    │
              │  (0–100 scale)   │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  FILTER ≥ 70     │◄── Below 70: discard
              │  (n8n Filter)    │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  HUBSPOT CHECK   │
              │  Existing contact│◄── If exists: skip
              │  lookup via API  │
              └────────┬─────────┘
                       │ (new lead only)
                       ▼
              ┌──────────────────┐
              │  ENRICHMENT      │
              │  Hunter.io       │
              │  (email + name)  │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  OUTREACH GEN    │
              │  Gemini API      │
              │  Signal-specific │
              │  email + LinkedIn│
              └────────┬─────────┘
                       │
           ┌───────────┼───────────┐
           ▼           ▼           ▼
  ┌──────────────┐ ┌──────────┐ ┌──────────────┐
  │   HUBSPOT    │ │  GOOGLE  │ │   DISCORD    │
  │  Create      │ │  SHEETS  │ │  Webhook     │
  │  Contact +   │ │  Log row │ │  Notify team │
  │  Company     │ │          │ │              │
  └──────────────┘ └──────────┘ └──────────────┘
```

---

## 5. Tech Stack — When and Why Each Tool

```
PHASE          TOOL              WHY THIS TOOL (NOT ANOTHER)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ORCHESTRATION  n8n               Listed in Productboard JD. Open-source,
                                 self-hostable, handles scheduling +
                                 multi-step workflows with HTTP nodes.
                                 Unlike Zapier/Make, it gives full control
                                 over data flow and branching logic.

SCHEDULING     n8n Cron Trigger  Enterprise GTM tools run on schedules,
                                 not manual triggers. Cron = production
                                 mindset. Daily at 9 AM PST.

SCRAPING       Apify             JavaScript-rendered pages (G2, LinkedIn)
                                 require headless browsers + IP rotation.
                                 Apify handles this at scale. Raw requests
                                 get blocked. Same pattern as Project F.

FUNDING DATA   Crunchbase API    Most reliable structured source for
                                 funding events. Clean JSON, company
                                 metadata included. Alternative: Tracxn,
                                 but Crunchbase has best coverage.

JOB DATA       Apify →           LinkedIn blocks raw scraping. Apify's
               LinkedIn Actor    pre-built LinkedIn actors handle auth
                                 and anti-bot measures. Returns job
                                 posting data including company name,
                                 role title, posting date.

REVIEW DATA    Apify → G2        G2 is the primary B2B software review
                                 platform. Competitor review pages are
                                 public. Apify scrapes paginated review
                                 lists with star ratings and text content.

COMMUNITY      Apify → Reddit    Reddit API (PRAW) or Apify Reddit actor.
SIGNALS        (PRAW or Actor)   Targets r/ProductManagement,
                                 r/productdesign. Filters for competitor
                                 mentions and tool request threads.

SENTIMENT/     Gemini API        Classify signal text: is this negative
CLASSIFY       (Flash model)     sentiment about a competitor? Is this
                                 an active tool request? LLM outperforms
                                 regex for nuanced natural language.
                                 Flash model = fast + cheap for batch.

ICP SCORING    Python            Weighted scoring algorithm needs exact
               (scoring.py)      control over logic. n8n's Code node
                                 runs JS — call a FastAPI endpoint or
                                 run scoring in-node. Python gives
                                 testability (pytest, like Project F).

DEDUPLICATION  SQLite /          Track seen company domains locally
               seen_companies    before hitting paid APIs. Saves
               .json             Crunchbase + Hunter.io API calls.
                                 Same pattern as Project F seen_leads.

EMAIL          Hunter.io         Domain-to-email discovery. Already
ENRICHMENT                       integrated in Project F. Has
                                 verification endpoint. Alternative:
                                 Apollo.io API (broader database but
                                 requires paid plan sooner).

OUTREACH GEN   Gemini API        Signal-specific prompting: a company
               (Pro model)       frustrated with Aha! gets a different
                                 email than a Series B company scaling
                                 their PM team. Gemini Pro for higher
                                 quality generation. Dual-key fallback
                                 for rate limits (same as Project F).

CRM OUTPUT     HubSpot API       Productboard's likely CRM for mid-market
                                 motion. REST API with Private App auth.
                                 Creates Contact + Company objects.
                                 Maps signal data to custom properties.
                                 This is where you learn their stack.

LOGGING        Google Sheets     Parallel visual output for QA and demo
               API               purposes. Same gspread pattern as
                                 Project F. Stakeholders can see leads
                                 without CRM access.

NOTIFICATION   Discord Webhook   Real-time alerts per qualified lead.
                                 Same pattern as Project F. Shows the
                                 system is running live.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 6. Phase Breakdown

### PHASE 0 — Setup & Configuration
```
┌─────────────────────────────────────────────────┐
│  PHASE 0: SETUP                                 │
│  Duration: 30 min (one-time)                    │
├─────────────────────────────────────────────────┤
│  □ Create n8n account (n8n.cloud free tier)     │
│  □ Register API keys (see env vars section)     │
│  □ Create HubSpot developer sandbox account     │
│  □ Create HubSpot Private App + token           │
│  □ Create Google Sheet + share with service     │
│    account                                      │
│  □ Create Discord server + webhook URL          │
│  □ Clone repo, copy .env.example → .env         │
│  □ pip install -r requirements.txt              │
└─────────────────────────────────────────────────┘
```

---

### PHASE 1 — Signal Collection (Parallel)
```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: SIGNAL COLLECTION                                     │
│  Trigger: n8n Cron (daily, 9 AM PST)                           │
│  All three sources run IN PARALLEL (n8n parallel branches)      │
├──────────────────┬──────────────────┬──────────────────────────┤
│  BRANCH A        │  BRANCH B        │  BRANCH C                │
│  Funding Signal  │  Hiring Signal   │  Intent Signal           │
├──────────────────┼──────────────────┼──────────────────────────┤
│  Tool: Crunchbase│  Tool: Apify     │  Tool: Apify (G2)        │
│  API             │  LinkedIn Actor  │  Tool: Apify (Reddit)    │
├──────────────────┼──────────────────┼──────────────────────────┤
│  Query:          │  Query:          │  Query:                  │
│  - Funded in     │  - Job title     │  G2: reviews of          │
│    last 90 days  │    contains "PM" │  Aha!, Jira PD,         │
│  - Series A or B │    or "Product   │  ProductPlan,            │
│  - SaaS category │    Manager"      │  Craft.io                │
│                  │  - Posted in     │  Star rating ≤ 3         │
│                  │    last 60 days  │                          │
│                  │                  │  Reddit: search          │
│                  │                  │  r/ProductManagement     │
│                  │                  │  for competitor names    │
│                  │                  │  + "alternative"         │
├──────────────────┼──────────────────┼──────────────────────────┤
│  Output:         │  Output:         │  Output:                 │
│  company_name    │  company_name    │  company_name (if        │
│  domain          │  domain          │    mentioned in review)  │
│  funding_amount  │  pm_post_count   │  competitor_mentioned    │
│  funding_date    │  posting_date    │  review_text             │
│  funding_stage   │  job_title       │  star_rating             │
│  company_size    │  company_size    │  source (g2/reddit)      │
└──────────────────┴──────────────────┴──────────────────────────┘

  Expected volume per run: 50–200 raw signals across all branches
```

---

### PHASE 2 — Merge, Normalize, Deduplicate
```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2: MERGE + DEDUPLICATE                                   │
│  Tool: n8n Merge Node + Code Node                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Input: Raw arrays from all 3 branches                          │
│                                                                  │
│  Steps:                                                          │
│  1. Merge all three signal arrays into one list                 │
│  2. Normalize company names (lowercase, strip Inc/LLC/Corp)     │
│  3. Extract root domain from all company URLs                   │
│  4. Check domain against seen_companies.json                    │
│     → Already processed in last 7 days? SKIP                    │
│  5. Group signals by domain (same company, multiple signals)    │
│     → Multiple signals = higher base score                      │
│  6. Add signal_type tag:                                        │
│     "TIMING"  = funding + hiring only                           │
│     "INTENT"  = competitor frustration only                     │
│     "BOTH"    = company appears in timing AND intent signals    │
│                                                                  │
│  Output: Deduplicated company list with all signals attached    │
│  Expected: 30–100 unique companies                              │
└─────────────────────────────────────────────────────────────────┘
```

---

### PHASE 3 — Signal Classification (AI Layer)
```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: SIGNAL CLASSIFICATION                                 │
│  Tool: Gemini API (Flash) via n8n HTTP Request                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  For each company with text signals (G2 review, Reddit post):   │
│                                                                  │
│  Prompt structure:                                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ You are a GTM analyst. Classify the following customer   │   │
│  │ review/post:                                             │   │
│  │                                                          │   │
│  │ Text: {signal_text}                                      │   │
│  │                                                          │   │
│  │ Return JSON:                                             │   │
│  │ {                                                        │   │
│  │   "sentiment": "negative|neutral|positive",             │   │
│  │   "is_tool_evaluation": true|false,                     │   │
│  │   "pain_points": ["list of specific complaints"],        │   │
│  │   "competitor_mentioned": "tool name or null",          │   │
│  │   "urgency": "high|medium|low"                          │   │
│  │ }                                                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Use Flash model (fast + cheap for batch classification)        │
│  Implement exponential backoff for rate limits                  │
│  Dual API key fallback (same pattern as Project F)              │
│                                                                  │
│  Output: Each company object now has classification metadata    │
└─────────────────────────────────────────────────────────────────┘
```

---

### PHASE 4 — ICP Scoring
```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4: ICP SCORING (Python — scoring.py)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ICP SCORE = sum of weighted signals (max 120, threshold ≥ 70) │
│                                                                  │
│  TIMING SIGNALS                              MAX POINTS         │
│  ├── Raised Series A/B in last 90 days         +25             │
│  ├── Raised Series A/B in last 91–180 days     +15             │
│  ├── 2+ PM job postings in last 60 days        +15             │
│  ├── 1 PM job posting in last 60 days          +08             │
│  └── Posted "Product Operations" role          +10             │
│                                              ───────            │
│                                           max: 50 pts          │
│                                                                  │
│  INTENT SIGNALS                              MAX POINTS         │
│  ├── G2 review ≤ 3 stars (competitor)         +20             │
│  ├── Reddit post requesting alternatives       +15             │
│  ├── LinkedIn post mentioning roadmap chaos    +15             │
│  └── Multiple competitor signals               +10             │
│                                              ───────            │
│                                           max: 40 pts          │
│                                                                  │
│  DEMOGRAPHIC FIT                             MAX POINTS         │
│  ├── Company size 50–200 employees            +15             │
│  ├── Company size 200–500 employees           +10             │
│  ├── Confirmed B2B SaaS                       +10             │
│  └── No existing Product Ops title found      +05             │
│                                              ───────            │
│                                           max: 30 pts          │
│                                                                  │
│  DEDUCTIONS                                                      │
│  ├── Already a Productboard customer          -100             │
│  ├── Company size < 20 or > 1000              -20             │
│  └── Non-SaaS industry detected              -15             │
│                                                                  │
│  SIGNAL TYPE BONUS                                               │
│  └── BOTH timing + intent signals             +10             │
│                                                                  │
│  ─────────────────────────────────────────────────────────────  │
│  THRESHOLD: Score ≥ 70 = qualified lead → continue pipeline    │
│             Score < 70 = discard                                │
│  ─────────────────────────────────────────────────────────────  │
│  Expected pass rate: ~30–40% of deduplicated companies          │
└─────────────────────────────────────────────────────────────────┘
```

---

### PHASE 5 — HubSpot Deduplication Check
```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5: HUBSPOT DEDUP CHECK                                   │
│  Tool: HubSpot API (Search endpoint) via n8n HTTP Request       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  For each qualified company (score ≥ 70):                       │
│                                                                  │
│  Request:                                                        │
│  POST /crm/v3/objects/companies/search                          │
│  Body: { filter: { domain: {company_domain} } }                 │
│                                                                  │
│  If company EXISTS in HubSpot:                                  │
│    → Check last_contacted_date property                         │
│    → If contacted in last 30 days: SKIP                         │
│    → If not recently contacted: UPDATE record + continue        │
│                                                                  │
│  If company does NOT exist: CONTINUE to enrichment              │
│                                                                  │
│  Why this step:                                                  │
│  Prevents duplicate outreach. Shows awareness of CRM hygiene    │
│  — a core responsibility in the actual role.                    │
└─────────────────────────────────────────────────────────────────┘
```

---

### PHASE 6 — Contact Enrichment
```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 6: CONTACT ENRICHMENT                                    │
│  Tool: Hunter.io API                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  For each new qualified company:                                 │
│                                                                  │
│  Step 1: Domain Search                                           │
│  GET /domain-search?domain={company_domain}&limit=5             │
│  Filter results for: Head of Product, VP Product,               │
│  Chief Product Officer, Director of Product,                    │
│  Product Operations                                             │
│                                                                  │
│  Priority order:                                                 │
│  1. Head of Product / CPO (decision maker)                      │
│  2. Director of Product (strong influencer)                     │
│  3. VP Product (strong influencer)                              │
│  4. Senior Product Manager (user/champion)                      │
│                                                                  │
│  Step 2: Email Verification                                      │
│  GET /email-verifier?email={found_email}                        │
│  Only keep: "deliverable" status                                 │
│  Discard: "risky" or "undeliverable"                            │
│                                                                  │
│  If Hunter.io returns no results:                                │
│  → Use Apollo.io domain search as fallback (if API key set)     │
│  → If still no contact: flag as "domain_only" and continue      │
│    (company-level record still valuable for Productboard)       │
│                                                                  │
│  Output:                                                         │
│  contact_name, contact_title, contact_email, email_confidence   │
└─────────────────────────────────────────────────────────────────┘
```

---

### PHASE 7 — Signal-Specific Outreach Generation
```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 7: OUTREACH GENERATION                                   │
│  Tool: Gemini API (Pro model) via n8n HTTP Request              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  CRITICAL: Signal type determines the outreach angle            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  IF signal_type == "TIMING"                             │   │
│  │  Angle: Scaling your product team is the right move.    │   │
│  │  Here's how teams at your stage prevent roadmap chaos.  │   │
│  │  Reference: their funding round + PM hiring activity    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  IF signal_type == "INTENT"                             │   │
│  │  Angle: You've outgrown {competitor_mentioned}.         │   │
│  │  Here's what teams switch to and why.                   │   │
│  │  Reference: their specific pain points from review/post │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  IF signal_type == "BOTH"                               │   │
│  │  Angle: Timing + proof of pain. Highest urgency frame.  │   │
│  │  "Companies at your exact stage that outgrow            │   │
│  │   {competitor} typically make this switch in 90 days."  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Generate per lead:                                              │
│  - email_subject (A/B variant A)                                │
│  - email_subject (A/B variant B)                                │
│  - email_body (150 words max, no fluff)                         │
│  - linkedin_message (300 chars max)                             │
│  - call_script (3 bullet opening + 2 discovery questions)       │
│                                                                  │
│  Implement dual-key fallback + exponential backoff              │
└─────────────────────────────────────────────────────────────────┘
```

---

### PHASE 8 — CRM Output (HubSpot + Sheets + Discord)
```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 8: OUTPUT — runs in PARALLEL                             │
├────────────────────┬────────────────────┬───────────────────────┤
│  HubSpot           │  Google Sheets     │  Discord              │
├────────────────────┼────────────────────┼───────────────────────┤
│  Create Company:   │  Append row with   │  Webhook POST:        │
│  POST /companies   │  all fields        │  "🎯 New lead:        │
│                    │  (see output       │  {company} scored     │
│  Create Contact:   │  schema below)     │  {score}/100          │
│  POST /contacts    │                    │  Signal: {type}       │
│                    │  Tab structure:    │  Contact: {name}"     │
│  Associate them:   │  - Pipeline        │                       │
│  PUT /associations │  - Leads           │  Color code:          │
│                    │  - Intelligence    │  🟢 BOTH signal       │
│  Set properties:   │  - Dashboard       │  🟡 TIMING only       │
│  - signal_type                          │  🔵 INTENT only       │
│  - icp_score       │  (Same structure   │                       │
│  - signal_source   │  as Project F      │                       │
│  - pain_points     │  Google Sheet)     │                       │
│  - outreach assets │                    │                       │
│  - deal_stage:     │                    │                       │
│    "signal_queued" │                    │                       │
└────────────────────┴────────────────────┴───────────────────────┘
```

---

## 7. n8n Workflow — Node Map

```
[CRON TRIGGER]
Daily: 9:00 AM PST
─────────────────────────────────────────
        │
        ▼
[SPLIT IN BATCHES] ─── runs all 3 branches simultaneously
        │
        ├── [HTTP REQUEST] Crunchbase API
        │   Method: GET
        │   URL: https://api.crunchbase.com/api/v4/searches/organizations
        │   Auth: Header — X-cb-user-key: {{$env.CRUNCHBASE_API_KEY}}
        │   Body: filter for funded_at last 90 days, series A/B, SaaS
        │
        ├── [HTTP REQUEST] Apify — LinkedIn Job Scraper
        │   Method: POST
        │   URL: https://api.apify.com/v2/acts/curious_coder~linkedin-jobs-scraper/runs
        │   Auth: Bearer {{$env.APIFY_API_TOKEN}}
        │   Body: { keywords: "product manager", datePosted: "past month" }
        │
        └── [HTTP REQUEST] Apify — G2 Review Scraper
            Method: POST
            URL: https://api.apify.com/v2/acts/{g2-actor-id}/runs
            Body: { urls: [Aha!/JiraPD/ProductPlan G2 pages], maxReviews: 50 }
─────────────────────────────────────────
        │ (all 3 complete)
        ▼
[MERGE NODE] — Merge All Results (Wait for All)
─────────────────────────────────────────
        │
        ▼
[CODE NODE] — Normalize + Deduplicate
  Language: JavaScript
  Logic: extract domain, normalize names,
         check seen_companies list,
         group by domain, tag signal_type
─────────────────────────────────────────
        │
        ▼
[HTTP REQUEST] — Gemini API (Sentiment Classification)
  Method: POST
  URL: https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent
  Auth: API Key param — key={{$env.GEMINI_API_KEY}}
  Body: structured prompt with signal text
─────────────────────────────────────────
        │
        ▼
[CODE NODE] — ICP Scoring Algorithm
  Language: JavaScript (inline) OR
  [HTTP REQUEST] → FastAPI /score endpoint (Python)
  Returns: icp_score, score_breakdown
─────────────────────────────────────────
        │
        ▼
[FILTER NODE] — icp_score >= 70
─────────────────────────────────────────
        │ (qualified only)
        ▼
[HTTP REQUEST] — HubSpot Company Search
  Method: POST
  URL: https://api.hubapi.com/crm/v3/objects/companies/search
  Auth: Bearer {{$env.HUBSPOT_PRIVATE_APP_TOKEN}}
─────────────────────────────────────────
        │ (new companies only)
        ▼
[HTTP REQUEST] — Hunter.io Domain Search
  Method: GET
  URL: https://api.hunter.io/v2/domain-search
  Params: domain, api_key, limit=5
─────────────────────────────────────────
        │
        ▼
[HTTP REQUEST] — Gemini API (Outreach Generation)
  Model: gemini-2.0-pro (higher quality)
  Signal-specific prompt based on signal_type
─────────────────────────────────────────
        │
        ▼
[SPLIT IN BATCHES] ─── runs all 3 outputs simultaneously
        │
        ├── [HTTP REQUEST] HubSpot — Create Company + Contact
        │
        ├── [HTTP REQUEST] Google Sheets — Append Row
        │
        └── [HTTP REQUEST] Discord — Webhook Notification
```

---

## 8. Output Schema

All fields written to both HubSpot and Google Sheets:

```
FIELD                    TYPE        SOURCE              HUBSPOT PROPERTY
─────────────────────────────────────────────────────────────────────────
company_name             string      Crunchbase/Apify    name
company_domain           string      extracted           domain
company_size             integer     Crunchbase          numberofemployees
funding_stage            string      Crunchbase          custom: funding_stage
funding_date             date        Crunchbase          custom: funding_date
funding_amount           string      Crunchbase          custom: funding_amount_usd
pm_job_post_count        integer     Apify LinkedIn      custom: pm_hiring_velocity
signal_type              enum        computed            custom: gtm_signal_type
                         TIMING|INTENT|BOTH
signal_source            string      Apify/Crunchbase    custom: signal_source
signal_text              string      raw review/post     custom: signal_detail
competitor_mentioned     string      Gemini extract      custom: competitor_using
pain_points              array→str   Gemini extract      custom: pain_points
icp_score                integer     scoring.py          custom: icp_score
score_breakdown          json→str    scoring.py          custom: score_detail
contact_name             string      Hunter.io           firstname + lastname
contact_title            string      Hunter.io           jobtitle
contact_email            string      Hunter.io           email
email_confidence         integer     Hunter.io           custom: email_confidence
outreach_email_subj_a    string      Gemini              custom: outreach_subject_a
outreach_email_subj_b    string      Gemini              custom: outreach_subject_b
outreach_email_body      string      Gemini              custom: outreach_email
outreach_linkedin        string      Gemini              custom: outreach_linkedin
outreach_call_script     string      Gemini              custom: call_script
deal_stage               enum        computed            dealstage: signal_queued
created_at               timestamp   system              createdate
hubspot_contact_id       string      HubSpot response    (internal)
```

---

## 9. HubSpot Setup (Sandbox)

```
HUBSPOT CONFIGURATION STEPS
────────────────────────────────────────────────────────
1. Create free HubSpot Developer account
   → https://developers.hubspot.com/

2. Create a Sandbox account (free within developer account)

3. Create Private App:
   Settings → Integrations → Private Apps → Create
   Scopes needed:
   - crm.objects.contacts.write
   - crm.objects.contacts.read
   - crm.objects.companies.write
   - crm.objects.companies.read
   - crm.schemas.contacts.write   (for custom properties)

4. Create Custom Properties on Company object:
   Settings → Properties → Company → Create property
   Create all custom: properties from output schema above

5. Create Custom Properties on Contact object:
   Same flow — add outreach assets as contact properties

6. Copy Private App Token → add to .env
```

---

## 10. File Structure (New Repo)

```
gtm-signal-engine/
│
├── .env.example                 # All required env vars (no values)
├── .env                         # Your actual keys (gitignored)
├── .gitignore
├── README.md                    # Project overview + setup instructions
├── requirements.txt
│
├── n8n/
│   └── workflow.json            # Exportable n8n workflow file
│                                # Import via n8n UI → Import from file
│
├── python/
│   ├── scoring.py               # ICP scoring algorithm (testable)
│   ├── enrichment.py            # Hunter.io integration + Apollo fallback
│   ├── outreach.py              # Gemini outreach generation + prompts
│   └── classify.py              # Gemini signal classification
│
├── utils/
│   ├── gemini.py                # Gemini client with dual-key + backoff
│   ├── hubspot.py               # HubSpot API wrapper
│   ├── sheets.py                # gspread integration
│   └── discord.py               # Discord webhook helper
│
├── api/
│   └── main.py                  # FastAPI app — exposes /score endpoint
│                                # Called by n8n Code node via HTTP
│
├── tests/
│   ├── test_scoring.py          # pytest — scoring algorithm
│   ├── test_enrichment.py       # pytest — enrichment logic
│   └── test_classify.py         # pytest — classification output
│
├── schemas/
│   └── hubspot_mapping.md       # Field mapping doc (this output schema)
│
└── data/
    └── seen_companies.json      # Dedup state file (gitignored)
```

---

## 11. Environment Variables (.env.example)

```bash
# Scraping
APIFY_API_TOKEN=

# Funding Data
CRUNCHBASE_API_KEY=

# Email Enrichment
HUNTER_API_KEY=
APOLLO_API_KEY=                  # Optional fallback

# AI Generation
GEMINI_API_KEY=
GEMINI_API_KEY_2=                # Dual-key fallback for rate limits

# CRM
HUBSPOT_PRIVATE_APP_TOKEN=

# Output
GOOGLE_SHEETS_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=     # Path to service account key file
DISCORD_WEBHOOK_URL=

# Config
ICP_SCORE_THRESHOLD=70           # Minimum score to qualify lead
LOOKBACK_DAYS_FUNDING=90         # Days back for funding events
LOOKBACK_DAYS_JOBS=60            # Days back for job postings
DEDUP_WINDOW_DAYS=7              # Skip company if seen within N days
```

---

## 12. Success Criteria

```
METRIC                           TARGET
──────────────────────────────────────────────────────
Runs without manual intervention  YES — cron scheduled
Leads per run (score ≥ 70)        20–50 qualified leads
Signal coverage                   All 3 sources firing
HubSpot records created           Each lead has Contact
                                  + Company with all
                                  custom properties set
Outreach quality                  Signal-specific angle,
                                  not generic
Deduplication working             No duplicate companies
                                  within 7-day window
Discord notifications             Real-time per lead
Demo-ready output                 Google Sheet viewable
                                  without CRM access
```

---

## 13. Interview Talking Points — Built For This Project

When Darrell asks "walk me through something you built":

1. **The problem framing:** "Most outbound pipelines target demographics. I built this to detect behavioral signals — companies actively experiencing the pain Productboard solves, not just companies that fit a profile."

2. **Why n8n:** "n8n gives full control over branching logic and data flow. I can run parallel signal sources, merge results, and route conditionally — things that get messy in Zapier or Make at this complexity. It's also self-hostable, which matters for data quality and rate limit management."

3. **Why signal-specific outreach:** "A company frustrated with Aha! needs a different message than a company that just raised a Series B and is scaling their PM team. The signal determines the angle. Generic outreach ignores that."

4. **The HubSpot decision:** "I wanted the output to plug directly into a real CRM workflow — not just a spreadsheet. HubSpot's API creates Company and Contact objects, custom properties for signal data, and sets deal stage. The sheet runs in parallel for QA and stakeholder visibility."

5. **What you'd do next:** "The next layer is building an n8n sub-workflow that monitors HubSpot deal stage changes and triggers follow-up sequences based on engagement — essentially closing the feedback loop between signal capture and outreach performance."
```

---

*Blueprint version 1.0 — July 2026*
*Transfer to new repo. Do not build in Project-Interview-Prep.*
