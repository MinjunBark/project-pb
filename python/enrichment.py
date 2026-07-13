"""Phase 6: Clay enrichment via a CSV export/import round-trip (ADR-017).

Clay's live Webhook trigger is paid-only on the user's current plan, so this
is a batch flow instead of a real-time one: export companies missing real
data -> import into a free Clay Blank table -> run the "Company Enrichment"
waterfall (Clearbit/Apollo/PDL-backed - resolves domain via a real Website
URL, plus employee count and industry, all in one pass) -> export the
result -> import_enriched_dataset() loads it back into Postgres.

Consolidated (2026-07-13) from two separate round-trips (domain-only,
demographics-only) into one. The user pointed out Clay's "Company
Enrichment" option already returns everything in a single waterfall pass -
there was never a real reason to run two separate Clay tables/exports for
data one enrichment call already provides together. One queue, one incoming
folder, one import function.

Real, honest uncertainty (same class as ADR-017's "Domain" capital-D
correction): Clay's exact exported column names for employee count and
industry/category depend on which enrichment provider column the user adds
in their Clay table, and aren't knowable until a real export exists. Built
with reasonable, flexible name-matching (a few real candidate names tried
in order) and documented here - confirmed against the user's real Company
Enrichment export (2026-07-13): "Employee Count", "Industry", "Website",
"Domain"/"domain" are all real, live-confirmed column names.
"""
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import psycopg2.errors

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import db  # noqa: E402

EXPORT_DIR = "data/clay"

# Companies still missing ANY of the fields Clay's "Company Enrichment"
# waterfall can fill in - domain, employee_count, is_saas - in one combined
# queue (mirrors sql/queries.sql's dedup-lookup spirit, kept in sync
# manually since one is raw SQL for humans/psql, the other is psycopg2-driven).
MISSING_ENRICHMENT_QUERY = """
    SELECT id, name, domain
    FROM companies
    WHERE domain IS NULL OR employee_count IS NULL OR is_saas IS NULL
    ORDER BY first_seen_at ASC;
"""


def get_companies_needing_enrichment(conn) -> list[dict]:
    """Companies still missing domain and/or employee_count/is_saas - the
    single Clay "Company Enrichment" queue."""
    with conn.cursor() as cur:
        cur.execute(MISSING_ENRICHMENT_QUERY)
        rows = cur.fetchall()
    return [{"company_id": row[0], "company_name": row[1], "domain": row[2]} for row in rows]


def export_companies_needing_enrichment(conn, export_dir: str = EXPORT_DIR) -> str:
    """Write a CSV of companies needing any enrichment, ready to import into
    a Clay table and run "Company Enrichment" on. Returns the file path
    written. Column order matters for Clay's CSV import mapping -
    company_id first so it survives the round-trip and lets
    import_enriched_dataset() match each enriched row back to the right
    Postgres row without re-guessing on name alone. domain is included
    (even when NULL for many rows) so Company Enrichment can use it when
    present - Clay's firmographic providers work more reliably off a real
    domain than a bare company name."""
    companies = get_companies_needing_enrichment(conn)

    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(export_dir, f"clay_enrichment_export_{timestamp}.csv")

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company_id", "company_name", "domain"])
        writer.writeheader()
        writer.writerows(companies)

    return path


# Keyword heuristic for deriving is_saas from Clay's industry/category text
# field (Clay/Clearbit-style providers give an industry classification, not
# a literal "is this SaaS" boolean) - same documented-heuristic spirit as
# funding_edgar.approximate_funding_stage(), not a fabricated fact. Checked
# in order; the first list that matches wins. A category that matches
# neither list leaves is_saas untouched (absence of evidence isn't evidence
# of absence - same principle already applied to INTENT scoring).
#
# "staffing"/"recruiting"/"government" added 2026-07-13 from real data: a
# live Company Enrichment export showed "Staffing and Recruiting" 9 times
# (Jobot, Robert Half, Salt, CultureMill, LaSalle Network, Tandym Group,
# Kforce, Optomi, Equal Platform Solutions) - the exact same non-ICP
# category hiring_adzuna.py's staffing-agency filter already excludes
# upstream, now recognized here too. "government" catches real cases like
# HM Revenue & Customs ("Government Administration").
SAAS_INDUSTRY_KEYWORDS = ["software", "saas", "internet", "computer software", "information technology"]
NON_SAAS_INDUSTRY_KEYWORDS = [
    "retail", "manufacturing", "restaurant", "construction", "healthcare services",
    "staffing", "recruiting", "government",
]

# Real candidate column names confirmed against the user's actual "Company
# Enrichment" export (2026-07-13, not just the original single-purpose
# demographic pass): "Employee Count"/"Industry" are the live, real names
# Clay's export uses. Other variants kept as a documented fallback in case
# a different enrichment provider column is used later.
EMPLOYEE_COUNT_COLUMNS = ["Employee Count", "employee_count", "Employees", "Estimated Employees"]
INDUSTRY_COLUMNS = ["Industry", "Category", "industry", "SIC Description"]


def _first_present(row: dict, candidate_columns: list[str]) -> str | None:
    for column in candidate_columns:
        value = row.get(column)
        if value:
            return value
    return None


def _parse_employee_count(raw_value: str | None) -> int | None:
    """Extracts the FIRST contiguous number found - handles a bare count
    ("250") and a real-shaped range ("501-1000", "~500", "500+") by taking
    its lower/only bound, not concatenating every digit in the string
    (a naive "keep all digits" approach would turn "501-1000" into the
    nonsensical 5011000)."""
    if not raw_value:
        return None
    match = re.search(r"\d+", raw_value)
    return int(match.group()) if match else None


def _derive_is_saas(industry_text: str | None) -> bool | None:
    if not industry_text:
        return None
    lowered = industry_text.lower()
    if any(keyword in lowered for keyword in SAAS_INDUSTRY_KEYWORDS):
        return True
    if any(keyword in lowered for keyword in NON_SAAS_INDUSTRY_KEYWORDS):
        return False
    return None


def _extract_domain_from_url(url: str | None) -> str | None:
    """Derives a bare domain (e.g. "smithmicro.com") from a full Website URL
    (e.g. "https://www.smithmicro.com") - "Company Enrichment" returns a
    real clickable Website URL, not a bare domain like the narrower domain-
    only enrichment used to. Strips a leading "www." only; otherwise trusts
    the URL as given - same "trusts Clay's output as-is, doesn't validate
    plausibility" stance already applied to the domain column (a real
    Website value can itself be wrong - a URL shortener or a careers-page
    deep link, both seen in a real export - not something this function
    tries to detect or correct)."""
    if not url:
        return None
    netloc = urlparse(url).netloc or urlparse(f"//{url}").netloc
    return netloc[4:] if netloc.startswith("www.") else netloc or None


def import_enriched_dataset(conn, csv_path: str) -> list[int]:
    """Reads Clay's "Company Enrichment" CSV export back in, and writes
    real domain/employee_count/is_saas onto each matching company row
    (matched by company_id, which round-trips through the export/import
    cycle - see export_companies_needing_enrichment()).

    Domain resolution order: the row's own "Domain"/"domain" column wins
    first (the CSV's own carried-through value, from export - the most
    directly known fact); falls back to deriving one from "Website" only
    when both are blank, so a fresh guess never overwrites a value the row
    itself already reports as known. employee_count/is_saas are parsed
    exactly as before (_parse_employee_count/_derive_is_saas). A row where
    NONE of domain/employee_count/is_saas is determinable is skipped
    entirely - nothing to write (matches Clay's own "❌ Company Not Found"
    real output for an unmatched company, confirmed against the user's
    actual export - such rows have every other column blank).

    Same UniqueViolation catch-and-skip-that-row protection built for the
    real, live-hit domain-collision bug (two different companies both
    mismatched to the same placeholder domain, e.g. several Chrome-
    extension-style Product Hunt launches both resolving to "google.com") -
    caught per-row, not fatal to the whole file, so one bad Clay row can't
    wedge the incoming-folder file in a permanent retry loop (see
    full_pipeline_run.py's poller). Returns the list of company ids updated.
    """
    updated_ids = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            domain = row.get("Domain") or row.get("domain") or _extract_domain_from_url(row.get("Website"))
            employee_count = _parse_employee_count(_first_present(row, EMPLOYEE_COUNT_COLUMNS))
            is_saas = _derive_is_saas(_first_present(row, INDUSTRY_COLUMNS))

            fields = {}
            if domain:
                fields["domain"] = domain
            if employee_count is not None:
                fields["employee_count"] = employee_count
            if is_saas is not None:
                fields["is_saas"] = is_saas

            if not fields:
                continue

            company_id = int(row["company_id"])
            try:
                db.update_company_by_id(conn, company_id, **fields)
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                continue
            updated_ids.append(company_id)

    return updated_ids


# Redesign v2, Tier 5/6: the "known folder" human-in-the-loop convention -
# the user drops a Clay-enriched CSV here (or uploads it to #clay-enrichment,
# see utils/discord_bot.py) and full_pipeline_run.py's background poller (or
# the next full run) picks it up automatically, no manual script invocation
# required. Files are moved to CLAY_PROCESSED_DIR after import so they're
# never re-imported on a later check.
CLAY_INCOMING_ENRICHMENT_DIR = "data/clay/incoming_enrichment"
CLAY_PROCESSED_DIR = "data/clay/processed"


def _process_incoming_files(conn, incoming_dir: str, import_fn, processed_dir: str = CLAY_PROCESSED_DIR) -> list[int]:
    """Scans incoming_dir for .csv files, runs import_fn(conn, path) on
    each, then moves the file into processed_dir - the "mark as done" step
    that keeps a later check from re-importing the same file. Returns the
    combined list of company ids updated across all files found."""
    os.makedirs(incoming_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)

    updated_ids: list[int] = []
    for filename in sorted(os.listdir(incoming_dir)):
        if not filename.endswith(".csv"):
            continue
        path = os.path.join(incoming_dir, filename)
        updated_ids.extend(import_fn(conn, path))
        os.rename(path, os.path.join(processed_dir, filename))

    return updated_ids


def process_incoming_enrichment(conn) -> list[int]:
    """Auto-pickup for the single enrichment queue."""
    return _process_incoming_files(conn, CLAY_INCOMING_ENRICHMENT_DIR, import_enriched_dataset)


def save_incoming_enrichment_file(filename: str, content: bytes) -> str:
    """Writes raw bytes (already downloaded from a Discord attachment) into
    the known-folder queue, timestamp-prefixing the filename (same
    convention export_companies_needing_enrichment() already uses for its
    own exports) so two uploads - even of the same original filename - can
    never collide or silently overwrite each other. Returns the full path
    written; the existing 60s poller (or an immediate resume_after_enrichment()
    call right after, for a faster response) picks it up exactly like a
    manually-dropped file - no special-casing needed downstream."""
    os.makedirs(CLAY_INCOMING_ENRICHMENT_DIR, exist_ok=True)

    # Microsecond precision (not just the export functions' second-precision
    # "%Y%m%dT%H%M%SZ") - two rapid back-to-back uploads of the same
    # original filename must never collide, and a real Discord upload burst
    # can easily land within the same second.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_filename = f"{timestamp}_{filename}"
    path = os.path.join(CLAY_INCOMING_ENRICHMENT_DIR, safe_filename)

    with open(path, "wb") as f:
        f.write(content)

    return path


if __name__ == "__main__":
    connection = db.get_connection()
    try:
        written_path = export_companies_needing_enrichment(connection)
        print(f"Exported companies needing enrichment to: {written_path}")
    finally:
        connection.close()
