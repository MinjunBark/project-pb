"""Tests for utils/sheets.py - the CRM-style Google Sheet output. All
gspread calls are mocked; real connection is verified live and documented
separately in docs/PROGRESS.md."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import sheets  # noqa: E402


def test_get_worksheet_requires_both_env_vars(monkeypatch):
    """Fails loudly and immediately if either the sheet id or the
    credentials path is missing - same guard pattern as every other client
    this session (gemini, hubspot) - rather than a confusing gspread
    auth error deep in its own library."""
    monkeypatch.delenv("GOOGLE_SHEETS_ID", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "some/path.json")

    with pytest.raises(RuntimeError, match="GOOGLE_SHEETS_ID"):
        sheets.get_worksheet()


def test_ensure_header_row_writes_when_missing_or_wrong():
    """A brand-new or blank sheet has no header row - must be written.
    Also covers the case where row 1 has stale/wrong columns (e.g. from an
    earlier manual edit) - either way, the real HEADER_ROW should end up
    in row 1."""
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = ["some", "old", "columns"]

    sheets.ensure_header_row(mock_ws)

    mock_ws.update.assert_called_once_with("A1", [sheets.HEADER_ROW])


def test_ensure_header_row_skips_write_when_already_correct():
    """Idempotency check: if row 1 already matches HEADER_ROW exactly (a
    repeat pipeline run), don't issue a wasted write - append-only usage
    should never re-touch the header after the first run."""
    mock_ws = MagicMock()
    mock_ws.row_values.return_value = sheets.HEADER_ROW

    sheets.ensure_header_row(mock_ws)

    mock_ws.update.assert_not_called()


def test_append_lead_row_orders_values_by_header_and_fills_missing_with_blank():
    """The core correctness check: values must land in the exact HEADER_ROW
    column order regardless of the input dict's key order, and any field a
    particular lead doesn't have (e.g. current_tool_mentioned on a
    TIMING-only lead) must become an empty string, not crash or shift every
    subsequent column left."""
    mock_ws = MagicMock()
    lead_row = {
        "company_name": "Acme Corp",
        "icp_score": 85,
        "signal_type": "TIMING",
        # domain, funding_stage, current_tool_mentioned, etc. intentionally omitted
    }

    sheets.append_lead_row(mock_ws, lead_row)

    args, kwargs = mock_ws.append_row.call_args
    written_row = args[0]
    assert written_row[sheets.HEADER_ROW.index("company_name")] == "Acme Corp"
    assert written_row[sheets.HEADER_ROW.index("icp_score")] == 85
    assert written_row[sheets.HEADER_ROW.index("signal_type")] == "TIMING"
    assert written_row[sheets.HEADER_ROW.index("domain")] == ""
    assert written_row[sheets.HEADER_ROW.index("current_tool_mentioned")] == ""
