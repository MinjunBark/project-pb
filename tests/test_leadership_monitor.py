"""Tests for python/leadership_monitor.py - redesign v2, Tier 1's leadership-
page diffing (new decision-maker hire detection). All HTTP + Gemini calls
mocked. See the module docstring for the real limitations this feature has
(domain-only coverage, direct-DB-write architecture exception)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import leadership_monitor  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


ABOUT_PAGE_HTML = """
<html><head><style>.x{color:red}</style></head>
<body><script>var x = 1;</script>
<h1>Leadership</h1>
<p>Jane Doe, VP of Product</p>
<p>John Smith, Chief Executive Officer</p>
</body></html>
"""


# ---------------------------------------------------------------------------
# fetch_leadership_page
# ---------------------------------------------------------------------------


def test_fetch_leadership_page_returns_first_hit(monkeypatch):
    def fake_get(url, timeout=None):
        if url.endswith("/leadership"):
            return FakeResponse(200, ABOUT_PAGE_HTML)
        return FakeResponse(404)

    monkeypatch.setattr(leadership_monitor.requests, "get", fake_get)

    page_url, page_text = leadership_monitor.fetch_leadership_page("acme.com")

    assert page_url == "https://acme.com/leadership"
    assert "Jane Doe" in page_text
    assert "var x = 1" not in page_text  # script tag stripped
    assert "color:red" not in page_text  # style tag stripped


def test_fetch_leadership_page_returns_none_when_all_paths_404(monkeypatch):
    monkeypatch.setattr(leadership_monitor.requests, "get", lambda url, timeout=None: FakeResponse(404))

    page_url, page_text = leadership_monitor.fetch_leadership_page("ghost.com")

    assert page_url is None
    assert page_text is None


# ---------------------------------------------------------------------------
# classify_leadership_page
# ---------------------------------------------------------------------------


def test_classify_leadership_page_returns_none_for_blank_text_without_calling_gemini(monkeypatch):
    mock_generate = MagicMock()
    monkeypatch.setattr(leadership_monitor, "generate_content", mock_generate)

    assert leadership_monitor.classify_leadership_page(None) is None
    assert leadership_monitor.classify_leadership_page("   ") is None
    mock_generate.assert_not_called()


def test_classify_leadership_page_parses_clean_json_response(monkeypatch):
    monkeypatch.setattr(
        leadership_monitor,
        "generate_content",
        lambda prompt: '{"leaders": [{"name": "Jane Doe", "title": "VP of Product"}]}',
    )

    result = leadership_monitor.classify_leadership_page("Jane Doe, VP of Product")

    assert result == {"leaders": [{"name": "Jane Doe", "title": "VP of Product"}]}


def test_classify_leadership_page_returns_none_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(leadership_monitor, "generate_content", lambda prompt: "not json")

    result = leadership_monitor.classify_leadership_page("some page text")

    assert result is None


# ---------------------------------------------------------------------------
# check_for_new_leadership - the full diff flow
# ---------------------------------------------------------------------------


def test_first_ever_snapshot_never_flags_a_new_hire(monkeypatch):
    """The easiest case to get wrong: a company with no prior snapshot has
    nothing to diff against, so even a page full of leaders must NOT be
    reported as a 'new hire' - it's just the baseline. The snapshot must
    still be recorded so the NEXT run has something to diff against."""
    monkeypatch.setattr(leadership_monitor, "fetch_leadership_page", lambda domain: ("https://acme.com/about", "Jane Doe, VP of Product"))
    monkeypatch.setattr(leadership_monitor.db, "get_latest_leadership_snapshot", lambda conn, company_id: None)
    monkeypatch.setattr(
        leadership_monitor, "classify_leadership_page", lambda text: {"leaders": [{"name": "Jane Doe", "title": "VP of Product"}]}
    )
    mock_insert_snapshot = MagicMock(return_value=1)
    monkeypatch.setattr(leadership_monitor.db, "insert_leadership_snapshot", mock_insert_snapshot)
    mock_insert_signal = MagicMock()
    monkeypatch.setattr(leadership_monitor.db, "insert_signal", mock_insert_signal)

    result = leadership_monitor.check_for_new_leadership(MagicMock(), company_id=5, domain="acme.com")

    assert result is None
    mock_insert_snapshot.assert_called_once()
    mock_insert_signal.assert_not_called()


def test_unchanged_content_hash_skips_gemini_call_entirely(monkeypatch):
    """Real cost control: if the page text hasn't changed since the last
    snapshot, the Gemini classification call must never happen."""
    monkeypatch.setattr(leadership_monitor, "fetch_leadership_page", lambda domain: ("https://acme.com/about", "same text"))
    same_hash = leadership_monitor.hashlib.sha256("same text".encode()).hexdigest()
    monkeypatch.setattr(
        leadership_monitor.db,
        "get_latest_leadership_snapshot",
        lambda conn, company_id: {"content_hash": same_hash, "detected_names": [{"name": "Jane Doe", "title": "VP of Product"}]},
    )
    mock_classify = MagicMock()
    monkeypatch.setattr(leadership_monitor, "classify_leadership_page", mock_classify)
    mock_insert_snapshot = MagicMock()
    monkeypatch.setattr(leadership_monitor.db, "insert_leadership_snapshot", mock_insert_snapshot)

    result = leadership_monitor.check_for_new_leadership(MagicMock(), company_id=5, domain="acme.com")

    assert result is None
    mock_classify.assert_not_called()
    mock_insert_snapshot.assert_not_called()


def test_changed_content_with_new_name_emits_leadership_hire_signal(monkeypatch):
    monkeypatch.setattr(leadership_monitor, "fetch_leadership_page", lambda domain: ("https://acme.com/about", "new page text"))
    monkeypatch.setattr(
        leadership_monitor.db,
        "get_latest_leadership_snapshot",
        lambda conn, company_id: {"content_hash": "old-hash", "detected_names": [{"name": "Old Person", "title": "VP of Product"}]},
    )
    monkeypatch.setattr(
        leadership_monitor,
        "classify_leadership_page",
        lambda text: {"leaders": [{"name": "New Person", "title": "Chief Product Officer"}]},
    )
    mock_insert_snapshot = MagicMock(return_value=2)
    monkeypatch.setattr(leadership_monitor.db, "insert_leadership_snapshot", mock_insert_snapshot)
    mock_insert_signal = MagicMock(return_value=100)
    monkeypatch.setattr(leadership_monitor.db, "insert_signal", mock_insert_signal)

    result = leadership_monitor.check_for_new_leadership(MagicMock(), company_id=5, domain="acme.com")

    assert result == {"new_hires": [{"name": "New Person", "title": "Chief Product Officer"}]}
    mock_insert_signal.assert_called_once()
    _, kwargs = mock_insert_signal.call_args
    assert kwargs["signal_category"] == "leadership_hire"
    assert "New Person" in kwargs["raw_text"]


def test_changed_content_with_same_names_emits_no_signal(monkeypatch):
    """Page text changed (e.g. a bio blurb was edited) but the set of
    product-leadership names is identical - not a new hire, must not fire a
    signal, but should still record the updated snapshot."""
    monkeypatch.setattr(leadership_monitor, "fetch_leadership_page", lambda domain: ("https://acme.com/about", "slightly different text"))
    monkeypatch.setattr(
        leadership_monitor.db,
        "get_latest_leadership_snapshot",
        lambda conn, company_id: {"content_hash": "old-hash", "detected_names": [{"name": "Jane Doe", "title": "VP of Product"}]},
    )
    monkeypatch.setattr(
        leadership_monitor, "classify_leadership_page", lambda text: {"leaders": [{"name": "Jane Doe", "title": "VP of Product"}]}
    )
    mock_insert_snapshot = MagicMock(return_value=3)
    monkeypatch.setattr(leadership_monitor.db, "insert_leadership_snapshot", mock_insert_snapshot)
    mock_insert_signal = MagicMock()
    monkeypatch.setattr(leadership_monitor.db, "insert_signal", mock_insert_signal)

    result = leadership_monitor.check_for_new_leadership(MagicMock(), company_id=5, domain="acme.com")

    assert result is None
    mock_insert_snapshot.assert_called_once()
    mock_insert_signal.assert_not_called()


def test_no_leadership_page_found_returns_none_without_touching_db(monkeypatch):
    monkeypatch.setattr(leadership_monitor, "fetch_leadership_page", lambda domain: (None, None))
    mock_get_snapshot = MagicMock()
    monkeypatch.setattr(leadership_monitor.db, "get_latest_leadership_snapshot", mock_get_snapshot)

    result = leadership_monitor.check_for_new_leadership(MagicMock(), company_id=5, domain="ghost.com")

    assert result is None
    mock_get_snapshot.assert_not_called()
