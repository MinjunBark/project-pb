# Current System Architecture — Post Redesign v2, Tier 1 through Tier 5

> Snapshot date: 2026-07-13, after Tier 1 (buying-intent language mining, leadership-page diffing, Product Hunt launch monitoring), the outreach-copy gap fix, Tier 2 (Discord ops-progress + SDR digest + `full_pipeline_run.py` orchestrator), Tier 3 (demand-driven Branch C + digest watchlist + run-query logging), Tier 4 (Clay demographic enrichment pass), and Tier 5 (Discord-driven Clay human-in-the-loop with automatic resume). See `docs/HANDOFF.md`/`docs/PROGRESS.md` for live-verification numbers behind every item. This file goes stale as further work happens; treat it as a point-in-time reference, not a living doc.
>
> **Tier 5 update:** the DEMOGRAPHIC bucket referenced below as "built, still not live-wired — Clay gap unchanged" is now closed. Clay enrichment (both the original domain pass and Tier 4's demographic pass) is no longer a silent, forgettable manual side-quest: `full_pipeline_run.py` now auto-detects when either queue is non-empty, exports a real CSV, and posts it to a dedicated `#clay-enrichment` Discord channel (`DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL`) with exact round-trip instructions. The moment the user drops the enriched file back into `data/clay/incoming_domain/` or `data/clay/incoming_demographics/`, a background poller running inside the same `uvicorn` process (60s interval) auto-imports it and automatically re-runs leadership check → scoring → SDR digest (`resume_after_enrichment()`) — no manual re-trigger. Live-verified end-to-end 2026-07-13.

```
════════════════════════════════════════════════════════════════════════════
  GTM SIGNAL ENGINE — CURRENT ARCHITECTURE (post Redesign v2, Tier 1 + Tier 2)
  Orchestration: n8n PAUSED — but a real, manual, Discord-visible full-cycle
  orchestrator now exists (see ORCHESTRATION box below)
════════════════════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — SIGNAL COLLECTION (independent sources, called directly today) │
│                                                                            │
│   Branch A          Branch B                Branch C         Branch D    │
│   SEC EDGAR      Adzuna+Greenhouse/Lever      G2(Apify)   Product Hunt    │
│   (funding)          (hiring)              (competitor    (new product   │
│   free               free                    intent)       launches)     │
│                         │                     paid/call      free        │
│                         ▼                   (opt-in only)  (real token   │
│                 ┌───────────────────┐                       verified)    │
│                 │ buying-intent      │  Gemini call on the SAME job-desc  │
│                 │ language scan      │  text already fetched — no new     │
│                 │ (LLM, not regex)   │  external source, cost-guarded     │
│                 └───────────────────┘  (once per co., most-recent post)  │
│  POST /branch-a/run   /branch-b/run   /branch-c/run      /branch-d/run   │
└────────────┬───────────────┬───────────────────┬─────────────┬──────────┘
             │               │                   │             │
             ▼               ▼                   ▼             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 2 — LANDING + MERGE (system of record)                            │
│                                                                            │
│   data/raw/*.json (local landing, pre-merge safety net)                  │
│                        │                                                  │
│                        ▼                    POST /merge/run              │
│   Supabase / Postgres — companies, signals (funding | pm_hiring |        │
│   buying_intent | competitor_review | product_launch),                   │
│   competitor_intel, g2_reviews, leads                                    │
└────────────────────────────┬─────────────────────────────────────────---─┘
                              │
        ┌─────────────────────┴──────────────────────┐
        │  SEPARATE PATH — leadership_monitor.py       │
        │  Own endpoint: POST /leadership/run          │
        │  ⚠ ARCHITECTURAL EXCEPTION: writes directly  │
        │  to Postgres (not land-then-merge) because   │
        │  it needs durable snapshot state to diff      │
        │  against next run                             │
        │                                                │
        │  companies (domain IS NOT NULL, 22/62 today)  │
        │      │  guess /about, /team, /leadership, ... │
        │      ▼  (55% real hit rate, measured live)    │
        │  fetch page → BeautifulSoup → hash            │
        │      │                                         │
        │      ├─ hash unchanged → skip (no Gemini call) │
        │      └─ hash changed/first run → Gemini extract│
        │              CPO/VP Product/Head of Product     │
        │              names → diff vs. prior snapshot   │
        │              → new name? → signals row          │
        │                (signal_category=leadership_hire)│
        │  → company_leadership_snapshots table            │
        └─────────────────────┬──────────────────────────┘
                               │  (feeds back into signals table above)
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 3 — ENRICHMENT                                                    │
│   Clay (name → domain waterfall)   Gemini classify (G2 review →         │
│                                      company attribution, rare)          │
└────────────────────────────┬─────────────────────────────────────────---─┘
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 4 — FILTERING / SCORING (python/scoring.py)                       │
│                                                                            │
│   TIMING (max 50, explicit min(50) cap)                                  │
│     funding_recency (25/15) + pm_posting_count (15/8) +                  │
│     product_ops_posting (10) + recent_product_launch (10, ≤30d) +        │
│     new_leadership_hire (15, ≤90d)                                       │
│                                                                            │
│   INTENT (max 40, capped)                                                │
│     competitor_severity (15/25/40, from G2 corpus) +                     │
│     buying_intent_language (10, from job-posting text)                   │
│                                                                            │
│   DEMOGRAPHIC (max 25, built, still not live-wired — Clay gap unchanged) │
│   DEDUCTIONS + BOTH-signal bonus (+10 if TIMING>0 AND INTENT>0)          │
│                                                                            │
│   icp_score ≥ 70 → qualified                                             │
└────────────────────────────┬─────────────────────────────────────────---─┘
                              │  qualifies?
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 5 — DEDUPE / GATING                                               │
│   Postgres recency window → HubSpot "recently contacted" check          │
└────────────────────────────┬─────────────────────────────────────────---─┘
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 6 — OUTREACH GENERATION (Gemini)              ✅ GAP CLOSED       │
│   build_lead_context() now pulls buying_intent_phrase, new_leadership_   │
│   hire, and recent_product_launch into what actually gets sent to        │
│   Gemini. outreach.py rewritten to dynamic fact lists (fixed a real      │
│   latent bug: a lead can now score TIMING/INTENT purely from one of the  │
│   3 new signals alone, and the old fixed-field template would have      │
│   rendered literal "None"). Live-verified against Anduril Industries.    │
└────────────────────────────┬─────────────────────────────────────────---─┘
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 7 — OUTPUT FAN-OUT                                                │
│   leads table │ HubSpot company create/update │ Google Sheet │           │
│   Discord (per-lead, color-coded, DISCORD_WEBHOOK_URL)                   │
│   Still only 1 test lead has ever reached this layer for real - no real  │
│   company has organically qualified yet across any live run so far.     │
└────────────────────────────┬─────────────────────────────────────────---─┘
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 8 — OBSERVABILITY (Discord)  ◄ NEW this session                   │
│                                                                            │
│   3 separate channels/webhooks, 3 separate purposes:                     │
│   1. Per-lead (DISCORD_WEBHOOK_URL) — fires once per qualifying lead,    │
│      real-time, color-coded. Existing, unchanged.                        │
│   2. Ops-progress (DISCORD_PROGRESS_WEBHOOK_URL) — plain-text status      │
│      line posted at every phase boundary of a full_pipeline_run.py run.  │
│      Noisy by design - meant for whoever's watching a run happen live.   │
│   3. SDR-digest (DISCORD_SDR_DIGEST_WEBHOOK_URL) — ONE clean message per  │
│      run: date, qualified-lead count, one field per lead (company,       │
│      icp_score, signal_type, priority_summary). Built from the SAME      │
│      in-memory results just written to the Sheet/HubSpot - not a second  │
│      read, no drift risk. 0-qualified case reads as normal, not broken.  │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATION — n8n PAUSED, but a real manual orchestrator exists ◄NEW  │
│                                                                            │
│   n8n workflow "GTM Signal Engine" (SsGnN1xKSHqz68c3) still exists but   │
│   is EXCLUDED from active use - does not know Branch D, /leadership/run, │
│   or /pipeline/run-full-cycle exist.                                    │
│                                                                            │
│   NEW: python/full_pipeline_run.py + POST /pipeline/run-full-cycle       │
│   Runs Branch A/B/D (C opt-in only, ADR-009) → merge → leadership check  │
│   → score + process every company, in ONE call, in-process (not via      │
│   self-HTTP-calls), posting to Layer 8's ops-progress channel at every   │
│   phase boundary and the SDR digest at the end. Fails loud: any phase's  │
│   exception posts a ❌ to ops-progress then re-raises, stopping the run. │
│   This is the real "run everything, watch it happen" entry point until   │
│   n8n (or whatever replaces it) resumes.                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Sequence diagram — what `POST /pipeline/run-full-cycle` actually does

This is the exact chronological sequence `full_pipeline_run.run_full_cycle()` executes for one real full-cycle test run, including what each phase calls, what it expects back, where output gets stored, and the exact Discord message posted at each boundary.

```
FULL PIPELINE RUN — run_full_cycle() chronological sequence
(triggered by: POST /pipeline/run-full-cycle {"include_branch_c": false})

00. HTTP request → api/main.py → full_pipeline_run.run_full_cycle()
    Discord[ops-progress]: "🚀 Starting full pipeline run..."

01. BRANCH A — funding_edgar.get_funding_signals()
    Calls:    SEC EDGAR full-text search (efts.sec.gov) + primary_doc.xml fetches
    Expects:  list[dict] — company_name, funding_stage, funding_date,
              funding_amount_usd, industry, biz_location, cik, accession_no
    Stores:   data/raw/branch_a_<timestamp>.json (local landing only, no DB yet)
    Discord:  "✅ Branch A (funding): N signals landed."

02. BRANCH B — hiring_signals.get_hiring_signals()
    Calls:    Adzuna API (broad) → Greenhouse/Lever APIs (per-company) →
              Gemini (buying-intent classify, once per co., most-recent
              PM posting only)
    Expects:  list[dict] — company_name, pm_job_post_count, job_titles,
              current_tools_mentioned, buying_intent{detected, phrase}
    Stores:   data/raw/branch_b_<timestamp>.json
    Discord:  "✅ Branch B (hiring): N signals landed."

03. BRANCH D — producthunt_launches.get_launch_signals()
    Calls:    Product Hunt GraphQL API v2 (real developer token)
    Expects:  list[dict] — company_name(=product name), tagline, launched_at, url
    Stores:   data/raw/branch_d_<timestamp>.json
    Discord:  "✅ Branch D (launches): N signals landed."

04. BRANCH C — SKIPPED by default (real Apify $, ADR-009)
    Discord:  "⏭️ Branch C skipped (opt-in only, ADR-009)."

05. MERGE — merge_signals.run_full_merge(conn)
    Calls:    Supabase/Postgres (db.get_connection)
    Reads:    the 3 just-landed JSON files (raw_landing.load_latest_raw_signals)
    Writes:   companies table (upsert, dedup by normalized_name/domain)
              signals table — new rows tagged: funding | pm_hiring |
              buying_intent | product_launch
    Discord:  "✅ Merge complete: N distinct companies touched."

06. LEADERSHIP CHECK — leadership_monitor.check_for_new_leadership()
    Scope:    only companies where domain IS NOT NULL (22/62 as of last count)
    Calls:    each company's own website (5 guessed paths) → BeautifulSoup →
              Gemini (only if content hash changed since last snapshot)
    Writes:   company_leadership_snapshots (always) + signals row
              (signal_category=leadership_hire, only on a genuinely new name)
    Discord:  "✅ Leadership check: N companies checked, N new hire(s) found."

07. SCORE + PROCESS EVERY COMPANY — loop over db.get_all_companies()
    For each company:
      a. scoring.score_company() — TIMING/INTENT buckets, now including
         buying_intent_language / recent_product_launch / new_leadership_hire
      b. icp_score < 70 → status "not_qualified", stop here (most companies)
      c. icp_score >= 70 → dedup checks (Postgres recency window, then
         HubSpot "recently contacted") → may stop here too
      d. Still qualified → outreach.generate_outreach() [Gemini call] →
         now includes the buying-intent phrase / leadership hire / launch
         tagline in the generated copy (outreach-copy-gap fix, Layer 6)
      e. HubSpot: create_company() or update_company() — REAL CRM WRITE
      f. Postgres: db.insert_lead() — leads table row
      g. Google Sheets: sheets.append_lead_row() — REAL SPREADSHEET ROW
      h. Discord[per-lead channel]: send_lead_notification() — color-coded
         (green=BOTH/yellow=TIMING/blue=INTENT) — fires immediately, per lead
    Discord[ops-progress]: "✅ Scoring + outreach complete: N evaluated,
                            N qualified and processed."

08. SDR DIGEST — discord.send_sdr_digest()
    Built from: the in-memory "processed" results captured in step 07
                (NOT a second read of the Sheet — same data, no drift risk)
    Discord[sdr-digest channel]: ONE message —
      0 qualified: grey embed, "No new qualified leads today... no action needed."
      >0 qualified: green embed(s), date + count + one field per lead
                    (company, icp_score, signal_type, priority_summary)

09. Discord[ops-progress]: "🏁 Full pipeline run complete."
    conn.close()
    HTTP response ← RunFullCycleResponse (all the counts from every phase)
```

### What's realistically expected on the next real run
Every prior live run this session found **0 organically-qualifying companies** (real EDGAR/Adzuna/Product Hunt data, strict multi-signal threshold). The next run will very likely also show `qualified_count: 0`, and the SDR digest will show the "no action needed" message — that's the correct, already-validated behavior of this scoring model, not a sign anything is broken. The value of running it is confirming the *new* pieces (Discord progress/digest, the full orchestrator, all 3 redesign-v2 signals in one real pass together) work correctly end-to-end, not necessarily producing a qualifying lead.

---

## Open items visible in this diagram

1. ~~**Layer 6 gap**~~ — **CLOSED.** `build_lead_context()` now surfaces all 3 new signal types in outreach copy.
2. **Layer 2's leadership_monitor exception** — still the only write path bypassing `/merge/run`. Deliberate, documented.
3. **Discord observability (Layer 8) and the full-cycle orchestrator are built and unit-tested (229/229) but not yet exercised against a real live run** — the next step is actually calling `POST /pipeline/run-full-cycle` for real and confirming both new Discord channels populate correctly against real data.
4. **Orchestration is still split**: n8n (paused, doesn't know about Branch D/leadership/full-cycle) vs. the new manual `full_pipeline_run.py` (works today, not on a schedule). Whatever resumes/replaces n8n needs to reconcile with this.
