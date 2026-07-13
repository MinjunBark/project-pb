"""Tests for python/classify.py - Gemini-based G2 review company attribution.
generate_content() (the actual network call) is mocked throughout."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import classify  # noqa: E402


def test_extract_reviewer_company_returns_none_for_empty_text_without_calling_gemini(monkeypatch):
    """Cost/correctness guard: most G2 reviews have no text at all in some
    fields, or blank strings. Must short-circuit before spending an API call
    on text that obviously can't name a company - confirmed by asserting
    generate_content is never invoked."""
    mock_generate = MagicMock()
    monkeypatch.setattr(classify, "generate_content", mock_generate)

    assert classify.extract_reviewer_company(None) is None
    assert classify.extract_reviewer_company("   ") is None
    mock_generate.assert_not_called()


def test_extract_reviewer_company_parses_clean_json_response(monkeypatch):
    """The happy path: Gemini follows instructions and returns bare JSON -
    confirms the field name (company_name) is read correctly."""
    monkeypatch.setattr(classify, "generate_content", lambda prompt: '{"company_name": "Acme Corp"}')

    result = classify.extract_reviewer_company("We use this at Acme Corp and love it.")

    assert result == "Acme Corp"


def test_extract_reviewer_company_strips_markdown_code_fences(monkeypatch):
    """Real-world LLM quirk: despite being told to return ONLY JSON, models
    frequently wrap output in ```json ... ``` fences anyway. This must not
    break parsing - a regression here would silently turn every response
    into a failed extraction (None), even when Gemini answered correctly."""
    fenced_response = '```json\n{"company_name": "Beta Inc"}\n```'
    monkeypatch.setattr(classify, "generate_content", lambda prompt: fenced_response)

    result = classify.extract_reviewer_company("Our team at Beta Inc evaluated this tool.")

    assert result == "Beta Inc"


def test_extract_reviewer_company_returns_none_when_no_company_named():
    """The overwhelmingly common case per ADR-012 (G2 reviews are anonymous
    by design) - explicit null in the JSON must map to Python None, not the
    string 'null' or an error."""
    # exercised via _parse_json_response directly since it's the pure part of the flow
    parsed = classify._parse_json_response('{"company_name": null}')

    assert parsed["company_name"] is None


def test_extract_reviewer_company_returns_none_on_unparseable_response(monkeypatch):
    """If Gemini returns something that isn't valid JSON at all (rare, but
    possible with any LLM), this must degrade to 'no attribution found'
    rather than crash and take down classification of the rest of the batch."""
    monkeypatch.setattr(classify, "generate_content", lambda prompt: "I cannot determine the company.")

    result = classify.extract_reviewer_company("Some review text with no company mentioned.")

    assert result is None


def test_classify_reviews_for_company_attribution_adds_field_without_mutating_originals(monkeypatch):
    """Batch-processing check: confirms every review in the input list gets
    an `attributed_company` key added (even when None), and that the
    original review dicts aren't mutated in place - callers may still hold
    a reference to the original list elsewhere in the pipeline."""
    monkeypatch.setattr(
        classify, "extract_reviewer_company", lambda text: "Acme Corp" if text == "mentions acme" else None
    )
    reviews = [
        {"review_id": "1", "text": "mentions acme", "star_rating": 2},
        {"review_id": "2", "text": "no company here", "star_rating": 5},
    ]

    results = classify.classify_reviews_for_company_attribution(reviews)

    assert results[0]["attributed_company"] == "Acme Corp"
    assert results[1]["attributed_company"] is None
    assert "attributed_company" not in reviews[0]  # originals untouched
