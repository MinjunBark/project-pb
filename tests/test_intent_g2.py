"""Tests for python/intent_g2.py. Per ADR-009, Claude does not run live Apify
calls - all HTTP calls mocked here, shaped against automation-lab/g2-scraper's
documented output fields."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import intent_g2  # noqa: E402


class FakeResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def json(self):
        return self._json_data

    def raise_for_status(self):
        pass


NEGATIVE_SWITCH_REVIEW = {
    "reviewId": "r1",
    "title": "Clunky and slow to set up",
    "reviewText": "We switched from a competing tool because the roadmap views took forever to load and the admin overhead was too high for our small team.",
    "starRating": 2,
    "nps": 3,
    "publishedAt": "2026-06-01",
    "loveTheme": None,
    "hateTheme": "Performance",
    "switchedFromOtherProduct": "yes",  # real values are "yes"/"no"/"unknown", never a product name
    "switchedReason": "Slow performance and high admin overhead",
    "country": "US",
    "companySegment": 2,
    "industry": 14,
    "url": "https://www.g2.com/products/aha/reviews/r1",
}

POSITIVE_REVIEW = {
    "reviewId": "r2",
    "title": "Great tool",
    "reviewText": "Does everything we need.",
    "starRating": 5,
    "nps": 9,
    "publishedAt": "2026-06-10",
    "loveTheme": "Ease of use",
    "hateTheme": None,
    "switchedFromOtherProduct": None,
    "switchedReason": None,
    "country": "CA",
    "companySegment": 1,
    "industry": 7,
    "url": "https://www.g2.com/products/aha/reviews/r2",
}

# Regression fixture for the real bug found 2026-07-10: "no" and "unknown" are
# non-empty strings, so a naive `bool(switchedFromOtherProduct)` check was
# incorrectly flagging these as switch signals too.
NO_SWITCH_REVIEW = {
    "reviewId": "r3",
    "title": "Solid, no complaints",
    "reviewText": "Been using it from day one, works fine.",
    "starRating": 4,
    "nps": 8,
    "publishedAt": "2026-06-05",
    "loveTheme": None,
    "hateTheme": None,
    "switchedFromOtherProduct": "no",
    "switchedReason": None,
    "country": "US",
    "companySegment": 1,
    "industry": 7,
    "url": "https://www.g2.com/products/aha/reviews/r3",
}


@pytest.fixture(autouse=True)
def apify_token(monkeypatch):
    monkeypatch.setenv("APIFY_API_TOKEN", "test-token")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(intent_g2.time, "sleep", lambda _seconds: None)


def test_run_g2_review_scraper_requires_token(monkeypatch):
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        intent_g2.run_g2_review_scraper("aha")


def test_build_product_review_url():
    assert intent_g2.build_product_review_url("aha") == "https://www.g2.com/products/aha/reviews"


def test_run_g2_review_scraper_calls_correct_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, params=None, json=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        return FakeResponse(json_data=[NEGATIVE_SWITCH_REVIEW])

    monkeypatch.setattr(intent_g2.requests, "post", fake_post)

    result = intent_g2.run_g2_review_scraper("aha", max_reviews=50)

    assert intent_g2.ACTOR_ID in captured["url"]
    assert captured["params"]["token"] == "test-token"
    assert captured["json"]["productUrls"] == ["https://www.g2.com/products/aha/reviews"]
    assert captured["json"]["maxReviews"] == 50
    assert result == [NEGATIVE_SWITCH_REVIEW]


def test_normalize_flags_negative_and_switch_signals():
    normalized = intent_g2.normalize_g2_reviews(
        [NEGATIVE_SWITCH_REVIEW, POSITIVE_REVIEW], competitor_name="Aha!"
    )

    negative = next(r for r in normalized if r["review_id"] == "r1")
    assert negative["is_negative"] is True
    assert negative["is_switch_signal"] is True
    assert negative["switched_from_other_product"] is True
    assert negative["competitor"] == "Aha!"
    assert negative["switch_reason"] == "Slow performance and high admin overhead"

    positive = next(r for r in normalized if r["review_id"] == "r2")
    assert positive["is_negative"] is False
    assert positive["is_switch_signal"] is False
    assert positive["switched_from_other_product"] is False


def test_normalize_does_not_flag_no_or_unknown_as_switch_signal():
    """Regression test for the real bug found 2026-07-10 (docs/ISSUES.md):
    switchedFromOtherProduct == "no" is a non-empty string, so a naive
    bool() check incorrectly treated it as a switch signal."""
    normalized = intent_g2.normalize_g2_reviews([NO_SWITCH_REVIEW], competitor_name="Aha!")

    review = normalized[0]
    assert review["is_switch_signal"] is False
    assert review["switched_from_other_product"] is False


def test_build_pain_point_corpus_aggregates_per_competitor():
    normalized = intent_g2.normalize_g2_reviews(
        [NEGATIVE_SWITCH_REVIEW, POSITIVE_REVIEW], competitor_name="Aha!"
    )

    corpus = intent_g2.build_pain_point_corpus(normalized)

    aha_entry = corpus["Aha!"]
    assert aha_entry["total_reviews_seen"] == 2
    assert aha_entry["negative_review_count"] == 1
    assert aha_entry["switch_signal_count"] == 1
    assert len(aha_entry["representative_quotes"]) == 1
    assert "switched from a competing tool" in aha_entry["representative_quotes"][0]["text"]


def test_get_intent_signals_orchestrates_all_competitors(monkeypatch):
    calls = []

    def fake_scraper(slug, max_reviews=100):
        calls.append(slug)
        return [NEGATIVE_SWITCH_REVIEW] if slug == "aha" else [POSITIVE_REVIEW]

    monkeypatch.setattr(intent_g2, "run_g2_review_scraper", fake_scraper)

    result = intent_g2.get_intent_signals(
        competitors={"Aha!": "aha", "ProductPlan": "productplan"}
    )

    assert set(calls) == {"aha", "productplan"}
    assert len(result["reviews"]) == 2
    assert "Aha!" in result["pain_point_corpus"]
    assert "ProductPlan" in result["pain_point_corpus"]
    assert result["pain_point_corpus"]["Aha!"]["negative_review_count"] == 1
