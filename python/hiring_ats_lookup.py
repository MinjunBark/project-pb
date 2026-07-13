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
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

from gemini import generate_content  # noqa: E402
from gemini import parse_json_response as _parse_json_response  # noqa: E402

GREENHOUSE_URL_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
LEVER_URL_TEMPLATE = "https://api.lever.co/v0/postings/{client}?mode=json"

PM_TITLE_PATTERN = re.compile(r"product\s+(manager|operations)", re.IGNORECASE)

REQUEST_DELAY_SECONDS = 0.2

# Job-description tool-mention scan (2026-07-10 plan notes): PM job postings
# sometimes explicitly name the team's current tools (e.g. "experience with
# Jira, Aha!, or similar roadmapping tools"). This is the one genuinely
# per-company signal we can connect to Branch C's G2 pain-point corpus later,
# since G2 reviews themselves can't carry company identity (ADR-012).
# "Aha" alone is a common word (see docs/ISSUES.md HN findings) - require the
# exclamation mark or "roadmaps" to avoid false positives in formal job-post text.
COMPETITOR_TOOL_PATTERNS = {
    "Aha!": re.compile(r"\baha!|aha\s+roadmaps", re.IGNORECASE),
    "Jira Product Discovery": re.compile(r"jira\s+product\s+discovery", re.IGNORECASE),
    "ProductPlan": re.compile(r"productplan", re.IGNORECASE),
    "Craft.io": re.compile(r"craft\.io", re.IGNORECASE),
}


def scan_for_competitor_tools(text: str | None) -> list[str]:
    """Scan job title + description text for explicit mentions of our named
    competitors. Returns the list of competitors mentioned (usually empty)."""
    if not text:
        return []
    return [name for name, pattern in COMPETITOR_TOOL_PATTERNS.items() if pattern.search(text)]


# Redesign v2, Tier 1 (see redesign/03-creative-signal-approaches.md): mining
# job-posting TEXT for literal buying-intent phrasing, not just counting that
# a PM posting exists or scanning for named competitor tools. Same data we
# already fetch (Greenhouse/Lever description text) - a new question asked
# of it, not a new external source. Mirrors classify.py's exact pattern
# (prompt template + cost guard + generate_content + parse_json_response),
# kept in this module rather than classify.py since that module is scoped to
# G2 review company-attribution (ADR-015) - a different, unrelated LLM task.
BUYING_INTENT_PROMPT_TEMPLATE = """You are analyzing a Product Manager job posting to determine whether it signals that the hiring company is actively evaluating or has not yet formalized its product management tooling/process. Only flag this if the text EXPLICITLY suggests the company is choosing, evaluating, or lacks a formal PM tool/process (e.g. "will define our roadmap process from scratch", "evaluate and select our PM tool stack", "no formalized product ops function yet", "help us build our PM tooling as we scale"). Do not guess, and do not infer buying intent merely from the existence of a PM hiring posting - most PM job posts do NOT contain this signal.

Job posting text:
{posting_text}

Return ONLY strict JSON, no other text, in exactly this shape:
{{"buying_intent_detected": true or false, "matched_phrase": "the exact phrase from the text" or null}}"""


def build_buying_intent_prompt(posting_text: str) -> str:
    return BUYING_INTENT_PROMPT_TEMPLATE.format(posting_text=posting_text)


def classify_buying_intent(posting_text: str | None) -> dict | None:
    """Cost guard on blank text (never calls Gemini for nothing). Returns
    {"buying_intent_detected": bool, "matched_phrase": str | None}, or None
    on blank input or an unparseable LLM response (safe-empty - a genuine
    API/network failure still raises, per generate_content's contract)."""
    if not posting_text or not posting_text.strip():
        return None

    raw_response = generate_content(build_buying_intent_prompt(posting_text))
    parsed = _parse_json_response(raw_response)
    if not parsed:
        return None

    return {
        "buying_intent_detected": bool(parsed.get("buying_intent_detected")),
        "matched_phrase": parsed.get("matched_phrase"),
    }


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
            "description": job.get("content"),  # requires ?content=true on the request
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
            "description": posting.get("descriptionPlain"),
            "url": posting.get("hostedUrl"),
        }
        for posting in raw_postings
    ]


def enrich_company_with_ats_data(company_name: str) -> dict:
    """Layer 2 entry point: try Greenhouse, then Lever, for one company.

    Returns the full job list, which PM-relevant postings were found, and any
    competitor tools explicitly mentioned in PM job descriptions (the one
    genuinely per-company signal connecting Branch B to Branch C's G2 corpus -
    see the 2026-07-10 plan notes). If neither ATS resolves, source is None -
    caller falls back to Adzuna-only data.
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
            return {
                "source": None,
                "matched_slug": None,
                "pm_postings": [],
                "current_tools_mentioned": [],
                "buying_intent": None,
            }

    pm_postings = [job for job in all_jobs if job["title"] and PM_TITLE_PATTERN.search(job["title"])]

    tools_mentioned: list[str] = []
    for job in pm_postings:
        combined_text = f"{job.get('title') or ''} {job.get('description') or ''}"
        for tool in scan_for_competitor_tools(combined_text):
            if tool not in tools_mentioned:
                tools_mentioned.append(tool)

    # Buying-intent classification runs ONCE per company (the most recently
    # posted PM posting with real description text), not once per posting -
    # a deliberate cost-control choice, mirroring how scoring.py already
    # treats pm_hiring signals as "most recent wins" rather than summing
    # every posting. A company with 5 open PM roles doesn't cost 5x Gemini calls.
    postings_with_description = [p for p in pm_postings if p.get("description")]
    most_recent_pm_posting = max(
        postings_with_description,
        key=lambda p: p.get("posted_date") or "",
        default=None,
    )
    buying_intent = (
        classify_buying_intent(f"{most_recent_pm_posting.get('title') or ''} {most_recent_pm_posting.get('description') or ''}")
        if most_recent_pm_posting
        else None
    )

    return {
        "source": source,
        "matched_slug": matched_slug,
        "pm_postings": pm_postings,
        "current_tools_mentioned": tools_mentioned,
        "buying_intent": buying_intent,
    }
