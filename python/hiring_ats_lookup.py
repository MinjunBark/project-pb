"""Branch B, Layer 2 (timing signal): deepen on Adzuna candidates via Greenhouse/Lever.

Both APIs are official, free, public, read-only, no auth required - verified live
2026-07-09 (see docs/ISSUES.md): Greenhouse returns a clean 404 for an unknown board
token; Lever also returns a clean 404 with {"ok": false, "error": "Document not found"}
for an unknown client name, and a bare JSON array (possibly empty) for a valid one.

Per-company board token/client name is guessed from the company name - this is a
documented heuristic (ADR-010), not guaranteed to resolve. When neither Greenhouse
nor Lever resolves, callers should fall back to Adzuna's data alone for that company.
"""
import re
import time

import requests

GREENHOUSE_URL_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_URL_TEMPLATE = "https://api.lever.co/v0/postings/{client}?mode=json"

PM_TITLE_PATTERN = re.compile(r"product\s+(manager|operations)", re.IGNORECASE)

REQUEST_DELAY_SECONDS = 0.2


def generate_candidate_slugs(company_name: str) -> list[str]:
    """Guess a company's Greenhouse board token / Lever client name from its name.

    Heuristic only (ADR-010) - strips common suffixes and tries a few common
    slug conventions. Order matters: most-likely guesses first, since callers
    stop at the first hit.
    """
    name = company_name.lower()
    name = re.sub(r"\b(inc|llc|corp|corporation|ltd|co)\.?\b", "", name)
    name = name.strip()

    no_spaces = re.sub(r"[^a-z0-9]", "", name)
    hyphenated = re.sub(r"[^a-z0-9]+", "-", name).strip("-")

    candidates = [no_spaces, hyphenated]
    # dedupe while preserving order
    seen = set()
    unique = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def try_greenhouse(company_name: str) -> dict | None:
    """Try each candidate slug against Greenhouse's public Job Board API.
    Returns {"matched_slug": ..., "raw_jobs": [...]} on first hit, else None."""
    for slug in generate_candidate_slugs(company_name):
        url = GREENHOUSE_URL_TEMPLATE.format(token=slug)
        resp = requests.get(url, timeout=10)
        time.sleep(REQUEST_DELAY_SECONDS)

        if resp.status_code == 200:
            jobs = resp.json().get("jobs", [])
            return {"matched_slug": slug, "raw_jobs": jobs}

    return None


def try_lever(company_name: str) -> dict | None:
    """Try each candidate slug against Lever's public Postings API.
    Returns {"matched_slug": ..., "raw_postings": [...]} on first hit, else None."""
    for slug in generate_candidate_slugs(company_name):
        url = LEVER_URL_TEMPLATE.format(client=slug)
        resp = requests.get(url, timeout=10)
        time.sleep(REQUEST_DELAY_SECONDS)

        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return {"matched_slug": slug, "raw_postings": data}

    return None


def _normalize_greenhouse_jobs(raw_jobs: list[dict]) -> list[dict]:
    return [
        {
            "title": job.get("title"),
            "location": (job.get("location") or {}).get("name"),
            "posted_date": job.get("first_published"),
            "url": job.get("absolute_url"),
        }
        for job in raw_jobs
    ]


def _normalize_lever_postings(raw_postings: list[dict]) -> list[dict]:
    return [
        {
            "title": posting.get("text"),
            "location": (posting.get("categories") or {}).get("location"),
            "posted_date": None,  # Lever's public fields don't include a reliable date
            "url": posting.get("hostedUrl"),
        }
        for posting in raw_postings
    ]


def enrich_company_with_ats_data(company_name: str) -> dict:
    """Layer 2 entry point: try Greenhouse, then Lever, for one company.

    Returns the full job list plus which PM-relevant postings were found. If
    neither ATS resolves, source is None - caller falls back to Adzuna-only data.
    """
    greenhouse_result = try_greenhouse(company_name)
    if greenhouse_result:
        all_jobs = _normalize_greenhouse_jobs(greenhouse_result["raw_jobs"])
        source = "greenhouse"
        matched_slug = greenhouse_result["matched_slug"]
    else:
        lever_result = try_lever(company_name)
        if lever_result:
            all_jobs = _normalize_lever_postings(lever_result["raw_postings"])
            source = "lever"
            matched_slug = lever_result["matched_slug"]
        else:
            return {"source": None, "matched_slug": None, "pm_postings": []}

    pm_postings = [job for job in all_jobs if job["title"] and PM_TITLE_PATTERN.search(job["title"])]

    return {"source": source, "matched_slug": matched_slug, "pm_postings": pm_postings}
