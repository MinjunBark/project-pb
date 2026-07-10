# Code Guide — What Each Script Does and Why

> Owns: plain-language explanation of what each Python module in `python/` actually does, how its pieces fit together, and real sample output from testing it. This is the "read this to understand the code" doc — status lives in `PROGRESS.md`, tool-choice rationale lives in `DECISIONS.md`, bugs live in `ISSUES.md`. Update this whenever a module's behavior changes; don't leave it describing code that no longer exists.

---

## The big picture

Three signal branches exist so far. Branches A and B both produce the same shape: a list of dicts describing a company and why it's a candidate lead. Branch C is different on purpose (see its section below) — it produces competitive-intelligence content, not per-company lead records. Nothing here talks to Postgres, HubSpot, or n8n yet — that wiring comes in later phases. Right now these are standalone, testable Python functions you can run and inspect on their own.

```
Branch A: python/funding_edgar.py         → funding events (SEC EDGAR)
Branch B: python/hiring_adzuna.py          → Layer 1: broad PM-hiring discovery (Adzuna)
          python/hiring_ats_lookup.py      → Layer 2: per-company deepening (Greenhouse/Lever)
          python/hiring_signals.py         → orchestrator combining Layers 1 + 2
Branch C: python/intent_g2.py              → competitor G2 reviews + pain-point corpus
          python/raw_landing.py            → local landing zone for all branches' raw output (replaces S3)
```

---

## Branch A: `python/funding_edgar.py`

**What it answers:** "Which companies recently raised money?"

**How it works, in order:**

1. **`search_form_d_filings(keywords, lookback_days)`** — calls SEC EDGAR's full-text search API asking for Form D filings (the mandatory disclosure any US company makes when raising private capital) that mention a keyword like `"software"`, filed within the last N days. A keyword is required — a bare date-range search returns mostly venture funds raising their own capital, not companies that got funded (see `docs/ISSUES.md`). Also filters out anything that looks like a fund name (`"Fund"`, ends in `"LP"`, etc.) as a second safety net, and de-duplicates by CIK across multiple keyword searches.

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

4. **`enrich_company_with_ats_data(company_name)`** — tries Greenhouse first, then Lever if Greenhouse doesn't resolve, and filters whatever it finds down to just the PM/Product-Operations-relevant postings (since these APIs return *all* of a company's jobs, not just PM ones).

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
      "url": "https://job-boards.greenhouse.io/gitlab/jobs/8564957002"
    }
  ]
}
```
(4 more real postings omitted here — see `data/hiring_signals_sample.json` for the full list.)

**Known limitation:** the slug guess won't always work — many companies use a different ATS entirely (Workday, Ashby, etc.), or a less obvious slug. When neither Greenhouse nor Lever resolves, this returns `{"source": None, "pm_postings": []}` — not an error, just "couldn't verify this one."

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

---

## How to run any of this yourself

```bash
cd /Users/alexbark/Documents/project-productboard
python3 -m pytest tests/ -v          # all 37 tests
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
