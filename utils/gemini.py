"""Gemini API client: dual-key fallback + exponential backoff, per the
original blueprint's pattern (GEMINI_API_KEY / GEMINI_API_KEY_2 in .env).

Used by python/classify.py (Phase 5). Kept generic (just "send a prompt, get
text back") so any future Gemini use (e.g. Phase 8 outreach generation) can
reuse this instead of duplicating the retry/fallback logic.
"""
import json
import os
import re
import time

import requests

_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# gemini-2.0-flash (the original default) is deprecated (429 on every call).
# Its would-be successor, gemini-2.5-flash-lite, is ALSO already "no longer
# available to new users" per a live 404 - both pinned version numbers are
# stale faster than expected in a fast-moving model lineup. Live-verified
# 2026-07-10 (GET /v1beta/models, then real POST calls against candidates):
# "gemini-flash-lite-latest" is a rolling alias Google maintains to always
# point at the current lite model, so it shouldn't go stale the same way -
# the right fit for a lightweight extraction task like this one anyway.
DEFAULT_MODEL = "gemini-flash-lite-latest"

MAX_RETRIES_PER_KEY = 3
BACKOFF_BASE_SECONDS = 2
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


def _api_keys() -> list[str]:
    keys = [os.environ.get("GEMINI_API_KEY"), os.environ.get("GEMINI_API_KEY_2")]
    keys = [k for k in keys if k]
    if not keys:
        raise RuntimeError("At least one of GEMINI_API_KEY / GEMINI_API_KEY_2 must be set in .env")
    return keys


def generate_content(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Send a single-turn prompt to Gemini, return the raw text response.

    Tries each configured key in order; within a key, retries on rate-limit
    (429) or server errors (5xx) with exponential backoff. Raises if every
    key/retry combination fails.
    """
    url = API_URL_TEMPLATE.format(model=model)
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    last_error: Exception | None = None
    for key in _api_keys():
        for attempt in range(MAX_RETRIES_PER_KEY):
            resp = requests.post(url, params={"key": key}, json=body, timeout=30)

            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]

            if resp.status_code in RETRYABLE_STATUS_CODES:
                last_error = RuntimeError(f"Gemini returned {resp.status_code}: {resp.text[:200]}")
                time.sleep(BACKOFF_BASE_SECONDS * (2 ** attempt))
                continue

            resp.raise_for_status()

        # exhausted retries on this key - fall through to try the next key

    raise RuntimeError(f"Gemini API failed on all configured keys. Last error: {last_error}")


def parse_json_response(raw_text: str) -> dict | None:
    """Gemini frequently wraps JSON in ```json ... ``` code fences despite
    being asked not to - strip those before parsing. Returns None (not a
    crash) on anything unparseable, so a caller can decide whether that's
    fatal (e.g. outreach.py) or safely skippable (e.g. classify.py).

    Moved here from python/classify.py once python/outreach.py (Phase 8)
    needed the identical logic - shared, not duplicated, across every
    Gemini call site that expects structured JSON back.
    """
    cleaned = _JSON_FENCE_PATTERN.sub("", raw_text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None
