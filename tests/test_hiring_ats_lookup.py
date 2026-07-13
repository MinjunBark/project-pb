"""Tests for python/hiring_ats_lookup.py. All HTTP calls mocked, but shaped exactly
like the real Greenhouse/Lever responses verified live 2026-07-09 (see docs/ISSUES.md):
Greenhouse 404s cleanly for an unknown board token; Lever 404s with
{"ok": false, "error": "Document not found"} for an unknown client, and returns a
bare JSON array (possibly empty) for a valid one."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import hiring_ats_lookup  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data


GREENHOUSE_JOBS = {
    "jobs": [
        {
            "title": "Senior Product Manager",
            "location": {"name": "Remote, US"},
            "first_published": "2026-06-01T00:00:00-04:00",
            "content": "You'll own our roadmap. Experience with Jira Product Discovery or similar tools preferred.",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
        },
        {
            "title": "Account Executive",
            "location": {"name": "New York, NY"},
            "first_published": "2026-05-01T00:00:00-04:00",
            "content": "Close deals and grow revenue.",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/456",
        },
    ]
}

LEVER_POSTINGS = [
    {
        "text": "Product Operations Manager",
        "categories": {"location": "San Francisco, CA"},
        "descriptionPlain": "We currently run our roadmap in ProductPlan and are looking to level up our process.",
        "hostedUrl": "https://jobs.lever.co/acme/789",
    }
]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(hiring_ats_lookup.time, "sleep", lambda _seconds: None)


def test_generate_candidate_slugs_strips_suffix_and_variants():
    slugs = hiring_ats_lookup.generate_candidate_slugs("Acme Corp")
    assert "acme" in slugs


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Experience with Jira Product Discovery a plus", ["Jira Product Discovery"]),
        ("We use ProductPlan for our roadmap", ["ProductPlan"]),
        ("Currently on Craft.io, evaluating alternatives", ["Craft.io"]),
        ("Migrated off Aha! last year", ["Aha!"]),
        ("We use aha to acknowledge good ideas in standup", []),  # bare "aha" - not a match
        ("Standard PM role, no tools mentioned", []),
        (None, []),
    ],
)
def test_scan_for_competitor_tools(text, expected):
    assert hiring_ats_lookup.scan_for_competitor_tools(text) == expected


def test_try_greenhouse_returns_first_hit(monkeypatch):
    def fake_get(url, timeout=None):
        if "/boards/acme/" in url:
            return FakeResponse(200, GREENHOUSE_JOBS)
        return FakeResponse(404, {})

    monkeypatch.setattr(hiring_ats_lookup.requests, "get", fake_get)

    result = hiring_ats_lookup.try_greenhouse("Acme Corp")

    assert result is not None
    assert result["matched_slug"] == "acme"
    assert len(result["raw_jobs"]) == 2


def test_try_greenhouse_returns_none_when_no_slug_matches(monkeypatch):
    monkeypatch.setattr(
        hiring_ats_lookup.requests, "get", lambda url, timeout=None: FakeResponse(404, {})
    )

    result = hiring_ats_lookup.try_greenhouse("Totally Unknown Company")

    assert result is None


def test_try_lever_distinguishes_404_from_valid_empty_array(monkeypatch):
    def fake_get(url, timeout=None):
        if "/postings/acme" in url:
            return FakeResponse(200, LEVER_POSTINGS)
        return FakeResponse(404, {"ok": False, "error": "Document not found"})

    monkeypatch.setattr(hiring_ats_lookup.requests, "get", fake_get)

    result = hiring_ats_lookup.try_lever("Acme Corp")

    assert result is not None
    assert result["matched_slug"] == "acme"
    assert len(result["raw_postings"]) == 1


def test_try_lever_returns_none_on_404(monkeypatch):
    monkeypatch.setattr(
        hiring_ats_lookup.requests,
        "get",
        lambda url, timeout=None: FakeResponse(404, {"ok": False, "error": "Document not found"}),
    )

    result = hiring_ats_lookup.try_lever("Unknown Co")

    assert result is None


def test_enrich_company_prefers_greenhouse_and_filters_pm_titles(monkeypatch):
    monkeypatch.setattr(
        hiring_ats_lookup,
        "try_greenhouse",
        lambda name: {"matched_slug": "acme", "raw_jobs": GREENHOUSE_JOBS["jobs"]},
    )
    monkeypatch.setattr(hiring_ats_lookup, "try_lever", lambda name: None)
    monkeypatch.setattr(hiring_ats_lookup, "classify_buying_intent", lambda text: None)

    result = hiring_ats_lookup.enrich_company_with_ats_data("Acme Corp")

    assert result["source"] == "greenhouse"
    assert len(result["pm_postings"]) == 1
    assert result["pm_postings"][0]["title"] == "Senior Product Manager"
    assert result["current_tools_mentioned"] == ["Jira Product Discovery"]


def test_enrich_company_falls_back_to_lever_when_greenhouse_misses(monkeypatch):
    monkeypatch.setattr(hiring_ats_lookup, "try_greenhouse", lambda name: None)
    monkeypatch.setattr(
        hiring_ats_lookup,
        "try_lever",
        lambda name: {"matched_slug": "acme", "raw_postings": LEVER_POSTINGS},
    )
    monkeypatch.setattr(hiring_ats_lookup, "classify_buying_intent", lambda text: None)

    result = hiring_ats_lookup.enrich_company_with_ats_data("Acme Corp")

    assert result["source"] == "lever"
    assert len(result["pm_postings"]) == 1
    assert result["current_tools_mentioned"] == ["ProductPlan"]


def test_enrich_company_returns_none_source_when_neither_resolves(monkeypatch):
    monkeypatch.setattr(hiring_ats_lookup, "try_greenhouse", lambda name: None)
    monkeypatch.setattr(hiring_ats_lookup, "try_lever", lambda name: None)

    result = hiring_ats_lookup.enrich_company_with_ats_data("Ghost Company")

    assert result["source"] is None
    assert result["pm_postings"] == []
    assert result["current_tools_mentioned"] == []
    assert result["buying_intent"] is None


# ---------------------------------------------------------------------------
# Buying-intent language mining (redesign v2, Tier 1)
# ---------------------------------------------------------------------------


def test_classify_buying_intent_returns_none_for_blank_text_without_calling_gemini(monkeypatch):
    """Cost guard, mirrors classify.py's identical pattern: never spend an
    API call on text that's obviously empty."""
    mock_generate = MagicMock()
    monkeypatch.setattr(hiring_ats_lookup, "generate_content", mock_generate)

    assert hiring_ats_lookup.classify_buying_intent(None) is None
    assert hiring_ats_lookup.classify_buying_intent("   ") is None
    mock_generate.assert_not_called()


def test_classify_buying_intent_parses_clean_json_response(monkeypatch):
    monkeypatch.setattr(
        hiring_ats_lookup,
        "generate_content",
        lambda prompt: '{"buying_intent_detected": true, "matched_phrase": "evaluate and select our PM tool stack"}',
    )

    result = hiring_ats_lookup.classify_buying_intent("We will evaluate and select our PM tool stack this quarter.")

    assert result == {"buying_intent_detected": True, "matched_phrase": "evaluate and select our PM tool stack"}


def test_classify_buying_intent_returns_none_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(hiring_ats_lookup, "generate_content", lambda prompt: "not json at all")

    result = hiring_ats_lookup.classify_buying_intent("Standard PM posting, nothing special.")

    assert result is None


def test_enrich_company_classifies_only_the_most_recent_pm_posting(monkeypatch):
    """Cost-control design decision (confirmed with the user): the buying-
    intent classifier should run ONCE per company, on the most recently
    posted PM posting with real description text - not once per posting.
    Confirms both the call count AND that the correct (most recent) posting
    text was the one actually sent."""
    two_pm_postings = {
        "jobs": [
            {
                "title": "Product Manager",
                "location": {"name": "Remote"},
                "first_published": "2026-05-01T00:00:00-04:00",
                "content": "Older posting, no signal here.",
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
            },
            {
                "title": "Senior Product Manager",
                "location": {"name": "Remote"},
                "first_published": "2026-06-15T00:00:00-04:00",
                "content": "We will evaluate and select our PM tool stack this quarter.",
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
            },
        ]
    }
    monkeypatch.setattr(
        hiring_ats_lookup,
        "try_greenhouse",
        lambda name: {"matched_slug": "acme", "raw_jobs": two_pm_postings["jobs"]},
    )
    monkeypatch.setattr(hiring_ats_lookup, "try_lever", lambda name: None)

    mock_classify = MagicMock(return_value={"buying_intent_detected": True, "matched_phrase": "evaluate and select our PM tool stack"})
    monkeypatch.setattr(hiring_ats_lookup, "classify_buying_intent", mock_classify)

    result = hiring_ats_lookup.enrich_company_with_ats_data("Acme Corp")

    mock_classify.assert_called_once()
    called_text = mock_classify.call_args[0][0]
    assert "evaluate and select our PM tool stack" in called_text
    assert result["buying_intent"] == {"buying_intent_detected": True, "matched_phrase": "evaluate and select our PM tool stack"}


def test_enrich_company_buying_intent_is_none_when_no_pm_posting_has_description(monkeypatch):
    """Edge case: PM postings exist but none have description text (e.g. a
    Lever posting with a null descriptionPlain) - must not call the
    classifier with empty/None text, and buying_intent should be None."""
    monkeypatch.setattr(
        hiring_ats_lookup,
        "try_greenhouse",
        lambda name: {
            "matched_slug": "acme",
            "raw_jobs": [
                {
                    "title": "Product Manager",
                    "location": {"name": "Remote"},
                    "first_published": "2026-06-01T00:00:00-04:00",
                    "content": None,
                    "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
                }
            ],
        },
    )
    monkeypatch.setattr(hiring_ats_lookup, "try_lever", lambda name: None)
    mock_classify = MagicMock()
    monkeypatch.setattr(hiring_ats_lookup, "classify_buying_intent", mock_classify)

    result = hiring_ats_lookup.enrich_company_with_ats_data("Acme Corp")

    mock_classify.assert_not_called()
    assert result["buying_intent"] is None
