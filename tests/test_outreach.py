"""Tests for python/outreach.py - Phase 8's signal-specific outreach
generation. generate_content() (the actual network call) is mocked
throughout - see docs/PROGRESS.md for the real live test run."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import outreach  # noqa: E402

TIMING_LEAD = {
    "company_name": "Acme Corp",
    "signal_type": "TIMING",
    "icp_score": 55,
    "funding_stage": "Series B",
    "funding_date": "2026-06-10",
    "pm_job_post_count": 2,
}

INTENT_LEAD = {
    "company_name": "Beta Inc",
    "signal_type": "INTENT",
    "icp_score": 40,
    "current_tool_mentioned": "Aha!",
    "competitor_pain_quotes": [{"text": "too expensive for what it does"}],
}

BOTH_LEAD = {
    **TIMING_LEAD,
    "signal_type": "BOTH",
    "current_tool_mentioned": "Aha!",
    "competitor_pain_quotes": [{"text": "too expensive for what it does"}],
}

FULL_RESPONSE = {
    "priority_summary": "Funded and hiring - strike now.",
    "email_subject_a": "Scaling your product team?",
    "email_subject_b": "A question about your PM roadmap",
    "email_body": "Hi there...",
    "linkedin_message": "Saw your Series B...",
    "call_script": "1. Congrats on the raise. 2. ...",
}


def test_build_outreach_prompt_raises_for_invalid_signal_type():
    """A lead reaching Phase 8 should always have a real signal_type
    (TIMING/INTENT/BOTH) - it already passed scoring.py's >=70 threshold and
    Phase 7's dedupe check. A 'NONE' or missing signal_type here means an
    upstream bug let an unqualified lead through; this must fail loudly
    rather than silently generate a generic, angle-less prompt."""
    with pytest.raises(ValueError, match="TIMING/INTENT/BOTH"):
        outreach.build_outreach_prompt({"company_name": "X", "signal_type": "NONE"})


def test_build_outreach_prompt_timing_references_funding_and_hiring():
    """Confirms the TIMING angle actually pulls in the real funding stage,
    date, and PM posting count - not a generic template - since that
    specificity is the entire point of signal-specific outreach per the
    blueprint."""
    prompt = outreach.build_outreach_prompt(TIMING_LEAD)

    assert "Series B" in prompt
    assert "2026-06-10" in prompt
    assert "2 open PM postings" in prompt


def test_build_outreach_prompt_intent_includes_real_pain_quotes():
    """Confirms the INTENT angle actually embeds the real G2 pain-point
    quote text (from competitor_intel via scoring.py's INTENT bucket), not
    just the competitor's name - the whole value of Branch C's corpus is
    using real customer language, not generic 'you might be unhappy' copy."""
    prompt = outreach.build_outreach_prompt(INTENT_LEAD)

    assert "Aha!" in prompt
    assert "too expensive for what it does" in prompt


def test_build_outreach_prompt_intent_handles_no_pain_quotes_gracefully():
    """A tool was identified but competitor_intel has no quotes for it yet
    (e.g. G2 scrape hasn't run for that competitor, matching scoring.py's
    'weak base points' case) - must not crash formatting an empty list, and
    should produce a clearly-marked placeholder instead of blank text."""
    lead = {**INTENT_LEAD, "competitor_pain_quotes": []}

    prompt = outreach.build_outreach_prompt(lead)

    assert "no specific quotes available" in prompt


def test_build_outreach_prompt_both_combines_timing_and_intent_facts():
    """The highest-priority signal type should reference BOTH the funding/
    hiring facts AND the competitor pain quotes in one prompt - proves the
    combined angle isn't just picking one signal and ignoring the other."""
    prompt = outreach.build_outreach_prompt(BOTH_LEAD)

    assert "Series B" in prompt
    assert "Aha!" in prompt
    assert "too expensive for what it does" in prompt


def test_build_outreach_prompt_timing_includes_leadership_hire_and_launch_when_present():
    """Redesign v2, Tier 1: the outreach-copy gap fix - a TIMING lead whose
    context includes a new leadership hire and/or a recent product launch
    must have those specific facts appear in the prompt, not just the
    original funding/hiring facts."""
    lead = {
        **TIMING_LEAD,
        "new_leadership_hire": "Jane Doe (VP Product)",
        "recent_product_launch": "Roadmaps that write themselves",
    }

    prompt = outreach.build_outreach_prompt(lead)

    assert "Jane Doe (VP Product)" in prompt
    assert "Roadmaps that write themselves" in prompt


def test_build_outreach_prompt_timing_with_only_leadership_hire_has_no_none_literals():
    """A lead can now score TIMING purely from a leadership hire or product
    launch, with no funding/hiring data at all - the prompt must not
    contain literal 'None' text where funding_stage/pm_job_post_count would
    have been, since scoring.score_timing() no longer requires those two
    original signals to produce a TIMING signal_type."""
    lead = {
        "company_name": "Acme Corp",
        "signal_type": "TIMING",
        "icp_score": 15,
        "new_leadership_hire": "Jane Doe (VP Product)",
    }

    prompt = outreach.build_outreach_prompt(lead)

    assert "None" not in prompt
    assert "Jane Doe (VP Product)" in prompt


def test_build_outreach_prompt_intent_includes_buying_intent_phrase():
    """Redesign v2, Tier 1: an INTENT lead whose context includes a
    buying-intent phrase (from a job posting, not a named competitor tool)
    must reference that specific phrase in the prompt."""
    lead = {
        **INTENT_LEAD,
        "buying_intent_phrase": "evaluate and select our PM tool stack",
    }

    prompt = outreach.build_outreach_prompt(lead)

    assert "evaluate and select our PM tool stack" in prompt


def test_build_outreach_prompt_intent_with_only_buying_intent_omits_pain_quotes_block():
    """A lead can now score INTENT purely from buying-intent language, with
    no current_tool_mentioned at all (scoring.score_intent() awards INTENT
    points for either path independently). With no competitor identified,
    there's nothing to quote pain-point reviews against - the prompt must
    reference the buying-intent phrase but not render a misleading 'Real
    customer reviews of None' block."""
    lead = {
        "company_name": "Acme Corp",
        "signal_type": "INTENT",
        "icp_score": 10,
        "buying_intent_phrase": "no formalized product ops function yet",
    }

    prompt = outreach.build_outreach_prompt(lead)

    assert "no formalized product ops function yet" in prompt
    assert "Real customer reviews of" not in prompt
    assert "None" not in prompt


def test_build_outreach_prompt_both_includes_all_new_signal_facts_together():
    """The BOTH angle should surface every applicable fact at once - the
    original funding/hiring/tool/pain-quotes AND the 3 new signal types,
    when all happen to be present on the same lead."""
    lead = {
        **BOTH_LEAD,
        "buying_intent_phrase": "evaluate our PM tool stack",
        "new_leadership_hire": "Jane Doe (VP Product)",
        "recent_product_launch": "Roadmaps that write themselves",
    }

    prompt = outreach.build_outreach_prompt(lead)

    assert "Series B" in prompt
    assert "Aha!" in prompt
    assert "too expensive for what it does" in prompt
    assert "evaluate our PM tool stack" in prompt
    assert "Jane Doe (VP Product)" in prompt
    assert "Roadmaps that write themselves" in prompt


def test_generate_outreach_returns_all_expected_fields(monkeypatch):
    """The happy path: a clean, complete JSON response from Gemini should
    produce a dict with exactly the 6 expected fields (the blueprint's 4 plus
    the new priority_summary), pulled correctly by name."""
    monkeypatch.setattr(outreach, "generate_content", lambda prompt: json.dumps(FULL_RESPONSE))

    result = outreach.generate_outreach(TIMING_LEAD)

    assert result == FULL_RESPONSE


def test_generate_outreach_handles_markdown_fenced_response(monkeypatch):
    """Same real-world LLM quirk classify.py already had to handle - Gemini
    wrapping JSON in ```json fences despite instructions not to. Uses the
    shared gemini.parse_json_response() now (moved out of classify.py once
    this module needed the identical behavior)."""
    fenced = "```json\n" + json.dumps(FULL_RESPONSE) + "\n```"
    monkeypatch.setattr(outreach, "generate_content", lambda prompt: fenced)

    result = outreach.generate_outreach(TIMING_LEAD)

    assert result == FULL_RESPONSE


def test_generate_outreach_raises_on_unparseable_response(monkeypatch):
    """Unlike classify.py's best-effort extraction (where a bad response
    just means 'no company found', a safe no-op), outreach copy is
    customer-facing content - a bad response here must fail loudly, not
    silently produce blank/broken outreach that could actually get sent."""
    monkeypatch.setattr(outreach, "generate_content", lambda prompt: "I cannot help with that.")

    with pytest.raises(RuntimeError, match="unparseable"):
        outreach.generate_outreach(TIMING_LEAD)


def test_generate_outreach_raises_when_response_missing_fields(monkeypatch):
    """Gemini could return syntactically valid JSON that's still incomplete
    (e.g. it skipped call_script). Must be caught explicitly and named in
    the error, not silently produce a lead record with a missing outreach
    field that only surfaces as a confusing KeyError three phases later."""
    incomplete = {k: v for k, v in FULL_RESPONSE.items() if k != "call_script"}
    monkeypatch.setattr(outreach, "generate_content", lambda prompt: json.dumps(incomplete))

    with pytest.raises(RuntimeError, match="call_script"):
        outreach.generate_outreach(TIMING_LEAD)
