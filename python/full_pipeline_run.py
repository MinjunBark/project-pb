"""Redesign v2, Tier 2/3: one entry point that runs Branch A, B, D (Branch C
opt-in only, ADR-009) -> merge -> leadership check -> score + process every
company - posting progress to Discord's ops-progress channel at each phase
boundary, then sending a final SDR digest. Exists to give a human watching
Discord full visibility into a real live end-to-end run, without needing to
tail logs (this project has none - see docs/CODE_GUIDE.md) or poll each
endpoint by hand, the way every live-verification pass this session has
been done manually so far.

Branch C, when included, is demand-driven by Branch B's real findings this
run (see _competitors_mentioned_this_run()) rather than always blindly
scraping the same fixed 4 tracked competitors - it only runs after Branch
B, restricted to whichever tracked competitors were actually mentioned in
this run's real job postings, and is skipped entirely (not a wasted Apify
call) when none were.

Calls every other module's already-tested functions directly, in-process -
not by re-calling this API's own other endpoints over HTTP. Matches how
merge_signals.run_full_merge() already composes other modules' functions,
and avoids the app calling itself over the network (auth/timeout/failure
surface for no real benefit).

Fails loud: any phase's exception is posted to the ops-progress channel as
a message, then re-raised - the whole run stops. Matches this project's
existing convention everywhere else (missing webhook/API-key config all
raise immediately, nothing is silently swallowed) - a live external-API
hiccup should be visible, not silently absorbed into a partial result.
"""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
import discord_webhooks as discord  # noqa: E402
import enrichment  # noqa: E402
import funding_edgar  # noqa: E402
import hiring_signals  # noqa: E402
import intent_g2  # noqa: E402
import leadership_monitor  # noqa: E402
import merge_signals  # noqa: E402
import pipeline  # noqa: E402
import producthunt_launches  # noqa: E402
import raw_landing  # noqa: E402
from scoring import score_company  # noqa: E402

# Redesign v2, Tier 3: how many top-scoring, not-yet-qualified companies to
# surface in the SDR digest's watchlist section - matches Discord's
# comfortable per-embed field count (utils/discord.py's DIGEST_LEADS_PER_EMBED).
WATCHLIST_SIZE = 15

# Redesign v2: fixed step counts for each trigger's tracker, so the
# progress bar always reaches a clean 100% at completion. Every phase
# always calls tracker.advance() exactly once, even a no-op/skipped one
# (the label reflects the real outcome; the step count is deterministic).
FULL_RUN_TOTAL_STEPS = 12  # Branch A/B/D/C, Merge, Clay pickup/request, Leadership, Scoring, Digest, Run log, Complete
AUTO_RESUME_TOTAL_STEPS = 5  # Leadership, Scoring, Digest, Run log, Complete


class ProgressTracker:
    """Redesign v2: wraps one live-editing Discord message across an
    entire run, instead of the old one-new-message-per-phase approach
    (~10-15 messages per run before this). Created once at the top of
    run_full_cycle()/resume_after_enrichment() with that trigger's real
    total step count."""

    def __init__(self, total_steps: int, initial_label: str):
        self.total_steps = total_steps
        self.current_step = 0
        self.message_id = discord.send_progress_bar_update(0, total_steps, initial_label)

    def advance(self, label: str) -> None:
        self.current_step += 1
        self.message_id = discord.send_progress_bar_update(self.current_step, self.total_steps, label, self.message_id)

    def fail(self, label: str, exc: Exception) -> None:
        """Freezes the bar at its current step, swaps the label to a real
        ❌ failure line - the run stops right after this, so no further
        advance() calls happen."""
        self.message_id = discord.send_progress_bar_update(
            self.current_step, self.total_steps, f"❌ FAILED at {label}: {exc}", self.message_id
        )


def _run_phase(tracker: ProgressTracker, label: str, fn, *args, **kwargs):
    """Runs one phase, freezing the live progress bar with a ❌ failure
    line and re-raising on failure - the single place this fail-loud
    policy is implemented, so every phase gets identical error-visibility
    behavior."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        tracker.fail(label, exc)
        raise


def _competitors_mentioned_this_run(hiring_signal_list: list[dict]) -> dict[str, str]:
    """Redesign v2, Tier 3: makes Branch C demand-driven by Branch B's real
    findings instead of always scraping the same fixed 4 competitors
    regardless of relevance. Unions every company's current_tools_mentioned
    from this run's real Branch B output, intersected with
    intent_g2.DEFAULT_COMPETITORS' keys - restricted to competitors we have
    a verified, real G2 slug for (see intent_g2.py's module docstring on
    the real slug quirks, e.g. "aha" not "aha-roadmaps" - a name alone
    can't be reliably turned into a slug, so anything outside this known
    set is deliberately excluded rather than guessed at)."""
    mentioned: set[str] = set()
    for signal in hiring_signal_list:
        mentioned.update(signal.get("current_tools_mentioned") or [])

    return {name: slug for name, slug in intent_g2.DEFAULT_COMPETITORS.items() if name in mentioned}


def run_full_cycle(
    include_branch_c: bool = False,
    branch_c_competitors: dict | None = None,
    dedup_window_days: int = pipeline.DEFAULT_DEDUP_WINDOW_DAYS,
    include_enrichment_request: bool = True,
) -> dict:
    """Runs the entire pipeline live, in-process, posting progress to
    Discord along the way, then sends the SDR digest. Returns a summary
    dict describing every phase's outcome."""
    initial_label = "🚀 Starting full pipeline run..."
    if include_branch_c:
        initial_label = "🚀 Starting full pipeline run (Branch C included — real Apify cost)..."
    tracker = ProgressTracker(FULL_RUN_TOTAL_STEPS, initial_label)

    # Redesign v2, Tier 3: accumulates the real query parameters and result
    # counts from every phase, landed as data/raw/run_log_<timestamp>.json
    # at the end (same convention every branch already uses via
    # raw_landing.save_raw_signals) - the "learn from every scrape" record
    # the user asked for, so real recall gaps can be diagnosed later
    # instead of guessed at.
    query_log: dict = {"run_started_at": datetime.now(timezone.utc).isoformat()}

    funding_signals = _run_phase(tracker, "Branch A (funding)", funding_edgar.get_funding_signals)
    _run_phase(tracker, "Landing Branch A", raw_landing.save_raw_signals, "branch_a", funding_signals)
    tracker.advance(f"✅ Branch A (funding): {len(funding_signals)} signals landed.")
    query_log["branch_a"] = {"count": len(funding_signals)}

    hiring_signal_list = _run_phase(tracker, "Branch B (hiring)", hiring_signals.get_hiring_signals)
    _run_phase(tracker, "Landing Branch B", raw_landing.save_raw_signals, "branch_b", hiring_signal_list)
    tracker.advance(f"✅ Branch B (hiring): {len(hiring_signal_list)} signals landed.")
    query_log["branch_b"] = {
        "count": len(hiring_signal_list),
        "companies": [
            {
                "company_name": s.get("company_name"),
                "ats_source": s.get("source"),
                "matched_slug": s.get("ats_matched_slug"),
                "current_tools_mentioned": s.get("current_tools_mentioned") or [],
                "buying_intent_detected": bool((s.get("buying_intent") or {}).get("buying_intent_detected")),
            }
            for s in hiring_signal_list
        ],
    }

    launch_signals = _run_phase(tracker, "Branch D (launches)", producthunt_launches.get_launch_signals)
    _run_phase(tracker, "Landing Branch D", raw_landing.save_raw_signals, "branch_d", launch_signals)
    tracker.advance(f"✅ Branch D (launches): {len(launch_signals)} signals landed.")
    query_log["branch_d"] = {"count": len(launch_signals)}

    branch_c_review_count = None
    if include_branch_c:
        # Demand-driven: use the caller's explicit override if given,
        # otherwise derive the set from what Branch B actually found this
        # run - not a blind default to all 4 tracked competitors.
        effective_competitors = (
            branch_c_competitors
            if branch_c_competitors is not None
            else _competitors_mentioned_this_run(hiring_signal_list)
        )

        if not effective_competitors:
            tracker.advance(
                "⏭️ Branch C included but skipped — no tracked competitor mentions found in this run's Branch B data."
            )
            query_log["branch_c"] = {"included": True, "skipped_reason": "no tracked competitor mentions this run"}
        else:
            branch_c_result = _run_phase(
                tracker, "Branch C (G2 intent)", intent_g2.get_intent_signals, competitors=effective_competitors
            )
            _run_phase(tracker, "Landing Branch C", raw_landing.save_raw_signals, "branch_c", branch_c_result)
            branch_c_review_count = len(branch_c_result["reviews"])
            tracker.advance(
                f"✅ Branch C (G2 intent): {branch_c_review_count} reviews landed for "
                f"{len(effective_competitors)} competitor(s)."
            )
            query_log["branch_c"] = {
                "included": True,
                "competitors_used": effective_competitors,
                "review_count": branch_c_review_count,
            }
    else:
        tracker.advance("⏭️ Branch C skipped (opt-in only, ADR-009).")
        query_log["branch_c"] = {"included": False, "skipped_reason": "opt-in only, ADR-009"}

    conn = db.get_connection()
    try:
        merge_result = _run_phase(tracker, "Merge", merge_signals.run_full_merge, conn)
        tracker.advance(
            f"✅ Supabase updated: {merge_result['distinct_company_ids']} companies written/updated "
            f"(A:{merge_result['companies_from_funding']} B:{merge_result['companies_from_hiring']} "
            f"D:{merge_result['companies_from_launches']}, {merge_result['competitors_updated']} competitor(s) refreshed)."
        )

        _run_clay_pickup_and_request_phase(conn, query_log, tracker, include_enrichment_request=include_enrichment_request)

        finish_result = _finish_run(conn, dedup_window_days, trigger_label="full_run", tracker=tracker, query_log=query_log)

        return {
            **finish_result,
            "branch_a_count": len(funding_signals),
            "branch_b_count": len(hiring_signal_list),
            "branch_d_count": len(launch_signals),
            "branch_c_count": branch_c_review_count,
            "merge_result": merge_result,
        }
    finally:
        conn.close()


def _run_clay_pickup_and_request_phase(
    conn, query_log: dict, tracker: ProgressTracker, include_enrichment_request: bool = True
) -> None:
    """Redesign v2, Tier 5/6: the human-in-the-loop Clay phase, run once
    right after Merge, before scoring - so anything picked up here benefits
    THIS run's scoring instead of waiting for a later run.

    Consolidated 2026-07-13 into a single enrichment queue (was two -
    domain-only, demographics-only) since Clay's real "Company Enrichment"
    waterfall already returns domain + employee count + industry together
    in one pass - there was never a real reason to run two separate
    request/import tracks for data one enrichment call provides.

    Pickup always runs first (auto-imports anything already dropped back
    into data/clay/incoming_enrichment/ since the last check - see
    enrichment.process_incoming_enrichment()) - picking up already-completed
    work is always safe and keeps data current, unlike requesting NEW work.

    Request runs second: if the queue is still non-empty after pickup,
    exports a fresh CSV and posts it to #clay-enrichment via
    discord.send_clay_enrichment_request() so the user knows exactly what
    still needs manual Clay work. Can be skipped for a given run via
    include_enrichment_request=False (mirrors include_branch_c's "opt out
    of a whole optional phase" pattern)."""
    picked_up = enrichment.process_incoming_enrichment(conn)
    if picked_up:
        tracker.advance(f"✅ Clay enrichment picked up: {len(picked_up)} companies updated from prior manual enrichment.")
    else:
        tracker.advance("✅ Clay pickup checked: nothing new to import.")
    query_log["clay_pickup"] = {"updated": len(picked_up)}

    if not include_enrichment_request:
        tracker.advance("⏭️ Clay enrichment request skipped (excluded for this run).")
        query_log["clay_request"] = {"skipped": True, "reason": "excluded for this run"}
        return

    queue = enrichment.get_companies_needing_enrichment(conn)
    if not queue:
        tracker.advance("✅ Clay enrichment request: nothing needed, every company fully enriched.")
        query_log["clay_request"] = {"count": 0}
        return

    path = enrichment.export_companies_needing_enrichment(conn)
    _run_phase(tracker, "Clay enrichment request", discord.send_clay_enrichment_request, len(queue), path)
    tracker.advance(f"📤 Clay enrichment requested: {len(queue)} companies need enrichment.")
    query_log["clay_request"] = {"count": len(queue), "export_path": path}


def _finish_run(conn, dedup_window_days: int, trigger_label: str, tracker: ProgressTracker, query_log: dict | None = None) -> dict:
    """The shared tail every real run ends with, regardless of how it
    started - leadership check -> scoring/outreach -> watchlist -> SDR
    digest -> run log landing. Used by both a fresh full run (run_full_cycle)
    and an automatic resume-after-enrichment (resume_after_enrichment), so
    the two paths can never drift apart into subtly different scoring or
    digest behavior. Always advances the shared tracker exactly 5 times
    (leadership, scoring, digest, run log, complete), matching both
    callers' declared total step counts."""
    query_log = query_log if query_log is not None else {"run_started_at": datetime.now(timezone.utc).isoformat()}
    query_log["trigger"] = trigger_label

    domain_companies = [c for c in db.get_all_companies(conn) if c.get("domain")]
    leadership_results = _run_phase(
        tracker,
        "Leadership check",
        lambda: [leadership_monitor.check_for_new_leadership(conn, c["id"], c["domain"]) for c in domain_companies],
    )
    leadership_new_hires = sum(1 for r in leadership_results if r)
    tracker.advance(
        f"✅ Leadership check: {len(domain_companies)} companies checked, {leadership_new_hires} new hire(s) found."
    )
    query_log["leadership"] = {
        "companies_checked": len(domain_companies),
        "details": [
            {"company_name": c["name"], "domain": c["domain"], "new_hire_found": bool(r)}
            for c, r in zip(domain_companies, leadership_results)
        ],
    }

    all_companies = db.get_all_companies(conn)
    competitor_intel = db.get_all_competitor_intel(conn)

    def _score_all():
        results = []
        for company in all_companies:
            signals = db.get_signals_for_company(conn, company["id"])
            results.append(
                pipeline.process_qualified_lead(
                    conn, company, signals, competitor_intel, dedup_window_days=dedup_window_days
                )
            )
        return results

    results = _run_phase(tracker, "Scoring + outreach", _score_all)
    qualified_leads = [r for r in results if r["status"] == "processed"]
    tracker.advance(
        f"✅ Scoring + outreach complete: {len(all_companies)} evaluated, {len(qualified_leads)} qualified and processed."
    )
    query_log["scoring"] = [
        {"company_name": r.get("company_name"), "icp_score": r.get("icp_score"), "signal_type": r.get("signal_type")}
        for r in results
    ]

    # Redesign v2, Tier 3: the digest should never look empty. Build a
    # watchlist of the top-scoring companies that did NOT qualify this
    # run - every non-"processed" status now carries company_name/
    # domain/signal_type/score_breakdown (extended this session), so
    # this doesn't need to re-score anything.
    watchlist_candidates = [r for r in results if r["status"] != "processed"]
    watchlist = sorted(watchlist_candidates, key=lambda r: r.get("icp_score", 0), reverse=True)[:WATCHLIST_SIZE]

    summary = {"date": date.today().isoformat(), "qualified_leads": qualified_leads, "watchlist": watchlist}
    _run_phase(tracker, "SDR digest", discord.send_sdr_digest, summary)
    tracker.advance("📧 SDR digest sent.")

    log_path = _run_phase(tracker, "Landing run log", raw_landing.save_raw_signals, "run_log", query_log)
    tracker.advance(f"📝 Full run log saved: {log_path}")

    tracker.advance("🏁 Full pipeline run complete.")

    return {
        "companies_evaluated": len(all_companies),
        "qualified_count": len(qualified_leads),
        "leadership_companies_checked": len(domain_companies),
        "leadership_new_hires_found": leadership_new_hires,
        "run_log_path": log_path,
    }


def resume_after_enrichment(dedup_window_days: int = pipeline.DEFAULT_DEDUP_WINDOW_DAYS) -> dict | None:
    """Redesign v2, Tier 5: the automatic-resume path. Called by
    api/main.py's background poller every ~60s (and available as a manual
    on-demand trigger via POST /pipeline/resume-after-enrichment).

    Opens its own connection, checks the incoming_enrichment/ folder for
    anything the user has dropped back since the last check. If nothing new
    was picked up, it's a genuine no-op - returns None so the poller doesn't
    post noise every single tick. If something WAS picked up, it means the
    user just finished a manual Clay round-trip, so this finishes the
    workflow for them automatically: same leadership check -> scoring ->
    SDR digest tail every real run ends with (_finish_run), using the
    freshly-imported data - no manual re-trigger required."""
    conn = db.get_connection()
    try:
        picked_up = enrichment.process_incoming_enrichment(conn)
        if not picked_up:
            return None

        tracker = ProgressTracker(
            AUTO_RESUME_TOTAL_STEPS, "🔄 New Clay enrichment detected — automatically resuming the pipeline..."
        )
        query_log = {
            "run_started_at": datetime.now(timezone.utc).isoformat(),
            "clay_pickup": {"updated": len(picked_up)},
        }
        return _finish_run(conn, dedup_window_days, trigger_label="auto-resume", tracker=tracker, query_log=query_log)
    finally:
        conn.close()
