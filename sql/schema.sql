-- GTM Signal Engine schema
-- Replaces the flat-file seen_companies.json dedup approach from the original blueprint
-- with a real relational store: companies (dedup + demographic fit), signals (raw
-- per-source events), leads (scored + enriched + outreach-ready output).

-- domain is nullable and backfilled later (Phase 7, Clay/Apollo waterfall
-- enrichment) - neither Branch A (EDGAR) nor Branch B (Adzuna/Greenhouse/Lever)
-- produces a domain at collection time. normalized_name (lowercased, suffixes
-- stripped) is the interim dedup key until a real domain is known. Postgres
-- UNIQUE allows multiple NULLs, so this is safe pre-enrichment.
CREATE TABLE IF NOT EXISTS companies (
    id                      SERIAL PRIMARY KEY,
    normalized_name         TEXT UNIQUE NOT NULL,
    name                    TEXT NOT NULL,
    domain                  TEXT UNIQUE,
    employee_count          INTEGER,
    funding_stage           TEXT,
    funding_date            DATE,
    funding_amount_usd      BIGINT,
    industry                TEXT,
    biz_location            TEXT,            -- for US-only ICP filtering + auditing
    current_tool_mentioned  TEXT,            -- from Branch B job-description scan (ADR-013)
    is_saas                 BOOLEAN,
    is_existing_customer    BOOLEAN DEFAULT FALSE,
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
    id                      SERIAL PRIMARY KEY,
    company_id              INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source                  TEXT NOT NULL,   -- sec_edgar_form_d | adzuna | greenhouse | lever | g2
    signal_category         TEXT NOT NULL,   -- funding | pm_hiring | competitor_review
    raw_text                TEXT,
    star_rating             SMALLINT,
    competitor_mentioned    TEXT,
    posted_at               DATE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Branch C's primary output (ADR-012): per-competitor pain-point corpus, NOT
-- per-company. Most G2 reviews can't be attributed to a specific company
-- (reviews are anonymous by design), so this is a separate reference table
-- Phase 8's outreach generation queries directly - the rare case where a
-- review IS attributable to a company still goes through the normal
-- `signals` table above like any Branch A/B signal.
CREATE TABLE IF NOT EXISTS competitor_intel (
    id                      SERIAL PRIMARY KEY,
    competitor              TEXT UNIQUE NOT NULL,
    total_reviews_seen      INTEGER NOT NULL DEFAULT 0,
    negative_review_count   INTEGER NOT NULL DEFAULT 0,
    switch_signal_count     INTEGER NOT NULL DEFAULT 0,
    representative_quotes   JSONB,
    last_updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Individual G2 reviews (2026-07-12 addition): tracks every review ever
-- seen, keyed by review_id, so a periodic re-scrape can safely capture new
-- reviews without losing or double-counting history. competitor_intel above
-- is now a RECOMPUTED aggregate derived from this table (see
-- get_competitor_intel_aggregate() in utils/db.py), not a wholesale
-- snapshot of whatever the latest scrape batch happened to contain -
-- running the scraper again and getting some already-seen reviews back is
-- harmless, they just fail to insert (ON CONFLICT DO NOTHING).
CREATE TABLE IF NOT EXISTS g2_reviews (
    id                  SERIAL PRIMARY KEY,
    review_id           TEXT UNIQUE NOT NULL,
    competitor          TEXT NOT NULL,
    star_rating         SMALLINT,
    is_negative         BOOLEAN NOT NULL DEFAULT FALSE,
    is_switch_signal    BOOLEAN NOT NULL DEFAULT FALSE,
    switch_reason       TEXT,
    review_text         TEXT,
    reviewer_country    TEXT,
    posted_date         DATE,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_g2_reviews_competitor ON g2_reviews(competitor);

CREATE TABLE IF NOT EXISTS leads (
    id                          SERIAL PRIMARY KEY,
    company_id                  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    icp_score                   INTEGER NOT NULL,
    score_breakdown             JSONB,
    signal_type                 TEXT NOT NULL,  -- TIMING | INTENT | BOTH
    priority_summary            TEXT,           -- Phase 8/ADR-019, user-requested "why contact now" rationale
    contact_name                TEXT,
    contact_title                TEXT,
    contact_email               TEXT,
    email_confidence            INTEGER,
    outreach_email_subject_a    TEXT,
    outreach_email_subject_b    TEXT,
    outreach_email_body         TEXT,
    outreach_linkedin           TEXT,
    outreach_call_script         TEXT,
    hubspot_company_id          TEXT,
    hubspot_contact_id          TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ADD COLUMN IF NOT EXISTS so re-applying this schema against an
-- already-live database (created before priority_summary existed) picks up
-- the new column without a separate migration file - apply_schema() in
-- utils/db.py runs this whole file every time, idempotently.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS priority_summary TEXT;

CREATE INDEX IF NOT EXISTS idx_signals_company_id ON signals(company_id);
CREATE INDEX IF NOT EXISTS idx_leads_company_id ON leads(company_id);
CREATE INDEX IF NOT EXISTS idx_companies_last_seen_at ON companies(last_seen_at);

-- Redesign v2, Tier 1 (leadership-page diffing): durable snapshot state a
-- new decision-maker hire can be diffed against on the NEXT run. This is
-- fundamentally different from every table above - it's not a raw event log
-- like `signals`, it's a point-in-time snapshot per company, kept so
-- python/leadership_monitor.py can tell "changed since last time" without
-- re-classifying an unchanged page (content_hash short-circuits the Gemini
-- call). Only ever populated for companies with a known domain (see
-- leadership_monitor.py's module docstring on that real limitation).
CREATE TABLE IF NOT EXISTS company_leadership_snapshots (
    id                  SERIAL PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    page_url            TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    detected_names      JSONB,
    snapshotted_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leadership_snapshots_company_id ON company_leadership_snapshots(company_id);
