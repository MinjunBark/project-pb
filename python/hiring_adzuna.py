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
import time

import requests

SEARCH_URL_TEMPLATE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

DEFAULT_KEYWORDS = ["Product Manager", "Product Operations"]

# Free tier allows 25/min; stay comfortably under it across sequential keyword calls.
REQUEST_DELAY_SECONDS = 3.0


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
    that's resolved later by Clay, ADR-010)."""
    by_company: dict[str, dict] = {}

    for job in raw_results:
        company_name = (job.get("company") or {}).get("display_name")
        if not company_name:
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
