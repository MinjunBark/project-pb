"""Tests for api/main.py - the FastAPI wrapper around scoring.py.

These tests only check that the HTTP layer correctly passes data through to
score_company() and shapes the response - the scoring logic itself is
already covered exhaustively in test_scoring.py, so it isn't re-tested here.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import main  # noqa: E402
import pipeline  # noqa: E402

client = TestClient(main.app)


def test_health_endpoint_confirms_the_service_is_up():
    """A trivial liveness check - useful for n8n (or a human) to confirm the
    locally-run uvicorn service is actually reachable before wiring a real
    HTTP node against it in Phase 9."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_score_endpoint_returns_qualified_lead_for_both_signal_company():
    """End-to-end HTTP check using the same 'hot lead' shape from
    test_scoring.py's integration test - confirms the request/response JSON
    shapes round-trip correctly through Pydantic, not just that the
    underlying Python function works when called directly."""
    payload = {
        "company": {
            "funding_stage": "Series B",
            "funding_date": "2026-06-10",
            "current_tool_mentioned": "Aha!",
        },
        "signals": [
            {
                "signal_category": "pm_hiring",
                "raw_text": "Senior Product Manager, Product Manager",
                "posted_at": "2026-06-30",
            }
        ],
        "competitor_intel": {"Aha!": {"switch_signal_count": 13, "total_reviews_seen": 60}},
    }

    response = client.post("/score", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["signal_type"] == "BOTH"
    assert body["qualified"] is True
    assert body["score_breakdown"]["both_signal_bonus"] == 10


def test_score_endpoint_defaults_signals_and_competitor_intel_to_empty():
    """A minimal request with only `company` and no signals/competitor_intel
    at all must not error - these fields are genuinely optional (a brand new
    company with no signal history yet), and Pydantic's defaults should
    cover that instead of requiring callers to always send empty lists/dicts."""
    response = client.post("/score", json={"company": {}})

    assert response.status_code == 200
    body = response.json()
    assert body["signal_type"] == "NONE"
    assert body["qualified"] is False


def test_branch_a_run_lands_signals_and_returns_count(monkeypatch):
    """Confirms this endpoint is a thin wrapper: calls the real
    funding_edgar function, lands the result via raw_landing (so a repeat
    /merge/run picks it up), and reports back count + path - no scoring or
    filtering logic duplicated here."""
    monkeypatch.setattr(main.funding_edgar, "get_funding_signals", MagicMock(return_value=[{"company_name": "Acme"}]))
    monkeypatch.setattr(main.raw_landing, "save_raw_signals", MagicMock(return_value="data/raw/branch_a_x.json"))

    response = client.post("/branch-a/run", json={})

    assert response.status_code == 200
    assert response.json() == {"count": 1, "landed_path": "data/raw/branch_a_x.json"}
    main.raw_landing.save_raw_signals.assert_called_once_with("branch_a", [{"company_name": "Acme"}])


def test_branch_b_run_passes_through_custom_lookback(monkeypatch):
    """A caller (n8n) should be able to override the default lookback -
    confirms the request body's field actually reaches the underlying
    function, not silently ignored in favor of a hardcoded default."""
    monkeypatch.setattr(main.hiring_signals, "get_hiring_signals", MagicMock(return_value=[]))
    monkeypatch.setattr(main.raw_landing, "save_raw_signals", MagicMock(return_value="data/raw/branch_b_x.json"))

    response = client.post("/branch-b/run", json={"lookback_days": 30})

    assert response.status_code == 200
    _, kwargs = main.hiring_signals.get_hiring_signals.call_args
    assert kwargs["lookback_days"] == 30


def test_branch_c_run_lands_the_full_result_and_counts_reviews(monkeypatch):
    """Branch C's raw landing shape is different from A/B - it's a dict
    with both "reviews" and "pain_point_corpus" keys, not a bare list.
    Confirms the count comes from the reviews list specifically, and the
    whole dict (not just the reviews) gets landed - merge/run's reload
    logic depends on the "reviews" key existing in the landed file."""
    fake_result = {"reviews": [{"review_id": "1"}, {"review_id": "2"}], "pain_point_corpus": {}}
    monkeypatch.setattr(main.intent_g2, "get_intent_signals", MagicMock(return_value=fake_result))
    monkeypatch.setattr(main.raw_landing, "save_raw_signals", MagicMock(return_value="data/raw/branch_c_x.json"))

    response = client.post("/branch-c/run", json={})

    assert response.status_code == 200
    assert response.json() == {"count": 2, "landed_path": "data/raw/branch_c_x.json"}
    main.raw_landing.save_raw_signals.assert_called_once_with("branch_c", fake_result)


def test_merge_run_opens_and_closes_a_connection(monkeypatch):
    """Confirms the endpoint manages its own connection lifecycle (open,
    use, close) rather than leaking one per request - important for a
    service meant to be called repeatedly on a schedule."""
    mock_conn = MagicMock()
    monkeypatch.setattr(main.db, "get_connection", MagicMock(return_value=mock_conn))
    monkeypatch.setattr(
        main.merge_signals,
        "run_full_merge",
        MagicMock(
            return_value={
                "companies_from_funding": 5,
                "companies_from_hiring": 3,
                "competitors_updated": 2,
                "companies_from_launches": 1,
                "distinct_company_ids": 7,
            }
        ),
    )

    response = client.post("/merge/run")

    assert response.status_code == 200
    assert response.json()["distinct_company_ids"] == 7
    assert response.json()["companies_from_launches"] == 1
    mock_conn.close.assert_called_once()


def test_branch_d_run_lands_signals_and_returns_count(monkeypatch):
    """Redesign v2, Tier 1: same thin-wrapper shape as branches A/B/C - calls
    producthunt_launches.get_launch_signals(), lands the result, reports
    count + path, no scoring/filtering logic duplicated here."""
    monkeypatch.setattr(
        main.producthunt_launches, "get_launch_signals", MagicMock(return_value=[{"company_name": "Acme AI"}])
    )
    monkeypatch.setattr(main.raw_landing, "save_raw_signals", MagicMock(return_value="data/raw/branch_d_x.json"))

    response = client.post("/branch-d/run", json={"lookback_days": 14})

    assert response.status_code == 200
    assert response.json() == {"count": 1, "landed_path": "data/raw/branch_d_x.json"}
    main.raw_landing.save_raw_signals.assert_called_once_with("branch_d", [{"company_name": "Acme AI"}])
    _, kwargs = main.producthunt_launches.get_launch_signals.call_args
    assert kwargs["lookback_days"] == 14


def test_leadership_run_only_processes_companies_with_a_domain(monkeypatch):
    """Redesign v2, Tier 1: the real, load-bearing limitation - a company
    with no domain must be silently skipped (not an error), since there's
    no reliable way to guess a leadership-page URL from a name alone."""
    mock_conn = MagicMock()
    monkeypatch.setattr(main.db, "get_connection", MagicMock(return_value=mock_conn))
    monkeypatch.setattr(
        main.db,
        "get_all_companies",
        MagicMock(return_value=[{"id": 1, "domain": "acme.com"}, {"id": 2, "domain": None}]),
    )
    monkeypatch.setattr(
        main.leadership_monitor,
        "check_for_new_leadership",
        MagicMock(return_value={"new_hires": [{"name": "Jane Doe", "title": "VP Product"}]}),
    )

    response = client.post("/leadership/run")

    assert response.status_code == 200
    assert response.json() == {"companies_checked": 1, "new_hires_found": 1}
    main.leadership_monitor.check_for_new_leadership.assert_called_once_with(mock_conn, 1, "acme.com")
    mock_conn.close.assert_called_once()


def test_run_full_cycle_endpoint_calls_full_pipeline_run_with_request_fields(monkeypatch):
    """Redesign v2, Tier 2: confirms this endpoint is a thin wrapper around
    full_pipeline_run.run_full_cycle() - request fields reach the
    underlying function, and its response round-trips through the
    RunFullCycleResponse model correctly."""
    mock_run = MagicMock(
        return_value={
            "companies_evaluated": 62,
            "qualified_count": 1,
            "branch_a_count": 22,
            "branch_b_count": 40,
            "branch_d_count": 20,
            "branch_c_count": 5,
            "merge_result": {"distinct_company_ids": 62},
            "leadership_companies_checked": 22,
            "leadership_new_hires_found": 0,
            "run_log_path": "data/raw/run_log_x.json",
        }
    )
    monkeypatch.setattr(main.full_pipeline_run, "run_full_cycle", mock_run)

    response = client.post(
        "/pipeline/run-full-cycle",
        json={
            "include_branch_c": True,
            "branch_c_competitors": {"Aha!": "aha"},
            "dedup_window_days": 3,
            "include_demographics_enrichment": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["qualified_count"] == 1
    mock_run.assert_called_once_with(
        include_branch_c=True,
        branch_c_competitors={"Aha!": "aha"},
        dedup_window_days=3,
        include_demographics_enrichment=False,
    )


def test_run_full_cycle_endpoint_defaults_branch_c_to_excluded(monkeypatch):
    """The one assertion most directly protecting the ADR-009 opt-in-only
    guarantee at the HTTP layer - a caller that sends no body at all must
    not accidentally trigger real Apify spend."""
    mock_run = MagicMock(
        return_value={
            "companies_evaluated": 0,
            "qualified_count": 0,
            "branch_a_count": 0,
            "branch_b_count": 0,
            "branch_d_count": 0,
            "branch_c_count": None,
            "merge_result": {"distinct_company_ids": 0},
            "leadership_companies_checked": 0,
            "leadership_new_hires_found": 0,
            "run_log_path": "data/raw/run_log_x.json",
        }
    )
    monkeypatch.setattr(main.full_pipeline_run, "run_full_cycle", mock_run)

    response = client.post("/pipeline/run-full-cycle", json={})

    assert response.status_code == 200
    _, kwargs = mock_run.call_args
    assert kwargs["include_branch_c"] is False


def test_resume_after_enrichment_endpoint_returns_resumed_false_when_nothing_picked_up(monkeypatch):
    """Redesign v2, Tier 5: the manual/on-demand version of the same check
    the background poller runs automatically - confirms the endpoint is a
    thin wrapper and correctly reports the genuine no-op case (nothing new
    dropped into data/clay/incoming_*/) rather than a real run summary."""
    mock_resume = MagicMock(return_value=None)
    monkeypatch.setattr(main.full_pipeline_run, "resume_after_enrichment", mock_resume)

    response = client.post("/pipeline/resume-after-enrichment", json={})

    assert response.status_code == 200
    assert response.json() == {"resumed": False}
    mock_resume.assert_called_once_with(dedup_window_days=pipeline.DEFAULT_DEDUP_WINDOW_DAYS)


def test_resume_after_enrichment_endpoint_returns_summary_when_something_resumed(monkeypatch):
    """When Clay enrichment WAS picked up, the endpoint should surface the
    real run summary (not just a bare boolean) so a manual caller can see
    what happened, same as /pipeline/run-full-cycle's response shape."""
    mock_resume = MagicMock(
        return_value={
            "companies_evaluated": 62,
            "qualified_count": 2,
            "leadership_companies_checked": 22,
            "leadership_new_hires_found": 0,
            "run_log_path": "data/raw/run_log_x.json",
        }
    )
    monkeypatch.setattr(main.full_pipeline_run, "resume_after_enrichment", mock_resume)

    response = client.post("/pipeline/resume-after-enrichment", json={"dedup_window_days": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["resumed"] is True
    assert body["qualified_count"] == 2
    mock_resume.assert_called_once_with(dedup_window_days=3)


def test_pipeline_run_all_evaluates_every_company_and_summarizes_statuses(monkeypatch):
    """Confirms the batch endpoint loops every company, calls
    process_qualified_lead() for each with the real per-company signals,
    and rolls the individual results up into a status_counts summary -
    this is the endpoint n8n's final workflow node actually calls."""
    mock_conn = MagicMock()
    monkeypatch.setattr(main.db, "get_connection", MagicMock(return_value=mock_conn))
    monkeypatch.setattr(main.db, "get_all_competitor_intel", MagicMock(return_value={}))
    monkeypatch.setattr(main.db, "get_all_companies", MagicMock(return_value=[{"id": 1}, {"id": 2}, {"id": 3}]))
    monkeypatch.setattr(main.db, "get_signals_for_company", MagicMock(return_value=[]))
    monkeypatch.setattr(
        main.pipeline,
        "process_qualified_lead",
        MagicMock(
            side_effect=[
                {"status": "not_qualified", "icp_score": 20},
                {"status": "not_qualified", "icp_score": 30},
                {"status": "processed", "lead_id": 1},
            ]
        ),
    )

    response = client.post("/pipeline/run-all", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["companies_evaluated"] == 3
    assert body["status_counts"] == {"not_qualified": 2, "processed": 1}
    mock_conn.close.assert_called_once()
