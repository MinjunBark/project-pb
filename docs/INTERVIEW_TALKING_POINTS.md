# Interview Talking Points

> Owns: interview-ready synthesis of this build's strongest material. Doesn't duplicate `DECISIONS.md`/`ISSUES.md` in full — points back to them for the complete writeup. This file is the "if I only have 2 minutes on this topic" version.

## The 30-second pitch

"I built a signal-driven GTM lead-qualification pipeline mapping to this role's actual stack — n8n, Clay, HubSpot, Postgres, Python, REST APIs. It watches for companies that just raised funding *and* are hiring PMs *and/or* are complaining about a named competitor on G2, scores the real overlap between those signals, and for anything that clears threshold, automatically generates outreach copy and writes it to HubSpot, a tracking sheet, and Discord. The interesting part isn't the final pipeline — it's the roughly two dozen real tradeoffs I hit and documented along the way: dropped tools, pivoted data sources, real bugs caught by live data that mocked tests couldn't catch."

## Architecture decisions worth walking through

**Every major swap was a real constraint, not a preference.** In order they happened:
- Crunchbase → SEC EDGAR (ADR-008): Crunchbase's API went Enterprise-only; EDGAR's Form D filings are free/public/no-key. Tradeoff: EDGAR doesn't label funding rounds, so stage is approximated from offering amount — a real heuristic, documented as one.
- LinkedIn scraper → Adzuna + Greenhouse/Lever (ADR-010): questioned the LinkedIn actor's ToS risk myself, researched real alternatives, rebuilt on three officially-sanctioned free APIs instead of just mitigating the original risk.
- AWS → local FastAPI (ADR-003): AWS required billing registration even for free-tier IAM access; chose not to attach a card to a portfolio project. Same service, same code shape, one step from a real Lambda deploy via Mangum if it needed to move to production.
- Docker Postgres → Supabase (ADR-004): same Postgres, hosted for free, no card — restores the "hosted cloud" talking point AWS would have given without AWS's billing wall.
- ADR-007 → ADR-023 (the n8n build itself): originally scoped so *I'd* build the Python and the *user* would build the n8n workflow by hand for real hands-on practice. Reversed explicitly, after presenting the tradeoff directly, once n8n's official MCP server made direct build-and-run possible — recorded as an explicit reversal, not a silent edit, because "what changed and why" is itself the interesting answer.

**Talking point on why this matters:** "None of these were the 'ideal' tool from a whiteboard-first design — they were the best real option once I actually checked whether the ideal one was accessible. That's the muscle I think matters more than picking the fanciest stack on paper."

## Real bugs, not hypotheticals

Pick 2-3 depending on what the interviewer's asking about (full log: `docs/ISSUES.md`):

**The truthy-string bug (Branch C / G2):** `switchedFromOtherProduct` is a `"yes"/"no"/"unknown"` string flag, not a product name. `bool("no")` is `True` in Python — a naive truthiness check flagged 42 of 60 real reviews as switch signals when only 13 actually were. Caught by inspecting the real downloaded data, not by the mocked tests (which were written with the same wrong assumption baked in). Fixed with an explicit `== "yes"` check.

**The deprecated-model-looks-like-a-quota-error bug (Gemini):** first live call to `gemini-2.0-flash` returned a 429 that read exactly like quota exhaustion. It wasn't — the model was deprecated. Even the "obvious" next pinned model (`gemini-2.5-flash-lite`) was already 404'd for new users. Landed on a rolling alias (`gemini-flash-lite-latest`) specifically so a pinned version number can't quietly go stale again.

**The alphabetical-vs-actual-time bug (raw signal landing):** `sorted(glob.glob(...))[-1]` picked the "latest" raw signals file by filename string sort. A stale file named `branch_a_funding_...` alphabetically outranked a genuinely newer `branch_a_...` file because `'f' > '2'` in ASCII — silently reintroducing a company that had already been correctly filtered out. Fixed to sort by real file mtime.

**Two integration-ordering bugs only a full end-to-end run caught (Phase 9):** `leads.hubspot_company_id` was landing NULL because the DB insert ran before the HubSpot write existed in the sequence; the Google Sheet was missing its header row because `ensure_header_row()` existed and was tested, but nothing ever called it from the actual pipeline. Every individual piece was correctly unit-tested and even live-verified in isolation — the *sequence* connecting them was the actual gap. "Each piece works" and "the whole pipeline works" are different claims.

**Talking point on this category:** "These are the bugs that mocked unit tests structurally can't catch — either because the mock encodes the same wrong assumption as the code, or because the bug lives in the ordering between two individually-correct pieces. That's a big part of why I insisted on running things live wherever it was free to do so, and why the ones I *didn't* run live (Apify calls) are explicitly flagged as an open risk rather than assumed fine."

## The "we found zero qualified leads" story

Ran both free branches live for real on the same day: 22 companies from EDGAR, 39 from Adzuna/Greenhouse/Lever, zero overlap, zero of the 39 job postings mentioned a tracked competitor. Result: 0 of 61 real companies scored above the 70-point threshold.

**This is not a failure case — it's the intended behavior of a strict multi-signal model**, and it's arguably the more meaningful validation than the one synthetic test lead that *did* qualify: 61 real companies went through real scoring and were correctly, silently discarded, with zero wasted Gemini calls and zero junk HubSpot records. The negative path is validated just as rigorously as the positive path.

**If asked "so does it actually work?":** "The pipeline correctly discarding 61-for-61 non-qualifying companies on a real day's data is exactly what I'd want to see before trusting it — a model that qualifies everything isn't discriminating, it's just noisy."

## Honest limitations (don't hide these — name them first)

- **Branch C's per-company attribution is structurally limited.** G2 reviews are anonymous by design — most can't be tied to a specific company, so the corpus is aggregate competitive intel (pain-point quotes, switch-signal rates), not per-lead attribution. Reframed the design around what G2 data is actually good for instead of forcing a fit that doesn't exist.
- **Greenhouse/Lever board-token guessing has a measured ~7% hit rate.** Flagged as an unknown risk before building it, then measured for real on live data instead of assuming either way. The graceful-fallback design means a miss costs nothing (falls back to Adzuna-only data), it just adds less value than hoped for most companies.
- **The demographic scoring bucket (employee_count, is_saas) is fully built and tested but not live-wired** — Clay enrichment only ever backfilled `domain`, not those two fields. Built once, correctly, deferred until the data exists rather than half-wiring it against nulls.
- **Two of 22 real Clay-enriched domains are wrong** — a real, expected failure rate for waterfall enrichment on generic company names, caught by actually reading the output before importing it, not silently trusted.
- **n8n has zero per-company visibility into the fan-out step.** Per the ADR-022/023 architecture (n8n calls the API, doesn't reimplement logic), HubSpot/Sheets/Discord all happen inside one opaque `/pipeline/run-all` call — n8n only sees aggregate counts. A real, named tradeoff of "orchestrate, don't reimplement," not an oversight.
- **The current live deployment depends on a free-tier ngrok tunnel staying up on a laptop.** Fine for a portfolio demo; explicitly not how this would run in production (needs a real deployment or a paid static tunnel).

**Talking point on this whole category:** "I'd rather walk in and name every real gap myself than have you find one I didn't mention. None of these are secret — they're all written up in `docs/ISSUES.md` and `docs/DECISIONS.md` with the actual reasoning, because I think being upfront about tradeoffs is a stronger signal than pretending everything's clean."

## If asked "what would you do differently with more time"

- Backfill `employee_count`/`is_saas` via a second Clay enrichment pass to activate the demographic scoring bucket.
- Give `/pipeline/run-all` a real second Gemini key (currently invalid, never blocking since primary key hasn't hit quota) and per-company response detail so n8n could branch/alert on individual qualifying leads instead of only aggregate counts.
- Move off the free ngrok tunnel to a real deployment (Fly.io/Railway/small EC2) so the schedule doesn't depend on a laptop staying awake.
- Widen Branch B's keyword/lookback scope, and let the daily cron accumulate signal history over multiple days — a company funded today might post a PM role next week, and the current one-shot same-day test can't capture that overlap.

## Where the deeper material lives

- `docs/DECISIONS.md` — all 23 ADRs, full reasoning, alternatives considered
- `docs/ISSUES.md` — every bug, the dead-end investigated first, the fix, the talking point
- `gtm-signal-blueprint-v2.md` — the final as-built architecture vs. the original plan
