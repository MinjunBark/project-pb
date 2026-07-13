"""Phase 6: Clay enrichment via a CSV export/import round-trip (ADR-017).

Clay's live Webhook trigger is paid-only on the user's current plan, so this
is a batch flow instead of a real-time one: export companies missing a
domain -> import into a free Clay Blank table -> run waterfall enrichment
(name -> domain/employee_count/etc, Clearbit/Apollo/PDL-backed) -> export the
result -> import_enriched_companies() loads it back into Postgres.

Redesign v2, Tier 4 (demographic enrichment pass): a second round-trip,
same pattern, for scoring.py's DEMOGRAPHIC bucket - employee_count/is_saas
have been NULL for every real company since Phase 4 (score_demographic()
was always correctly wired into score_company(), it just contributes 0
points with no data - "not live" meant "no data," not "disconnected code").
export_companies_needing_demographics()/import_enriched_demographics() are
the export/import halves of that second pass, using domain (not just name)
as the lookup key this time, since Clay's firmographic providers are more
reliable keyed off a real domain than a bare company name.

Real, honest uncertainty (same class as ADR-017's "Domain" capital-D
correction): Clay's exact exported column names for employee count and
industry/category depend on which enrichment provider column the user adds
in their Clay table, and aren't knowable until a real export exists. Built
with reasonable, flexible name-matching (a few real candidate names tried
in order) and documented here - NOT assumed correct until confirmed against
a real Clay export, exactly like the domain column was.
"""
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2.errors

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import db  # noqa: E402

EXPORT_DIR = "data/clay"

# Mirrors sql/queries.sql's "Companies still missing a real domain" lookup -
# kept in sync manually since one is raw SQL for humans/psql, the other is
# psycopg2-driven for this script; both must stay logically identical.
MISSING_DOMAIN_QUERY = """
    SELECT id, name
    FROM companies
    WHERE domain IS NULL
    ORDER BY first_seen_at ASC;
"""


def get_companies_needing_domain(conn) -> list[dict]:
    """Companies with no domain yet - the Phase 6 enrichment queue."""
    with conn.cursor() as cur:
        cur.execute(MISSING_DOMAIN_QUERY)
        rows = cur.fetchall()
    return [{"company_id": row[0], "company_name": row[1]} for row in rows]


def export_companies_needing_domain(conn, export_dir: str = EXPORT_DIR) -> str:
    """Write a CSV of companies missing a domain, ready to import into Clay.
    Returns the file path written. Column order matters for Clay's CSV
    import mapping - company_id first so it survives the round-trip and
    lets import_enriched_companies() match each enriched row back to the
    right Postgres row without re-guessing on name alone."""
    companies = get_companies_needing_domain(conn)

    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(export_dir, f"clay_export_{timestamp}.csv")

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company_id", "company_name"])
        writer.writeheader()
        writer.writerows(companies)

    return path


def import_enriched_companies(conn, csv_path: str) -> list[int]:
    """Read Clay's enriched CSV export back in, and write each real domain
    onto its matching company row (matched by company_id, which round-trips
    through the export/import cycle - see export_companies_needing_domain()).

    Clay's exported column is "Domain" (capital D), not "domain" - real,
    confirmed against the user's actual export (2026-07-11), not assumed.
    Rows with no domain value are skipped (an enrichment miss for that
    company - nothing to write). Returns the list of company ids updated.

    Known limitation, not something this function tries to fix: waterfall
    enrichment can mismatch on generic-sounding company names and return an
    unrelated or placeholder domain (e.g. a Webflow staging subdomain when
    no real domain was found) - see docs/ISSUES.md. This function trusts
    Clay's output as-is; it does not validate domain plausibility.

    Real, live-hit case of that mismatch: two different companies can both
    get mismatched to the SAME placeholder domain (e.g. several Chrome-
    extension-style Product Hunt launches all resolving to "google.com").
    `companies.domain` is UNIQUE, so the second such row would violate that
    constraint. Caught per-row (not fatal to the whole file) and skipped -
    same "nothing to write, not a stop-the-world error" spirit as a missing
    domain value, so one bad Clay row can't wedge the incoming-folder file
    in a permanent retry loop (see full_pipeline_run.py's poller).
    """
    updated_ids = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            domain = row.get("Domain") or row.get("domain")
            if not domain:
                continue

            company_id = int(row["company_id"])
            try:
                db.update_company_by_id(conn, company_id, domain=domain)
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                continue
            updated_ids.append(company_id)

    return updated_ids


# Redesign v2, Tier 4: demographic enrichment queue - companies that already
# have a real domain (Phase 6 already ran) but are still missing
# employee_count or is_saas for scoring.py's DEMOGRAPHIC bucket.
MISSING_DEMOGRAPHICS_QUERY = """
    SELECT id, name, domain
    FROM companies
    WHERE domain IS NOT NULL AND (employee_count IS NULL OR is_saas IS NULL)
    ORDER BY first_seen_at ASC;
"""

# Keyword heuristic for deriving is_saas from Clay's industry/category text
# field (Clay/Clearbit-style providers give an industry classification, not
# a literal "is this SaaS" boolean) - same documented-heuristic spirit as
# funding_edgar.approximate_funding_stage(), not a fabricated fact. Checked
# in order; the first list that matches wins. A category that matches
# neither list leaves is_saas untouched (absence of evidence isn't evidence
# of absence - same principle already applied to INTENT scoring).
SAAS_INDUSTRY_KEYWORDS = ["software", "saas", "internet", "computer software", "information technology"]
NON_SAAS_INDUSTRY_KEYWORDS = ["retail", "manufacturing", "restaurant", "construction", "healthcare services"]

# Real candidate column names Clay's export might use - tried in order,
# first match wins. NOT confirmed against a real export yet (see module
# docstring) - update this list once the user's real Clay demographic
# enrichment table is exported, the same correction ADR-017 already made
# once for the domain column ("Domain", not "domain").
EMPLOYEE_COUNT_COLUMNS = ["Employee Count", "employee_count", "Employees", "Estimated Employees"]
INDUSTRY_COLUMNS = ["Industry", "Category", "industry", "SIC Description"]


def get_companies_needing_demographics(conn) -> list[dict]:
    """Companies with a real domain but no employee_count/is_saas yet - the
    demographic-pass enrichment queue."""
    with conn.cursor() as cur:
        cur.execute(MISSING_DEMOGRAPHICS_QUERY)
        rows = cur.fetchall()
    return [{"company_id": row[0], "company_name": row[1], "domain": row[2]} for row in rows]


def export_companies_needing_demographics(conn, export_dir: str = EXPORT_DIR) -> str:
    """Write a CSV of companies needing demographic enrichment, ready to
    import into a Clay table with a firmographic enrichment column added.
    Includes domain (unlike the original domain-enrichment export) since
    Clay's firmographic providers work more reliably off a real domain than
    a bare company name. Returns the file path written."""
    companies = get_companies_needing_demographics(conn)

    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(export_dir, f"clay_demographics_export_{timestamp}.csv")

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company_id", "company_name", "domain"])
        writer.writeheader()
        writer.writerows(companies)

    return path


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


def import_enriched_demographics(conn, csv_path: str) -> list[int]:
    """Reads Clay's demographic-enrichment CSV export back in, and writes
    real employee_count/is_saas onto each matching company row (matched by
    company_id, same round-trip pattern as import_enriched_companies()).

    employee_count is parsed from whichever candidate column is present
    (digits only, so "500-1000" or "~500" style ranges still yield a usable
    number - takes the first number found, not an average). is_saas is
    DERIVED from an industry/category text column via a documented keyword
    heuristic (SAAS_INDUSTRY_KEYWORDS/NON_SAAS_INDUSTRY_KEYWORDS) - Clay
    does not export a literal "is this SaaS" boolean. A row where neither
    value can be determined is skipped entirely (nothing to write - not
    written as a false/zero value, matching import_enriched_companies()'s
    same "skip on no real data" behavior). Returns the list of company ids
    updated."""
    updated_ids = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            employee_count = _parse_employee_count(_first_present(row, EMPLOYEE_COUNT_COLUMNS))
            is_saas = _derive_is_saas(_first_present(row, INDUSTRY_COLUMNS))

            fields = {}
            if employee_count is not None:
                fields["employee_count"] = employee_count
            if is_saas is not None:
                fields["is_saas"] = is_saas

            if not fields:
                continue

            company_id = int(row["company_id"])
            db.update_company_by_id(conn, company_id, **fields)
            updated_ids.append(company_id)

    return updated_ids


# Redesign v2, Tier 5: the "known folder" human-in-the-loop convention -
# the user drops a Clay-enriched CSV here and full_pipeline_run.py's
# background poller (or the next full run) picks it up automatically, no
# manual script invocation required. Files are moved to CLAY_PROCESSED_DIR
# after import so they're never re-imported on a later check.
CLAY_INCOMING_DOMAIN_DIR = "data/clay/incoming_domain"
CLAY_INCOMING_DEMOGRAPHICS_DIR = "data/clay/incoming_demographics"
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


def process_incoming_domain_enrichment(conn) -> list[int]:
    """Auto-pickup for domain enrichment - the domain-CSV half of the
    known-folder convention."""
    return _process_incoming_files(conn, CLAY_INCOMING_DOMAIN_DIR, import_enriched_companies)


def process_incoming_demographic_enrichment(conn) -> list[int]:
    """Auto-pickup for demographic enrichment - the demographics-CSV half
    of the known-folder convention."""
    return _process_incoming_files(conn, CLAY_INCOMING_DEMOGRAPHICS_DIR, import_enriched_demographics)


# Redesign v2, Tier 6: lets a Discord bot (utils/discord_bot.py) figure out
# which known-folder queue a real user upload belongs to, and land it there
# - without guessing from the attachment's filename alone, since Clay's own
# export step may have renamed the file by the time the user re-uploads it.
KNOWN_FOLDER_DIRS = {"domain": CLAY_INCOMING_DOMAIN_DIR, "demographics": CLAY_INCOMING_DEMOGRAPHICS_DIR}


def _detect_enrichment_kind(header: list[str]) -> str | None:
    """Real-content based classification (not filename-based): if the
    header contains any of the demographic candidate columns already used
    by import_enriched_demographics() (EMPLOYEE_COUNT_COLUMNS/
    INDUSTRY_COLUMNS), it's a demographics-enriched file - those columns
    only exist once Clay has added firmographic data on top of the
    original company_id/company_name/domain export. Otherwise, a "Domain"/
    "domain" column present means it's a domain-enriched file (the original
    export has no domain column at all - Clay adds it). Returns None if
    neither shape is recognized, so a caller can refuse to guess wrong
    rather than silently importing into the wrong queue.

    Known, honestly-flagged edge case: the demographics queue's own
    UNENRICHED export already has a lowercase "domain" column (see
    export_companies_needing_demographics()). If a user re-uploads that
    raw file by mistake (before running Clay enrichment on it), it would
    be misclassified as "domain" rather than rejected - harmless (re-writes
    already-correct domains, imports nothing new) but not flagged as an
    error either. Not worth extra heuristics for a low-probability mistake;
    documented here instead, same spirit as this file's other real,
    acknowledged uncertainties."""
    if set(header) & set(EMPLOYEE_COUNT_COLUMNS + INDUSTRY_COLUMNS):
        return "demographics"
    if any(h.lower() == "domain" for h in header):
        return "domain"
    return None


def save_incoming_enrichment_file(kind: str, filename: str, content: bytes) -> str:
    """Writes raw bytes (already downloaded from a Discord attachment) into
    the correct known-folder queue, timestamp-prefixing the filename (same
    convention export_companies_needing_domain() already uses for its own
    exports) so two uploads - even of the same original filename - can
    never collide or silently overwrite each other. Returns the full path
    written; the existing 60s poller (or an immediate resume_after_enrichment()
    call right after, for a faster response) picks it up exactly like a
    manually-dropped file - no special-casing needed downstream."""
    incoming_dir = KNOWN_FOLDER_DIRS[kind]
    os.makedirs(incoming_dir, exist_ok=True)

    # Microsecond precision (not just the export functions' second-precision
    # "%Y%m%dT%H%M%SZ") - two rapid back-to-back uploads of the same
    # original filename must never collide, and a real Discord upload burst
    # can easily land within the same second.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_filename = f"{timestamp}_{filename}"
    path = os.path.join(incoming_dir, safe_filename)

    with open(path, "wb") as f:
        f.write(content)

    return path


if __name__ == "__main__":
    import sys as _sys

    connection = db.get_connection()
    try:
        if "--demographics" in _sys.argv:
            written_path = export_companies_needing_demographics(connection)
            print(f"Exported companies needing demographic enrichment to: {written_path}")
        else:
            written_path = export_companies_needing_domain(connection)
            print(f"Exported companies needing a domain to: {written_path}")
    finally:
        connection.close()
