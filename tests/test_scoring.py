"""Tests for python/scoring.py - Phase 4's ICP scoring.

Every test below is written to guard a specific real design decision or bug
class discussed while planning this phase, not just to exercise the code.
See the docstring on each test for what it checks and why.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import scoring  # noqa: E402

TODAY = scoring.date(2026, 7, 10)


def _company(**overrides) -> dict:
    base = {
        "funding_stage": None,
        "funding_date": None,
        "employee_count": None,
        "is_saas": None,
        "is_existing_customer": False,
        "current_tool_mentioned": None,
    }
    base.update(overrides)
    return base


def _hiring_signal(job_titles: list[str], posted_at: str, category: str = "pm_hiring") -> dict:
    return {"signal_category": category, "raw_text": ", ".join(job_titles), "posted_at": posted_at, "created_at": posted_at}


def _buying_intent_signal(matched_phrase: str, posted_at: str = "2026-07-01") -> dict:
    return {
        "signal_category": "buying_intent",
        "raw_text": matched_phrase,
        "posted_at": posted_at,
        "created_at": posted_at,
    }


# ---------------------------------------------------------------------------
# TIMING bucket
# ---------------------------------------------------------------------------


def test_recent_series_b_funding_and_two_pm_postings_score_full_timing_points():
    """The core 'hot lead' case: funded 30 days ago (Series B, well within the
    90-day tier) + 2 PM postings 10 days ago. Confirms both timing sub-scores
    fire at their top band together (25 + 15 = 40), not just individually."""
    company = _company(funding_stage="Series B", funding_date="2026-06-10")
    signals = [_hiring_signal(["Senior Product Manager", "Product Manager"], "2026-06-30")]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert result["points"] == 40
    assert result["detail"] == {"funding_recency": 25, "pm_posting_count": 15}


def test_funding_older_than_180_days_earns_no_recency_points():
    """Guards the recency cutoff itself: a company funded 200 days ago must
    NOT still earn timing points just because it once qualified. Without this
    boundary check, a bug that drops the days_since comparison would let
    every funded company score full timing points forever."""
    company = _company(funding_stage="Series B", funding_date="2025-12-23")  # ~200 days before TODAY

    result = scoring.score_timing(company, [], today=TODAY)

    assert result["points"] == 0
    assert "funding_recency" not in result["detail"]


def test_stale_pm_hiring_signal_beyond_60_days_is_not_counted():
    """A pm_hiring signal from 90 days ago (older than the 60-day hiring
    lookback) must not count toward current hiring velocity - otherwise a
    company that hired once, long ago, would look like it's actively
    scaling today."""
    company = _company()
    signals = [_hiring_signal(["Product Manager"], "2026-04-10")]  # ~90 days before TODAY

    result = scoring.score_timing(company, signals, today=TODAY)

    assert result["points"] == 0


def test_product_ops_bonus_awarded_for_dedicated_ops_title():
    """'Product Operations Lead' unambiguously signals a dedicated ops hire -
    should earn both the general PM-posting-count points AND the Product Ops
    bonus, since these represent two genuinely different facts (team is
    growing, AND specifically wants a dedicated ops role)."""
    company = _company()
    signals = [_hiring_signal(["Product Operations Lead"], "2026-07-01")]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert result["detail"]["pm_posting_count"] == 8
    assert result["detail"]["product_ops_posting"] == 10


def test_product_ops_bonus_excludes_titles_that_also_say_manager():
    """The agreed fix: a title like 'Product Operations Manager' contains
    BOTH 'operations' and 'manager' - ambiguous whether it's a true
    dedicated-ops signal or just another manager-level posting. Must only
    earn the general PM-count points, not the Product Ops bonus, otherwise
    one posting inflates the score by double-counting the same fact."""
    company = _company()
    signals = [_hiring_signal(["Product Operations Manager"], "2026-07-01")]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert result["detail"]["pm_posting_count"] == 8
    assert "product_ops_posting" not in result["detail"]


def test_latest_pm_hiring_signal_used_ignoring_older_accumulated_rows():
    """merge_signals.py appends a new pm_hiring signal row every merge run
    (no overwrite) - a company can accumulate several over time. This checks
    that only the MOST RECENT row (by posted_at) drives scoring, so an old
    run's data doesn't get double-counted or wrongly override current
    activity."""
    company = _company()
    signals = [
        _hiring_signal(["Product Manager", "Product Manager", "Product Manager"], "2026-03-01"),  # stale, 3 titles
        _hiring_signal(["Product Manager"], "2026-07-01"),  # latest, 1 title
    ]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert result["detail"]["pm_posting_count"] == 8  # 1 posting band, not the stale 3-posting band


def test_recent_product_launch_earns_timing_points():
    """Redesign v2, Tier 1 (Product Hunt / Branch D): a launch within the
    30-day lookback window earns TIMING points, same recency-based
    reasoning as funding."""
    company = _company()
    signals = [{"signal_category": "product_launch", "raw_text": "Roadmaps that write themselves", "posted_at": "2026-06-25", "created_at": "2026-06-25"}]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert result["detail"]["recent_product_launch"] == 10


def test_stale_product_launch_beyond_30_days_earns_no_points():
    company = _company()
    signals = [{"signal_category": "product_launch", "raw_text": "x", "posted_at": "2026-05-01", "created_at": "2026-05-01"}]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert "recent_product_launch" not in result["detail"]


def test_recent_leadership_hire_earns_timing_points():
    """Redesign v2, Tier 1 (leadership-page diffing): a new product-
    leadership hire within the 90-day lookback window earns TIMING points -
    same recency-based reasoning as funding, since a fresh decision-maker
    is a timing/urgency signal, not evidence of buying intent."""
    company = _company()
    signals = [{"signal_category": "leadership_hire", "raw_text": "Jane Doe (VP Product)", "posted_at": "2026-06-01", "created_at": "2026-06-01"}]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert result["detail"]["new_leadership_hire"] == 15


def test_stale_leadership_hire_beyond_90_days_earns_no_points():
    company = _company()
    signals = [{"signal_category": "leadership_hire", "raw_text": "x", "posted_at": "2026-03-01", "created_at": "2026-03-01"}]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert "new_leadership_hire" not in result["detail"]


def test_timing_bucket_caps_at_50_when_every_sub_bonus_fires_together():
    """With a fourth TIMING contributor now possible (funding_recency 25 +
    pm_posting_count 15 + product_ops_posting 10 + recent_product_launch 10
    = 60 uncapped), confirms the explicit min(50) guard actually holds."""
    company = _company(funding_stage="Series B", funding_date="2026-06-10")
    signals = [
        _hiring_signal(["Senior Product Manager", "Product Operations Lead"], "2026-06-30"),
        {"signal_category": "product_launch", "raw_text": "x", "posted_at": "2026-06-25", "created_at": "2026-06-25"},
    ]

    result = scoring.score_timing(company, signals, today=TODAY)

    assert result["points"] == 50


# ---------------------------------------------------------------------------
# INTENT bucket
# ---------------------------------------------------------------------------


def test_intent_scores_high_band_using_real_aha_calibration_data():
    """Calibration check: the real 2026-07-10 G2 test found Aha! had a
    13/60 = 21.7% switch-signal rate. This confirms that exact real ratio
    lands in the HIGH severity band (>=20%), which is what the band
    threshold was chosen against."""
    company = _company(current_tool_mentioned="Aha!")
    competitor_intel = {"Aha!": {"switch_signal_count": 13, "total_reviews_seen": 60}}

    result = scoring.score_intent(company, [], competitor_intel)

    assert result["points"] == 40


def test_intent_medium_and_low_severity_bands():
    """Confirms the band boundaries themselves are correctly ordered (a
    common off-by-one risk with >= comparisons): exactly 10% -> medium (25),
    just under 10% -> low (15)."""
    medium = scoring.score_intent(
        _company(current_tool_mentioned="X"), [], {"X": {"switch_signal_count": 10, "total_reviews_seen": 100}}
    )
    low = scoring.score_intent(
        _company(current_tool_mentioned="X"), [], {"X": {"switch_signal_count": 5, "total_reviews_seen": 100}}
    )

    assert medium["points"] == 25
    assert low["points"] == 15


def test_intent_scores_zero_without_penalty_when_no_tool_identified():
    """Core design decision from our discussion: a company where we simply
    don't know their current tool (untracked competitor, or nothing found)
    must score exactly 0 INTENT points - not negative. Absence of evidence
    isn't evidence of absence; we must not punish companies for a gap in
    our own detection coverage."""
    company = _company(current_tool_mentioned=None)

    result = scoring.score_intent(company, [], {"Aha!": {"switch_signal_count": 13, "total_reviews_seen": 60}})

    assert result["points"] == 0
    assert result["detail"] == {}


def test_intent_awards_weak_base_points_when_tool_known_but_no_corpus_data_yet():
    """A company's tool was identified (ADR-013 scan matched), but the G2
    scrape for that specific competitor hasn't landed any reviews yet
    (empty/missing competitor_intel entry). This is real, if weak, evidence
    - should score a small flat amount, not the same as 'no tool found'."""
    company = _company(current_tool_mentioned="Craft.io")

    result = scoring.score_intent(company, [], competitor_intel={})

    assert result["points"] == 10


def test_intent_scores_via_buying_intent_language_alone_when_no_tool_identified():
    """Redesign v2, Tier 1: a company with no current_tool_mentioned at all
    can still earn INTENT points if a job posting's own text contains
    explicit buying-intent language - a genuinely different evidence path
    than the G2-corpus-based competitor severity scoring above."""
    company = _company(current_tool_mentioned=None)
    signals = [_buying_intent_signal("evaluate and select our PM tool stack")]

    result = scoring.score_intent(company, signals, competitor_intel={})

    assert result["points"] == 10
    assert result["detail"] == {"buying_intent_language": 10}


def test_intent_bucket_caps_at_40_when_both_tool_severity_and_buying_intent_present():
    """A company already at the HIGH severity band (40 pts) that ALSO has a
    buying-intent signal must not exceed the bucket's documented 40-point
    max - confirms the min() guard added when a second INTENT contributor
    was introduced actually holds, not just that it was written."""
    company = _company(current_tool_mentioned="Aha!")
    competitor_intel = {"Aha!": {"switch_signal_count": 13, "total_reviews_seen": 60}}
    signals = [_buying_intent_signal("no formalized product ops function yet")]

    result = scoring.score_intent(company, signals, competitor_intel)

    assert result["points"] == 40
    assert result["detail"]["buying_intent_language"] == 10
    assert result["detail"]["competitor_severity"] == 40


# ---------------------------------------------------------------------------
# DEMOGRAPHIC + DEDUCTIONS
# ---------------------------------------------------------------------------


def test_demographic_saas_confirmation_only():
    """Recalibrated 2026-07-13: the employee-count band bonus was removed
    (real named Productboard customers range ~1,800-95,000 employees per
    redesign/01-trigger-prompt-filled-productboard.md's real research -
    too wide a range for company size to be a meaningful positive signal).
    Only the is_saas confirmation bonus remains."""
    saas_co = scoring.score_demographic(_company(employee_count=120, is_saas=True))
    non_saas_co = scoring.score_demographic(_company(employee_count=350, is_saas=False))
    huge_real_customer_shaped_co = scoring.score_demographic(_company(employee_count=70000, is_saas=True))

    assert saas_co["points"] == 10
    assert non_saas_co["points"] == 0
    assert huge_real_customer_shaped_co["points"] == 10  # a Salesforce-scale employee count earns no penalty


def test_deductions_existing_customer_and_tiny_company_size():
    """Recalibrated 2026-07-13: removed the employee_count > 1000 and
    is_saas is False deductions - real named Productboard customers
    (1,800-95,000 employees, including non-SaaS industries like gaming and
    medical devices) would have been penalized by both. Only the <20
    lower-bound size deduction and the existing-customer deduction remain."""
    company = _company(is_existing_customer=True, employee_count=5, is_saas=False)

    result = scoring.score_deductions(company)

    assert result["points"] == -100 + -20
    assert "non_saas" not in result["detail"]


def test_deductions_do_not_penalize_a_real_enterprise_scale_employee_count():
    """A Medtronic/Salesforce-scale company (tens of thousands of employees)
    must not be penalized - this was the exact real-world case the old
    >1000 deduction got wrong."""
    company = _company(employee_count=95000, is_saas=False)

    result = scoring.score_deductions(company)

    assert result["points"] == 0
    assert result["detail"] == {}


# ---------------------------------------------------------------------------
# Full score_company() integration
# ---------------------------------------------------------------------------


def test_company_with_both_timing_and_intent_earns_bonus_and_qualifies():
    """The highest-priority bucket per the blueprint: a company hitting both
    TIMING and INTENT should be tagged 'BOTH', earn the +10 bonus on top of
    both buckets' own points, and clear the >=70 qualifying threshold."""
    company = _company(
        funding_stage="Series B", funding_date="2026-06-10", current_tool_mentioned="Aha!"
    )
    signals = [_hiring_signal(["Senior Product Manager", "Product Manager"], "2026-06-30")]
    competitor_intel = {"Aha!": {"switch_signal_count": 13, "total_reviews_seen": 60}}

    result = scoring.score_company(company, signals, competitor_intel, today=TODAY)

    assert result["signal_type"] == "BOTH"
    assert result["score_breakdown"]["both_signal_bonus"] == 10
    assert result["icp_score"] == 40 + 40 + 10  # timing + intent + bonus
    assert result["qualified"] is True


def test_company_with_only_timing_signal_is_tagged_timing_and_not_bonused():
    """Confirms the bonus does NOT fire for a single-signal-type company, and
    that signal_type correctly reflects TIMING-only rather than defaulting
    to BOTH or INTENT."""
    company = _company(funding_stage="Series B", funding_date="2026-06-10")

    result = scoring.score_company(company, [], today=TODAY)

    assert result["signal_type"] == "TIMING"
    assert result["score_breakdown"]["both_signal_bonus"] == 0


def test_company_with_no_signals_is_tagged_none_and_does_not_qualify():
    """Baseline sanity check: a company with no timing or intent evidence at
    all must score low enough to fail the >=70 threshold and be tagged
    'NONE', not accidentally qualify via deductions/demographic alone."""
    company = _company()

    result = scoring.score_company(company, [], today=TODAY)

    assert result["signal_type"] == "NONE"
    assert result["qualified"] is False
