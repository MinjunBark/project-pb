"""Tests for utils/hubspot.py - Phase 7's dedupe check. All HTTP calls are
mocked; the real endpoint/property shapes they're mocked against were
confirmed live against the real HubSpot sandbox account (2026-07-11) before
writing any of this code - see the module docstring."""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import hubspot  # noqa: E402

TODAY = date(2026, 7, 11)


def _response(status_code: int, json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    return resp


def _hubspot_company(company_id: str = "123", name: str = "Acme Corp", domain: str = "acme.com", last_contacted: str | None = None) -> dict:
    return {
        "id": company_id,
        "properties": {"name": name, "domain": domain, "notes_last_contacted": last_contacted},
    }


def test_missing_token_raises_before_any_network_call(monkeypatch):
    """Same guard as utils/gemini.py's missing-key check - fail loudly and
    immediately rather than sending a request with an invalid Authorization
    header and getting back a confusing 401."""
    monkeypatch.delenv("HUBSPOT_PRIVATE_APP_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="HUBSPOT_PRIVATE_APP_TOKEN"):
        hubspot.search_company_by_domain("acme.com")


def test_search_company_by_domain_builds_correct_filter(monkeypatch):
    """Confirms the request body uses the real, live-verified filterGroups
    shape with an EQ operator on the domain property - not a guessed shape."""
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    mock_post = MagicMock(return_value=_response(200, {"results": [_hubspot_company()]}))
    monkeypatch.setattr(hubspot.requests, "post", mock_post)

    result = hubspot.search_company_by_domain("acme.com")

    assert result["id"] == "123"
    _, kwargs = mock_post.call_args
    filters = kwargs["json"]["filterGroups"][0]["filters"][0]
    assert filters == {"propertyName": "domain", "operator": "EQ", "value": "acme.com"}


def test_search_returns_none_when_results_array_is_empty(monkeypatch):
    """The real empty-result shape confirmed live against the sandbox is
    {"results": []}, not a 404 or a null body - confirms that's correctly
    read as 'not found' rather than raising or mis-parsing."""
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    monkeypatch.setattr(hubspot.requests, "post", MagicMock(return_value=_response(200, {"results": []})))

    assert hubspot.search_company_by_domain("nonexistent.com") is None


def test_find_existing_company_tries_domain_first_and_returns_on_hit(monkeypatch):
    """The core Phase 6->7 payoff: with a real domain now available (Clay
    enrichment, ADR-017), domain search should be tried first and, on a
    hit, name search should never even be called - domain is the reliable
    match, name is only the fallback."""
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    monkeypatch.setattr(hubspot, "search_company_by_domain", lambda d: _hubspot_company())
    mock_name_search = MagicMock()
    monkeypatch.setattr(hubspot, "search_company_by_name", mock_name_search)

    result = hubspot.find_existing_company("acme.com", "Acme Corp")

    assert result["id"] == "123"
    mock_name_search.assert_not_called()


def test_find_existing_company_falls_back_to_name_when_domain_search_misses(monkeypatch):
    """Covers both the 'no domain at all' case and the 'domain search found
    nothing' case (e.g. a Clay enrichment mismatch, docs/ISSUES.md Phase 6) -
    either way, name search must still run rather than giving up."""
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    monkeypatch.setattr(hubspot, "search_company_by_domain", lambda d: None)
    monkeypatch.setattr(hubspot, "search_company_by_name", lambda n: _hubspot_company())

    result = hubspot.find_existing_company(None, "Acme Corp")

    assert result["id"] == "123"


def test_check_dedupe_status_returns_create_when_not_found(monkeypatch):
    """The baseline case: a genuinely new lead should be tagged 'create',
    with no HubSpot id, so Phase 8/9 knows to make a brand-new record."""
    monkeypatch.setattr(hubspot, "find_existing_company", lambda domain, name: None)

    result = hubspot.check_dedupe_status("acme.com", "Acme Corp", today=TODAY)

    assert result == {"status": "create", "hubspot_company_id": None}


def test_check_dedupe_status_returns_skip_when_recently_contacted(monkeypatch):
    """A company contacted 5 days ago (well within the 30-day window) must
    be skipped - this is the core anti-spam guarantee of the whole dedupe
    check, preventing the pipeline from re-outreaching someone who was just
    messaged."""
    monkeypatch.setattr(
        hubspot, "find_existing_company", lambda domain, name: _hubspot_company(last_contacted="2026-07-06T12:00:00.000Z")
    )

    result = hubspot.check_dedupe_status("acme.com", "Acme Corp", today=TODAY)

    assert result == {"status": "skip", "hubspot_company_id": "123"}


def test_check_dedupe_status_returns_update_when_contact_is_stale(monkeypatch):
    """A company last contacted 45 days ago (outside the 30-day window)
    should be tagged 'update', not 'skip' - the record already exists but
    is fair game for a fresh outreach cycle."""
    monkeypatch.setattr(
        hubspot, "find_existing_company", lambda domain, name: _hubspot_company(last_contacted="2026-05-27T12:00:00.000Z")
    )

    result = hubspot.check_dedupe_status("acme.com", "Acme Corp", today=TODAY)

    assert result == {"status": "update", "hubspot_company_id": "123"}


def test_check_dedupe_status_returns_update_when_found_but_never_contacted(monkeypatch):
    """A company that exists in HubSpot but has a null notes_last_contacted
    (e.g. created by an earlier merge/import but never actually messaged)
    must not crash on a None date comparison, and should be treated as
    fair game for outreach - 'update', not an error."""
    monkeypatch.setattr(
        hubspot, "find_existing_company", lambda domain, name: _hubspot_company(last_contacted=None)
    )

    result = hubspot.check_dedupe_status("acme.com", "Acme Corp", today=TODAY)

    assert result == {"status": "update", "hubspot_company_id": "123"}


def test_ensure_property_group_exists_skips_creation_when_already_present(monkeypatch):
    """A property group is a prerequisite for any property in it (confirmed
    live - HubSpot returns a real 400 GROUP_DOES_NOT_EXIST otherwise). On a
    repeat run the group already exists, so no POST should fire."""
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    monkeypatch.setattr(hubspot, "_existing_property_group_names", lambda: {hubspot.CUSTOM_PROPERTY_GROUP})
    mock_post = MagicMock()
    monkeypatch.setattr(hubspot.requests, "post", mock_post)

    hubspot._ensure_property_group_exists()

    mock_post.assert_not_called()


def test_ensure_custom_properties_exist_only_creates_missing_ones(monkeypatch):
    """Idempotency check: if some CUSTOM_PROPERTIES already exist (e.g. a
    second pipeline run), only the genuinely missing ones should trigger a
    POST - re-creating an existing property would be a wasted call at best
    and a 409 conflict at worst. Also confirms the property group is
    ensured first (mocked as already-present here, so only property POSTs
    are counted)."""
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    monkeypatch.setattr(hubspot, "_existing_property_group_names", lambda: {hubspot.CUSTOM_PROPERTY_GROUP})
    already_exists = {"icp_score", "gtm_signal_type"}
    monkeypatch.setattr(hubspot, "_existing_property_names", lambda: already_exists)
    mock_post = MagicMock(return_value=_response(200, {}))
    monkeypatch.setattr(hubspot.requests, "post", mock_post)

    created = hubspot.ensure_custom_properties_exist()

    all_names = {p["name"] for p in hubspot.CUSTOM_PROPERTIES}
    assert set(created) == all_names - already_exists
    assert mock_post.call_count == len(all_names) - len(already_exists)


def test_create_company_includes_domain_when_present(monkeypatch):
    """Confirms domain is only added to the request body when actually
    provided - a lead with no domain (the rare Clay-enrichment-miss case)
    must still be creatable in HubSpot without sending domain: null."""
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    mock_post = MagicMock(return_value=_response(200, {"id": "999"}))
    monkeypatch.setattr(hubspot.requests, "post", mock_post)

    company_id = hubspot.create_company("acme.com", "Acme Corp", {"icp_score": 85})

    assert company_id == "999"
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["properties"]["domain"] == "acme.com"
    assert kwargs["json"]["properties"]["name"] == "Acme Corp"
    assert kwargs["json"]["properties"]["icp_score"] == 85


def test_create_company_omits_domain_when_none(monkeypatch):
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    mock_post = MagicMock(return_value=_response(200, {"id": "999"}))
    monkeypatch.setattr(hubspot.requests, "post", mock_post)

    hubspot.create_company(None, "Acme Corp", {})

    _, kwargs = mock_post.call_args
    assert "domain" not in kwargs["json"]["properties"]


def test_update_company_sends_patch_to_correct_id(monkeypatch):
    monkeypatch.setenv("HUBSPOT_PRIVATE_APP_TOKEN", "token")
    mock_patch = MagicMock(return_value=_response(200, {}))
    monkeypatch.setattr(hubspot.requests, "patch", mock_patch)

    hubspot.update_company("123", {"icp_score": 90})

    args, kwargs = mock_patch.call_args
    assert args[0] == f"{hubspot.COMPANIES_URL}/123"
    assert kwargs["json"]["properties"] == {"icp_score": 90}


def test_check_dedupe_status_boundary_exactly_30_days_counts_as_recent(monkeypatch):
    """Off-by-one guard on the recency window itself: exactly 30 days ago
    should still count as 'recently contacted' (<=), matching the
    blueprint's '30 days' language as inclusive, not exclusive."""
    monkeypatch.setattr(
        hubspot, "find_existing_company", lambda domain, name: _hubspot_company(last_contacted="2026-06-11T12:00:00.000Z")
    )

    result = hubspot.check_dedupe_status("acme.com", "Acme Corp", today=TODAY)

    assert result["status"] == "skip"
