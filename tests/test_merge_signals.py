"""Tests for python/merge_signals.py - Phase 3's merge/dedupe orchestration.
All db.* calls are mocked; these tests check that each branch's raw signal
shape gets translated into the correct db.py calls, not real SQL."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import merge_signals  # noqa: E402

FUNDING_SIGNAL = {
    "company_name": "Acme Corp",
    "funding_amount_usd": 12_000_000,
    "funding_date": "2026-06-01",
    "funding_stage": "Seed/Series A",
    "industry": "Software",
    "biz_location": "New York, NY",
    "cik": "0001234567",
    "accession_no": "0001234567-26-000123",
    "source": "sec_edgar_form_d",
}

HIRING_SIGNAL_WITH_TOOL = {
    "company_name": "Acme Corp",
    "domain": None,
    "employee_count": None,
    "pm_job_post_count": 2,
    "job_titles": ["Senior Product Manager", "Product Operations Lead"],
    "most_recent_posting_date": "2026-06-15T00:00:00-04:00",
    "source": "greenhouse",
    "ats_matched_slug": "acme",
    "current_tools_mentioned": ["Jira Product Discovery"],
}

HIRING_SIGNAL_NO_TOOL = {
    "company_name": "Beta Inc",
    "domain": None,
    "employee_count": None,
    "pm_job_post_count": 1,
    "job_titles": ["Product Manager"],
    "most_recent_posting_date": "2026-05-20T00:00:00Z",
    "source": "adzuna",
    "ats_matched_slug": None,
    "current_tools_mentioned": [],
}

NORMALIZED_REVIEWS = [
    {
        "review_id": "101",
        "text": "Too expensive as we scaled up.",
        "star_rating": 2,
        "is_negative": True,
        "is_switch_signal": True,
        "switch_reason": "cost",
        "competitor": "Aha!",
        "reviewer_country": "US",
        "posted_date": "2026-07-01",
    },
    {
        "review_id": "102",
        "text": "Great roadmap visuals.",
        "star_rating": 5,
        "is_negative": False,
        "is_switch_signal": False,
        "switch_reason": None,
        "competitor": "Aha!",
        "reviewer_country": "US",
        "posted_date": "2026-07-02",
    },
]

AGGREGATE_RESULT = {
    "total_reviews_seen": 15,
    "negative_review_count": 4,
    "switch_signal_count": 3,
    "representative_quotes": [{"text": f"quote {i}"} for i in range(10)],
}


def test_merge_funding_signals_upserts_company_and_inserts_signal(monkeypatch):
    monkeypatch.setattr(merge_signals.db, "upsert_company", MagicMock(return_value=1))
    monkeypatch.setattr(merge_signals.db, "insert_signal", MagicMock(return_value=100))
    mock_conn = MagicMock()

    company_ids = merge_signals.merge_funding_signals(mock_conn, [FUNDING_SIGNAL])

    assert company_ids == [1]
    merge_signals.db.upsert_company.assert_called_once_with(
        mock_conn,
        "Acme Corp",
        funding_stage="Seed/Series A",
        funding_date="2026-06-01",
        funding_amount_usd=12_000_000,
        industry="Software",
        biz_location="New York, NY",
    )
    merge_signals.db.insert_signal.assert_called_once_with(
        mock_conn, 1, source="sec_edgar_form_d", signal_category="funding", posted_at="2026-06-01"
    )


def test_merge_hiring_signals_includes_current_tool_when_found(monkeypatch):
    monkeypatch.setattr(merge_signals.db, "upsert_company", MagicMock(return_value=2))
    monkeypatch.setattr(merge_signals.db, "insert_signal", MagicMock(return_value=101))
    mock_conn = MagicMock()

    merge_signals.merge_hiring_signals(mock_conn, [HIRING_SIGNAL_WITH_TOOL])

    merge_signals.db.upsert_company.assert_called_once_with(
        mock_conn, "Acme Corp", current_tool_mentioned="Jira Product Discovery"
    )
    merge_signals.db.insert_signal.assert_called_once_with(
        mock_conn,
        2,
        source="greenhouse",
        signal_category="pm_hiring",
        raw_text="Senior Product Manager, Product Operations Lead",
        posted_at="2026-06-15T00:00:00-04:00",
    )


def test_merge_hiring_signals_omits_current_tool_field_when_none_found(monkeypatch):
    monkeypatch.setattr(merge_signals.db, "upsert_company", MagicMock(return_value=3))
    monkeypatch.setattr(merge_signals.db, "insert_signal", MagicMock(return_value=102))
    mock_conn = MagicMock()

    merge_signals.merge_hiring_signals(mock_conn, [HIRING_SIGNAL_NO_TOOL])

    # No current_tool_mentioned kwarg at all - must not overwrite an existing
    # value with NULL just because this run's scan found nothing.
    merge_signals.db.upsert_company.assert_called_once_with(mock_conn, "Beta Inc")


def test_merge_hiring_signals_inserts_second_signal_row_when_buying_intent_detected(monkeypatch):
    """Redesign v2, Tier 1: a distinct signal_category row, not an extra
    field on the pm_hiring row - confirms both db.insert_signal calls
    happen (pm_hiring, then buying_intent) with the right shape."""
    monkeypatch.setattr(merge_signals.db, "upsert_company", MagicMock(return_value=2))
    monkeypatch.setattr(merge_signals.db, "insert_signal", MagicMock(return_value=101))
    mock_conn = MagicMock()

    signal_with_buying_intent = {
        **HIRING_SIGNAL_WITH_TOOL,
        "buying_intent": {"buying_intent_detected": True, "matched_phrase": "evaluate our PM tool stack"},
    }

    merge_signals.merge_hiring_signals(mock_conn, [signal_with_buying_intent])

    assert merge_signals.db.insert_signal.call_count == 2
    merge_signals.db.insert_signal.assert_any_call(
        mock_conn,
        2,
        source="greenhouse",
        signal_category="buying_intent",
        raw_text="evaluate our PM tool stack",
        posted_at="2026-06-15T00:00:00-04:00",
    )


def test_merge_hiring_signals_skips_second_insert_when_buying_intent_not_detected(monkeypatch):
    """A None result, or a detected=False result, must not write a
    buying_intent signal row - no accidental positive-signal noise."""
    monkeypatch.setattr(merge_signals.db, "upsert_company", MagicMock(return_value=2))
    monkeypatch.setattr(merge_signals.db, "insert_signal", MagicMock(return_value=101))
    mock_conn = MagicMock()

    signal_false = {
        **HIRING_SIGNAL_WITH_TOOL,
        "buying_intent": {"buying_intent_detected": False, "matched_phrase": None},
    }

    merge_signals.merge_hiring_signals(mock_conn, [signal_false])

    assert merge_signals.db.insert_signal.call_count == 1  # only the pm_hiring insert


ATTRIBUTED_REVIEWS = [
    {
        "review_id": "1",
        "text": "We use this at Acme Corp and it's been rocky.",
        "star_rating": 2,
        "competitor": "Aha!",
        "posted_date": "2026-07-01",
        "attributed_company": "Acme Corp",
    },
    {
        "review_id": "2",
        "text": "Generic review, no company mentioned.",
        "star_rating": 4,
        "competitor": "Aha!",
        "posted_date": "2026-07-02",
        "attributed_company": None,
    },
]


def test_merge_attributed_reviews_only_merges_reviews_with_a_company_identified(monkeypatch):
    """The core behavior this function exists for: only the rare review
    where classify.py successfully named a company should become a real
    company signal. The common case (attributed_company is None) must be
    silently skipped here, not upserted as a company called 'None'."""
    monkeypatch.setattr(merge_signals.db, "upsert_company", MagicMock(return_value=5))
    monkeypatch.setattr(merge_signals.db, "insert_signal", MagicMock(return_value=200))
    mock_conn = MagicMock()

    company_ids = merge_signals.merge_attributed_reviews(mock_conn, ATTRIBUTED_REVIEWS)

    assert company_ids == [5]
    merge_signals.db.upsert_company.assert_called_once_with(mock_conn, "Acme Corp")
    merge_signals.db.insert_signal.assert_called_once_with(
        mock_conn,
        5,
        source="g2",
        signal_category="competitor_review",
        raw_text="We use this at Acme Corp and it's been rocky.",
        star_rating=2,
        competitor_mentioned="Aha!",
        posted_at="2026-07-01",
    )


def test_merge_intent_signals_upserts_each_review_and_recomputes_aggregate(monkeypatch):
    """ADR-021's core behavior: every normalized review is individually
    upserted (deduped by review_id at the DB layer), and competitor_intel is
    written from a RECOMPUTED aggregate (queried fresh from the full
    g2_reviews history), not from this batch's own local totals - proves
    the accumulate-don't-replace design is actually wired up correctly."""
    monkeypatch.setattr(merge_signals.db, "upsert_g2_review", MagicMock(return_value=True))
    monkeypatch.setattr(merge_signals.db, "get_competitor_intel_aggregate", MagicMock(return_value=AGGREGATE_RESULT))
    monkeypatch.setattr(merge_signals.db, "upsert_competitor_intel", MagicMock(return_value=9))
    mock_conn = MagicMock()

    row_ids = merge_signals.merge_intent_signals(mock_conn, NORMALIZED_REVIEWS)

    assert row_ids == [9]
    assert merge_signals.db.upsert_g2_review.call_count == 2
    merge_signals.db.get_competitor_intel_aggregate.assert_called_once_with(
        mock_conn, "Aha!", quote_limit=merge_signals.MAX_QUOTES_PER_COMPETITOR
    )
    merge_signals.db.upsert_competitor_intel.assert_called_once_with(mock_conn, "Aha!", **AGGREGATE_RESULT)


def test_merge_intent_signals_only_recomputes_once_per_distinct_competitor(monkeypatch):
    """A batch with multiple reviews for the SAME competitor should only
    trigger one aggregate recompute + one competitor_intel upsert, not one
    per review - otherwise a 15-review batch would issue 15 redundant
    aggregate queries for identical data."""
    monkeypatch.setattr(merge_signals.db, "upsert_g2_review", MagicMock(return_value=True))
    monkeypatch.setattr(merge_signals.db, "get_competitor_intel_aggregate", MagicMock(return_value=AGGREGATE_RESULT))
    monkeypatch.setattr(merge_signals.db, "upsert_competitor_intel", MagicMock(return_value=9))
    mock_conn = MagicMock()

    merge_signals.merge_intent_signals(mock_conn, NORMALIZED_REVIEWS)  # both reviews are "Aha!"

    assert merge_signals.db.get_competitor_intel_aggregate.call_count == 1
    assert merge_signals.db.upsert_competitor_intel.call_count == 1


LAUNCH_SIGNAL = {
    "company_name": "Acme AI",
    "product_name": "Acme AI",
    "tagline": "Roadmaps that write themselves",
    "launched_at": "2026-07-01T00:00:00Z",
    "url": "https://www.producthunt.com/posts/acme-ai",
    "source": "producthunt",
}


def test_merge_launch_signals_upserts_company_and_inserts_signal(monkeypatch):
    monkeypatch.setattr(merge_signals.db, "upsert_company", MagicMock(return_value=6))
    monkeypatch.setattr(merge_signals.db, "insert_signal", MagicMock(return_value=300))
    mock_conn = MagicMock()

    company_ids = merge_signals.merge_launch_signals(mock_conn, [LAUNCH_SIGNAL])

    assert company_ids == [6]
    merge_signals.db.upsert_company.assert_called_once_with(mock_conn, "Acme AI")
    merge_signals.db.insert_signal.assert_called_once_with(
        mock_conn,
        6,
        source="producthunt",
        signal_category="product_launch",
        raw_text="Roadmaps that write themselves",
        posted_at="2026-07-01T00:00:00Z",
    )


def test_run_full_merge_uses_passed_in_data_without_touching_raw_landing(monkeypatch):
    monkeypatch.setattr(merge_signals, "load_latest_raw_signals", MagicMock(side_effect=AssertionError("should not be called")))
    monkeypatch.setattr(merge_signals, "merge_funding_signals", MagicMock(return_value=[1]))
    monkeypatch.setattr(merge_signals, "merge_hiring_signals", MagicMock(return_value=[1, 2]))
    monkeypatch.setattr(merge_signals, "merge_intent_signals", MagicMock(return_value=[9]))
    monkeypatch.setattr(merge_signals, "merge_launch_signals", MagicMock(return_value=[6]))
    mock_conn = MagicMock()

    summary = merge_signals.run_full_merge(
        mock_conn,
        funding_signals=[FUNDING_SIGNAL],
        hiring_signals=[HIRING_SIGNAL_WITH_TOOL],
        normalized_reviews=NORMALIZED_REVIEWS,
        launch_signals=[LAUNCH_SIGNAL],
    )

    assert summary == {
        "companies_from_funding": 1,
        "companies_from_hiring": 2,
        "competitors_updated": 1,
        "companies_from_launches": 1,
        "distinct_company_ids": 3,
    }


def test_run_full_merge_reloads_from_raw_landing_when_not_passed(monkeypatch):
    landing_data = {
        "branch_a": [FUNDING_SIGNAL],
        "branch_b": [HIRING_SIGNAL_NO_TOOL],
        "branch_c": {"reviews": NORMALIZED_REVIEWS},
        "branch_d": [LAUNCH_SIGNAL],
    }
    monkeypatch.setattr(
        merge_signals, "load_latest_raw_signals", MagicMock(side_effect=lambda name: landing_data[name])
    )
    monkeypatch.setattr(merge_signals, "merge_funding_signals", MagicMock(return_value=[1]))
    monkeypatch.setattr(merge_signals, "merge_hiring_signals", MagicMock(return_value=[3]))
    monkeypatch.setattr(merge_signals, "merge_intent_signals", MagicMock(return_value=[9]))
    monkeypatch.setattr(merge_signals, "merge_launch_signals", MagicMock(return_value=[6]))
    mock_conn = MagicMock()

    summary = merge_signals.run_full_merge(mock_conn)

    merge_signals.merge_funding_signals.assert_called_once_with(mock_conn, [FUNDING_SIGNAL])
    merge_signals.merge_hiring_signals.assert_called_once_with(mock_conn, [HIRING_SIGNAL_NO_TOOL])
    merge_signals.merge_intent_signals.assert_called_once_with(mock_conn, NORMALIZED_REVIEWS)
    merge_signals.merge_launch_signals.assert_called_once_with(mock_conn, [LAUNCH_SIGNAL])
    assert summary["distinct_company_ids"] == 3
