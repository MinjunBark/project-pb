"""Branch B, Layer 1 (timing signal): broad PM-hiring discovery via Adzuna.

Replaces the Apify LinkedIn Jobs Scraper (ADR-010 in docs/DECISIONS.md) - Adzuna is
an official, free, key-based job search API, same posture as SEC EDGAR: no scraping,
no ToS gray area. Confirmed rate limits (2026-07-09): 25 req/min, 250/day, 1,000/week,
2,500/month on the free tier.

Adzuna returns company.display_name, not a website domain - the same domain
resolution gap already deferred to Clay for Branch A (ADR-008) applies here too.
Layer 2 (python/hiring_ats_lookup.py) deepens on the candidates this module finds.
"""
import os
import re
import time

import requests

SEARCH_URL_TEMPLATE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

DEFAULT_KEYWORDS = ["Product Manager", "Product Operations"]

# Free tier allows 25/min; stay comfortably under it across sequential keyword calls.
REQUEST_DELAY_SECONDS = 3.0

# Heuristic only, same documented-limitation spirit as funding_edgar.py's
# FUND_NAME_PATTERN: "Product Manager"/"Product Operations" are generic
# titles used across every industry, not a software-specific signal, so
# Adzuna's bare keyword search surfaces a lot of real, honest non-ICP
# noise - most reliably, staffing/recruiting agencies posting PM roles on
# behalf of an undisclosed third-party client. Those can never represent
# genuine buying intent for OUR product no matter how good a later
# Greenhouse/Lever slug guess is (hiring_ats_lookup.py), so excluding them
# here - before any ATS HTTP calls are wasted on them - is both more
# accurate and cheaper. Combines a regex on common industry-naming words
# with a curated list of known agency brand names (regex alone misses
# brand names with no literal "staffing"/"recruiting" in them, e.g.
# "Jobot", "RemX", "Beacon Talent" - real names found live in this
# project's own data, 2026-07-13). Documented limitation, not a fabricated
# classifier: a real staffing agency with an unusual name, or a real SaaS
# company whose name happens to contain one of these words, can still be
# mis-filtered either way - not attempting a "megacorp"/company-size
# filter here at all, since no real firmographic signal exists this early
# in the pipeline (only Clay's later per-company domain enrichment has
# that) - see docs/ISSUES.md for the full diagnosis this came from.
STAFFING_AGENCY_WORD_PATTERN = re.compile(
    r"\b(staffing|recruiting|recruitment|talent acquisition|personnel agency)\b", re.IGNORECASE
)
KNOWN_STAFFING_AGENCY_NAMES = {
    "robert half", "kelly services", "adecco", "randstad", "manpowergroup",
    "insight global", "aerotek", "teksystems", "robert walters", "michael page",
    "hays", "cybercoders", "vaco", "jobot", "remx", "mondo", "tandym", "tandym tech",
    "apex systems", "beacon talent", "optomi", "d24 search",
}


def _is_staffing_agency(company_name: str) -> bool:
    normalized = company_name.strip().lower()
    return bool(STAFFING_AGENCY_WORD_PATTERN.search(normalized)) or normalized in KNOWN_STAFFING_AGENCY_NAMES


def _credentials() -> tuple[str, str]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError("ADZUNA_APP_ID and ADZUNA_APP_KEY must both be set in .env")
    return app_id, app_key


def search_adzuna_jobs(
    keyword: str,
    country: str = "us",
    max_days_old: int = 60,
    results_per_page: int = 50,
    page: int = 1,
) -> list[dict]:
    """Search Adzuna for jobs matching a keyword, filtered to recent postings."""
    app_id, app_key = _credentials()

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": keyword,
        "max_days_old": max_days_old,
        "results_per_page": results_per_page,
    }
    url = SEARCH_URL_TEMPLATE.format(country=country, page=page)

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)

    return resp.json().get("results", [])


def normalize_adzuna_results(raw_results: list[dict]) -> list[dict]:
    """Group raw job results by company name (Adzuna gives no domain to dedupe on -
    that's resolved later by Clay, ADR-010). Also excludes staffing/recruiting
    agencies (see _is_staffing_agency() above) - they never represent real
    end-company buying intent, so they're dropped here rather than wasting
    a later ATS-lookup HTTP call on them."""
    by_company: dict[str, dict] = {}

    for job in raw_results:
        company_name = (job.get("company") or {}).get("display_name")
        if not company_name or _is_staffing_agency(company_name):
            continue

        if company_name not in by_company:
            by_company[company_name] = {
                "company_name": company_name,
                "job_titles": [],
                "pm_job_post_count": 0,
                "most_recent_posting_date": None,
                "location": (job.get("location") or {}).get("display_name"),
                "source": "adzuna",
            }

        entry = by_company[company_name]
        entry["pm_job_post_count"] += 1
        title = job.get("title")
        if title:
            entry["job_titles"].append(title)

        created = job.get("created")
        if created and (
            entry["most_recent_posting_date"] is None
            or created > entry["most_recent_posting_date"]
        ):
            entry["most_recent_posting_date"] = created

    return list(by_company.values())


def get_adzuna_hiring_signals(
    keywords: list[str] | None = None, lookback_days: int = 60
) -> list[dict]:
    """Full Layer 1 flow: search each keyword, normalize by company name."""
    keywords = keywords or DEFAULT_KEYWORDS

    all_raw_results = []
    for keyword in keywords:
        all_raw_results.extend(search_adzuna_jobs(keyword, max_days_old=lookback_days))

    return normalize_adzuna_results(all_raw_results)
