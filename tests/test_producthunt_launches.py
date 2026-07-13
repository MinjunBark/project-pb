"""Tests for python/producthunt_launches.py - redesign v2, Tier 1's Branch D
(Product Hunt launch monitoring). All HTTP calls mocked - no live Product
Hunt calls, matching this project's pattern for paid/rate-limited/uncertain-
match-rate sources (see docs/DECISIONS.md ADR-009)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import producthunt_launches  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


GRAPHQL_RESPONSE = {
    "data": {
        "posts": {
            "edges": [
                {
                    "node": {
                        "id": "1",
                        "name": "Acme AI",
                        "tagline": "Roadmaps that write themselves",
                        "url": "https://www.producthunt.com/posts/acme-ai",
                        "createdAt": "2026-07-01T00:00:00Z",
                    }
                },
                {
                    "node": {
                        "id": "2",
                        "name": "Beta Sync",
                        "tagline": "Sync everything",
                        "url": "https://www.producthunt.com/posts/beta-sync",
                        "createdAt": "2026-07-02T00:00:00Z",
                    }
                },
            ]
        }
    }
}


def test_headers_raises_when_token_unset(monkeypatch):
    monkeypatch.delenv("PRODUCT_HUNT_API_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="PRODUCT_HUNT_API_TOKEN"):
        producthunt_launches._headers()


def test_headers_returns_bearer_token_when_set(monkeypatch):
    monkeypatch.setenv("PRODUCT_HUNT_API_TOKEN", "test-token-123")

    headers = producthunt_launches._headers()

    assert headers["Authorization"] == "Bearer test-token-123"


def test_search_recent_launches_normalizes_graphql_response(monkeypatch):
    monkeypatch.setenv("PRODUCT_HUNT_API_TOKEN", "test-token-123")
    monkeypatch.setattr(
        producthunt_launches.requests, "post", lambda url, headers=None, json=None, timeout=None: FakeResponse(200, GRAPHQL_RESPONSE)
    )

    results = producthunt_launches.search_recent_launches(lookback_days=30)

    assert len(results) == 2
    assert results[0] == {
        "product_name": "Acme AI",
        "tagline": "Roadmaps that write themselves",
        "launched_at": "2026-07-01T00:00:00Z",
        "url": "https://www.producthunt.com/posts/acme-ai",
    }


def test_search_recent_launches_handles_empty_edges(monkeypatch):
    monkeypatch.setenv("PRODUCT_HUNT_API_TOKEN", "test-token-123")
    empty_response = {"data": {"posts": {"edges": []}}}
    monkeypatch.setattr(
        producthunt_launches.requests, "post", lambda url, headers=None, json=None, timeout=None: FakeResponse(200, empty_response)
    )

    results = producthunt_launches.search_recent_launches(lookback_days=30)

    assert results == []


def test_get_launch_signals_shapes_output_for_signals_pipeline(monkeypatch):
    monkeypatch.setenv("PRODUCT_HUNT_API_TOKEN", "test-token-123")
    monkeypatch.setattr(
        producthunt_launches,
        "search_recent_launches",
        lambda lookback_days=30, first=50: [
            {"product_name": "Acme AI", "tagline": "Roadmaps that write themselves", "launched_at": "2026-07-01T00:00:00Z", "url": "https://x.com"}
        ],
    )

    signals = producthunt_launches.get_launch_signals(lookback_days=30)

    assert signals == [
        {
            "company_name": "Acme AI",
            "product_name": "Acme AI",
            "tagline": "Roadmaps that write themselves",
            "launched_at": "2026-07-01T00:00:00Z",
            "url": "https://x.com",
            "source": "producthunt",
        }
    ]
