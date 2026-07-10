"""Local raw-signal landing zone - replaces the S3 landing bucket from the
original blueprint (ADR-003: AWS dropped to narrative-only).

Purpose (unchanged from the original S3 design intent): decouple signal
collection from processing. Each branch's raw output gets saved here before
Phase 3's merge/dedupe step touches it, so a bug in merge/dedupe logic doesn't
require re-hitting rate-limited APIs (EDGAR, Adzuna, Apify) to recover - just
reload the same raw file.
"""
import glob
import json
import os
from datetime import datetime, timezone

LANDING_DIR = "data/raw"


def save_raw_signals(branch_name: str, data) -> str:
    """Save one branch's raw output as a timestamped JSON file. Returns the
    file path written."""
    os.makedirs(LANDING_DIR, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{branch_name}_{timestamp}.json"
    path = os.path.join(LANDING_DIR, filename)

    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    return path


def load_latest_raw_signals(branch_name: str):
    """Load the most recently saved raw file for a given branch, or None if
    nothing has been landed yet."""
    pattern = os.path.join(LANDING_DIR, f"{branch_name}_*.json")
    matches = sorted(glob.glob(pattern))

    if not matches:
        return None

    with open(matches[-1]) as f:
        return json.load(f)
