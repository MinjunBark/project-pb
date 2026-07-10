# Issues & Debugging Log

> Owns: bugs, debugging dead-ends, and how each was resolved. This is the "what broke and how'd you fix it" material for the interview — log the real dead-end, not just the final fix, since the dead-end is often the more interesting part to talk about.

## [Phase 2] Truthy-string bug: "no" and "unknown" incorrectly counted as switch signals
**Symptom:** After the user's first live G2 run (60 real reviews across all 4 competitors), inspecting the raw data showed `switchedFromOtherProduct` takes values `"yes"`, `"no"`, `"unknown"`, or `null` - it's a categorical flag, not (as assumed) the name of the product the reviewer switched from.
**Root cause:** `normalize_g2_reviews()` computed `is_switch_signal` as `bool(review.get("switchedFromOtherProduct") or review.get("switchedReason"))`. In Python, `bool("no")` and `bool("unknown")` are both `True` - any non-empty string is truthy. Real distribution across the 60 reviews: 13 `"yes"`, 25 `"no"`, 4 `"unknown"`, 18 `null`. The buggy version would have flagged 42 of 60 reviews as switch signals when only 13 actually were.
**Fix:** Changed the check to `review.get("switchedFromOtherProduct") == "yes"` specifically. Also renamed the misleadingly-named `prior_product` field (which held `"yes"`/`"no"`/`"unknown"`, not a product name) to `switched_from_other_product` (a proper boolean). The actual name of a prior product, when mentioned, lives in free text (`switch_reason`/`text`) - still a Phase 5 Gemini extraction job, not a structured field. Added a regression test (`test_normalize_does_not_flag_no_or_unknown_as_switch_signal`) using real-shaped data. Re-ran the corrected code against the actual 60-review dataset: exactly 13 switch signals now, matching the real "yes" count precisely.
**Talking point:** A classic "truthy string" bug - Python (and JS) treat any non-empty string as `True`, so a categorical field like this needs an explicit equality check, not a bare `bool()`. Real downloaded data caught it; the mocked tests alone wouldn't have, since the mocks were written with the same wrong assumption baked in.

## [Phase 2] G2 actor input param and output field names were wrong before first live run
**Symptom:** Before running the first live Apify test, user asked for a more thorough documentation pass on `automation-lab/g2-scraper` than the initial research. That deeper pass (the actor's full parameter table and example JSON, not just a summary) revealed the original `python/intent_g2.py` was built against wrong names throughout: input param `productSlugs` should have been `productUrls` (an array of full G2 URLs, not bare slugs), and output fields like `id`, `text`, `npsScore`, `priorProductName`, `reasonForSwitching`, `reviewerCountry` should have been `reviewId`, `reviewText`, `nps`, `switchedFromOtherProduct`, `switchedReason`, `country`.
**Root cause:** The initial research pass (before writing the code) summarized the actor's fields in prose rather than pulling the actual parameter table and example JSON output - close enough to sound plausible, wrong in the specifics.
**Fix:** Re-fetched the actor's full documentation (console readme + public store page + targeted search for the input-schema page) to get the literal parameter table and example JSON, then corrected every field mapping in `normalize_g2_reviews()` and the input body in `run_g2_review_scraper()`. Added `build_product_review_url()` to construct the full URL the actor actually expects. All 6 tests (5 existing + 1 new) updated to match and passing.
**Talking point:** This would have been a genuinely embarrassing live-run failure (or worse, silently wrong data - e.g. `None` for every field if the wrong keys just don't match) had it not been caught before spending real Apify credits. Good argument for always pulling the literal parameter table and example payload, not a prose summary, before writing integration code - especially before a paid live run.

## [Phase 3 prep] Supabase direct connection failed DNS resolution
**Symptom:** `psycopg2.connect()` against Supabase's "Direct connection" URI (`db.<ref>.supabase.co`) failed with `could not translate host name ... nodename nor servname provided`.
**Root cause:** Supabase's direct-connection host resolves over IPv6 by default; the local network couldn't resolve/route it at all.
**Fix:** Switched to Supabase's "Session pooler" connection string instead (`aws-0-<region>.pooler.supabase.com`), built specifically for IPv4 networks. Connected successfully — confirmed live against a real PostgreSQL 17.6 instance.
**Talking point:** A reminder that "free and hosted" doesn't mean "zero network friction" — IPv6-only defaults are a real, common gotcha, and knowing the pooler fallback existed (rather than assuming the direct string was the only option) is exactly the kind of infra troubleshooting this role expects.

## [Phase 2] .env drifted: duplicate DATABASE_URL lines, one corrupted with an exposed secret
**Symptom:** After several rounds of manual `.env` edits (adding G2 token, then Supabase URL), the file ended up with two `DATABASE_URL=` lines — one correct, one malformed where `DATABASE_URL=` had been accidentally prepended onto the `G2_API_TOKEN` line, merging a variable name with an unrelated secret's value.
**Root cause:** Manual copy-paste edits into a growing `.env` file without re-reading the whole file afterward to confirm structure.
**Fix:** Ran a read-only check listing just the env var *keys* (values redacted) to spot the duplication before touching anything; removed the known-safe old default line via an exact-match `grep -v`, and had the user manually fix the corrupted line and regenerate the exposed G2 token rather than risk editing blind around a real secret.
**Talking point:** Good example of treating a secrets file with real caution — verify structure without printing values, and when a token is accidentally exposed (even to a low-risk personal test account), rotate it rather than assume it's fine.

Format per entry:

```
## [Phase N] Short title
**Symptom:** what went wrong / what was observed
**Root cause:** what actually caused it
**Fix:** what changed
**Talking point:** why this is worth mentioning to Darrell
```

## [Phase 1] EDGAR Form D search returns mostly investment funds, not operating companies
**Symptom:** A raw date-range query (`forms=D`, no search text) against EDGAR's full-text search API returned 10,000+ hits, and manually inspecting the first page showed almost entirely venture fund/SPV entities raising their own capital ("1EP Ventures I, L.P.", "OT YC Fund IV, LLC", "GTOWN CENTURY LP, LLC") rather than operating startups that just received funding.
**Root cause:** Form D is filed by whoever is the *issuer* of the private securities — for a venture fund raising money from its own LPs, the fund itself is the issuer, so it files a Form D exactly like an operating company raising a Series B would. Nothing in a plain date-range query distinguishes the two.
**Fix:** Added a required search keyword (e.g. "software", "SaaS", "platform") to the full-text query — narrowed 10,000+ hits to 13 for a similar window, and surfaced real operating companies ("Kepler Software, Inc.", "Blacksmith Software Inc.", "Nova AI Software Inc."). Also added a name-based heuristic filter (excludes names containing "fund", ending in "LP"/"L.P.", or containing "SPV") as a second safety net. Confirmed via live test calls to `efts.sec.gov` before writing any parsing code, rather than assuming the schema from secondhand descriptions.
**Talking point:** "The naive version of this query would've flooded the pipeline with venture funds instead of prospects. I caught it by actually inspecting live API output before writing code, not by trusting the docs blindly — same instinct as validating any third-party data source before building on it."

## [Phase 1] SIC industry codes are sparsely populated for early-stage filers
**Symptom:** Expected to filter/tag companies by SIC industry code (a possible SaaS-detection signal), but the `sics` field was empty (`[]`) for nearly every private operating company checked, only populated for one already-public filer.
**Root cause:** SIC codes appear to be assigned inconsistently for younger/private filers in EDGAR's full-text search index — not a reliable field to depend on for early-stage companies specifically.
**Fix:** Dropped SIC code as a filter; rely on the search keyword + name-heuristic approach instead, and use the filing's own `industryGroupType` field (e.g. "Other Technology") from the actual Form D document body as the industry signal instead of the index-level `sics` field.
**Talking point:** Good example of a data source looking clean in docs but requiring hands-on inspection to find where it's actually sparse — informs the "score_breakdown" transparency built into the ICP scoring model.

## [Phase 1] Lever's error response looked ambiguous on first pass
**Symptom:** First live test against `api.lever.co/v0/postings/attentive?mode=json` returned a JSON body `{"ok": false, "error": "Document not found"}` without checking the HTTP status code alongside it — looked like it might be a 200 with an in-body error, which would have meant checking response bodies instead of status codes to detect an invalid company slug.
**Root cause:** The first test only printed the body, not the status code, so the actual status went unobserved.
**Fix:** Re-ran the same request capturing both status and body together, across several company slugs. Confirmed Lever returns a proper HTTP 404 (not 200) for an unknown client name, and a clean 200 with a bare JSON array (empty or populated) for a valid one — simpler to handle than initially feared, checking `status_code == 200` is sufficient.
**Talking point:** A reminder to always capture the full response (status + body together) before drawing a conclusion about an API's error-handling contract — a partial observation nearly led to more defensive code than the API actually required.

## [Phase 1] Layer 2 (Greenhouse/Lever) hit rate measured: ~7% in first live run
**Symptom:** Before building Layer 2, Claude flagged that the board-token-guessing approach had an unknown success rate and might not be worth the engineering time. Now measured for real: a live end-to-end run of 28 companies from a 30-day Adzuna "Product Manager" search resolved only **2 companies (~7%)** via Greenhouse/Lever guessing; the other 26 fell back to Adzuna-only data.
**Root cause:** Not a bug — this is just the real distribution of which companies happen to use Greenhouse or Lever (vs. Workday, Ashby, a custom careers page, or no guessable slug match) among a fairly generic cross-section of companies hiring PMs.
**Fix:** None needed — this is exactly the graceful-degradation behavior Layer 2 was designed for (ADR-010). No action required, but the number is worth knowing precisely rather than assuming.
**Talking point:** "Before building the Greenhouse/Lever layer, I was upfront that I didn't know its real hit rate and flagged it as a risk. First live run measured it at about 7% — low, but the design accounted for that from the start with a graceful fallback, so it doesn't cost us data, just doesn't add as much value as I'd hoped for most companies. That's a good example of validating an assumption with real data rather than assuming it either way."
