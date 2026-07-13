"""Tests for python/pipeline.py - Phase 9's per-lead orchestration. Every
external call (scoring, hubspot, outreach, db, sheets, discord) is mocked;
this file only checks that pipeline.py sequences and wires them together
correctly, not that any individual piece's own logic is right (that's each
piece's own test file's job)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import pipeline  # noqa: E402

COMPANY = {
    "id": 5,
    "name": "Acme Corp",
    "domain": "acme.com",
    "funding_stage": "Series B",
    "funding_date": "2026-06-10",
    "funding_amount_usd": 20_000_000,
    "current_tool_mentioned": "Aha!",
}

SIGNALS = [
    {"signal_category": "pm_hiring", "raw_text": "Senior PM, PM", "posted_at": "2026-07-01"},
]

COMPETITOR_INTEL = {"Aha!": {"representative_quotes": [{"text": "too expensive"}]}}

NOT_QUALIFIED_SCORE = {"qualified": False, "icp_score": 20, "signal_type": "NONE", "score_breakdown": {}}
QUALIFIED_SCORE = {
    "qualified": True,
    "icp_score": 90,
    "signal_type": "BOTH",
    "score_breakdown": {"timing": {"funding_recency": 25}},
}

OUTREACH_COPY = {
    "priority_summary": "Act now.",
    "email_subject_a": "Subject A",
    "email_subject_b": "Subject B",
    "email_body": "Body text.",
    "linkedin_message": "LinkedIn text.",
    "call_script": "Script text.",
}


def _mock_all(monkeypatch, score_result, dedupe_result, has_recent_lead=False):
    monkeypatch.setattr(pipeline, "score_company", MagicMock(return_value=score_result))
    monkeypatch.setattr(pipeline.db, "has_recent_lead", MagicMock(return_value=has_recent_lead))
    monkeypatch.setattr(pipeline.hubspot, "check_dedupe_status", MagicMock(return_value=dedupe_result))
    monkeypatch.setattr(pipeline.outreach, "generate_outreach", MagicMock(return_value=OUTREACH_COPY))
    monkeypatch.setattr(pipeline.db, "insert_lead", MagicMock(return_value=42))
    monkeypatch.setattr(pipeline.hubspot, "create_company", MagicMock(return_value="hs-999"))
    monkeypatch.setattr(pipeline.hubspot, "update_company", MagicMock())
    monkeypatch.setattr(pipeline.sheets, "get_worksheet", MagicMock())
    monkeypatch.setattr(pipeline.sheets, "ensure_header_row", MagicMock())
    monkeypatch.setattr(pipeline.sheets, "append_lead_row", MagicMock())
    monkeypatch.setattr(pipeline.discord, "send_lead_notification", MagicMock())


def test_stops_early_when_not_qualified(monkeypatch):
    """A sub-70 score must stop the pipeline immediately - no dedupe check,
    no outreach generation (real Gemini cost), no writes anywhere. This is
    the cheapest, most important short-circuit in the whole flow."""
    _mock_all(monkeypatch, NOT_QUALIFIED_SCORE, dedupe_result={"status": "create", "hubspot_company_id": None})
    mock_conn = MagicMock()

    result = pipeline.process_qualified_lead(mock_conn, COMPANY, SIGNALS, COMPETITOR_INTEL)

    assert result == {
        "status": "not_qualified",
        "icp_score": 20,
        "company_name": COMPANY["name"],
        "domain": COMPANY["domain"],
        "signal_type": "NONE",
        "score_breakdown": {},
    }
    pipeline.hubspot.check_dedupe_status.assert_not_called()
    pipeline.outreach.generate_outreach.assert_not_called()


def test_stops_early_when_recently_processed(monkeypatch):
    """A company that already has a leads row within the dedup window must
    stop BEFORE the HubSpot dedupe check (a real network call) and before
    outreach generation (a real Gemini call, real cost) - this is what
    keeps a daily-scheduled run from repeating expensive work for a company
    that still qualifies today the same way it did yesterday."""
    _mock_all(
        monkeypatch,
        QUALIFIED_SCORE,
        dedupe_result={"status": "create", "hubspot_company_id": None},
        has_recent_lead=True,
    )
    mock_conn = MagicMock()

    result = pipeline.process_qualified_lead(mock_conn, COMPANY, SIGNALS, COMPETITOR_INTEL)

    assert result == {
        "status": "skipped_recently_processed",
        "icp_score": 90,
        "company_name": COMPANY["name"],
        "domain": COMPANY["domain"],
        "signal_type": "BOTH",
        "score_breakdown": QUALIFIED_SCORE["score_breakdown"],
    }
    pipeline.hubspot.check_dedupe_status.assert_not_called()
    pipeline.outreach.generate_outreach.assert_not_called()


def test_has_recent_lead_checked_with_the_configured_dedup_window(monkeypatch):
    """Confirms the dedup_window_days parameter actually reaches
    db.has_recent_lead() - a caller passing a custom window (e.g. from an
    env-configured value in the API layer) must have it honored, not
    silently ignored in favor of some hardcoded number."""
    _mock_all(monkeypatch, QUALIFIED_SCORE, dedupe_result={"status": "create", "hubspot_company_id": None})
    mock_conn = MagicMock()

    pipeline.process_qualified_lead(mock_conn, COMPANY, SIGNALS, COMPETITOR_INTEL, dedup_window_days=14)

    pipeline.db.has_recent_lead.assert_called_once_with(mock_conn, COMPANY["id"], 14)


def test_stops_after_dedupe_when_recently_contacted(monkeypatch):
    """A qualified lead that was already recently contacted must stop right
    after the dedupe check - no outreach generation (avoids spending real
    Gemini calls on a lead we're not going to message), no leads-table
    write, no sheet/Discord output. This is the whole point of Phase 7
    existing before Phase 8/9 in the pipeline order."""
    _mock_all(monkeypatch, QUALIFIED_SCORE, dedupe_result={"status": "skip", "hubspot_company_id": "hs-123"})
    mock_conn = MagicMock()

    result = pipeline.process_qualified_lead(mock_conn, COMPANY, SIGNALS, COMPETITOR_INTEL)

    assert result == {
        "status": "skipped_recently_contacted",
        "hubspot_company_id": "hs-123",
        "icp_score": 90,
        "company_name": COMPANY["name"],
        "domain": COMPANY["domain"],
        "signal_type": "BOTH",
        "score_breakdown": QUALIFIED_SCORE["score_breakdown"],
    }
    pipeline.outreach.generate_outreach.assert_not_called()
    pipeline.db.insert_lead.assert_not_called()


def test_full_flow_creates_new_hubspot_company_when_not_found(monkeypatch):
    """The 'create' path: a genuinely new qualified lead should generate
    outreach, write a leads row, CREATE (not update) a HubSpot company, and
    fan out to both the sheet and Discord - confirms every step actually
    runs, in the right order, for the most common real case."""
    _mock_all(monkeypatch, QUALIFIED_SCORE, dedupe_result={"status": "create", "hubspot_company_id": None})
    mock_conn = MagicMock()

    result = pipeline.process_qualified_lead(mock_conn, COMPANY, SIGNALS, COMPETITOR_INTEL)

    assert result["status"] == "processed"
    assert result["hubspot_company_id"] == "hs-999"
    pipeline.hubspot.create_company.assert_called_once()
    pipeline.hubspot.update_company.assert_not_called()
    pipeline.sheets.append_lead_row.assert_called_once()
    pipeline.discord.send_lead_notification.assert_called_once()

    # Redesign v2, Tier 2: additive fields on the "processed" result so a
    # caller (full_pipeline_run.py's SDR digest) can build a per-lead
    # summary without re-deriving lead_context/outreach_copy itself.
    assert result["company_name"] == COMPANY["name"]
    assert result["domain"] == COMPANY["domain"]
    assert result["priority_summary"] == OUTREACH_COPY["priority_summary"]


def test_full_flow_ensures_header_row_before_appending(monkeypatch):
    """Regression test for a real gap caught by the first live end-to-end
    test (docs/ISSUES.md): the pipeline called append_lead_row() directly
    without ever calling ensure_header_row() first, so a brand-new sheet
    ended up with data rows and no header at all. Confirms ensure_header_row
    is called before append_lead_row on every run - it's cheap to call
    repeatedly (sheets.py already makes it a no-op once the header exists)."""
    _mock_all(monkeypatch, QUALIFIED_SCORE, dedupe_result={"status": "create", "hubspot_company_id": None})
    mock_conn = MagicMock()

    pipeline.process_qualified_lead(mock_conn, COMPANY, SIGNALS, COMPETITOR_INTEL)

    pipeline.sheets.ensure_header_row.assert_called_once()


def test_full_flow_writes_real_hubspot_company_id_onto_the_leads_row(monkeypatch):
    """Regression test for a real bug caught by the first live end-to-end
    test (docs/ISSUES.md): the leads.hubspot_company_id column was landing
    as NULL because db.insert_lead() originally ran BEFORE the HubSpot
    create/update step, so the real id never made it into the insert call.
    Confirms insert_lead() is now called WITH the real hubspot_company_id
    kwarg, using the id create_company() actually returned."""
    _mock_all(monkeypatch, QUALIFIED_SCORE, dedupe_result={"status": "create", "hubspot_company_id": None})
    mock_conn = MagicMock()

    pipeline.process_qualified_lead(mock_conn, COMPANY, SIGNALS, COMPETITOR_INTEL)

    _, kwargs = pipeline.db.insert_lead.call_args
    assert kwargs["hubspot_company_id"] == "hs-999"


def test_full_flow_updates_existing_hubspot_company_when_stale_contact(monkeypatch):
    """The 'update' path: a qualified lead that already exists in HubSpot
    but wasn't recently contacted should UPDATE (not create a duplicate)
    the existing record, using its real hubspot_company_id from the dedupe
    check - a real duplicate-record bug would create a second company for
    the same real business."""
    _mock_all(monkeypatch, QUALIFIED_SCORE, dedupe_result={"status": "update", "hubspot_company_id": "hs-777"})
    mock_conn = MagicMock()

    result = pipeline.process_qualified_lead(mock_conn, COMPANY, SIGNALS, COMPETITOR_INTEL)

    assert result["hubspot_company_id"] == "hs-777"
    pipeline.hubspot.update_company.assert_called_once()
    args, _ = pipeline.hubspot.update_company.call_args
    assert args[0] == "hs-777"
    pipeline.hubspot.create_company.assert_not_called()


def test_build_lead_context_pulls_pain_quotes_for_the_mentioned_competitor():
    """Confirms the context passed to outreach.generate_outreach() actually
    carries the real representative_quotes for the SPECIFIC competitor the
    company's job posting mentioned (ADR-013) - not quotes for some other
    tracked competitor, and not an empty list when real quotes exist."""
    context = pipeline.build_lead_context(COMPANY, SIGNALS, COMPETITOR_INTEL, QUALIFIED_SCORE)

    assert context["current_tool_mentioned"] == "Aha!"
    assert context["competitor_pain_quotes"] == [{"text": "too expensive"}]
    assert context["pm_job_post_count"] == 2  # "Senior PM, PM" -> 2 titles


def test_build_lead_context_handles_no_current_tool_mentioned():
    """A TIMING-only company (no current_tool_mentioned set) must produce an
    empty pain-quotes list, not a KeyError trying to look up None in
    competitor_intel."""
    company = {**COMPANY, "current_tool_mentioned": None}

    context = pipeline.build_lead_context(company, SIGNALS, COMPETITOR_INTEL, QUALIFIED_SCORE)

    assert context["current_tool_mentioned"] is None
    assert context["competitor_pain_quotes"] == []


def test_build_lead_context_pulls_the_three_new_redesign_v2_signal_fields():
    """Redesign v2, Tier 1 - the outreach-copy gap fix: build_lead_context()
    must surface the buying-intent phrase, the new leadership-hire
    name/title, and the product-launch tagline from the signals list, using
    the most-recent row per category (mirrors scoring.py's _latest_signal
    pattern) - not just leave them for scoring and never reach outreach."""
    signals = SIGNALS + [
        {"signal_category": "buying_intent", "raw_text": "evaluate our PM tool stack", "posted_at": "2026-07-01"},
        {"signal_category": "leadership_hire", "raw_text": "Jane Doe (VP Product)", "posted_at": "2026-06-15"},
        {"signal_category": "product_launch", "raw_text": "Roadmaps that write themselves", "posted_at": "2026-06-20"},
    ]

    context = pipeline.build_lead_context(COMPANY, signals, COMPETITOR_INTEL, QUALIFIED_SCORE)

    assert context["buying_intent_phrase"] == "evaluate our PM tool stack"
    assert context["new_leadership_hire"] == "Jane Doe (VP Product)"
    assert context["recent_product_launch"] == "Roadmaps that write themselves"


def test_build_lead_context_new_signal_fields_default_to_none_when_absent():
    """The common case: a company with none of the 3 new signal types must
    produce None for all three fields, not KeyError or an empty string -
    outreach.py's fact-builders already handle None gracefully (omit the
    fact), so this is the correct default."""
    context = pipeline.build_lead_context(COMPANY, SIGNALS, COMPETITOR_INTEL, QUALIFIED_SCORE)

    assert context["buying_intent_phrase"] is None
    assert context["new_leadership_hire"] is None
    assert context["recent_product_launch"] is None
