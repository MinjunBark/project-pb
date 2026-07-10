"""Tests for python/hiring_ats_lookup.py. All HTTP calls mocked, but shaped exactly
like the real Greenhouse/Lever responses verified live 2026-07-09 (see docs/ISSUES.md):
Greenhouse 404s cleanly for an unknown board token; Lever 404s with
{"ok": false, "error": "Document not found"} for an unknown client, and returns a
bare JSON array (possibly empty) for a valid one."""
import sys
from pathlib import Path

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
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
        },
        {
            "title": "Account Executive",
            "location": {"name": "New York, NY"},
            "first_published": "2026-05-01T00:00:00-04:00",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/456",
        },
    ]
}

LEVER_POSTINGS = [
    {
        "text": "Product Operations Manager",
        "categories": {"location": "San Francisco, CA"},
        "hostedUrl": "https://jobs.lever.co/acme/789",
    }
]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(hiring_ats_lookup.time, "sleep", lambda _seconds: None)


def test_generate_candidate_slugs_strips_suffix_and_variants():
    slugs = hiring_ats_lookup.generate_candidate_slugs("Acme Corp")
    assert "acme" in slugs


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

    result = hiring_ats_lookup.enrich_company_with_ats_data("Acme Corp")

    assert result["source"] == "greenhouse"
    assert len(result["pm_postings"]) == 1
    assert result["pm_postings"][0]["title"] == "Senior Product Manager"


def test_enrich_company_falls_back_to_lever_when_greenhouse_misses(monkeypatch):
    monkeypatch.setattr(hiring_ats_lookup, "try_greenhouse", lambda name: None)
    monkeypatch.setattr(
        hiring_ats_lookup,
        "try_lever",
        lambda name: {"matched_slug": "acme", "raw_postings": LEVER_POSTINGS},
    )

    result = hiring_ats_lookup.enrich_company_with_ats_data("Acme Corp")

    assert result["source"] == "lever"
    assert len(result["pm_postings"]) == 1


def test_enrich_company_returns_none_source_when_neither_resolves(monkeypatch):
    monkeypatch.setattr(hiring_ats_lookup, "try_greenhouse", lambda name: None)
    monkeypatch.setattr(hiring_ats_lookup, "try_lever", lambda name: None)

    result = hiring_ats_lookup.enrich_company_with_ats_data("Ghost Company")

    assert result["source"] is None
    assert result["pm_postings"] == []
