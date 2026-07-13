"""Redesign v2, Tier 1 (see redesign/03-creative-signal-approaches.md): a new
TIMING signal - detects a new CPO/VP Product/Head of Product hire by
snapshotting a target company's own public leadership page over time and
diffing it against the prior snapshot. Solves a real gap the Trigger-Bot
analysis flagged ("new decision-maker hire" had no data source) without the
LinkedIn-scraping risk this project has twice already deliberately avoided
(ADR-009/010) - the source here is the company's own marketing page, not a
third party with ToS restrictions on automated access.

Real, load-bearing limitation, not silently worked around: this only runs
against companies with a known `domain` (currently 22/62 real companies).
There's no slug-guessing fallback like hiring_ats_lookup.py's ATS lookup -
a wrong guess here would poison the diff baseline with the wrong company's
page, which is worse than simply not running for that company at all.

Architecture note: unlike every other branch collector in this project,
this module writes to Postgres directly (via check_for_new_leadership())
rather than flowing through the land-then-merge pattern - it needs durable
snapshot state to diff against on the NEXT run, which a stateless
collect-and-land flow doesn't naturally support. See api/main.py's
/leadership/run endpoint docstring for the explicit exception this is.
"""
import hashlib
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import db  # noqa: E402
from gemini import generate_content  # noqa: E402
from gemini import parse_json_response as _parse_json_response  # noqa: E402

CANDIDATE_PATH_TEMPLATES = ["/about", "/about-us", "/leadership", "/team", "/company/leadership"]

LEADERSHIP_EXTRACTION_PROMPT_TEMPLATE = """You are analyzing the text of a company's About/Leadership/Team web page. Identify anyone listed with a Product-leadership title: Chief Product Officer (CPO), VP of Product, Head of Product, or an equivalent senior product-leadership title. Do not guess - only extract people whose title is explicitly stated on the page.

Page text:
{page_text}

Return ONLY strict JSON, no other text, in exactly this shape:
{{"leaders": [{{"name": "...", "title": "..."}}]}} (empty list if none found)"""


def build_leadership_extraction_prompt(page_text: str) -> str:
    return LEADERSHIP_EXTRACTION_PROMPT_TEMPLATE.format(page_text=page_text)


def fetch_leadership_page(domain: str) -> tuple[str, str] | tuple[None, None]:
    """Try each candidate path against the domain, first 200 wins (mirrors
    hiring_ats_lookup.py's try_greenhouse/try_lever "first hit wins" shape).
    Returns (page_url, clean_text) via BeautifulSoup extraction, or
    (None, None) if nothing resolved."""
    for path in CANDIDATE_PATH_TEMPLATES:
        url = f"https://{domain}{path}"
        try:
            resp = requests.get(url, timeout=10)
        except requests.RequestException:
            continue

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            return url, text

    return None, None


def classify_leadership_page(page_text: str | None) -> dict | None:
    """Cost guard on blank text. Returns {"leaders": [{"name", "title"}]} or
    None on blank input or an unparseable LLM response (same safe-empty
    contract as hiring_ats_lookup.classify_buying_intent / classify.py)."""
    if not page_text or not page_text.strip():
        return None

    raw_response = generate_content(build_leadership_extraction_prompt(page_text))
    parsed = _parse_json_response(raw_response)
    if not parsed:
        return None

    return {"leaders": parsed.get("leaders") or []}


def check_for_new_leadership(conn, company_id: int, domain: str) -> dict | None:
    """Fetch, hash, diff against the prior snapshot, and record a
    `leadership_hire` signal if a genuinely new product-leadership name
    appears. Always inserts a fresh snapshot (so the next run has a
    baseline), whether or not anything new was found.

    Returns {"new_hires": [...]} when new leaders were detected, else None.
    A company's FIRST-EVER snapshot always returns None - there's nothing to
    diff against yet, so nothing should be flagged as "new" on that run."""
    page_url, page_text = fetch_leadership_page(domain)
    if page_text is None:
        return None

    content_hash = hashlib.sha256(page_text.encode()).hexdigest()
    prior = db.get_latest_leadership_snapshot(conn, company_id)

    if prior and prior["content_hash"] == content_hash:
        # Unchanged since last snapshot - skip the Gemini call entirely,
        # a real cost control, not just an optimization.
        return None

    extraction = classify_leadership_page(page_text)
    current_leaders = extraction.get("leaders", []) if extraction else []
    current_names = {leader["name"] for leader in current_leaders if leader.get("name")}
    prior_names = (
        {leader["name"] for leader in (prior.get("detected_names") or []) if leader.get("name")}
        if prior
        else set()
    )
    new_names = current_names - prior_names

    db.insert_leadership_snapshot(conn, company_id, page_url, content_hash, current_leaders)

    if not prior or not new_names:
        return None

    new_hires = [leader for leader in current_leaders if leader.get("name") in new_names]
    db.insert_signal(
        conn,
        company_id,
        source="leadership_page",
        signal_category="leadership_hire",
        raw_text=", ".join(f'{h["name"]} ({h["title"]})' for h in new_hires),
        posted_at=date.today().isoformat(),
    )
    return {"new_hires": new_hires}
