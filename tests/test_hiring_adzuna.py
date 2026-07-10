"""Tests for python/hiring_adzuna.py. All HTTP calls mocked - no live Adzuna calls
(requires a real app_id/app_key the user hasn't signed up for yet)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import hiring_adzuna  # noqa: E402


class FakeResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def json(self):
        return self._json_data

    def raise_for_status(self):
        pass


JOB_ACME_1 = {
    "title": "Senior Product Manager",
    "company": {"display_name": "Acme Corp"},
    "location": {"display_name": "New York, NY"},
    "created": "2026-06-01T00:00:00Z",
}

JOB_ACME_2 = {
    "title": "Product Operations Lead",
    "company": {"display_name": "Acme Corp"},
    "location": {"display_name": "New York, NY"},
    "created": "2026-06-15T00:00:00Z",
}

JOB_OTHERCO = {
    "title": "Product Manager",
    "company": {"display_name": "OtherCo"},
    "location": {"display_name": "Austin, TX"},
    "created": "2026-05-20T00:00:00Z",
}


@pytest.fixture(autouse=True)
def adzuna_credentials(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(hiring_adzuna.time, "sleep", lambda _seconds: None)


def test_search_requires_credentials(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    with pytest.raises(RuntimeError):
        hiring_adzuna.search_adzuna_jobs("Product Manager")


def test_search_calls_correct_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse(json_data={"results": [JOB_ACME_1]})

    monkeypatch.setattr(hiring_adzuna.requests, "get", fake_get)

    results = hiring_adzuna.search_adzuna_jobs("Product Manager", max_days_old=60)

    assert "api.adzuna.com/v1/api/jobs/us/search/1" in captured["url"]
    assert captured["params"]["what"] == "Product Manager"
    assert captured["params"]["max_days_old"] == 60
    assert results == [JOB_ACME_1]


def test_normalize_groups_by_company_and_counts():
    results = hiring_adzuna.normalize_adzuna_results([JOB_ACME_1, JOB_ACME_2, JOB_OTHERCO])

    assert len(results) == 2
    acme = next(r for r in results if r["company_name"] == "Acme Corp")
    assert acme["pm_job_post_count"] == 2
    assert set(acme["job_titles"]) == {"Senior Product Manager", "Product Operations Lead"}
    assert acme["most_recent_posting_date"] == "2026-06-15T00:00:00Z"

    otherco = next(r for r in results if r["company_name"] == "OtherCo")
    assert otherco["pm_job_post_count"] == 1


def test_get_adzuna_hiring_signals_orchestrates_multiple_keywords(monkeypatch):
    calls = []

    def fake_search(keyword, max_days_old=60):
        calls.append(keyword)
        return [JOB_ACME_1] if keyword == "Product Manager" else [JOB_OTHERCO]

    monkeypatch.setattr(hiring_adzuna, "search_adzuna_jobs", fake_search)

    signals = hiring_adzuna.get_adzuna_hiring_signals(
        keywords=["Product Manager", "Product Operations"], lookback_days=60
    )

    assert calls == ["Product Manager", "Product Operations"]
    company_names = {s["company_name"] for s in signals}
    assert company_names == {"Acme Corp", "OtherCo"}
