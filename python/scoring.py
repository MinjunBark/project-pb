"""Phase 4: ICP scoring. Turns one company's row + its signal history into a
single icp_score (gates the pipeline at >=70) and a breakdown of where the
points came from.

Adapted from the original blueprint's formula (gtm-signal-blueprint.md
section 4) to match what our real branches actually produce - see the
2026-07-10 plan notes for the full discussion:

  - INTENT points come from ADR-013's current_tool_mentioned (job-description
    tool scan) scaled by that competitor's severity in competitor_intel, NOT
    a per-company G2 star rating (structurally impossible - G2 reviews are
    anonymous, ADR-012). Reddit/LinkedIn intent signals were dropped
    entirely and are not scored.
  - The "posted Product Ops role" bonus only counts a posting whose title
    says "operations" without also saying "manager", so one posting can't
    earn credit in both the general PM-count bucket and this bonus.
  - Demographic fit (employee_count, is_saas) is fully implemented per the
    blueprint, but every real company row has these as NULL until Phase 7's
    Clay enrichment exists - this module is not wired into any live
    orchestration yet. It's written and tested now so nothing blocks later.
  - "No existing Product Ops role found" (+5 in the original blueprint) is
    NOT implemented: we have no data source that tells us whether a company
    already employs someone in that role (would require something like a
    LinkedIn people-search, which was dropped per ADR-010's safety review).
    Rather than guess, this sub-bonus is omitted - documented gap, not a
    made-up value.
"""
from datetime import date, datetime

FUNDING_RECENT_DAYS_TIER1 = 90
FUNDING_RECENT_DAYS_TIER2 = 180
PM_POSTING_LOOKBACK_DAYS = 60

# Redesign v2, Tier 1: recency window for a fresh Product Hunt launch (TIMING
# bucket, same recency-based reasoning as funding - a dated, real momentum
# event, not evidence of buying intent).
PRODUCT_LAUNCH_LOOKBACK_DAYS = 30
PRODUCT_LAUNCH_POINTS = 10

# Redesign v2, Tier 1: recency window for a fresh product-leadership hire
# (TIMING bucket - a new decision-maker with fresh budget/mandate is a
# timing/urgency signal, not evidence of buying intent).
LEADERSHIP_HIRE_LOOKBACK_DAYS = 90
LEADERSHIP_HIRE_POINTS = 15

TIMING_BUCKET_MAX = 50

# Blueprint says "Raised Series A/B" for the timing recency bonus. Our
# approximate_funding_stage() bands (funding_edgar.py) don't map 1:1 onto
# named rounds, so this is our documented interpretation: any stage in the
# ICP's eligible range (Series A/B/C per gtm-signal-blueprint.md section 3)
# earns the recency bonus, not just literal "Series A/B" labels.
QUALIFYING_FUNDING_STAGES = {"Seed/Series A", "Series B", "Series C"}

# Severity bands for INTENT scoring, calibrated against the one real dataset
# we have (2026-07-10 live G2 test): Aha! had a 13/60 = 21.7% switch-signal
# rate. Banded rather than linear-scaled, since a straight ratio*40 formula
# would under-weight a 21.7% rate (real, meaningfully high pain evidence) to
# a mere ~9 points - bands avoid over-interpreting small-sample precision.
SEVERITY_BAND_HIGH = 0.20
SEVERITY_BAND_MEDIUM = 0.10

ICP_SCORE_THRESHOLD = 70


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _days_since(value, today: date) -> int | None:
    parsed = _parse_date(value)
    return (today - parsed).days if parsed else None


def _latest_signal(signals: list[dict], category: str) -> dict | None:
    """Most recent signal row in a category, by posted_at (fallback:
    created_at). A company can accumulate many pm_hiring rows across repeat
    merge runs - only the latest represents current hiring activity."""
    matches = [s for s in signals if s.get("signal_category") == category]
    if not matches:
        return None
    return max(matches, key=lambda s: s.get("posted_at") or s.get("created_at") or "")


def _job_titles_from_signal(signal: dict) -> list[str]:
    """merge_signals.py stores job titles as a comma-joined string in
    raw_text - split back into a list."""
    raw_text = signal.get("raw_text")
    return [title.strip() for title in raw_text.split(",")] if raw_text else []


def score_timing(company: dict, signals: list[dict], today: date | None = None) -> dict:
    """TIMING bucket, max 50 pts: recent funding + PM hiring velocity."""
    today = today or date.today()
    points = 0
    detail = {}

    funding_stage = company.get("funding_stage")
    days_since_funding = _days_since(company.get("funding_date"), today)
    if funding_stage in QUALIFYING_FUNDING_STAGES and days_since_funding is not None:
        if days_since_funding <= FUNDING_RECENT_DAYS_TIER1:
            points += 25
            detail["funding_recency"] = 25
        elif days_since_funding <= FUNDING_RECENT_DAYS_TIER2:
            points += 15
            detail["funding_recency"] = 15

    hiring_signal = _latest_signal(signals, "pm_hiring")
    if hiring_signal:
        days_since_posting = _days_since(hiring_signal.get("posted_at"), today)
        if days_since_posting is not None and days_since_posting <= PM_POSTING_LOOKBACK_DAYS:
            titles = _job_titles_from_signal(hiring_signal)
            posting_count = len(titles)
            if posting_count >= 2:
                points += 15
                detail["pm_posting_count"] = 15
            elif posting_count == 1:
                points += 8
                detail["pm_posting_count"] = 8

            # Agreed fix: only count a title toward the Product Ops bonus if
            # it says "operations" without also saying "manager" - otherwise
            # one posting (e.g. "Product Operations Lead") would separately
            # earn both the PM-count points above AND this bonus.
            has_dedicated_ops_posting = any(
                "operations" in title.lower() and "manager" not in title.lower()
                for title in titles
            )
            if has_dedicated_ops_posting:
                points += 10
                detail["product_ops_posting"] = 10

    launch_signal = _latest_signal(signals, "product_launch")
    if launch_signal:
        days_since_launch = _days_since(launch_signal.get("posted_at"), today)
        if days_since_launch is not None and days_since_launch <= PRODUCT_LAUNCH_LOOKBACK_DAYS:
            points += PRODUCT_LAUNCH_POINTS
            detail["recent_product_launch"] = PRODUCT_LAUNCH_POINTS

    leadership_signal = _latest_signal(signals, "leadership_hire")
    if leadership_signal:
        days_since_hire = _days_since(leadership_signal.get("posted_at"), today)
        if days_since_hire is not None and days_since_hire <= LEADERSHIP_HIRE_LOOKBACK_DAYS:
            points += LEADERSHIP_HIRE_POINTS
            detail["new_leadership_hire"] = LEADERSHIP_HIRE_POINTS

    # Explicit cap, added once a fourth TIMING sub-bonus existed (funding
    # recency + pm posting count + product ops posting + product launch, now
    # also leadership hire) - previously implicit since no combination of
    # the first three could exceed 50 on its own; no longer true now.
    return {"points": min(points, TIMING_BUCKET_MAX), "detail": detail}


def score_intent(company: dict, signals: list[dict], competitor_intel: dict[str, dict] | None = None) -> dict:
    """INTENT bucket, max 40 pts: current_tool_mentioned (ADR-013) scaled by
    that competitor's severity in the G2 pain-point corpus (ADR-012), plus a
    flat bonus (redesign v2, Tier 1) when a job posting's own text contains
    explicit buying-intent language (see hiring_ats_lookup.classify_buying_intent).
    Capped at 40 total - both contributors can independently reach the cap,
    so a min() guard is required now that there's more than one path in."""
    competitor_intel = competitor_intel or {}
    current_tool = company.get("current_tool_mentioned")
    points = 0
    detail: dict = {}

    if not current_tool:
        pass
    else:
        intel = competitor_intel.get(current_tool)
        if not intel or not intel.get("total_reviews_seen"):
            # We know they use a tracked competitor, but have no corpus data
            # on it yet (e.g. G2 scrape hasn't run for that competitor) -
            # weak but real evidence, not nothing.
            points += 10
            detail["tool_mentioned_no_corpus_data"] = 10
        else:
            severity_ratio = intel["switch_signal_count"] / intel["total_reviews_seen"]
            if severity_ratio >= SEVERITY_BAND_HIGH:
                severity_points = 40
            elif severity_ratio >= SEVERITY_BAND_MEDIUM:
                severity_points = 25
            else:
                severity_points = 15
            points += severity_points
            detail["competitor_severity"] = severity_points
            detail["severity_ratio"] = round(severity_ratio, 3)

    buying_intent_signal = _latest_signal(signals, "buying_intent")
    if buying_intent_signal:
        points += 10
        detail["buying_intent_language"] = 10

    return {"points": min(points, 40), "detail": detail}


def score_demographic(company: dict) -> dict:
    """DEMOGRAPHIC bucket, max 10 pts.

    Recalibrated 2026-07-13: the original blueprint's employee-count band
    bonus (50-200/200-500 employees) was built against the ORIGINAL
    project blueprint's assumed ICP (50-500 employees, Series A-C) - the
    real, researched ICP (redesign/01-trigger-prompt-filled-productboard.md,
    a real GTM engineer's trigger-prompt research, not the stale original
    blueprint) shows real named Productboard customers (Autodesk, Salesforce,
    Zoom, Ubisoft, Medtronic, OutSystems) span roughly 1,800 to 95,000
    employees - too wide a real range for company size to be a meaningful
    positive differentiator, so the band bonus was removed entirely rather
    than guessed at with new arbitrary numbers.

    The is_saas bonus is kept (a software/SaaS company may still be a
    somewhat faster/easier sale even though real customers aren't
    exclusively SaaS - Ubisoft/Medtronic prove non-SaaS isn't disqualifying,
    but that's a different claim than "SaaS status carries zero signal")."""
    points = 0
    detail = {}

    if company.get("is_saas") is True:
        points += 10
        detail["confirmed_saas"] = 10

    return {"points": points, "detail": detail}


def score_deductions(company: dict) -> dict:
    """Recalibrated 2026-07-13 (see score_demographic()'s docstring for the
    full real-evidence citation): removed the employee_count > 1000
    deduction and the is_saas is False deduction entirely - every one of
    Productboard's real named customers (1,800-95,000 employees; several
    non-SaaS industries like gaming and medical devices) would have been
    penalized by the old thresholds, which were never actually validated
    against real Productboard data - they came from the original project
    blueprint's own assumed ICP, not from research. The <20 lower bound is
    kept - a company that small is still genuinely unlikely to be a
    plausible near-term enterprise PM-tooling buyer regardless of segment."""
    points = 0
    detail = {}

    if company.get("is_existing_customer"):
        points -= 100
        detail["existing_customer"] = -100

    employee_count = company.get("employee_count")
    if employee_count is not None and employee_count < 20:
        points -= 20
        detail["company_size_out_of_range"] = -20

    return {"points": points, "detail": detail}


def score_company(
    company: dict,
    signals: list[dict],
    competitor_intel: dict[str, dict] | None = None,
    today: date | None = None,
) -> dict:
    """Full Phase 4 flow: score all buckets, apply the BOTH-signal bonus and
    deductions, and tag signal_type. Returns icp_score + score_breakdown +
    signal_type, ready to write to the leads table (once a caller exists)."""
    timing = score_timing(company, signals, today=today)
    intent = score_intent(company, signals, competitor_intel=competitor_intel)
    demographic = score_demographic(company)
    deductions = score_deductions(company)

    has_timing = timing["points"] > 0
    has_intent = intent["points"] > 0

    both_signal_bonus = 10 if (has_timing and has_intent) else 0

    if has_timing and has_intent:
        signal_type = "BOTH"
    elif has_timing:
        signal_type = "TIMING"
    elif has_intent:
        signal_type = "INTENT"
    else:
        signal_type = "NONE"

    icp_score = timing["points"] + intent["points"] + demographic["points"] + deductions["points"] + both_signal_bonus

    return {
        "icp_score": icp_score,
        "qualified": icp_score >= ICP_SCORE_THRESHOLD,
        "signal_type": signal_type,
        "score_breakdown": {
            "timing": timing["detail"],
            "intent": intent["detail"],
            "demographic": demographic["detail"],
            "deductions": deductions["detail"],
            "both_signal_bonus": both_signal_bonus,
        },
    }
