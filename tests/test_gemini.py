"""Tests for utils/gemini.py - the dual-key + backoff Gemini client.
All HTTP calls are mocked; time.sleep is patched out so retry tests run
instantly instead of actually waiting."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import gemini  # noqa: E402


def _response(status_code: int, text: str | None = None, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or ""
    resp.json.return_value = json_body or {}
    return resp


def _success_body(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_missing_api_keys_raises_before_any_network_call(monkeypatch):
    """Guards against a silent failure mode: if neither GEMINI_API_KEY nor
    GEMINI_API_KEY_2 is set, this must fail loudly and immediately, not
    attempt a network call with key=None and produce a confusing 400 error."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gemini.generate_content("hello")


def test_successful_call_returns_text_on_first_try(monkeypatch):
    """The plain happy path: one key, one call, 200 response - confirms the
    real Gemini response shape (candidates[0].content.parts[0].text) is
    parsed correctly."""
    monkeypatch.setenv("GEMINI_API_KEY", "key-1")
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    mock_post = MagicMock(return_value=_response(200, json_body=_success_body("hello back")))
    monkeypatch.setattr(gemini.requests, "post", mock_post)

    result = gemini.generate_content("hello")

    assert result == "hello back"
    assert mock_post.call_count == 1


def test_retries_on_429_then_succeeds_without_switching_keys(monkeypatch):
    """A rate-limit response (429) on a single key should be retried with
    backoff, not immediately treated as a fatal error or as a reason to jump
    to the second key - most 429s are transient."""
    monkeypatch.setenv("GEMINI_API_KEY", "key-1")
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.setattr(gemini.time, "sleep", MagicMock())
    mock_post = MagicMock(
        side_effect=[_response(429, text="rate limited"), _response(200, json_body=_success_body("ok"))]
    )
    monkeypatch.setattr(gemini.requests, "post", mock_post)

    result = gemini.generate_content("hello")

    assert result == "ok"
    assert mock_post.call_count == 2


def test_falls_back_to_second_key_after_first_key_exhausts_retries(monkeypatch):
    """The actual dual-key fallback: if the first key fails on every retry
    attempt, the second key must still be tried before giving up entirely -
    this is the whole point of configuring two keys."""
    monkeypatch.setenv("GEMINI_API_KEY", "key-1")
    monkeypatch.setenv("GEMINI_API_KEY_2", "key-2")
    monkeypatch.setattr(gemini.time, "sleep", MagicMock())
    mock_post = MagicMock(
        side_effect=[
            _response(429, text="rate limited"),
            _response(429, text="rate limited"),
            _response(429, text="rate limited"),
            _response(200, json_body=_success_body("ok from key 2")),
        ]
    )
    monkeypatch.setattr(gemini.requests, "post", mock_post)

    result = gemini.generate_content("hello")

    assert result == "ok from key 2"
    called_keys = [call.kwargs["params"]["key"] for call in mock_post.call_args_list]
    assert called_keys == ["key-1", "key-1", "key-1", "key-2"]


def test_raises_after_all_keys_and_retries_exhausted(monkeypatch):
    """Confirms this fails loudly (not silently returning None/empty string)
    when every key and every retry is exhausted - callers need to know
    classification genuinely failed, not treat a crash as 'no company found'."""
    monkeypatch.setenv("GEMINI_API_KEY", "key-1")
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.setattr(gemini.time, "sleep", MagicMock())
    mock_post = MagicMock(return_value=_response(429, text="rate limited"))
    monkeypatch.setattr(gemini.requests, "post", mock_post)

    with pytest.raises(RuntimeError, match="Gemini API failed"):
        gemini.generate_content("hello")
