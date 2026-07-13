"""Tests for python/raw_landing.py. Uses a temp directory for the landing
zone so tests never touch the real data/raw/ folder."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import raw_landing  # noqa: E402


@pytest.fixture(autouse=True)
def temp_landing_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(raw_landing, "LANDING_DIR", str(tmp_path / "raw"))


def test_save_raw_signals_writes_file_and_returns_path():
    path = raw_landing.save_raw_signals("branch_a", [{"company_name": "Acme"}])

    assert Path(path).exists()
    assert "branch_a_" in path
    assert path.endswith(".json")


def test_load_latest_raw_signals_returns_none_when_nothing_saved():
    assert raw_landing.load_latest_raw_signals("branch_never_saved") is None


def test_load_latest_raw_signals_round_trips_data():
    data = [{"company_name": "Acme", "funding_amount_usd": 5000000}]
    raw_landing.save_raw_signals("branch_a", data)

    loaded = raw_landing.load_latest_raw_signals("branch_a")

    assert loaded == data


def test_load_latest_raw_signals_picks_most_recent(monkeypatch):
    import time

    raw_landing.save_raw_signals("branch_b", [{"version": 1}])
    time.sleep(1.1)  # ensure a distinct second-resolution timestamp
    raw_landing.save_raw_signals("branch_b", [{"version": 2}])

    loaded = raw_landing.load_latest_raw_signals("branch_b")

    assert loaded == [{"version": 2}]


def test_load_latest_raw_signals_uses_file_mtime_not_filename_string_sort():
    """Regression test for a real bug caught during a live Phase 6 merge run
    (docs/ISSUES.md): an old file named "branch_a_funding_<timestamp>.json"
    (a leftover from earlier ad-hoc testing) matched the same glob pattern as
    the real "branch_a_<timestamp>.json" convention, and sorted AFTER it as
    a plain string ('f' > a digit) despite being chronologically older. That
    caused a live merge to silently reload stale 8-company data instead of a
    freshly-landed 22-company run. This test builds that exact scenario -
    older file gets a differently-prefixed name that would out-sort the
    newer one alphabetically - and confirms mtime-based selection picks the
    chronologically latest file regardless of filename string ordering."""
    older_path = Path(raw_landing.LANDING_DIR)
    older_path.mkdir(parents=True, exist_ok=True)
    stale_file = older_path / "branch_a_funding_20260710T004132Z.json"
    stale_file.write_text('[{"version": "stale"}]')

    # Newer file, but its filename sorts BEFORE the stale one as a plain
    # string ('2' < 'f') - the exact condition that broke the old sort.
    fresh_file = older_path / "branch_a_20260711T022934Z.json"
    fresh_file.write_text('[{"version": "fresh"}]')

    import os
    import time

    now = time.time()
    os.utime(stale_file, (now - 100, now - 100))  # older mtime
    os.utime(fresh_file, (now, now))  # newer mtime

    loaded = raw_landing.load_latest_raw_signals("branch_a")

    assert loaded == [{"version": "fresh"}]
