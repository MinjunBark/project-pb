"""Tests for python/hiring_signals.py - the Layer 1 + Layer 2 orchestrator."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import hiring_signals  # noqa: E402


ADZUNA_CANDIDATE = {
    "company_name": "Acme Corp",
    "job_titles": ["Product Manager"],
    "pm_job_post_count": 1,
    "most_recent_posting_date": "2026-05-20T00:00:00Z",
    "location": "New York, NY",
    "source": "adzuna",
}


def test_prefers_ats_data_when_layer_2_resolves(monkeypatch):
    monkeypatch.setattr(
        hiring_signals, "get_adzuna_hiring_signals", lambda keywords=None, lookback_days=60: [ADZUNA_CANDIDATE]
    )
    monkeypatch.setattr(
        hiring_signals,
        "enrich_company_with_ats_data",
        lambda name: {
            "source": "greenhouse",
            "matched_slug": "acme",
            "pm_postings": [
                {"title": "Senior Product Manager", "posted_date": "2026-06-01T00:00:00-04:00", "location": None, "url": None},
                {"title": "Product Operations Lead", "posted_date": "2026-06-15T00:00:00-04:00", "location": None, "url": None},
            ],
        },
    )

    signals = hiring_signals.get_hiring_signals()

    assert len(signals) == 1
    signal = signals[0]
    assert signal["source"] == "greenhouse"
    assert signal["ats_matched_slug"] == "acme"
    assert signal["pm_job_post_count"] == 2
    assert signal["most_recent_posting_date"] == "2026-06-15T00:00:00-04:00"
    assert signal["domain"] is None


def test_falls_back_to_adzuna_when_layer_2_does_not_resolve(monkeypatch):
    monkeypatch.setattr(
        hiring_signals, "get_adzuna_hiring_signals", lambda keywords=None, lookback_days=60: [ADZUNA_CANDIDATE]
    )
    monkeypatch.setattr(
        hiring_signals,
        "enrich_company_with_ats_data",
        lambda name: {"source": None, "matched_slug": None, "pm_postings": []},
    )

    signals = hiring_signals.get_hiring_signals()

    assert len(signals) == 1
    signal = signals[0]
    assert signal["source"] == "adzuna"
    assert signal["ats_matched_slug"] is None
    assert signal["pm_job_post_count"] == 1
    assert signal["most_recent_posting_date"] == "2026-05-20T00:00:00Z"
