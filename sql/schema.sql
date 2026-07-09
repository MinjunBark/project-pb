-- GTM Signal Engine schema
-- Replaces the flat-file seen_companies.json dedup approach from the original blueprint
-- with a real relational store: companies (dedup + demographic fit), signals (raw
-- per-source events), leads (scored + enriched + outreach-ready output).

CREATE TABLE IF NOT EXISTS companies (
    id                      SERIAL PRIMARY KEY,
    domain                  TEXT UNIQUE NOT NULL,
    name                    TEXT NOT NULL,
    employee_count          INTEGER,
    funding_stage           TEXT,
    funding_date            DATE,
    funding_amount_usd      BIGINT,
    industry                TEXT,
    is_saas                 BOOLEAN,
    is_existing_customer    BOOLEAN DEFAULT FALSE,
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
    id                      SERIAL PRIMARY KEY,
    company_id              INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source                  TEXT NOT NULL,   -- crunchbase | apify_linkedin | apify_g2
    signal_category         TEXT NOT NULL,   -- funding | pm_hiring | competitor_review
    raw_text                TEXT,
    star_rating             SMALLINT,
    competitor_mentioned    TEXT,
    posted_at               DATE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS leads (
    id                          SERIAL PRIMARY KEY,
    company_id                  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    icp_score                   INTEGER NOT NULL,
    score_breakdown             JSONB,
    signal_type                 TEXT NOT NULL,  -- TIMING | INTENT | BOTH
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

CREATE INDEX IF NOT EXISTS idx_signals_company_id ON signals(company_id);
CREATE INDEX IF NOT EXISTS idx_leads_company_id ON leads(company_id);
CREATE INDEX IF NOT EXISTS idx_companies_last_seen_at ON companies(last_seen_at);
