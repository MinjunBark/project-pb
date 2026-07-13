# Interview Talking Points

> Owns: interview-ready synthesis of this build's strongest material. Doesn't duplicate `DECISIONS.md`/`ISSUES.md` in full — points back to them for the complete writeup. This file is the "if I only have 2 minutes on this topic" version. A companion visual cram sheet exists as a separate Artifact for quick pre-call review — this file is the source-of-truth repo version.

## The recruiter's actual framing (use this as the organizing lens)

> "The key thing he'll want to talk about are Agents or tools you've built or built onto in the past. If they have a GTM twist, even better, but if not, still great to chat about. He'll dive into what tools you used and why, and try to get an understanding of your excitement for GTM in general."

Three things, in order: a real tool/agent built, why it was chosen, genuine GTM excitement. Everything below maps to one of those three.

## The 30-second pitch

"I built a signal-driven lead-qualification pipeline mapping to a GTM/Growth Engineer role's actual stack — Python, Postgres/Supabase, Clay, HubSpot, Discord, Gemini. It watches for companies at a real buying inflection point — just raised funding, actively hiring PMs, launching a product, or a new product leader just started — and scores the real overlap between those signals rather than a static firmographic list. Anything that clears a 70-point threshold automatically gets AI-generated outreach copy and gets written to HubSpot, a tracking sheet, and Discord. What's actually interesting isn't the final pipeline - it's the real tools built around it (a Discord bot that watches for a human's enrichment upload and auto-resumes the pipeline with zero re-trigger) and the real bugs and one real self-correction caught along the way."

## Agents & tools built (his #1 ask - lead with these)

- **A real Discord bot** (`utils/discord_bot.py`, `discord.py`) watching `#clay-enrichment` for a human's uploaded CSV - detects it, saves it, immediately triggers a full re-score. No polling wait, no manual re-run.
- **A background auto-resume poller** (`asyncio` task inside the same FastAPI process) checking every 60s for enrichment dropped back locally - independent fallback path to the bot.
- **A live, single-message progress bar** (`utils/discord_webhooks.py`'s `send_progress_bar_update()`) - one Discord message editing itself in place via webhook `PATCH` as a run progresses, replacing what used to be 10-15 separate messages per run.
- **A leadership-hire detector** (`python/leadership_monitor.py`) - fetches a company's real about/team page, hashes the content, only calls Gemini to extract a name when the page actually changed since the last check. A real diff-based agent, not a blind re-scrape.
- **A dynamic outreach-copy generator** (`python/outreach.py`) - builds email/LinkedIn/call-script copy from whichever real signals fired for that specific company, not a fixed template.
- **A staffing-agency filter** (`hiring_adzuna.py`'s `_is_staffing_agency()`) - added mid-build after finding real staffing agencies polluting the hiring-signal branch; a real, evidence-driven fix found by manually classifying real unmatched company names, not a guess.

**If asked "walk me through one end to end":** pick the Discord bot. Clay's free tier has no live webhook, so enrichment has to be a manual export-import round trip. Instead of making that block the pipeline, built a bot that watches the channel and, whenever the enriched file lands (minutes or hours later), auto-imports and re-runs scoring + the digest with zero manual re-trigger. Live-tested by literally dragging a real file into Discord and watching the bot pick it up within a second.

## Tech stack, and the real "why" behind each swap (his #2 ask)

| Considered | Chose instead | Real reason |
|---|---|---|
| Crunchbase | SEC EDGAR Form D | Crunchbase's API went Enterprise-only (~$588+/yr); EDGAR is free, public, no key |
| LinkedIn Jobs scraper | Adzuna + Greenhouse/Lever | Real ToS/ban risk researched and avoided - rebuilt on 3 official free APIs |
| AWS Lambda + S3 | Local FastAPI + Postgres/Supabase | AWS required a card even for free-tier IAM - chose not to attach one to a portfolio project |
| Two separate Clay enrichment tables | One consolidated round-trip | Clay's real "Company Enrichment" waterfall already returns domain + firmographics together - no reason to split it |
| Message-per-phase Discord log | One live-editing progress bar | ~10-15 messages/run was real noise; Discord webhooks support editing a message in place |
| n8n orchestration | Discord-driven `full_pipeline_run.py` | Real SDR feedback that funding+hiring alone was "the basic approach" - paused, not abandoned |

**Talking point:** "None of these were the 'ideal' tool from a whiteboard-first design - they were the best real option once I actually checked whether the ideal one was accessible, free, or safe. That's the muscle I think matters more than picking the fanciest stack on paper."

## GTM excitement - the real story, not a performance (his #3 ask)

**Refused to fabricate leads to hit a quota.** Real data produced 0 qualified leads for several days straight. The instinct was "just lower the threshold." Pushed back directly - a "qualified" label that's sometimes fake is worse than an honest empty digest, because it destroys the one thing that makes the tool useful: trust that the label means something. Landed on a better answer instead - a "top prospects to watch" section that's honest about not having qualified yet, rather than manufacturing a fake positive.

**Caught my own mistake and reversed it live.** Mid-build, cited a stale ICP definition (the original 50-500-employee spec from the project blueprint) when real research already done for this same project showed Productboard's real customers - Autodesk, Salesforce, Zoom, Ubisoft, Medtronic - run 1,800 to 95,000 employees. Verified with real headcounts that every single named customer would have been penalized by the old thresholds, then recalibrated the scoring model. Good GTM engineering means noticing when your own assumption about the ICP doesn't match reality and fixing it before it ships, not just building the model once and moving on.

**Human-in-the-loop as a design choice, not a fallback.** Clay's free tier has no live API - enrichment has to be manual. Rather than hiding that as a limitation, designed around it explicitly: request it clearly, let the human do it on their own schedule, and make the system smart enough to notice the moment it's done and finish the job itself automatically. That's the real shape of most GTM tooling - humans and automation trading off, not one replacing the other.

## Real bugs, not hypotheticals

Pick 2-3 depending on what's being asked about (full log: `docs/ISSUES.md`):

**Clay waterfall mismatch → permanent crash loop.** Clay's real enrichment matched 3 different companies to the same placeholder domain (`google.com`). The database's UNIQUE constraint correctly rejected the 2nd/3rd write, but the error was uncaught - killed the whole import and re-crashed identically every 60 seconds, forever. Caught from a real Discord screenshot showing the identical error three times in a row. Fixed by catching the specific error per-row and skipping just that row.

**The staffing-agency root cause, three layers upstream of scoring.** 0 qualified leads looked like a scoring bug. It wasn't - Adzuna's bare `"Product Manager"` keyword search was letting through real staffing agencies (Robert Half, Jobot) with zero industry filtering, polluting the hiring signal before scoring ever saw real data. Found by manually classifying the real unmatched company names, not by guessing. Fixed with a real name/keyword filter before those companies ever reach the enrichment step.

**The truthy-string bug (G2/Branch C).** `switchedFromOtherProduct` is a `"yes"/"no"/"unknown"` string flag, not a boolean or a product name. `bool("no")` is `True` in Python - a naive truthiness check flagged 42 of 60 real reviews as switch signals when only 13 actually were. Caught by inspecting the real downloaded data, not the mocked tests (which encoded the same wrong assumption). Fixed with an explicit `== "yes"` check.

**Known, deliberately deferred: Clay re-requests companies it already tried.** Found live: companies with real partial Clay data (an employee count already filled in from a past pass) still get re-exported and re-requested every single run, wasting real Clay credits - the query has no memory of "already asked." Fix is designed (an `attempted_at` timestamp, mirroring the same dedup-window pattern already used elsewhere in this codebase for lead-qualification) but deliberately not built yet - a real, live example of choosing to document a known issue clearly rather than rush a schema change right before a deadline.

**Talking point on this whole category:** "These bugs share a pattern - either the mock encoded the same wrong assumption as the code, or the bug lived in the sequence/ordering between two individually-correct pieces, or it only showed up at real data scale. That's why I kept running things live wherever it was free to do so, and why I chose to defer a real, understood fix rather than rush it under time pressure - both are real engineering judgment calls, not just code-writing."

## Honest limitations (name these first, don't wait to be asked)

- **Still 0 qualified leads as of the last live run.** Max real score is 45/70 (Anduril Industries) - the real bottleneck is INTENT signal coverage: only ~6% of companies resolve a real job board to scan for competitor mentions, since Adzuna's API doesn't expose full job description text.
- **Branch C (G2 competitor reviews) is currently blocked** - the Apify token expired mid-build, documented rather than silently worked around or ignored.
- **Tool-mention detection is narrow by design** - regex against exactly 4 named competitors (Aha!, Jira Product Discovery, ProductPlan, Craft.io), not a general tech-stack scan. There is no Gemini-based "deconstruct the job description" phase - a real, correctable misconception worth being precise about if asked.
- **n8n is paused, not deleted** - a deliberate pivot after real SDR feedback it was too basic, with a clear, documented reason recorded, not an abandoned feature.
- **Greenhouse/Lever board-token guessing has a real, measured ~6% hit rate** - flagged as a real risk before building it, then measured on live data instead of assumed either way.

## If asked "what would you do differently with more time"

- Fix the Clay re-request waste (real cost today, fix already designed).
- Widen the real ATS match rate so more companies get real competitor-mention scanning - that's the actual lever on qualified-lead count, not loosening the scoring threshold.
- Refresh the expired `G2_API_TOKEN` to unblock Branch C's independent INTENT source.
- Move off any remaining local-dev dependency (e.g. a laptop needing to stay awake for the poller) toward a real always-on deployment.

## Where the deeper material lives

- `docs/DECISIONS.md` — every ADR, full reasoning, alternatives considered
- `docs/ISSUES.md` — every real bug, the dead-end investigated first, the fix, the talking point
- `docs/HANDOFF.md` — exact current live state, including the architecture Q&A walkthrough
- `gtm-signal-blueprint-v2.md` — the final as-built architecture vs. the original plan
