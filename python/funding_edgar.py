"""Branch A (timing signal): funding events from SEC EDGAR Form D filings.

Replaces the original blueprint's Crunchbase API call (ADR-008 in docs/DECISIONS.md).
Two-step flow against real, verified EDGAR endpoints:
  1. search_form_d_filings() - full-text search for Form D filings matching an
     ICP-relevant keyword, within a lookback window.
  2. fetch_form_d_details() - fetch each filing's actual primary_doc.xml for the
     offering amount and industry group.

A plain date-range query with no search text returns mostly investment funds/SPVs
raising their own capital, not operating companies that received funding (see
docs/ISSUES.md, Phase 1) - the required `keywords` argument and the fund-name
heuristic filter below both exist specifically to work around that.
"""
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

DEFAULT_KEYWORDS = ["software", "SaaS", "platform"]

# Heuristic only - filters out venture funds/SPVs that file Form D for their own
# capital raises. Documented limitation: may false-negative on a real operating
# company that happens to have "fund" or "ventures" in its name.
FUND_NAME_PATTERN = re.compile(
    r"\b(fund|ventures?\s+(i|ii|iii|iv|v)\b|l\.?p\.?$|spv)\b", re.IGNORECASE
)

# SEC enforces 10 req/sec across all EDGAR endpoints; stay comfortably under it.
REQUEST_DELAY_SECONDS = 0.15


def _headers() -> dict:
    user_agent = os.environ.get("EDGAR_USER_AGENT")
    if not user_agent:
        raise RuntimeError(
            "EDGAR_USER_AGENT must be set in .env - SEC requires a descriptive "
            "User-Agent (name + contact email) on every request or it returns 403."
        )
    return {"User-Agent": user_agent}


def _is_fund_entity(entity_name: str) -> bool:
    return bool(FUND_NAME_PATTERN.search(entity_name))


def search_form_d_filings(
    keywords: list[str] | None = None,
    lookback_days: int = 90,
    size: int = 100,
) -> list[dict]:
    """Search EDGAR for Form D filings matching ICP-relevant keywords.

    Returns deduplicated (by CIK) candidate filings: entity_name, cik,
    accession_no, file_date, form_type.
    """
    keywords = keywords or DEFAULT_KEYWORDS
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=lookback_days)

    seen_ciks: set[str] = set()
    results: list[dict] = []

    for keyword in keywords:
        params = {
            "q": f'"{keyword}"',
            "forms": "D",
            "startdt": start_dt.isoformat(),
            "enddt": end_dt.isoformat(),
            "from": 0,
            "size": size,
        }
        resp = requests.get(SEARCH_URL, params=params, headers=_headers(), timeout=15)
        resp.raise_for_status()
        time.sleep(REQUEST_DELAY_SECONDS)

        hits = resp.json().get("hits", {}).get("hits", [])
        for hit in hits:
            source = hit.get("_source", {})
            ciks = source.get("ciks") or []
            if not ciks:
                continue
            cik = ciks[0]
            if cik in seen_ciks:
                continue

            display_names = source.get("display_names") or []
            entity_name = display_names[0].split("  (CIK")[0].strip() if display_names else None
            if not entity_name or _is_fund_entity(entity_name):
                continue

            seen_ciks.add(cik)
            results.append(
                {
                    "entity_name": entity_name,
                    "cik": cik,
                    "accession_no": source.get("adsh"),
                    "file_date": source.get("file_date"),
                    "form_type": source.get("form"),
                    "biz_location": (source.get("biz_locations") or [None])[0],
                }
            )

    return results


def fetch_form_d_details(cik: str, accession_no: str) -> dict:
    """Fetch a single Form D's primary_doc.xml and extract offering details."""
    cik_no_zeros = str(int(cik))
    accession_no_dashes_removed = accession_no.replace("-", "")
    url = f"{ARCHIVES_BASE}/{cik_no_zeros}/{accession_no_dashes_removed}/primary_doc.xml"

    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)

    root = ET.fromstring(resp.text)

    def findtext(path: str) -> str | None:
        el = root.find(path)
        return el.text if el is not None else None

    total_offering_amount = findtext(".//offeringData/offeringSalesAmounts/totalOfferingAmount")
    total_amount_sold = findtext(".//offeringData/offeringSalesAmounts/totalAmountSold")
    industry_group = findtext(".//offeringData/industryGroup/industryGroupType")
    year_of_inc = findtext(".//primaryIssuer/yearOfInc/value")

    return {
        "total_offering_amount": _parse_offering_amount(total_offering_amount),
        "total_amount_sold": _parse_offering_amount(total_amount_sold),
        "industry_group": industry_group,
        "year_of_incorporation": year_of_inc,
    }


def _parse_offering_amount(raw_value: str | None) -> int | None:
    """Form D allows a literal 'Indefinite' instead of a number for ongoing/open
    offerings - treat that (or any other non-numeric value) as unknown rather
    than crashing."""
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


def approximate_funding_stage(offering_amount: int | None) -> str:
    """Form D doesn't label rounds (e.g. 'Series A') - approximate from amount.

    Bands are a documented heuristic (ADR-008 in docs/DECISIONS.md), not a fact
    reported by the filing itself.
    """
    if offering_amount is None:
        return "Unknown"
    if offering_amount < 2_000_000:
        return "Pre-seed/Seed"
    if offering_amount < 15_000_000:
        return "Seed/Series A"
    if offering_amount < 50_000_000:
        return "Series B"
    if offering_amount < 150_000_000:
        return "Series C"
    return "Series C+/Growth"


def get_funding_signals(
    keywords: list[str] | None = None, lookback_days: int = 90
) -> list[dict]:
    """Full Branch A flow: search, fetch details, approximate stage.

    Returns a list of dicts shaped for the signals pipeline: company_name,
    funding_amount_usd, funding_date, funding_stage, industry, source.
    """
    candidates = search_form_d_filings(keywords=keywords, lookback_days=lookback_days)

    signals = []
    for candidate in candidates:
        details = fetch_form_d_details(candidate["cik"], candidate["accession_no"])
        offering_amount = details["total_offering_amount"] or details["total_amount_sold"]

        signals.append(
            {
                "company_name": candidate["entity_name"],
                "funding_amount_usd": offering_amount,
                "funding_date": candidate["file_date"],
                "funding_stage": approximate_funding_stage(offering_amount),
                "industry": details["industry_group"],
                "biz_location": candidate["biz_location"],
                "cik": candidate["cik"],
                "accession_no": candidate["accession_no"],
                "source": "sec_edgar_form_d",
            }
        )

    return signals
