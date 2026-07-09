# Issues & Debugging Log

> Owns: bugs, debugging dead-ends, and how each was resolved. This is the "what broke and how'd you fix it" material for the interview — log the real dead-end, not just the final fix, since the dead-end is often the more interesting part to talk about.

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
