"""Phase 9: Google Sheets output - the CRM-style view the user asked for
(2026-07-11): one row per qualified lead, sortable by score, with company
info, funding, the score itself, the priority_summary rationale (ADR-019),
and every outreach field, so a human can triage leads without HubSpot access
- same "parallel visual output for QA/stakeholders" rationale as the
original blueprint's Google Sheets step.
"""
import os

import gspread

DEFAULT_WORKSHEET_NAME = "Sheet1"

HEADER_ROW = [
    "company_name",
    "domain",
    "funding_stage",
    "funding_amount_usd",
    "pm_job_post_count",
    "signal_type",
    "icp_score",
    "current_tool_mentioned",
    "priority_summary",
    "outreach_subject_a",
    "outreach_subject_b",
    "outreach_email_body",
    "outreach_linkedin",
    "outreach_call_script",
    "hubspot_company_id",
    "created_at",
]


def get_worksheet(worksheet_name: str = DEFAULT_WORKSHEET_NAME):
    """Opens the configured Google Sheet via the service account credentials
    in .env. Raises RuntimeError with a clear message if either env var is
    missing, rather than a confusing gspread/auth stack trace."""
    sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID")
    if not sa_path or not sheet_id:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEETS_ID must both be set in .env")

    gc = gspread.service_account(filename=sa_path)
    return gc.open_by_key(sheet_id).worksheet(worksheet_name)


def ensure_header_row(worksheet) -> None:
    """Writes HEADER_ROW to row 1 if it's missing or doesn't match - safe to
    call every run, only writes when actually needed."""
    if worksheet.row_values(1) != HEADER_ROW:
        worksheet.update("A1", [HEADER_ROW])


def append_lead_row(worksheet, lead_row: dict) -> None:
    """Appends one lead as a new row, in HEADER_ROW's column order. Missing
    keys become an empty string rather than raising - not every lead has
    every field (e.g. a TIMING-only lead has no current_tool_mentioned)."""
    row = [lead_row.get(column, "") for column in HEADER_ROW]
    worksheet.append_row(row, value_input_option="USER_ENTERED")
