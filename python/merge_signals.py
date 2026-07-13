"""Phase 3 merge/dedupe orchestration: takes each branch's raw signal output
(live, or reloaded from python/raw_landing.py's local landing zone) and writes
it into the live Postgres database via utils/db.py.

This is what replaces the original blueprint's flat-file seen_companies.json:
dedup now happens in Postgres via companies.normalized_name (utils/db.py's
upsert_company), not an in-memory/JSON set of names checked at runtime.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
from raw_landing import load_latest_raw_signals  # noqa: E402

BRANCH_A_LANDING_NAME = "branch_a"
BRANCH_B_LANDING_NAME = "branch_b"
BRANCH_C_LANDING_NAME = "branch_c"
BRANCH_D_LANDING_NAME = "branch_d"

# Cap stored quotes per competitor - the pain-point corpus can accumulate many
# switch-signal reviews across repeated runs; representative_quotes is meant
# for Phase 8 outreach-prompt reference material, not an unbounded archive.
MAX_QUOTES_PER_COMPETITOR = 10


def merge_funding_signals(conn, funding_signals: list[dict]) -> list[int]:
    """Branch A (SEC EDGAR): upsert each company's funding fields, then log a
    `funding` signal event. Returns the list of company ids touched."""
    company_ids = []
    for signal in funding_signals:
        company_id = db.upsert_company(
            conn,
            signal["company_name"],
            funding_stage=signal.get("funding_stage"),
            funding_date=signal.get("funding_date"),
            funding_amount_usd=signal.get("funding_amount_usd"),
            industry=signal.get("industry"),
            biz_location=signal.get("biz_location"),
        )
        db.insert_signal(
            conn,
            company_id,
            source=signal.get("source", "sec_edgar_form_d"),
            signal_category="funding",
            posted_at=signal.get("funding_date"),
        )
        company_ids.append(company_id)
    return company_ids


def merge_hiring_signals(conn, hiring_signals: list[dict]) -> list[int]:
    """Branch B (Adzuna/Greenhouse/Lever): upsert each company, recording
    current_tool_mentioned when ADR-013's job-description scan found one, then
    log a `pm_hiring` signal event. Returns the list of company ids touched.

    current_tool_mentioned is only passed to upsert_company when the scan
    actually found something - an empty scan result must not overwrite a
    tool already recorded by an earlier run for the same company."""
    company_ids = []
    for signal in hiring_signals:
        company_fields = {}
        tools_mentioned = signal.get("current_tools_mentioned") or []
        if tools_mentioned:
            company_fields["current_tool_mentioned"] = ", ".join(tools_mentioned)

        company_id = db.upsert_company(conn, signal["company_name"], **company_fields)
        db.insert_signal(
            conn,
            company_id,
            source=signal.get("source", "adzuna"),
            signal_category="pm_hiring",
            raw_text=", ".join(signal.get("job_titles") or []) or None,
            posted_at=signal.get("most_recent_posting_date"),
        )

        # Redesign v2, Tier 1: a distinct signal_category, not an extra field
        # on the pm_hiring row - only inserted when the classifier actually
        # found buying-intent language, so a null/negative result never
        # writes a row (no accidental positive-signal noise).
        buying_intent = signal.get("buying_intent")
        if buying_intent and buying_intent.get("buying_intent_detected"):
            db.insert_signal(
                conn,
                company_id,
                source=signal.get("source", "adzuna"),
                signal_category="buying_intent",
                raw_text=buying_intent.get("matched_phrase"),
                posted_at=signal.get("most_recent_posting_date"),
            )

        company_ids.append(company_id)
    return company_ids


def merge_attributed_reviews(conn, attributed_reviews: list[dict]) -> list[int]:
    """Branch C reviews that Phase 5's classify.py successfully attributed to
    a real company (the rare case - ADR-012) - these flow into the normal
    per-company signal pipeline exactly like Branch A/B, making them eligible
    for scoring.py's INTENT points and the BOTH-signal bonus. Reviews with no
    attribution (attributed_company is None - the common case) are skipped
    here; they're still captured in the aggregate corpus via
    merge_intent_signals(). Returns the list of company ids touched."""
    company_ids = []
    for review in attributed_reviews:
        company_name = review.get("attributed_company")
        if not company_name:
            continue

        company_id = db.upsert_company(conn, company_name)
        db.insert_signal(
            conn,
            company_id,
            source="g2",
            signal_category="competitor_review",
            raw_text=review.get("text"),
            star_rating=review.get("star_rating"),
            competitor_mentioned=review.get("competitor"),
            posted_at=review.get("posted_date"),
        )
        company_ids.append(company_id)
    return company_ids


def merge_intent_signals(conn, normalized_reviews: list[dict]) -> list[int]:
    """Branch C (G2), rewritten 2026-07-12 (ADR-021) to accumulate rather
    than replace: inserts any genuinely new reviews into g2_reviews (deduped
    by review_id, safe against overlapping scrape batches - a periodic
    re-scrape that re-fetches some already-seen reviews is harmless), then
    RECOMPUTES each touched competitor's competitor_intel row from the full
    accumulated history, not just this run's batch. This means a periodic
    Branch C run captures new/recent reviews and grows the dataset over
    time, instead of each run silently overwriting prior history with
    whatever the latest scrape happened to contain. Returns the list of
    competitor_intel row ids touched."""
    touched_competitors: set[str] = set()
    for review in normalized_reviews:
        db.upsert_g2_review(conn, review)
        touched_competitors.add(review["competitor"])

    row_ids = []
    for competitor in touched_competitors:
        aggregate = db.get_competitor_intel_aggregate(conn, competitor, quote_limit=MAX_QUOTES_PER_COMPETITOR)
        row_id = db.upsert_competitor_intel(conn, competitor, **aggregate)
        row_ids.append(row_id)
    return row_ids


def merge_launch_signals(conn, launch_signals: list[dict]) -> list[int]:
    """Branch D (Product Hunt, redesign v2 Tier 1): upsert each launched
    product/company (name-based match - see producthunt_launches.py's
    docstring on the real, unmeasured match-rate uncertainty), then log a
    `product_launch` signal event. Returns the list of company ids touched."""
    company_ids = []
    for signal in launch_signals:
        company_id = db.upsert_company(conn, signal["company_name"])
        db.insert_signal(
            conn,
            company_id,
            source=signal.get("source", "producthunt"),
            signal_category="product_launch",
            raw_text=signal.get("tagline"),
            posted_at=signal.get("launched_at"),
        )
        company_ids.append(company_id)
    return company_ids


def run_full_merge(
    conn,
    funding_signals: list[dict] | None = None,
    hiring_signals: list[dict] | None = None,
    normalized_reviews: list[dict] | None = None,
    launch_signals: list[dict] | None = None,
) -> dict:
    """Full Phase 3 merge: for any branch not passed in directly, reload its
    most recently landed raw file (python/raw_landing.py) instead of
    re-hitting rate-limited APIs. Returns a summary of what was merged."""
    if funding_signals is None:
        funding_signals = load_latest_raw_signals(BRANCH_A_LANDING_NAME) or []
    if hiring_signals is None:
        hiring_signals = load_latest_raw_signals(BRANCH_B_LANDING_NAME) or []
    if normalized_reviews is None:
        loaded = load_latest_raw_signals(BRANCH_C_LANDING_NAME) or {}
        normalized_reviews = loaded.get("reviews", []) if isinstance(loaded, dict) else []
    if launch_signals is None:
        launch_signals = load_latest_raw_signals(BRANCH_D_LANDING_NAME) or []

    funding_company_ids = merge_funding_signals(conn, funding_signals)
    hiring_company_ids = merge_hiring_signals(conn, hiring_signals)
    competitor_intel_ids = merge_intent_signals(conn, normalized_reviews)
    launch_company_ids = merge_launch_signals(conn, launch_signals)

    return {
        "companies_from_funding": len(funding_company_ids),
        "companies_from_hiring": len(hiring_company_ids),
        "competitors_updated": len(competitor_intel_ids),
        "companies_from_launches": len(launch_company_ids),
        "distinct_company_ids": len(
            set(funding_company_ids) | set(hiring_company_ids) | set(launch_company_ids)
        ),
    }
