"""Phase 9: the full per-lead pipeline, tying together every phase built so
far - scoring (4) -> HubSpot dedupe (7) -> outreach generation (8) -> output
fan-out (9: leads table, HubSpot write, Google Sheet, Discord).

This is the sequence n8n's workflow (built by the user in the UI, ADR-007)
will mirror node-by-node - each function here corresponds to roughly one
HTTP Request / Code node in that workflow.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
import discord_webhooks as discord  # noqa: E402
import hubspot  # noqa: E402
import outreach  # noqa: E402
import sheets  # noqa: E402
from scoring import score_company  # noqa: E402

PIPELINE_STATUS_QUEUED = "signal_queued"

# Mirrors DEDUP_WINDOW_DAYS in .env (defined since Phase 0, unused until
# now) - default kept in sync manually since pipeline.py stays testable
# without requiring env vars, matching the existing pattern of scoring.py's
# ICP_SCORE_THRESHOLD also being a plain constant rather than env-read.
DEFAULT_DEDUP_WINDOW_DAYS = 7


def _latest_pm_job_post_count(signals: list[dict]) -> int:
    """Mirrors scoring.py's own pm_hiring-signal counting logic (most
    recent signal row's raw_text, comma-split) - kept separate rather than
    importing scoring's private helpers, since this is display/prompt
    context, not itself a scoring decision."""
    hiring_signals = [s for s in signals if s.get("signal_category") == "pm_hiring"]
    if not hiring_signals:
        return 0
    latest = max(hiring_signals, key=lambda s: s.get("posted_at") or s.get("created_at") or "")
    raw_text = latest.get("raw_text")
    return len(raw_text.split(",")) if raw_text else 0


def _latest_signal_raw_text(signals: list[dict], category: str) -> str | None:
    """Redesign v2, Tier 1: the same 'most recent row wins' pattern
    scoring.py's _latest_signal() already uses, but returning just the
    raw_text a caller wants to display/quote (the buying-intent matched
    phrase, the new leader's name+title, or the launch tagline) rather than
    the whole row - display/prompt context, not a scoring decision, so kept
    separate from scoring.py's private helper like _latest_pm_job_post_count
    above."""
    matches = [s for s in signals if s.get("signal_category") == category]
    if not matches:
        return None
    latest = max(matches, key=lambda s: s.get("posted_at") or s.get("created_at") or "")
    return latest.get("raw_text")


def build_lead_context(company: dict, signals: list[dict], competitor_intel: dict, score_result: dict) -> dict:
    """Assembles the combined company + score + pain-quote context that
    both outreach.generate_outreach() and the output fan-out (sheet,
    Discord, HubSpot) need - one shared shape instead of re-deriving it at
    each output.

    Redesign v2, Tier 1: also pulls the buying-intent phrase, new
    leadership-hire name/title, and product-launch tagline (when present) -
    previously these 3 new signal types fed scoring.py but were invisible
    to outreach.generate_outreach(), so a lead could newly qualify because
    of e.g. a leadership hire and the generated email would never mention
    it. Closes that gap."""
    current_tool = company.get("current_tool_mentioned")
    intel = competitor_intel.get(current_tool) if current_tool else None

    return {
        "company_name": company.get("name"),
        "domain": company.get("domain"),
        "signal_type": score_result["signal_type"],
        "icp_score": score_result["icp_score"],
        "score_breakdown": score_result["score_breakdown"],
        "funding_stage": company.get("funding_stage"),
        "funding_date": company.get("funding_date"),
        "funding_amount_usd": company.get("funding_amount_usd"),
        "pm_job_post_count": _latest_pm_job_post_count(signals),
        "current_tool_mentioned": current_tool,
        "competitor_pain_quotes": (intel or {}).get("representative_quotes", []),
        "buying_intent_phrase": _latest_signal_raw_text(signals, "buying_intent"),
        "new_leadership_hire": _latest_signal_raw_text(signals, "leadership_hire"),
        "recent_product_launch": _latest_signal_raw_text(signals, "product_launch"),
    }


def _hubspot_properties(lead_context: dict, outreach_copy: dict) -> dict:
    """Maps our internal field names onto the custom HubSpot property names
    created by hubspot.ensure_custom_properties_exist() (ADR-020)."""
    return {
        "icp_score": lead_context["icp_score"],
        "gtm_signal_type": lead_context["signal_type"],
        "funding_stage": lead_context.get("funding_stage") or "",
        "funding_amount_usd": lead_context.get("funding_amount_usd") or 0,
        "current_tool_mentioned": lead_context.get("current_tool_mentioned") or "",
        "priority_summary": outreach_copy["priority_summary"],
        "outreach_subject_a": outreach_copy["email_subject_a"],
        "outreach_subject_b": outreach_copy["email_subject_b"],
        "outreach_email_body": outreach_copy["email_body"],
        "outreach_linkedin": outreach_copy["linkedin_message"],
        "outreach_call_script": outreach_copy["call_script"],
        "gtm_pipeline_status": PIPELINE_STATUS_QUEUED,
    }


def process_qualified_lead(
    conn, company: dict, signals: list[dict], competitor_intel: dict, dedup_window_days: int = DEFAULT_DEDUP_WINDOW_DAYS
) -> dict:
    """The full Phase 9 flow for one company:
      1. Score it (Phase 4). Not qualified (< 70) -> stop here.
      2. Check for a recent leads row (dedup_window_days) -> stop here if
         this company was already processed recently, so a daily-scheduled
         run doesn't repeat real Gemini calls and HubSpot writes for a
         company that still qualifies today the same way it did yesterday.
      3. Check HubSpot dedupe status (Phase 7). Recently contacted -> stop here.
      4. Generate outreach copy (Phase 8).
      5. Write a leads row (Postgres), write/update the HubSpot company
         record, append a row to the Google Sheet, and post a Discord
         notification.
    Returns a summary dict with a "status" key describing how far it got:
    "not_qualified" | "skipped_recently_processed" | "skipped_recently_contacted" | "processed".
    """
    score_result = score_company(company, signals, competitor_intel)
    if not score_result["qualified"]:
        # Redesign v2, Tier 3: additive fields so a caller (full_pipeline_run.py's
        # digest watchlist) can build a "top prospects, not yet qualified"
        # view without re-scoring - all already in scope here.
        return {
            "status": "not_qualified",
            "icp_score": score_result["icp_score"],
            "company_name": company.get("name"),
            "domain": company.get("domain"),
            "signal_type": score_result["signal_type"],
            "score_breakdown": score_result["score_breakdown"],
        }

    if db.has_recent_lead(conn, company["id"], dedup_window_days):
        return {
            "status": "skipped_recently_processed",
            "icp_score": score_result["icp_score"],
            "company_name": company.get("name"),
            "domain": company.get("domain"),
            "signal_type": score_result["signal_type"],
            "score_breakdown": score_result["score_breakdown"],
        }

    dedupe = hubspot.check_dedupe_status(company.get("domain"), company.get("name"))
    if dedupe["status"] == "skip":
        return {
            "status": "skipped_recently_contacted",
            "hubspot_company_id": dedupe["hubspot_company_id"],
            "icp_score": score_result["icp_score"],
            "company_name": company.get("name"),
            "domain": company.get("domain"),
            "signal_type": score_result["signal_type"],
            "score_breakdown": score_result["score_breakdown"],
        }

    lead_context = build_lead_context(company, signals, competitor_intel, score_result)
    outreach_copy = outreach.generate_outreach(lead_context)

    # HubSpot create/update runs BEFORE insert_lead() specifically so the
    # real hubspot_company_id can be written into the leads row directly,
    # rather than left NULL or requiring a separate follow-up UPDATE - a
    # real bug caught by the first live end-to-end test (docs/ISSUES.md).
    hubspot_properties = _hubspot_properties(lead_context, outreach_copy)
    if dedupe["status"] == "create":
        hubspot_company_id = hubspot.create_company(company.get("domain"), company.get("name"), hubspot_properties)
    else:
        hubspot_company_id = dedupe["hubspot_company_id"]
        hubspot.update_company(hubspot_company_id, hubspot_properties)

    lead_id = db.insert_lead(
        conn,
        company["id"],
        score_result["icp_score"],
        score_result["signal_type"],
        score_breakdown=score_result["score_breakdown"],
        priority_summary=outreach_copy["priority_summary"],
        outreach_email_subject_a=outreach_copy["email_subject_a"],
        outreach_email_subject_b=outreach_copy["email_subject_b"],
        outreach_email_body=outreach_copy["email_body"],
        outreach_linkedin=outreach_copy["linkedin_message"],
        outreach_call_script=outreach_copy["call_script"],
        hubspot_company_id=hubspot_company_id,
    )

    sheet_row = {
        **lead_context,
        "priority_summary": outreach_copy["priority_summary"],
        "outreach_subject_a": outreach_copy["email_subject_a"],
        "outreach_subject_b": outreach_copy["email_subject_b"],
        "outreach_email_body": outreach_copy["email_body"],
        "outreach_linkedin": outreach_copy["linkedin_message"],
        "outreach_call_script": outreach_copy["call_script"],
        "hubspot_company_id": hubspot_company_id,
    }
    worksheet = sheets.get_worksheet()
    sheets.ensure_header_row(worksheet)
    sheets.append_lead_row(worksheet, sheet_row)

    discord.send_lead_notification(
        {
            **lead_context,
            "priority_summary": outreach_copy["priority_summary"],
            # Redesign v2, Tier 3: platform-storage tracking - hubspot_company_id
            # and lead_id are only known at this point in the flow (after the
            # HubSpot write and the Postgres insert above), so they're added
            # here rather than in lead_context itself.
            "hubspot_company_id": hubspot_company_id,
            "lead_id": lead_id,
        }
    )

    return {
        "status": "processed",
        "lead_id": lead_id,
        "hubspot_company_id": hubspot_company_id,
        "icp_score": score_result["icp_score"],
        "signal_type": score_result["signal_type"],
        # Redesign v2, Tier 2: additive fields so a caller (full_pipeline_run.py's
        # SDR digest) can build a real per-lead summary without re-deriving
        # lead_context/outreach_copy itself - all three are already in scope here.
        "company_name": lead_context["company_name"],
        "domain": lead_context["domain"],
        "priority_summary": outreach_copy["priority_summary"],
    }
