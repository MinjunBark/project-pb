# Code Guide — What Each Script Does and Why

> Owns: plain-language explanation of what each Python module in `python/` actually does, how its pieces fit together, and real sample output from testing it. This is the "read this to understand the code" doc — status lives in `PROGRESS.md`, tool-choice rationale lives in `DECISIONS.md`, bugs live in `ISSUES.md`. Update this whenever a module's behavior changes; don't leave it describing code that no longer exists.

---

## The big picture

Three signal branches collect raw data. Branches A and B both produce the same shape: a list of dicts describing a company and why it's a candidate lead. Branch C is different on purpose (see its section below) — it produces competitive-intelligence content, not per-company lead records. `merge_signals.py` (Phase 3) writes all three branches into Postgres with real dedup; `scoring.py` (Phase 4) reads a company + its signals back out and produces a qualifying score. HubSpot/n8n wiring still comes in later phases.

```
Branch A: python/funding_edgar.py         → funding events (SEC EDGAR)
Branch B: python/hiring_adzuna.py          → Layer 1: broad PM-hiring discovery (Adzuna)
          python/hiring_ats_lookup.py      → Layer 2: per-company deepening (Greenhouse/Lever)
          python/hiring_signals.py         → orchestrator combining Layers 1 + 2
Branch C: python/intent_g2.py              → competitor G2 reviews + pain-point corpus
          python/raw_landing.py            → local landing zone for all branches' raw output (replaces S3)

Phase 3:  python/merge_signals.py          → writes all 3 branches into Postgres (dedup via utils/db.py)
Phase 4:  python/scoring.py                → reads a company + signals, returns icp_score + signal_type
```

---

## Branch A: `python/funding_edgar.py`

**What it answers:** "Which companies recently raised money?"

**How it works, in order:**

1. **`search_form_d_filings(keywords, lookback_days)`** — calls SEC EDGAR's full-text search API asking for Form D filings (the mandatory disclosure any US company makes when raising private capital) that mention a keyword like `"software"`, filed within the last N days. A keyword is required — a bare date-range search returns mostly venture funds raising their own capital, not companies that got funded (see `docs/ISSUES.md`). Also filters out anything that looks like a fund name (`"Fund"`, ends in `"LP"`, etc.) as a second safety net, and de-duplicates by CIK across multiple keyword searches. **US-only filter (added 2026-07-10, ADR/ISSUES):** also drops any filing whose `biz_location` isn't a "City, ST" US state pair — EDGAR has no built-in country filter, and a live run turned up a real Israeli filer (Pulsenmore Ltd.) alongside genuine US companies.

2. **`fetch_form_d_details(cik, accession_no)`** — for each candidate company found above, fetches that company's *actual filing document* (an XML file) and pulls out the real numbers: how much money was raised (`total_offering_amount`), and what industry the company self-reported (`industry_group`).

3. **`approximate_funding_stage(offering_amount)`** — Form D doesn't say "this is a Series B" the way Crunchbase would. This function converts a raw dollar amount into a stage label using documented bands (e.g. $15M–$50M → "Series B"). It's a heuristic, not a fact reported by the filing.

4. **`get_funding_signals(keywords, lookback_days)`** — the one function everything else calls. Runs steps 1–3 together and returns a clean list of dicts, one per company.

**Real sample output** (from a live 60-day search for "software"):
```json
{
  "company_name": "Kepler Software, Inc.",
  "funding_amount_usd": 36164297,
  "funding_date": "2026-05-15",
  "funding_stage": "Series B",
  "industry": "Other Technology",
  "biz_location": "San Francisco, CA",
  "cik": "0002126990",
  "accession_no": "0002126990-26-000001",
  "source": "sec_edgar_form_d"
}
```

**Known gap:** this only gives a company *name*, not a website domain — needed later for deduping in Postgres. Deferred to Clay in Phase 7.

---

## Branch B, Layer 1: `python/hiring_adzuna.py`

**What it answers:** "Which companies are hiring Product Managers right now, broadly, across the whole job market?"

**How it works:**

1. **`search_adzuna_jobs(keyword, country, max_days_old)`** — calls Adzuna's official job-search API (needs a free `app_id`/`app_key`) for one keyword (e.g. "Product Manager"), filtered to postings within the last N days.

2. **`normalize_adzuna_results(raw_results)`** — Adzuna returns one row per job posting; this groups them by company name and counts how many PM-related postings each company has, tracking the most recent posting date.

3. **`get_adzuna_hiring_signals(keywords, lookback_days)`** — runs step 1 for each keyword (e.g. "Product Manager" and "Product Operations"), then groups everything together in step 2.

**Live-verified 2026-07-09** (Adzuna is free, so no usage concern like Apify): a real 30-day search for "Product Manager" returned 28 real companies (MaxCyte, LevelTen Energy, PacifiCorp, etc.) — see `data/adzuna_signals_sample.json`.

**Known gap:** same as Branch A — gives a company name, not a domain.

---

## Branch B, Layer 2: `python/hiring_ats_lookup.py`

**What it answers:** "For a specific company, what does its *own* careers page say about open PM roles — more complete and current than an aggregator's snapshot?"

**How it works:**

1. **`generate_candidate_slugs(company_name)`** — most companies that use Greenhouse or Lever have a "board token" (Greenhouse) or "client name" (Lever) that's a simplified version of their name — e.g. "Acme Corp" → `acme`. This function guesses a couple of likely variants. It's a heuristic — it won't always guess right, and that's documented, not hidden.

2. **`try_greenhouse(company_name)`** — tries each guessed slug against Greenhouse's public Job Board API (`boards-api.greenhouse.io/v1/boards/{slug}/jobs`). No login, no API key — this is Greenhouse's own public, sanctioned way for job boards to embed a company's listings. Returns the first slug that actually resolves (HTTP 200), or `None` if none do.

3. **`try_lever(company_name)`** — same idea, against Lever's equivalent public API. Verified live: Lever returns a clean HTTP 404 for a company that isn't a real client, and a plain JSON list (empty or not) for one that is.

4. **`enrich_company_with_ats_data(company_name)`** — tries Greenhouse first, then Lever if Greenhouse doesn't resolve, and filters whatever it finds down to just the PM/Product-Operations-relevant postings (since these APIs return *all* of a company's jobs, not just PM ones). Also fetches full job description text (Greenhouse via `?content=true`, Lever's `descriptionPlain`) and scans it for explicit mentions of our 4 named competitors — see below.

5. **`scan_for_competitor_tools(text)`** (ADR-013, added 2026-07-10) — the answer to "can we connect a *specific* lead to a *specific* competitor's pain points?" PM job postings sometimes explicitly name required/preferred tools (e.g. "experience with Jira Product Discovery a plus"). This is the one genuinely per-company signal that can point Phase 8's outreach at the *right slice* of Branch C's G2 corpus for that specific lead, since G2 reviews themselves can't carry company identity. Requires the exclamation mark or "roadmaps" for "Aha!" specifically, since bare "aha" is a common word (same lesson learned from the Hacker News false-positive research earlier).

**Real sample output** (live test against GitLab, which really does use Greenhouse):
```json
{
  "source": "greenhouse",
  "matched_slug": "gitlab",
  "pm_postings": [
    {
      "title": "Principal Product Manager, AI Custom Models",
      "location": "Remote, Canada; Remote, US",
      "posted_date": "2026-05-27T14:51:21-04:00",
      "description": "...",
      "url": "https://job-boards.greenhouse.io/gitlab/jobs/8564957002"
    }
  ],
  "current_tools_mentioned": []
}
```
(4 more real postings omitted here — see `data/hiring_signals_sample.json` for the full list. GitLab's real postings don't mention any of our 4 competitors, which is itself a correct, live-verified result — not every company will.)

**Known limitation:** the slug guess won't always work — many companies use a different ATS entirely (Workday, Ashby, etc.), or a less obvious slug. When neither Greenhouse nor Lever resolves, this returns `{"source": None, "pm_postings": [], "current_tools_mentioned": []}` — not an error, just "couldn't verify this one."

---

## Branch B orchestrator: `python/hiring_signals.py`

**What it does:** calls Layer 1 (Adzuna) to get a list of candidate companies, then for each one calls Layer 2 (Greenhouse/Lever) to try to get richer, more current data straight from that company's own careers page. If Layer 2 resolves, its data wins. If it doesn't, falls back to what Layer 1 already found — so a company is never dropped just because its ATS couldn't be guessed.

This is the one function the rest of the pipeline (later phases) will actually call — `get_hiring_signals()` — the two layers underneath are implementation detail.

**Live-verified 2026-07-09, full chain:** running `get_hiring_signals(keywords=['Product Manager'], lookback_days=30)` against real data returned 28 companies, of which only **2 (~7%)** resolved via Greenhouse/Lever — the rest fell back to Adzuna-only data, exactly as designed. Worth knowing this number precisely rather than assuming Layer 2 resolves for "most" companies — see `docs/ISSUES.md` for the full writeup.

---

## Branch C: `python/intent_g2.py`

**What it answers:** "What are real customers actually saying about our named competitors (Aha!, Jira Product Discovery, ProductPlan, Craft.io)?"

**Why this branch looks different from A and B:** G2 reviews are anonymous by design — the actor's reviewer fields are name, country, region, company-size segment, and industry code, but *not* the reviewer's company name. So most reviews can't be attached to a specific company the way Branch A/B signals can. Rather than force a bad fit, this branch is built around what G2 data is actually good for: real competitive-intelligence content, reusable in messaging.

**How it works:**

1. **`build_product_review_url(product_slug)`** — builds the full G2 URL the actor actually expects (e.g. `https://www.g2.com/products/aha/reviews`).

2. **`run_g2_review_scraper(product_slug, max_reviews)`** — calls the Apify actor `automation-lab/g2-scraper` for one competitor's reviews, passing that URL via the `productUrls` input param. **Not live-tested by Claude** (per ADR-009 — Apify usage isn't free like EDGAR, so the user tests live).

3. **`normalize_g2_reviews(raw_reviews, competitor_name)`** — cleans up each review into a consistent shape, and flags two things per review: `is_negative` (star rating ≤ 3) and `is_switch_signal` (the reviewer named a prior product or a reason for switching, via the actor's `switchedFromOtherProduct`/`switchedReason` fields). Does **not** try to guess the reviewer's company from the text — that's left to Phase 5's Gemini classification step, which is a genuine NLP job, not something a regex should attempt.

4. **`build_pain_point_corpus(normalized_reviews)`** — the actual point of this branch. Groups reviews by competitor and pulls out: how many were negative, how many mentioned switching, and representative quotes (the actual "reason for switching" text). This corpus is what Phase 8's outreach generation will draw on — e.g., an email to a company evaluating alternatives can reference *real, common* complaints about a specific competitor instead of generic messaging.

5. **`get_intent_signals(competitors, max_reviews_per_competitor)`** — runs the whole flow across all 4 competitors and returns `{"reviews": [...], "pain_point_corpus": {...}}`.

**Live-tested by the user, 2026-07-10** — first real run: 60 reviews across all 4 competitors (15 each), ~$0.31 total cost. The G2 product slugs in `DEFAULT_COMPETITORS` are **confirmed** against real G2 URLs — 2 of the original 4 guesses were wrong: it's `"aha"` not `"aha-roadmaps"`, and `"craft-io-craft-io"` (a real G2 URL quirk, not a typo) not `"craftio"`.

**Two real bugs caught, both logged in `docs/ISSUES.md`:**
1. **Before the live run** — a deeper documentation pass (the actor's actual parameter table and example JSON, not a prose summary) found the input param and several output field names were wrong: `productSlugs` should have been `productUrls`, `text`/`npsScore`/`priorProductName`/etc. should have been `reviewText`/`nps`/`switchedFromOtherProduct`/etc.
2. **After the live run, from the real data** — `switchedFromOtherProduct` turned out to be a `"yes"`/`"no"`/`"unknown"` flag, not a product name as assumed. A truthy-string bug (`bool("no")` is `True` in Python) meant 42 of 60 real reviews were being incorrectly counted as switch signals instead of the real 13. Fixed with an explicit `== "yes"` check, renamed the misleading `prior_product` field to `switched_from_other_product`, and re-validated against the full real dataset (now correctly counts 13/60).

---

## `python/raw_landing.py` — the local landing zone

**What it answers:** "Where does each branch's raw output go before Phase 3 merges/dedupes it?"

This replaces the S3 landing bucket from the original blueprint (ADR-003 — AWS dropped to narrative-only). The idea is unchanged: land raw data *before* processing it, so a bug in the merge/dedupe logic doesn't force you to re-hit rate-limited APIs (EDGAR, Adzuna, Apify) to recover — you just reload the same raw file.

- **`save_raw_signals(branch_name, data)`** — writes whatever a branch returns to a timestamped JSON file in `data/raw/` (e.g. `data/raw/branch_a_funding_20260710T004132Z.json`).
- **`load_latest_raw_signals(branch_name)`** — finds and loads the most recent file for that branch, or `None` if nothing's been landed yet.

**Live-verified 2026-07-09, real end-to-end:** ran Branch A live, landed 8 real companies to disk, reloaded them, and confirmed they matched exactly.

**Bug found and fixed 2026-07-11:** `load_latest_raw_signals()` originally picked "latest" via `sorted(glob.glob(...))[-1]` - a plain string sort on filenames. A live merge test surfaced the flaw: an old, differently-prefixed leftover file (`branch_a_funding_...`) alphabetically out-sorted a genuinely newer one (`branch_a_...`), because `'f' > '2'` in ASCII regardless of which file is actually older. Fixed to select by `os.path.getmtime()` (real file modification time) instead - see `docs/ISSUES.md` for the full story, including how this let a previously-fixed foreign-filer bug (Pulsenmore Ltd.) briefly reappear in the live database.

---

## `utils/db.py` — Postgres (Supabase) connection + dedup (Phase 3)

**What it answers:** "How do we turn three separate branches' output into one deduplicated company record, in a real database?"

- **`get_connection()`** — opens a connection using `DATABASE_URL` (now Supabase-hosted, ADR-004).
- **`normalize_company_name(name)`** — lowercases, strips common suffixes (Inc/LLC/Corp/etc.) and punctuation. This is the **interim dedup key** — see below for why.
- **`apply_schema(conn)`** — runs `sql/schema.sql` against the database. Safe to run repeatedly (every statement is `CREATE ... IF NOT EXISTS`).
- **`upsert_company(conn, name, **fields)`** — inserts a company, or updates it if a row with the same `normalized_name` already exists (`ON CONFLICT ... DO UPDATE`). Returns the row's `id` either way.
- **`get_company_by_normalized_name(conn, name)`** — looks up a company's full row.

**Why `normalized_name` instead of `domain` for dedup:** neither Branch A (EDGAR) nor Branch B (Adzuna/Greenhouse/Lever) actually produces a website domain — that's deferred to Clay in Phase 7 (see ADR-013). So `companies.domain` is nullable, and `normalized_name` is the best-available dedup key until Clay backfills the real domain later. This is standard practice for enrichment pipelines (insert with what you have, upgrade identifiers as better data arrives), not a workaround.

**Live-verified 2026-07-10:** applied the schema to the real Supabase database (confirmed all 4 tables exist: `companies`, `signals`, `leads`, `competitor_intel`). Ran a real dedup test — inserted "Acme Corp" then "Acme, Inc." — both correctly resolved to the same row (`id=1`), confirming the interim dedup key works as designed.

**Two more functions added when Phase 3 finished (2026-07-10):**
- **`insert_signal(conn, company_id, source, signal_category, **fields)`** — inserts one raw event row into `signals` (a funding event, a pm_hiring event, or the rare Branch C review attributable to a company). Plain insert, no conflict handling — every signal is its own event, not something you dedupe.
- **`upsert_competitor_intel(conn, competitor, **fields)`** — inserts or fully replaces a competitor's row in `competitor_intel`. `representative_quotes` is a Python list that gets wrapped in `psycopg2.extras.Json(...)` before it's sent, since the column is `JSONB`.

---

## `python/merge_signals.py` — Phase 3's merge/dedupe orchestrator

**What it answers:** "How does each branch's raw output actually get into Postgres?" This is the piece that replaces the original blueprint's flat-file `seen_companies.json` — dedup now happens for real, via `companies.normalized_name` and Postgres's `ON CONFLICT`, not an in-memory set of names checked at runtime.

- **`merge_funding_signals(conn, funding_signals)`** — for each Branch A signal: `upsert_company()` with the funding fields (stage, date, amount, industry, biz_location), then `insert_signal()` logging a `funding` event. Returns the company ids touched.
- **`merge_hiring_signals(conn, hiring_signals)`** — for each Branch B signal: `upsert_company()`, then `insert_signal()` logging a `pm_hiring` event. **Deliberate detail:** `current_tool_mentioned` is only passed to `upsert_company()` when ADR-013's job-description scan actually found a competitor mention that run — an empty scan result must never silently overwrite a tool a previous run already recorded for that company.
- **`merge_intent_signals(conn, pain_point_corpus)`** — for each competitor in Branch C's corpus: `upsert_competitor_intel()` with that run's recomputed totals, capped at `MAX_QUOTES_PER_COMPETITOR` (10) stored quotes per competitor so the JSONB column doesn't grow unbounded across repeated runs.
- **`run_full_merge(conn, funding_signals=None, hiring_signals=None, pain_point_corpus=None)`** — the top-level entry point. Pass data in directly, or leave any argument as `None` and it reloads that branch's most recently landed raw file via `python/raw_landing.py` instead of re-hitting rate-limited APIs. Returns a summary dict (counts merged per branch, distinct companies touched).

**Not yet live-tested** (see `docs/HANDOFF.md`) — 8 pytest cases, all mocked, confirm the translation logic is correct, but `run_full_merge()` has never been run against the real Supabase database with real branch output yet.

## `g2_reviews` table + `utils/db.py`'s `upsert_g2_review()` / `get_competitor_intel_aggregate()`

**What it answers:** "How does Branch C capture new reviews on a periodic schedule without losing everything it already knew?" (ADR-021, 2026-07-12). Previously `competitor_intel` was written directly from whatever a single scrape batch computed - fine for a one-time full scrape, but a real periodic schedule pulling only recent reviews would have silently overwritten (not added to) the accumulated totals each time.

- **`g2_reviews`** — one row per individual review, `review_id UNIQUE`. Re-scraping and getting some already-seen reviews back is harmless; they just fail to insert.
- **`upsert_g2_review(conn, review)`** — inserts if new, returns `True`/`False` so callers can tell new from already-seen.
- **`get_competitor_intel_aggregate(conn, competitor, quote_limit)`** — recomputes `total_reviews_seen`/`negative_review_count`/`switch_signal_count`/`representative_quotes` from the FULL `g2_reviews` history for that competitor, not a single batch.
- **`merge_signals.merge_intent_signals()`** now: upserts every review in the batch (dedup handles overlap), then recomputes and writes `competitor_intel` only for the competitors actually touched this run.

**Live-verified 2026-07-11/12:** merged the real 60-review dataset for the first time - `switch_signal_count` totals summed to exactly 13 across all 4 competitors, matching the figure already documented after the earlier truthy-bug fix (ADR-012), a genuine independent cross-check. Re-ran the identical merge - confirmed idempotent (still 60 rows, 0 duplicates). Added one synthetic new review and confirmed the aggregate correctly grew (15→16 total, 6→7 switch signals) instead of resetting - exactly the "capture new, keep the rest" behavior needed for a real periodic schedule.

---

## `sql/queries.sql` — the read side

**What it answers:** "Now that data is in Postgres, how do I actually read it back out?" Companion to the write side above.

Grouped into four sections: **dedup lookups** (find a company by its normalized name; find companies still missing a domain — Phase 7's Clay backfill queue), **signal-type reporting** (TIMING-only, INTENT-only, and the BOTH-signal intersection the scoring model in Phase 4 will weight highest, plus the join connecting a company's `current_tool_mentioned` to its specific slice of the `competitor_intel` corpus), **Branch C reporting** (the competitive-intel snapshot, ranked by switch-signal count — direct input to Phase 8's outreach generation), and a **pipeline health check** (funnel counts by source/day, plus a regex sanity check that flags any `biz_location` that isn't a valid `"City, ST"` pair — a second line of defense behind `funding_edgar.py`'s `is_us_location()` filter).

---

## `python/scoring.py` — Phase 4 ICP scoring

**What it answers:** "Is this company worth pursuing, and why?" Takes one company row + its signal history and returns a 0-120ish `icp_score`, a `signal_type` tag (TIMING/INTENT/BOTH/NONE), and a `qualified` boolean (score >= 70).

- **`score_timing(company, signals)`** — funding recency (25 pts if funded ≤90 days ago, 15 if ≤180) + PM hiring velocity (15 for 2+ postings, 8 for 1) + a Product Ops bonus (10 pts, only for a title that says "operations" without also saying "manager" — see ADR-014 for why that split matters). Only the **most recent** `pm_hiring` signal row is used, since a company can accumulate several over repeated merge runs.
- **`score_intent(company, competitor_intel)`** — looks at `current_tool_mentioned` (ADR-013) and, if set, scales points by that competitor's severity in `competitor_intel` (switch-signal rate): >=20% → 40 pts, >=10% → 25 pts, otherwise 15 pts, calibrated against the real Aha! 21.7% data point. No tool identified → 0 pts, never a penalty.
- **`score_demographic(company)`** — employee-count bands + confirmed-SaaS bonus. Written and tested, but **not called by any live pipeline yet** — `employee_count`/`is_saas` are NULL for every real company until Phase 7's Clay enrichment.
- **`score_deductions(company)`** — existing customer (-100), company size out of the 20-1000 range (-20), confirmed non-SaaS (-15).
- **`score_company(...)`** — the full entry point: runs all four buckets, adds the +10 BOTH-signal bonus when a company has both TIMING and INTENT points, and returns the final breakdown.

**Not yet live-tested against real data** — 15 pytest cases confirm the logic against realistic mocked data; `api/main.py` below adds a real live-smoke-tested HTTP path, but nothing has called either against a real Supabase company row yet (see `docs/HANDOFF.md`).

## `api/main.py` — the FastAPI `/score` endpoint

**What it answers:** "How does n8n (or anything else) actually call the scoring logic?" A thin HTTP wrapper — it adds no new logic of its own, just Pydantic request/response models around `scoring.score_company()`.

- **`GET /health`** — liveness check, returns `{"status": "ok"}`.
- **`POST /score`** — body: `{"company": {...}, "signals": [...], "competitor_intel": {...}}` (all fields optional/defaulted except `company`), returns `{"icp_score", "qualified", "signal_type", "score_breakdown"}`.

Run it locally with `uvicorn api.main:app --reload` (from the repo root). **Live-verified 2026-07-10:** started a real `uvicorn` process and hit both endpoints with `curl` — `/score` correctly returned `icp_score: 90, qualified: true, signal_type: "BOTH"` for a funded + hiring + Aha!-mentioning company, matching `test_scoring.py`'s equivalent unit test exactly.

**Environment note:** `fastapi`/`uvicorn` were already in `requirements.txt` but not actually installed in this dev environment until this phase — installed via `pip3 install`, plus `httpx` (newly added to `requirements.txt`; it's only a dependency of FastAPI's `TestClient` for tests, not used by the running app).

**Extended in Phase 9 (2026-07-12, ADR-022) into the full n8n-facing API surface:**
- **`POST /branch-a/run`**, **`POST /branch-b/run`** — run the free branches live and land the results (thin wrappers around `funding_edgar`/`hiring_signals` + `raw_landing`).
- **`POST /branch-c/run`** — runs the real Apify G2 scrape. Costs real money per call (ADR-009) - meant to be wired to a SEPARATE, less-frequent n8n trigger than the free daily A/B schedule.
- **`POST /merge/run`** — opens its own connection, calls `merge_signals.run_full_merge()`, closes the connection.
- **`POST /pipeline/run-all`** — the batch endpoint: fetches every company + its signals + the full `competitor_intel` dict (three new `utils/db.py` read helpers: `get_all_companies`, `get_signals_for_company`, `get_all_competitor_intel`), then calls `pipeline.process_qualified_lead()` for each, returning a `status_counts` summary. This is the endpoint n8n's final workflow node calls.

**A real bug caught by live-testing the actual deployed shape:** `api/main.py` never called `load_dotenv()` - a fresh `uvicorn` process had no environment variables, so every endpoint touching a credential (which is nearly all of them) failed with a `500`. FastAPI's `TestClient` in pytest never caught this, since test runs reuse a Python session where env vars were already loaded elsewhere. Fixed by adding an explicit `load_dotenv()` pointing at the repo's `.env` path, before any of the credential-reading modules get imported.

**Live-verified 2026-07-12** with a real standalone `uvicorn` process (not a warm session): `/branch-a/run` → 22 real companies. `/branch-b/run` → 40 real companies (a fresh live run). `/merge/run` → 62 distinct companies. `/pipeline/run-all` → 62 evaluated, all `not_qualified` (consistent with the earlier full-database finding) - and confirmed the existing test lead correctly got skipped via the new dedup-window check rather than silently re-processed. `/branch-c/run` confirmed only via its mocked unit test, not live-called.

## `utils/db.py`'s dedup-window check — `has_recent_lead()`

**What it answers:** "How do we stop the SAME company from being re-processed (real Gemini call, real HubSpot write) every single day it still qualifies?" Wires up the blueprint's `DEDUP_WINDOW_DAYS` env var, which had sat unused in `.env` since Phase 0.

- **`has_recent_lead(conn, company_id, within_days)`** — `True` if a `leads` row already exists for this company within the window.
- **`pipeline.process_qualified_lead()`** checks this right after the qualification gate, before the (real, network-calling) HubSpot dedupe check and before outreach generation - returns `"skipped_recently_processed"` if true.

**Live-verified**: re-running the existing test lead (already processed earlier that same day) correctly returned `skipped_recently_processed` with zero Gemini or HubSpot calls.

---

## `utils/gemini.py` — dual-key + backoff Gemini client

**What it answers:** "How do we call Gemini reliably, given rate limits are expected at scale?" One function, `generate_content(prompt)`: sends a prompt, returns the raw text response. Tries `GEMINI_API_KEY` first; on a 429 or 5xx, retries with exponential backoff (2s, 4s, 8s); if a key exhausts its retries, falls through to `GEMINI_API_KEY_2` before finally raising. Generic on purpose — no G2/classification-specific logic lives here, so Phase 8's outreach generation can reuse it later.

## `python/classify.py` — Phase 5 G2 review company attribution

**What it answers:** "Can we ever tell which real company a G2 review came from?" Almost never (G2 reviews are anonymous by design, ADR-012) — but on the rare occasion a reviewer's text explicitly names their employer, this catches it.

- **`extract_reviewer_company(review_text)`** — the core function. Skips the Gemini call entirely for empty/blank text (a cost guard, not just a null check). Otherwise sends a prompt instructing Gemini to extract a company name *only if explicitly stated* (not inferred, not guessed), and parses the JSON response.
- **`_parse_json_response(raw_text)`** — strips markdown code fences (```json ... ```) before parsing, since LLMs commonly add them despite being told not to. Returns `None` on anything unparseable rather than crashing — one bad response shouldn't break a whole batch.
- **`classify_reviews_for_company_attribution(reviews)`** — batch entry point: runs extraction over a list of normalized G2 reviews (from `intent_g2.py`), returns them with an added `attributed_company` field (`None` for the large majority).

When attribution succeeds, `python/merge_signals.py`'s new **`merge_attributed_reviews(conn, attributed_reviews)`** writes that review into the normal `signals` table (`source: g2`, `signal_category: competitor_review`) — the same pipeline Branch A/B use — making that specific company eligible for `scoring.py`'s INTENT points via a real star-rated review, not just the weaker job-description-mention proxy.

**Live-verified 2026-07-10** — ran against real G2 review text from the user's actual dataset (`data/apify/dataset_g2-scraper_2026-07-10_00-56-49-513.json`, 15 reviews, 0 attributed — expected, G2 is anonymous by design) and against synthetic text that does name a company (correctly extracted it). The first attempt hit a real dead end: the originally hardcoded model, `gemini-2.0-flash`, is deprecated and returned a `429` that looked like quota exhaustion but wasn't — see `docs/ISSUES.md` for the full debugging story, including why the "obvious" next model (`gemini-2.5-flash-lite`) was *also* already retired, and why `utils/gemini.py` now points at the rolling alias `gemini-flash-lite-latest` instead of a pinned version. 11 pytest cases (5 `utils/gemini.py`, 6 `python/classify.py`) confirm the logic against mocked responses.

---

## `python/enrichment.py` — Phase 6 Clay enrichment (export side)

**What it answers:** "Which companies need a real domain, and how do we get that list to Clay?" Originally planned as a live webhook integration, but Clay's Webhook trigger turned out to be paid-only on the user's account - switched to a free CSV export/import round-trip instead (ADR-017).

- **`get_companies_needing_domain(conn)`** — mirrors `sql/queries.sql`'s "missing a domain" lookup, but psycopg2-driven so this script can run standalone.
- **`export_companies_needing_domain(conn, export_dir)`** — writes a CSV (`company_id`, `company_name`) to `data/clay/`, timestamped. `company_id` is included specifically so the not-yet-built import step can match Clay's enriched output back to the exact right Postgres row, not re-guess by name.
- Runnable directly: `python3 python/enrichment.py` (uses `DATABASE_URL` from `.env`).

**Live-verified 2026-07-11** against the real Supabase database — produced a correct 22-row CSV.

**`import_enriched_companies(conn, csv_path)`** — reads Clay's exported CSV back in and writes each row's real domain onto its matching company (matched by `company_id`, not name - that's why the export includes it). Built against the user's real Clay export, whose domain column is literally named `"Domain"` (capital D) - handled explicitly, not assumed to be lowercase. Rows with no domain (an enrichment miss) are skipped, not written as an empty string (which would collide with the schema's `UNIQUE` constraint on `domain` across multiple skipped rows).

Uses a new `utils/db.py` function, **`update_company_by_id(conn, company_id, **fields)`** — writes directly by id rather than re-matching on `normalized_name` like `upsert_company()` does, since `company_id` is the trustworthy key here (it round-tripped through the export/import CSV, not re-derived from a name string that could theoretically drift).

**Live-verified end-to-end 2026-07-11:** ran the real import against the user's actual Clay export — all 22 companies updated with real domains in the live Supabase database; a follow-up call to `get_companies_needing_domain()` confirmed 0 remaining.

**Known, honest data-quality limitation (not a code bug):** reviewing the real Clay output before importing, 2 of 22 domains look like enrichment mismatches - see `docs/ISSUES.md`. This function imports Clay's output as-is and does not attempt to validate domain plausibility.

---

## `utils/hubspot.py` — Phase 7 dedupe check + Phase 9 real writes

**What it answers:** "Before generating outreach for a qualified lead, does this company already exist in HubSpot, and did we contact them recently?" Prevents duplicate records and duplicate outreach.

- **`search_company_by_domain(domain)`** / **`search_company_by_name(name)`** — thin wrappers around HubSpot's real Search API (`POST /crm/v3/objects/companies/search`, `filterGroups`/`EQ`), confirmed live before writing any of this code (see below).
- **`find_existing_company(domain, name)`** — tries domain first (the reliable match now that Phase 6 backfilled real domains), falls back to name search only when domain search misses.
- **`check_dedupe_status(domain, name, today)`** — the actual decision: not found → `"create"`; found + contacted within 30 days (inclusive) → `"skip"`; found + stale or never contacted → `"update"`.

**Verified live before coding, not assumed** — a documentation fetch this session actually returned a mismatched, incorrect endpoint path, so the real endpoint/filter shape and the "last contacted" property were confirmed directly against the real HubSpot sandbox instead. Real finding: `notes_last_contacted` ("Last Contacted") already exists as a **standard** Company property — no custom property setup needed, simpler than the original blueprint assumed. Full details in `docs/DECISIONS.md` ADR-018.

**Live-verified 2026-07-11**, real end-to-end: ran all 22 real companies from Phase 6 through `check_dedupe_status()` — all correctly returned `"create"`. Confirmed `"skip"` against the sandbox's one real seed company (contacted 2 days prior). Confirmed the name-fallback path by deliberately passing a wrong domain and verifying it still matched by name.

**Extended in Phase 9 with real writes**, not just search:
- **`ensure_custom_properties_exist()`** — idempotent: creates any of `CUSTOM_PROPERTIES` (12 total, adapted from the blueprint's output schema — `funding_stage`, `icp_score`, `gtm_signal_type`, `priority_summary`, all 5 outreach fields, `current_tool_mentioned`, and `gtm_pipeline_status` in place of the blueprint's Deal-object-only `deal_stage`) not already present on the Company object.
- **`_ensure_property_group_exists()`** — a real live bug caught this: HubSpot requires a property's group to already exist, or property creation fails with a genuine `400 GROUP_DOES_NOT_EXIST`. This function creates the `gtm_signal_engine` property group first, idempotently.
- **`create_company(domain, name, properties)`** / **`update_company(company_id, properties)`** — real `POST`/`PATCH` against `/crm/v3/objects/companies`.

**Live-verified 2026-07-11:** created the property group (`201`) then all 12 custom properties for real; re-running created 0 (confirmed idempotent). Then, as part of the full pipeline test below, created and later updated one real Company record with real property values.

---

## `python/outreach.py` — Phase 8 Gemini outreach generation

**What it answers:** "Now that a lead is qualified, deduped, and confirmed - what do we actually say to them?" Generates signal-specific outreach copy per the blueprint's TIMING/INTENT/BOTH angle design, plus one new field beyond the blueprint's original scope.

- **`build_outreach_prompt(lead)`** — picks the angle template based on `lead["signal_type"]`: TIMING references real funding stage/date + PM hiring count; INTENT embeds real G2 pain-point quotes for the specific competitor tool identified (ADR-013); BOTH combines both. Raises `ValueError` for anything other than TIMING/INTENT/BOTH — by the time a lead reaches Phase 8 it should never be untagged, so this is a loud upstream-bug catcher, not defensive clutter.
- **`generate_outreach(lead)`** — calls Gemini, parses the structured JSON response (`utils/gemini.py`'s shared `parse_json_response()` — moved out of `classify.py` once this module needed the identical fence-stripping logic), and returns exactly 6 fields: the blueprint's `email_subject_a/b`, `email_body`, `linkedin_message`, `call_script`, plus a new **`priority_summary`** — a 1-2 sentence "why contact now" rationale, added at the user's request specifically for Phase 9's planned CRM-style Google Sheet, where a human needs a scannable justification, not a raw JSON score breakdown.
- **Fails loudly, on purpose:** unlike `classify.py`'s best-effort extraction (a bad response there just means "no company found" — a safe no-op), a bad or incomplete Gemini response here raises `RuntimeError` instead of silently producing partial outreach copy that could actually get sent to a real prospect.

**Live-verified 2026-07-11, twice, with real and realistic data:**
1. TIMING angle against the real "InfraSight Software Corp" row (real `Seed/Series A` stage, real 2026-04-23 funding date from Phase 6) — generated copy correctly referenced the actual funding round and hiring activity, not boilerplate.
2. INTENT angle with realistic Aha! pain-point quotes ("steep learning curve," "pricing gets expensive fast") — generated email/LinkedIn/call-script all specifically referenced those quotes, confirming Branch C's G2 corpus flows all the way through to real, evidence-backed messaging.

---

## `utils/sheets.py` — Phase 9 CRM-style Google Sheet

**What it answers:** "How does a human triage qualified leads without opening HubSpot?" The Google Sheet the user explicitly requested (2026-07-10) — one row per lead: company info, funding, `icp_score`, `priority_summary`, and every outreach field.

- **`get_worksheet(worksheet_name)`** — opens the configured Sheet via `gspread` and the service-account credentials in `.env`. Fails loudly if either env var is missing.
- **`ensure_header_row(worksheet)`** — writes `HEADER_ROW` to row 1 if missing or wrong; a no-op once it's already correct.
- **`append_lead_row(worksheet, lead_row)`** — appends one lead, values ordered by `HEADER_ROW`, missing fields become `""` rather than shifting columns.

**Live-verified 2026-07-11** — real read access confirmed first (before any write), then a real end-to-end append via the full pipeline test below. **A real bug caught along the way:** `ensure_header_row()` existed and was correctly tested in isolation, but `python/pipeline.py` never actually called it — the first two live pipeline runs produced a Sheet with data rows and no header at all. Fixed by adding the missing call; confirmed clean on a third run (1 header row + 1 correct data row).

## `utils/discord.py` — Phase 9 lead notifications

**What it answers:** "How does the team get a real-time heads-up per qualified lead?" One color-coded embed per lead, matching the blueprint's green=BOTH/yellow=TIMING/blue=INTENT scheme.

- **`build_lead_embed(lead)`** — pure function, builds the Discord embed payload (title, `priority_summary` as the description, color by `signal_type`, ICP score/signal type/domain as fields). Falls back to grey for an unrecognized `signal_type` rather than crashing.
- **`send_lead_notification(lead)`** — POSTs it to `DISCORD_WEBHOOK_URL`.

**Live-verified 2026-07-11** — a standalone test message confirmed the webhook works (`204`), then a real lead notification was sent as part of the full pipeline test below.

## `python/pipeline.py` — Phase 9 per-lead orchestrator

**What it answers:** "Given one company, how does everything built so far actually fit together?" `process_qualified_lead(conn, company, signals, competitor_intel)` is the literal sequence the user's n8n workflow (built by hand in the UI, ADR-007) will replicate node-by-node:

1. **Score it** (`scoring.score_company`) — not qualified (< 70) → stop, cheapest possible short-circuit.
2. **Check HubSpot dedupe** (`hubspot.check_dedupe_status`) — recently contacted → stop before spending a real Gemini call on outreach nobody will send.
3. **Build the shared lead context** (`build_lead_context`) — company facts + score + the specific competitor's real pain-point quotes from `competitor_intel`, if a tool was identified.
4. **Generate outreach** (`outreach.generate_outreach`).
5. **Write everywhere**: create/update the real HubSpot company (with all 12 custom properties), insert a `leads` row in Postgres (including the real `hubspot_company_id`), append a row to the Google Sheet, post a Discord notification.

**Two real integration-ordering bugs caught by the first full live run** (see `docs/ISSUES.md` for the full story) — `leads.hubspot_company_id` was landing `NULL` because the database insert originally happened before the HubSpot write existed; and the Sheet's header row was never actually requested. Both fixed, both have regression tests now (`test_full_flow_writes_real_hubspot_company_id_onto_the_leads_row`, `test_full_flow_ensures_header_row_before_appending`).

**Live-verified end-to-end, twice, for real** (2026-07-11, user-approved): ran a real company (InfraSight Software Corp) with one synthetic supporting signal, name-suffixed `(TEST - GTM Signal Engine)` so the result is clearly identifiable. First run: caught the two bugs above. Second run (after fixes, and after clearing the stale test data): `status: "processed"`, `icp_score: 100`, `signal_type: BOTH` — a real HubSpot company was created with all 12 custom properties correctly set, a real Sheet row landed under a real header row, and a real Discord notification was sent. The second run also correctly exercised the `update` (not duplicate-`create`) path, since the real HubSpot company from the first run already existed at that domain.

---

## How to run any of this yourself

```bash
cd /Users/alexbark/Documents/project-productboard
python3 -m pytest tests/ -v          # all 62 tests
```

To run a module live (needs `.env` loaded):
```python
import sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, 'python')

import funding_edgar
signals = funding_edgar.get_funding_signals(keywords=['software'], lookback_days=60)
```
