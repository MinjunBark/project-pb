-- GTM Signal Engine - dedup lookup + reporting queries.
-- These are the read-side counterpart to utils/db.py and python/merge_signals.py:
-- that code writes/dedupes into companies/signals/competitor_intel; the queries
-- below are what a human (or Phase 4's scoring API) reads back out.

-- ============================================================
-- Dedup lookups
-- ============================================================

-- Look up a single company by its interim dedup key (mirrors
-- utils/db.py's get_company_by_normalized_name, useful for ad-hoc checks).
-- :normalized_name e.g. 'acme'
SELECT * FROM companies WHERE normalized_name = :normalized_name;

-- Companies still missing a real domain - the Phase 7 Clay/Apollo backfill
-- queue. Ordered oldest-first so the earliest-collected leads get enriched first.
SELECT id, name, normalized_name, first_seen_at
FROM companies
WHERE domain IS NULL
ORDER BY first_seen_at ASC;

-- ============================================================
-- Signal-type reporting (feeds Phase 4's scoring: TIMING / INTENT / BOTH)
-- ============================================================

-- Every company that currently has a funding signal (TIMING).
SELECT DISTINCT c.id, c.name, c.funding_stage, c.funding_date
FROM companies c
JOIN signals s ON s.company_id = c.id
WHERE s.signal_category = 'funding';

-- Every company that currently has a pm_hiring signal (also TIMING).
SELECT DISTINCT c.id, c.name, c.current_tool_mentioned
FROM companies c
JOIN signals s ON s.company_id = c.id
WHERE s.signal_category = 'pm_hiring';

-- BOTH-signal companies: funded AND hiring for PMs - the scoring model's
-- highest-priority bucket, per the original blueprint's signal_type tagging.
SELECT c.id, c.name, c.funding_stage, c.funding_amount_usd, c.current_tool_mentioned
FROM companies c
WHERE EXISTS (SELECT 1 FROM signals s WHERE s.company_id = c.id AND s.signal_category = 'funding')
  AND EXISTS (SELECT 1 FROM signals s WHERE s.company_id = c.id AND s.signal_category = 'pm_hiring');

-- Companies where Branch B's job-description scan (ADR-013) found a named
-- competitor tool - these are the leads whose outreach can pull that specific
-- competitor's slice of the G2 pain-point corpus instead of generic messaging.
SELECT c.id, c.name, c.current_tool_mentioned, ci.negative_review_count, ci.representative_quotes
FROM companies c
JOIN competitor_intel ci ON ci.competitor = c.current_tool_mentioned
WHERE c.current_tool_mentioned IS NOT NULL;

-- ============================================================
-- Branch C reporting (G2 pain-point corpus - not per-company, see ADR-012)
-- ============================================================

-- Current competitive-intel snapshot, most-switched-from competitor first -
-- direct input to Phase 8's outreach generation.
SELECT competitor, total_reviews_seen, negative_review_count, switch_signal_count, last_updated_at
FROM competitor_intel
ORDER BY switch_signal_count DESC;

-- ============================================================
-- Pipeline health / funnel counts
-- ============================================================

-- Companies collected per day, by which signal source first introduced them -
-- a basic funnel-volume sanity check across Branch A/B.
SELECT date_trunc('day', first_seen_at) AS day, s.source, COUNT(DISTINCT c.id) AS companies
FROM companies c
JOIN signals s ON s.company_id = c.id
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- US-only ICP sanity check (2026-07-10 requirement) - any company whose
-- biz_location isn't a "City, ST" pair slipped past funding_edgar.py's
-- is_us_location() filter and needs investigating.
SELECT id, name, biz_location
FROM companies
WHERE biz_location IS NOT NULL
  AND biz_location !~ ', [A-Z]{2}$';
