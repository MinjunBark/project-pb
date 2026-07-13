"""Phase 7: HubSpot dedupe check. Given a qualified lead (from scoring.py),
determine whether it already exists in HubSpot and whether it was recently
contacted, before Phase 8 generates outreach for it.

Endpoint, filter/operator shape, and the "last contacted" property name were
all confirmed live against the real HubSpot sandbox account (2026-07-11) -
not assumed from docs, which are unreliable for exact endpoint paths (a doc
fetch this session returned a mismatched, incorrect endpoint). Real findings:
  - POST /crm/v3/objects/companies/search with filterGroups/filters/EQ works
    exactly as documented in most sources.
  - "notes_last_contacted" ("Last Contacted", datetime) is a real, STANDARD
    property on the Company object already - no custom property setup
    needed, contrary to the original blueprint's assumption that this would
    require creating a custom property.
"""
import os
from datetime import date, datetime, timezone

import requests

COMPANIES_URL = "https://api.hubapi.com/crm/v3/objects/companies"
SEARCH_URL = f"{COMPANIES_URL}/search"
PROPERTIES_URL = "https://api.hubapi.com/crm/v3/properties/companies"
PROPERTY_GROUPS_URL = f"{PROPERTIES_URL}/groups"
SEARCH_PROPERTIES = ["name", "domain", "notes_last_contacted"]

RECENTLY_CONTACTED_WINDOW_DAYS = 30

# Custom Company properties this pipeline writes (Phase 9, ADR-020). Adapted
# from the blueprint's Section 8 output schema - "deal_stage" was dropped
# (that concept belongs on HubSpot's separate Deal object, not Company; a
# real Deal-object build is out of scope for this pass) and replaced with a
# simpler "gtm_pipeline_status" tracked directly on the company.
CUSTOM_PROPERTY_GROUP = "gtm_signal_engine"
CUSTOM_PROPERTIES = [
    {"name": "icp_score", "label": "ICP Score", "type": "number", "fieldType": "number"},
    {
        "name": "gtm_signal_type",
        "label": "GTM Signal Type",
        "type": "enumeration",
        "fieldType": "select",
        "options": [
            {"label": "TIMING", "value": "TIMING", "displayOrder": 0},
            {"label": "INTENT", "value": "INTENT", "displayOrder": 1},
            {"label": "BOTH", "value": "BOTH", "displayOrder": 2},
        ],
    },
    {"name": "funding_stage", "label": "Funding Stage", "type": "string", "fieldType": "text"},
    {"name": "funding_amount_usd", "label": "Funding Amount (USD)", "type": "number", "fieldType": "number"},
    {"name": "current_tool_mentioned", "label": "Current PM Tool Mentioned", "type": "string", "fieldType": "text"},
    {"name": "priority_summary", "label": "Priority Summary", "type": "string", "fieldType": "textarea"},
    {"name": "outreach_subject_a", "label": "Outreach Subject A", "type": "string", "fieldType": "text"},
    {"name": "outreach_subject_b", "label": "Outreach Subject B", "type": "string", "fieldType": "text"},
    {"name": "outreach_email_body", "label": "Outreach Email Body", "type": "string", "fieldType": "textarea"},
    {"name": "outreach_linkedin", "label": "Outreach LinkedIn Message", "type": "string", "fieldType": "textarea"},
    {"name": "outreach_call_script", "label": "Outreach Call Script", "type": "string", "fieldType": "textarea"},
    {
        "name": "gtm_pipeline_status",
        "label": "GTM Pipeline Status",
        "type": "enumeration",
        "fieldType": "select",
        "options": [
            {"label": "Signal Queued", "value": "signal_queued", "displayOrder": 0},
            {"label": "Contacted", "value": "contacted", "displayOrder": 1},
        ],
    },
]


def _headers() -> dict:
    token = os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN")
    if not token:
        raise RuntimeError("HUBSPOT_PRIVATE_APP_TOKEN must be set in .env")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _search(property_name: str, value: str) -> dict | None:
    body = {
        "filterGroups": [{"filters": [{"propertyName": property_name, "operator": "EQ", "value": value}]}],
        "properties": SEARCH_PROPERTIES,
    }
    resp = requests.post(SEARCH_URL, headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()

    results = resp.json().get("results", [])
    return results[0] if results else None


def search_company_by_domain(domain: str) -> dict | None:
    """Exact-match search on the domain property - the reliable match now
    that Phase 6's Clay enrichment has backfilled real domains."""
    return _search("domain", domain)


def search_company_by_name(name: str) -> dict | None:
    """Exact-match search on the name property - a weaker fallback for the
    rare company that still has no domain, or whose Clay-enriched domain
    doesn't match whatever's already in HubSpot (e.g. a typo, a rebrand)."""
    return _search("name", name)


def find_existing_company(domain: str | None, name: str) -> dict | None:
    """Domain search first when a domain exists, falling back to name
    search when it doesn't. Returns the matched HubSpot company (raw API
    result dict) or None if not found by either path."""
    if domain:
        match = search_company_by_domain(domain)
        if match:
            return match

    return search_company_by_name(name)


def _parse_hubspot_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_dedupe_status(domain: str | None, name: str, today: date | None = None) -> dict:
    """The full Phase 7 decision: not found -> create; found + contacted
    within the window -> skip; found + not recently contacted -> update.
    Returns {"status": "create"|"skip"|"update", "hubspot_company_id": str|None}."""
    today = today or datetime.now(timezone.utc).date()

    existing = find_existing_company(domain, name)
    if not existing:
        return {"status": "create", "hubspot_company_id": None}

    last_contacted = _parse_hubspot_datetime(existing["properties"].get("notes_last_contacted"))
    if last_contacted is not None:
        days_since_contact = (today - last_contacted.date()).days
        if days_since_contact <= RECENTLY_CONTACTED_WINDOW_DAYS:
            return {"status": "skip", "hubspot_company_id": existing["id"]}

    return {"status": "update", "hubspot_company_id": existing["id"]}


def _existing_property_names() -> set[str]:
    resp = requests.get(PROPERTIES_URL, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return {p["name"] for p in resp.json().get("results", [])}


def _existing_property_group_names() -> set[str]:
    resp = requests.get(PROPERTY_GROUPS_URL, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return {g["name"] for g in resp.json().get("results", [])}


def _ensure_property_group_exists() -> None:
    """A HubSpot property MUST belong to an existing group - creating a
    property in a not-yet-created group fails with a real 400
    (PropertyGroupError.GROUP_DOES_NOT_EXIST, confirmed live 2026-07-11).
    Idempotent - only creates the group if it doesn't already exist."""
    if CUSTOM_PROPERTY_GROUP in _existing_property_group_names():
        return

    body = {"name": CUSTOM_PROPERTY_GROUP, "label": "GTM Signal Engine"}
    resp = requests.post(PROPERTY_GROUPS_URL, headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()


def ensure_custom_properties_exist() -> list[str]:
    """Idempotent: creates the CUSTOM_PROPERTY_GROUP if missing, then any of
    CUSTOM_PROPERTIES not already present on the Company object. Safe to
    call every run - only POSTs what's actually missing. Returns the list
    of property names created (empty on a repeat run once they all exist)."""
    _ensure_property_group_exists()

    existing = _existing_property_names()
    created = []

    for prop in CUSTOM_PROPERTIES:
        if prop["name"] in existing:
            continue

        body = {**prop, "groupName": CUSTOM_PROPERTY_GROUP}
        resp = requests.post(PROPERTIES_URL, headers=_headers(), json=body, timeout=15)
        resp.raise_for_status()
        created.append(prop["name"])

    return created


def create_company(domain: str | None, name: str, properties: dict) -> str:
    """POST a new Company object. `properties` should be pre-formatted
    HubSpot property values (string keys matching CUSTOM_PROPERTIES names,
    plus optionally "name"/"domain"). Returns the new company's id."""
    body_properties = {"name": name, **properties}
    if domain:
        body_properties["domain"] = domain

    resp = requests.post(COMPANIES_URL, headers=_headers(), json={"properties": body_properties}, timeout=15)
    resp.raise_for_status()
    return resp.json()["id"]


def update_company(company_id: str, properties: dict) -> None:
    """PATCH an existing Company object's properties."""
    resp = requests.patch(
        f"{COMPANIES_URL}/{company_id}", headers=_headers(), json={"properties": properties}, timeout=15
    )
    resp.raise_for_status()
