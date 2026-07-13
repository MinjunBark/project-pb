"""Postgres (Supabase-hosted, ADR-004) connection helper and company dedup logic.

Replaces the flat-file seen_companies.json approach with real SQL. See
docs/DECISIONS.md ADR-004 for why Supabase, and the 2026-07-10 plan notes for
why `companies.domain` is nullable with `normalized_name` as the interim
dedup key (domain gets backfilled by Clay in Phase 7).
"""
import os
import re

import psycopg2
import psycopg2.extras

SCHEMA_PATH = "sql/schema.sql"

_SUFFIX_PATTERN = re.compile(r"\b(inc|llc|corp|corporation|ltd|co|company)\.?\b", re.IGNORECASE)


def get_connection():
    """Open a new connection using DATABASE_URL from the environment."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set in .env")
    return psycopg2.connect(database_url)


def normalize_company_name(name: str) -> str:
    """Lowercase, strip common suffixes and punctuation - the interim dedup
    key used before a real domain is known (see schema.sql comment)."""
    normalized = name.lower()
    normalized = _SUFFIX_PATTERN.sub("", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def apply_schema(conn, schema_path: str = SCHEMA_PATH) -> None:
    """Run sql/schema.sql against the given connection. Idempotent - every
    statement is CREATE TABLE/INDEX IF NOT EXISTS."""
    with open(schema_path) as f:
        schema_sql = f.read()

    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()


def upsert_company(conn, name: str, **fields) -> int:
    """Insert a company, or update it if its normalized_name already exists.
    Returns the company's id. `fields` may include any of: domain,
    employee_count, funding_stage, funding_date, funding_amount_usd, industry,
    biz_location, current_tool_mentioned, is_saas."""
    normalized_name = normalize_company_name(name)

    columns = ["normalized_name", "name"] + list(fields.keys())
    values = [normalized_name, name] + list(fields.values())
    placeholders = ["%s"] * len(values)

    update_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in fields) if fields else "name = EXCLUDED.name"

    query = f"""
        INSERT INTO companies ({", ".join(columns)})
        VALUES ({", ".join(placeholders)})
        ON CONFLICT (normalized_name) DO UPDATE SET
            {update_clause},
            last_seen_at = now()
        RETURNING id;
    """

    with conn.cursor() as cur:
        cur.execute(query, values)
        company_id = cur.fetchone()[0]
    conn.commit()

    return company_id


def update_company_by_id(conn, company_id: int, **fields) -> None:
    """Update an existing company row directly by its known id - used by
    Phase 6's Clay enrichment import, where company_id round-trips through
    the export/import CSV (python/enrichment.py) and is the authoritative
    match key, not normalized_name. Unlike upsert_company, this never
    inserts - the row is expected to already exist."""
    if not fields:
        return

    set_clause = ", ".join(f"{col} = %s" for col in fields)
    values = list(fields.values()) + [company_id]

    query = f"""
        UPDATE companies SET
            {set_clause},
            last_seen_at = now()
        WHERE id = %s;
    """

    with conn.cursor() as cur:
        cur.execute(query, values)
    conn.commit()


def has_recent_lead(conn, company_id: int, within_days: int) -> bool:
    """True if this company already has a leads row created within the
    last `within_days` days - wires up the blueprint's DEDUP_WINDOW_DAYS
    env var (defined since Phase 0 but never actually used until Phase 9's
    n8n scheduling prep, 2026-07-12). Prevents re-processing (real Gemini
    calls, real HubSpot writes) the same still-qualifying company on every
    scheduled run."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM leads WHERE company_id = %s AND created_at >= now() - (%s || ' days')::interval LIMIT 1;",
            (company_id, within_days),
        )
        return cur.fetchone() is not None


def insert_lead(conn, company_id: int, icp_score: int, signal_type: str, **fields) -> int:
    """Insert one lead row - Phase 9's output-fan-out record, tying a
    company to its final score, signal_type, and generated outreach copy.
    `fields` may include any of: score_breakdown (dict, stored as JSONB),
    priority_summary, contact_name/title/email, email_confidence,
    outreach_email_subject_a/b, outreach_email_body, outreach_linkedin,
    outreach_call_script, hubspot_company_id, hubspot_contact_id. Returns
    the lead's id."""
    if "score_breakdown" in fields:
        fields["score_breakdown"] = psycopg2.extras.Json(fields["score_breakdown"])

    columns = ["company_id", "icp_score", "signal_type"] + list(fields.keys())
    values = [company_id, icp_score, signal_type] + list(fields.values())
    placeholders = ["%s"] * len(values)

    query = f"""
        INSERT INTO leads ({", ".join(columns)})
        VALUES ({", ".join(placeholders)})
        RETURNING id;
    """

    with conn.cursor() as cur:
        cur.execute(query, values)
        lead_id = cur.fetchone()[0]
    conn.commit()

    return lead_id


def upsert_g2_review(conn, review: dict) -> bool:
    """Insert one G2 review if not already seen (review_id UNIQUE). Returns
    True if newly inserted, False if it already existed - safe to call
    repeatedly on overlapping scrape batches (2026-07-12 Branch C
    scheduling design, see docs/DECISIONS.md ADR-021)."""
    query = """
        INSERT INTO g2_reviews (
            review_id, competitor, star_rating, is_negative, is_switch_signal,
            switch_reason, review_text, reviewer_country, posted_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (review_id) DO NOTHING
        RETURNING id;
    """
    values = [
        review.get("review_id"),
        review.get("competitor"),
        review.get("star_rating"),
        review.get("is_negative", False),
        review.get("is_switch_signal", False),
        review.get("switch_reason"),
        review.get("text"),
        review.get("reviewer_country"),
        review.get("posted_date"),
    ]

    with conn.cursor() as cur:
        cur.execute(query, values)
        row = cur.fetchone()
    conn.commit()

    return row is not None


def get_competitor_intel_aggregate(conn, competitor: str, quote_limit: int = 10) -> dict:
    """Recomputes a competitor's aggregate stats from the FULL g2_reviews
    history, not a single scrape batch - the read side of the
    accumulate-don't-replace design (ADR-021). Representative quotes are the
    most recent switch-signal reviews, capped at quote_limit."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(is_negative::int), 0), COALESCE(SUM(is_switch_signal::int), 0)
            FROM g2_reviews WHERE competitor = %s;
            """,
            (competitor,),
        )
        total, negative, switch = cur.fetchone()

        cur.execute(
            """
            SELECT review_text, switch_reason, star_rating
            FROM g2_reviews
            WHERE competitor = %s AND is_switch_signal = TRUE AND review_text IS NOT NULL
            ORDER BY posted_date DESC NULLS LAST
            LIMIT %s;
            """,
            (competitor, quote_limit),
        )
        quotes = [
            {"text": text[:400], "switch_reason": reason, "star_rating": rating}
            for text, reason, rating in cur.fetchall()
        ]

    return {
        "total_reviews_seen": total,
        "negative_review_count": negative,
        "switch_signal_count": switch,
        "representative_quotes": quotes,
    }


def get_all_companies(conn) -> list[dict]:
    """All company rows - used by the /pipeline/run-all batch endpoint
    (Phase 9 n8n prep, 2026-07-12) to score every company in one pass."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM companies;")
        return [dict(row) for row in cur.fetchall()]


def get_signals_for_company(conn, company_id: int) -> list[dict]:
    """All signal rows for one company - paired with get_all_companies()
    for batch scoring."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM signals WHERE company_id = %s;", (company_id,))
        return [dict(row) for row in cur.fetchall()]


def get_all_competitor_intel(conn) -> dict[str, dict]:
    """All competitor_intel rows, keyed by competitor name - the shape
    scoring.score_intent() and pipeline.build_lead_context() expect."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM competitor_intel;")
        rows = [dict(row) for row in cur.fetchall()]
    return {row["competitor"]: row for row in rows}


def get_company_by_normalized_name(conn, name: str) -> dict | None:
    """Look up a company by its normalized name. Returns a dict of the row,
    or None if not found."""
    normalized_name = normalize_company_name(name)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM companies WHERE normalized_name = %s;", (normalized_name,))
        row = cur.fetchone()

    return dict(row) if row else None


def insert_signal(conn, company_id: int, source: str, signal_category: str, **fields) -> int:
    """Insert one raw signal event tied to a company (Branch A funding events,
    Branch B pm_hiring events, or the rare Branch C review attributable to a
    company). `fields` may include any of: raw_text, star_rating,
    competitor_mentioned, posted_at. Returns the signal's id."""
    columns = ["company_id", "source", "signal_category"] + list(fields.keys())
    values = [company_id, source, signal_category] + list(fields.values())
    placeholders = ["%s"] * len(values)

    query = f"""
        INSERT INTO signals ({", ".join(columns)})
        VALUES ({", ".join(placeholders)})
        RETURNING id;
    """

    with conn.cursor() as cur:
        cur.execute(query, values)
        signal_id = cur.fetchone()[0]
    conn.commit()

    return signal_id


def get_latest_leadership_snapshot(conn, company_id: int) -> dict | None:
    """Most recent leadership-page snapshot for a company (redesign v2, Tier
    1), or None if this company has never been snapshotted. The diff
    baseline python/leadership_monitor.py compares each new fetch against."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT * FROM company_leadership_snapshots
            WHERE company_id = %s
            ORDER BY snapshotted_at DESC
            LIMIT 1;
            """,
            (company_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def insert_leadership_snapshot(
    conn, company_id: int, page_url: str, content_hash: str, detected_names: list[dict]
) -> int:
    """Records a new leadership-page snapshot (redesign v2, Tier 1) - always
    inserted (never updated in place), so get_latest_leadership_snapshot()
    can walk the history if ever needed. Returns the new row's id."""
    query = """
        INSERT INTO company_leadership_snapshots (company_id, page_url, content_hash, detected_names)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
    """
    with conn.cursor() as cur:
        cur.execute(query, [company_id, page_url, content_hash, psycopg2.extras.Json(detected_names)])
        snapshot_id = cur.fetchone()[0]
    conn.commit()

    return snapshot_id


def upsert_competitor_intel(conn, competitor: str, **fields) -> int:
    """Insert or replace a competitor's pain-point corpus entry (Branch C's
    primary output, ADR-012). `fields` may include any of:
    total_reviews_seen, negative_review_count, switch_signal_count,
    representative_quotes (a list - stored as JSONB). Returns the row's id.

    Unlike upsert_company, this is a full replace on conflict (not an
    incremental merge) - callers pass the freshly recomputed corpus totals
    for a competitor each run, since build_pain_point_corpus() in
    python/intent_g2.py already aggregates across that run's full review set."""
    if "representative_quotes" in fields:
        fields["representative_quotes"] = psycopg2.extras.Json(fields["representative_quotes"])

    columns = ["competitor"] + list(fields.keys())
    values = [competitor] + list(fields.values())
    placeholders = ["%s"] * len(values)

    update_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in fields) if fields else "competitor = EXCLUDED.competitor"

    query = f"""
        INSERT INTO competitor_intel ({", ".join(columns)})
        VALUES ({", ".join(placeholders)})
        ON CONFLICT (competitor) DO UPDATE SET
            {update_clause},
            last_updated_at = now()
        RETURNING id;
    """

    with conn.cursor() as cur:
        cur.execute(query, values)
        row_id = cur.fetchone()[0]
    conn.commit()

    return row_id
