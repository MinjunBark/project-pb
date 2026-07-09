"""Tests for python/funding_edgar.py.

All HTTP calls are mocked with canned responses shaped exactly like the real
EDGAR API output captured during development (see docs/ISSUES.md, Phase 1) -
no live network calls or EDGAR_USER_AGENT needed to run this suite, except
where a test explicitly checks that missing the env var raises.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import funding_edgar  # noqa: E402


class FakeResponse:
    def __init__(self, json_data=None, text_data=None):
        self._json_data = json_data
        self.text = text_data

    def json(self):
        return self._json_data

    def raise_for_status(self):
        pass


FUND_HIT = {
    "_source": {
        "ciks": ["0002041717"],
        "display_names": ["1EP Ventures I, L.P.  (CIK 0002041717)"],
        "file_date": "2026-05-29",
        "form": "D/A",
        "adsh": "0002041717-26-000001",
        "biz_locations": ["Palo Alto, CA"],
    }
}

SOFTWARE_HIT = {
    "_source": {
        "ciks": ["0002126990"],
        "display_names": ["Kepler Software, Inc.  (CIK 0002126990)"],
        "file_date": "2026-05-15",
        "form": "D",
        "adsh": "0002126990-26-000001",
        "biz_locations": ["San Francisco, CA"],
    }
}

KEPLER_XML = """<?xml version="1.0"?>
<edgarSubmission>
    <primaryIssuer>
        <entityName>Kepler Software, Inc.</entityName>
        <yearOfInc><value>2023</value></yearOfInc>
    </primaryIssuer>
    <offeringData>
        <industryGroup>
            <industryGroupType>Other Technology</industryGroupType>
        </industryGroup>
        <offeringSalesAmounts>
            <totalOfferingAmount>36164297</totalOfferingAmount>
            <totalAmountSold>36164297</totalAmountSold>
        </offeringSalesAmounts>
    </offeringData>
</edgarSubmission>
"""


@pytest.fixture(autouse=True)
def edgar_user_agent(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test Suite test@example.com")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(funding_edgar.time, "sleep", lambda _seconds: None)


def test_missing_user_agent_raises(monkeypatch):
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError):
        funding_edgar.search_form_d_filings(keywords=["software"])


def test_search_excludes_fund_entities(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(json_data={"hits": {"hits": [FUND_HIT, SOFTWARE_HIT]}})

    monkeypatch.setattr(funding_edgar.requests, "get", fake_get)

    results = funding_edgar.search_form_d_filings(keywords=["software"])

    assert len(results) == 1
    assert results[0]["entity_name"] == "Kepler Software, Inc."


def test_search_dedupes_across_keywords(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(json_data={"hits": {"hits": [SOFTWARE_HIT]}})

    monkeypatch.setattr(funding_edgar.requests, "get", fake_get)

    results = funding_edgar.search_form_d_filings(keywords=["software", "SaaS"])

    assert len(results) == 1


def test_fetch_form_d_details_handles_indefinite_offering_amount(monkeypatch):
    indefinite_xml = KEPLER_XML.replace("36164297", "Indefinite")

    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(text_data=indefinite_xml)

    monkeypatch.setattr(funding_edgar.requests, "get", fake_get)

    details = funding_edgar.fetch_form_d_details("0002126990", "0002126990-26-000001")

    assert details["total_offering_amount"] is None
    assert details["total_amount_sold"] is None


def test_fetch_form_d_details_parses_fields(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert "2126990" in url
        assert "000212699026000001" in url
        return FakeResponse(text_data=KEPLER_XML)

    monkeypatch.setattr(funding_edgar.requests, "get", fake_get)

    details = funding_edgar.fetch_form_d_details("0002126990", "0002126990-26-000001")

    assert details["total_offering_amount"] == 36164297
    assert details["industry_group"] == "Other Technology"
    assert details["year_of_incorporation"] == "2023"


@pytest.mark.parametrize(
    "amount,expected_stage",
    [
        (None, "Unknown"),
        (500_000, "Pre-seed/Seed"),
        (5_000_000, "Seed/Series A"),
        (25_000_000, "Series B"),
        (100_000_000, "Series C"),
        (200_000_000, "Series C+/Growth"),
    ],
)
def test_approximate_funding_stage_bands(amount, expected_stage):
    assert funding_edgar.approximate_funding_stage(amount) == expected_stage


def test_get_funding_signals_shapes_output(monkeypatch):
    monkeypatch.setattr(
        funding_edgar,
        "search_form_d_filings",
        lambda keywords=None, lookback_days=90: [
            {
                "entity_name": "Kepler Software, Inc.",
                "cik": "0002126990",
                "accession_no": "0002126990-26-000001",
                "file_date": "2026-05-15",
                "form_type": "D",
                "biz_location": "San Francisco, CA",
            }
        ],
    )
    monkeypatch.setattr(
        funding_edgar,
        "fetch_form_d_details",
        lambda cik, accession_no: {
            "total_offering_amount": 36164297,
            "total_amount_sold": 36164297,
            "industry_group": "Other Technology",
            "year_of_incorporation": "2023",
        },
    )

    signals = funding_edgar.get_funding_signals()

    assert len(signals) == 1
    signal = signals[0]
    assert signal["company_name"] == "Kepler Software, Inc."
    assert signal["funding_amount_usd"] == 36164297
    assert signal["funding_stage"] == "Series B"
    assert signal["industry"] == "Other Technology"
    assert signal["source"] == "sec_edgar_form_d"
