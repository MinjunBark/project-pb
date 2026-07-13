"""Tests for utils/db.py. Connection-touching functions are mocked;
normalize_company_name is pure and tested directly."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import psycopg2.extras
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import db  # noqa: E402


def test_get_connection_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        db.get_connection()


@pytest.mark.parametrize(
    "raw_name,expected",
    [
        ("Acme Corp", "acme"),
        ("Acme, Inc.", "acme"),
        ("Acme LLC", "acme"),
        ("Acme Corporation", "acme"),
        ("Big Belly Solar LLC", "big belly solar"),
        ("Board Management Software, Inc.", "board management software"),
    ],
)
def test_normalize_company_name_strips_suffixes(raw_name, expected):
    assert db.normalize_company_name(raw_name) == expected


def test_upsert_company_builds_correct_query_and_returns_id():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = [42]

    company_id = db.upsert_company(
        mock_conn, "Acme Corp", domain="acme.com", funding_stage="Series B"
    )

    assert company_id == 42
    executed_query, executed_values = mock_cursor.execute.call_args[0]
    assert "normalized_name" in executed_query
    assert "ON CONFLICT (normalized_name)" in executed_query
    assert executed_values[0] == "acme"
    assert executed_values[1] == "Acme Corp"
    assert "acme.com" in executed_values
    assert "Series B" in executed_values
    mock_conn.commit.assert_called_once()


def test_get_company_by_normalized_name_returns_none_when_not_found():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = None

    result = db.get_company_by_normalized_name(mock_conn, "Totally Unknown Co")

    assert result is None


def test_get_company_by_normalized_name_returns_dict_when_found():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = {"id": 1, "name": "Acme Corp", "normalized_name": "acme"}

    result = db.get_company_by_normalized_name(mock_conn, "Acme Corp")

    assert result == {"id": 1, "name": "Acme Corp", "normalized_name": "acme"}


def test_update_company_by_id_builds_correct_query():
    """Confirms this writes directly by id (not normalized_name) and always
    touches last_seen_at - the whole point of this function is Phase 6's
    Clay import, where company_id is the trustworthy match key that
    round-tripped through the export/import CSV."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value

    db.update_company_by_id(mock_conn, 5, domain="acme.com")

    executed_query, executed_values = mock_cursor.execute.call_args[0]
    assert "UPDATE companies SET" in executed_query
    assert "WHERE id = %s" in executed_query
    assert executed_values == ["acme.com", 5]
    mock_conn.commit.assert_called_once()


def test_update_company_by_id_no_op_when_no_fields_given():
    """Guards against issuing a pointless SQL UPDATE (or a syntax error from
    an empty SET clause) when called with nothing to update - should just
    return without touching the connection at all."""
    mock_conn = MagicMock()

    db.update_company_by_id(mock_conn, 5)

    mock_conn.cursor.assert_not_called()


def test_insert_signal_builds_correct_query_and_returns_id():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = [7]

    signal_id = db.insert_signal(
        mock_conn, 42, source="sec_edgar_form_d", signal_category="funding", posted_at="2026-06-01"
    )

    assert signal_id == 7
    executed_query, executed_values = mock_cursor.execute.call_args[0]
    assert "INSERT INTO signals" in executed_query
    assert executed_values == [42, "sec_edgar_form_d", "funding", "2026-06-01"]
    mock_conn.commit.assert_called_once()


def test_upsert_g2_review_returns_true_when_newly_inserted():
    """The ON CONFLICT DO NOTHING + RETURNING pattern is what makes
    re-scraping overlapping reviews safe (ADR-021) - a genuinely new review
    should return True."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = [1]

    was_inserted = db.upsert_g2_review(
        mock_conn,
        {"review_id": "101", "competitor": "Aha!", "star_rating": 2, "is_negative": True, "is_switch_signal": True},
    )

    assert was_inserted is True
    mock_conn.commit.assert_called_once()


def test_upsert_g2_review_returns_false_when_already_seen():
    """The core dedup guarantee: a review_id that already exists must
    return False (not raise, not silently double-count) - this is what
    lets a periodic re-scrape safely re-fetch overlapping reviews without
    corrupting the accumulated totals."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = None  # ON CONFLICT DO NOTHING -> no row returned

    was_inserted = db.upsert_g2_review(mock_conn, {"review_id": "101", "competitor": "Aha!"})

    assert was_inserted is False


def test_get_competitor_intel_aggregate_reads_real_counts_and_quotes():
    """Confirms the aggregate is built from two separate real queries (a
    COUNT/SUM for totals, a separate SELECT for quote text) and assembled
    into the exact shape upsert_competitor_intel() expects - the contract
    between these two functions that merge_intent_signals() relies on."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = (15, 4, 3)
    mock_cursor.fetchall.return_value = [("too expensive", "cost", 2)]

    result = db.get_competitor_intel_aggregate(mock_conn, "Aha!", quote_limit=10)

    assert result == {
        "total_reviews_seen": 15,
        "negative_review_count": 4,
        "switch_signal_count": 3,
        "representative_quotes": [{"text": "too expensive", "switch_reason": "cost", "star_rating": 2}],
    }


def test_get_competitor_intel_aggregate_handles_zero_reviews_without_none_values():
    """A competitor with zero reviews so far (e.g. right after the property/
    table setup, before any scrape) must return 0s, not None - COALESCE in
    the SQL handles NULL SUM() results, but this proves it end-to-end
    through the Python return shape too."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = (0, 0, 0)
    mock_cursor.fetchall.return_value = []

    result = db.get_competitor_intel_aggregate(mock_conn, "Craft.io")

    assert result["total_reviews_seen"] == 0
    assert result["representative_quotes"] == []


def test_get_all_companies_returns_list_of_dicts():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [{"id": 1, "name": "Acme Corp"}]

    result = db.get_all_companies(mock_conn)

    assert result == [{"id": 1, "name": "Acme Corp"}]


def test_get_signals_for_company_filters_by_company_id():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [{"signal_category": "funding"}]

    result = db.get_signals_for_company(mock_conn, 5)

    assert result == [{"signal_category": "funding"}]
    _, executed_values = mock_cursor.execute.call_args[0]
    assert executed_values == (5,)


def test_get_all_competitor_intel_keys_by_competitor_name():
    """Confirms the flat row list from Postgres gets reshaped into the
    dict-keyed-by-competitor-name format scoring.score_intent() and
    pipeline.build_lead_context() both expect - a plain list wouldn't be
    usable by either without this reshaping."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [
        {"competitor": "Aha!", "switch_signal_count": 7, "total_reviews_seen": 16},
        {"competitor": "Craft.io", "switch_signal_count": 3, "total_reviews_seen": 15},
    ]

    result = db.get_all_competitor_intel(mock_conn)

    assert result["Aha!"]["switch_signal_count"] == 7
    assert result["Craft.io"]["total_reviews_seen"] == 15


def test_has_recent_lead_returns_true_when_a_row_exists():
    """Confirms the query uses a real Postgres interval comparison against
    created_at and correctly reports True when a matching row is found -
    this is what lets pipeline.py skip a company already processed within
    the dedup window (wires up DEDUP_WINDOW_DAYS, previously unused)."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = (1,)

    assert db.has_recent_lead(mock_conn, company_id=5, within_days=7) is True

    executed_query, executed_values = mock_cursor.execute.call_args[0]
    assert "created_at >=" in executed_query
    assert executed_values == (5, 7)


def test_has_recent_lead_returns_false_when_no_row_exists():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = None

    assert db.has_recent_lead(mock_conn, company_id=5, within_days=7) is False


def test_insert_lead_wraps_score_breakdown_as_json_and_returns_id():
    """Confirms score_breakdown (a plain Python dict from scoring.py) gets
    wrapped in psycopg2.extras.Json before being sent - the leads.
    score_breakdown column is JSONB, same pattern already proven for
    competitor_intel.representative_quotes below."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = [11]

    lead_id = db.insert_lead(
        mock_conn,
        company_id=5,
        icp_score=85,
        signal_type="BOTH",
        score_breakdown={"timing": {"funding_recency": 25}},
        priority_summary="Act now.",
    )

    assert lead_id == 11
    executed_query, executed_values = mock_cursor.execute.call_args[0]
    assert "INSERT INTO leads" in executed_query
    assert executed_values[0] == 5
    assert executed_values[1] == 85
    assert executed_values[2] == "BOTH"
    assert isinstance(executed_values[3], psycopg2.extras.Json)
    assert "Act now." in executed_values
    mock_conn.commit.assert_called_once()


def test_get_latest_leadership_snapshot_returns_none_when_never_snapshotted():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = None

    result = db.get_latest_leadership_snapshot(mock_conn, company_id=5)

    assert result is None


def test_get_latest_leadership_snapshot_returns_most_recent_row():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = {
        "id": 1,
        "company_id": 5,
        "content_hash": "abc123",
        "detected_names": [{"name": "Jane Doe", "title": "VP Product"}],
    }

    result = db.get_latest_leadership_snapshot(mock_conn, company_id=5)

    assert result["content_hash"] == "abc123"
    executed_query, executed_values = mock_cursor.execute.call_args[0]
    assert "ORDER BY snapshotted_at DESC" in executed_query
    assert executed_values == (5,)


def test_insert_leadership_snapshot_wraps_names_as_json_and_returns_id():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = [9]

    snapshot_id = db.insert_leadership_snapshot(
        mock_conn, company_id=5, page_url="https://acme.com/about", content_hash="abc123",
        detected_names=[{"name": "Jane Doe", "title": "VP Product"}],
    )

    assert snapshot_id == 9
    executed_query, executed_values = mock_cursor.execute.call_args[0]
    assert "INSERT INTO company_leadership_snapshots" in executed_query
    assert executed_values[0] == 5
    assert executed_values[1] == "https://acme.com/about"
    assert executed_values[2] == "abc123"
    assert isinstance(executed_values[3], psycopg2.extras.Json)
    mock_conn.commit.assert_called_once()


def test_upsert_competitor_intel_wraps_quotes_as_json_and_returns_id():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = [3]

    row_id = db.upsert_competitor_intel(
        mock_conn,
        "Aha!",
        total_reviews_seen=15,
        negative_review_count=4,
        switch_signal_count=2,
        representative_quotes=[{"text": "too expensive"}],
    )

    assert row_id == 3
    executed_query, executed_values = mock_cursor.execute.call_args[0]
    assert "ON CONFLICT (competitor)" in executed_query
    assert executed_values[0] == "Aha!"
    assert isinstance(executed_values[-1], psycopg2.extras.Json)
    mock_conn.commit.assert_called_once()
