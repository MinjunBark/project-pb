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
