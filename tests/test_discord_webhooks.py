"""Tests for utils/discord_webhooks.py - webhook notifications, color-coded
by signal_type. Real network call is mocked; a live test message was
actually sent and confirmed during Phase 9 setup (see docs/ISSUES.md).

Renamed from utils/discord.py (Redesign v2, Tier 6): a real naming
collision with the pip-installed `discord.py` library, which is also
imported as `discord` - our own module shadowed the real library on
sys.path once utils/discord_bot.py needed the actual SDK. See
docs/ISSUES.md for the live crash this caused and the fix."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import discord_webhooks as discord  # noqa: E402


def test_build_lead_embed_uses_correct_color_per_signal_type():
    """Confirms the blueprint's green/yellow/blue color coding (BOTH highest
    priority = green) actually maps correctly - a wrong mapping here would
    mislead whoever's triaging the Discord channel about which leads matter
    most, silently undermining the whole point of color-coding."""
    both = discord.build_lead_embed({"company_name": "A", "signal_type": "BOTH", "icp_score": 90})
    timing = discord.build_lead_embed({"company_name": "B", "signal_type": "TIMING", "icp_score": 60})
    intent = discord.build_lead_embed({"company_name": "C", "signal_type": "INTENT", "icp_score": 55})

    assert both["embeds"][0]["color"] == discord.SIGNAL_TYPE_COLORS["BOTH"]
    assert timing["embeds"][0]["color"] == discord.SIGNAL_TYPE_COLORS["TIMING"]
    assert intent["embeds"][0]["color"] == discord.SIGNAL_TYPE_COLORS["INTENT"]


def test_build_lead_embed_falls_back_to_grey_for_unexpected_signal_type():
    """Defensive check: an unrecognized/missing signal_type shouldn't crash
    embed construction (e.g. a KeyError) - falls back to a neutral grey
    rather than failing to notify at all."""
    embed = discord.build_lead_embed({"company_name": "X", "signal_type": "SOMETHING_UNEXPECTED"})

    assert embed["embeds"][0]["color"] == discord.DEFAULT_COLOR


def test_build_lead_embed_includes_priority_summary_as_description():
    """Confirms the actual point of the notification - a human glancing at
    Discord should see the 'why contact now' rationale (ADR-019) directly,
    not just a bare company name with no context."""
    embed = discord.build_lead_embed(
        {"company_name": "Acme Corp", "signal_type": "BOTH", "priority_summary": "Funded and hiring - act now."}
    )

    assert embed["embeds"][0]["description"] == "Funded and hiring - act now."


def test_build_lead_embed_includes_platform_storage_fields(monkeypatch):
    """Redesign v2, Tier 3: a real, verifiable HubSpot ID, a real clickable
    Google Sheet link, and the real Postgres leads.id - so the user can go
    look at this lead directly on each platform."""
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "abc123sheet")

    embed = discord.build_lead_embed(
        {
            "company_name": "Acme Corp",
            "signal_type": "BOTH",
            "hubspot_company_id": "hs-999",
            "lead_id": 42,
        }
    )

    fields = {f["name"]: f["value"] for f in embed["embeds"][0]["fields"]}
    assert fields["HubSpot"] == "Company ID: hs-999"
    assert "docs.google.com/spreadsheets/d/abc123sheet" in fields["Google Sheet"]
    assert fields["Database"] == "Supabase leads.id: 42"


def test_send_lead_notification_requires_webhook_url(monkeypatch):
    """Same fail-loud guard pattern as every other client this session -
    missing config should raise immediately, not attempt a POST to an empty
    URL and produce a confusing requests error."""
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    with pytest.raises(RuntimeError, match="DISCORD_WEBHOOK_URL"):
        discord.send_lead_notification({"company_name": "Acme Corp", "signal_type": "TIMING"})


def test_send_lead_notification_posts_to_configured_url(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/fake/fake")
    mock_response = MagicMock(status_code=204)
    mock_post = MagicMock(return_value=mock_response)
    monkeypatch.setattr(discord.requests, "post", mock_post)

    discord.send_lead_notification({"company_name": "Acme Corp", "signal_type": "BOTH"})

    args, kwargs = mock_post.call_args
    assert args[0] == "https://discord.com/api/webhooks/fake/fake"
    assert "embeds" in kwargs["json"]


# ---------------------------------------------------------------------------
# Redesign v2, Tier 2: ops-progress updates + SDR digest
# ---------------------------------------------------------------------------


def test_send_progress_update_requires_webhook_url(monkeypatch):
    monkeypatch.delenv("DISCORD_PROGRESS_WEBHOOK_URL", raising=False)

    with pytest.raises(RuntimeError, match="DISCORD_PROGRESS_WEBHOOK_URL"):
        discord.send_progress_update("Branch A complete")


def test_send_progress_update_posts_plain_content_to_configured_url(monkeypatch):
    monkeypatch.setenv("DISCORD_PROGRESS_WEBHOOK_URL", "https://discord.com/api/webhooks/progress/fake")
    mock_response = MagicMock(status_code=204)
    mock_post = MagicMock(return_value=mock_response)
    monkeypatch.setattr(discord.requests, "post", mock_post)

    discord.send_progress_update("✅ Branch A (funding): 22 signals landed.")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://discord.com/api/webhooks/progress/fake"
    assert kwargs["json"] == {"content": "✅ Branch A (funding): 22 signals landed."}


def test_build_sdr_digest_embed_handles_zero_qualified_leads():
    """The realistic common case per every live run this project has
    measured so far - must read as normal/expected, not alarming."""
    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": []})

    assert embed["embeds"][0]["color"] == discord.DIGEST_ZERO_LEADS_COLOR
    assert "No new qualified leads today" in embed["embeds"][0]["description"]
    assert "2026-07-13" in embed["embeds"][0]["title"]


def test_build_sdr_digest_embed_includes_one_field_per_lead():
    leads = [
        {"company_name": "Acme Corp", "icp_score": 90, "signal_type": "BOTH", "domain": "acme.com", "priority_summary": "Act now."},
        {"company_name": "Beta Inc", "icp_score": 75, "signal_type": "TIMING", "domain": "beta.com", "priority_summary": "Scaling fast."},
    ]

    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": leads})

    fields = embed["embeds"][0]["fields"]
    assert len(fields) == 2
    assert "Acme Corp" in fields[0]["name"]
    assert "90" in fields[0]["name"]
    assert "BOTH" in fields[0]["value"]
    assert "Act now." in fields[0]["value"]


def test_build_sdr_digest_embed_includes_a_real_clickable_sheet_link(monkeypatch):
    """The digest's top-level description must include the REAL, full
    spreadsheet URL (matching the exact address-bar format, .../edit?gid=0#gid=0)
    as a bare, auto-linking URL - not just descriptive text referencing
    'the spreadsheet' by name with nothing to click."""
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "abc123sheet")
    leads = [{"company_name": "Acme Corp", "icp_score": 90, "signal_type": "BOTH"}]

    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": leads})

    assert "https://docs.google.com/spreadsheets/d/abc123sheet/edit?gid=0#gid=0" in embed["embeds"][0]["description"]


def test_build_sdr_digest_embed_zero_qualified_also_includes_sheet_link(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ID", "abc123sheet")

    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": []})

    assert "https://docs.google.com/spreadsheets/d/abc123sheet/edit?gid=0#gid=0" in embed["embeds"][0]["description"]


def test_build_sdr_digest_embed_sorts_leads_by_icp_score_descending():
    leads = [
        {"company_name": "Low", "icp_score": 71, "signal_type": "TIMING"},
        {"company_name": "High", "icp_score": 99, "signal_type": "BOTH"},
        {"company_name": "Mid", "icp_score": 85, "signal_type": "INTENT"},
    ]

    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": leads})

    names_in_order = [f["name"] for f in embed["embeds"][0]["fields"]]
    assert "High" in names_in_order[0]
    assert "Mid" in names_in_order[1]
    assert "Low" in names_in_order[2]


def test_build_sdr_digest_embed_chunks_into_multiple_embeds_when_over_field_limit():
    leads = [{"company_name": f"Company {i}", "icp_score": 100 - i, "signal_type": "BOTH"} for i in range(45)]

    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": leads})

    assert len(embed["embeds"]) > 1
    for e in embed["embeds"]:
        if "fields" in e:
            assert len(e["fields"]) <= discord.DIGEST_LEADS_PER_EMBED


def test_build_sdr_digest_embed_truncates_long_priority_summary():
    """The priority_summary portion specifically must be capped, even
    though platform-storage fields (redesign v2, Tier 3) are appended
    after it in the same field value - checks the truncated summary text
    itself, not the tail of the whole field (which now legitimately ends
    with a Sheet link, not the summary)."""
    long_summary = "x" * 500
    leads = [{"company_name": "Acme Corp", "icp_score": 90, "signal_type": "BOTH", "priority_summary": long_summary}]

    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": leads})

    field_value = embed["embeds"][0]["fields"][0]["value"]
    assert len(field_value) < len(long_summary) + 100  # bounded, not the full 500-char summary
    assert "x" * (discord.PRIORITY_SUMMARY_MAX_CHARS - 1) + "…" in field_value


def test_build_sdr_digest_embed_always_shows_watchlist_even_with_zero_qualified():
    """The core fix: the digest should never look empty. Even with 0
    qualified leads, a non-empty watchlist must still render as its own
    section."""
    watchlist = [
        {
            "company_name": "Anduril Industries",
            "icp_score": 45,
            "signal_type": "BOTH",
            "domain": "anduril.com",
            "score_breakdown": {
                "timing": {"pm_posting_count": 15, "product_ops_posting": 10},
                "intent": {"buying_intent_language": 10},
                "demographic": {},
                "deductions": {},
                "both_signal_bonus": 10,
            },
        }
    ]

    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": [], "watchlist": watchlist})

    assert len(embed["embeds"]) == 2
    assert "No new qualified leads today" in embed["embeds"][0]["description"]
    watchlist_embed = embed["embeds"][1]
    assert "Top Prospects to Watch" in watchlist_embed["title"]
    assert len(watchlist_embed["fields"]) == 1
    assert "Anduril Industries" in watchlist_embed["fields"][0]["name"]
    assert "45" in watchlist_embed["fields"][0]["name"]
    assert "pm_posting_count=15" in watchlist_embed["fields"][0]["value"]
    assert "buying_intent_language=10" in watchlist_embed["fields"][0]["value"]


def test_build_sdr_digest_embed_omits_watchlist_section_when_empty():
    """No watchlist entries (e.g. every company scored exactly 0) should
    not render an empty/pointless section."""
    embed = discord.build_sdr_digest_embed({"date": "2026-07-13", "qualified_leads": [], "watchlist": []})

    assert len(embed["embeds"]) == 1


def test_build_sdr_digest_embed_shows_watchlist_alongside_qualified_leads():
    """The watchlist isn't only-when-zero-qualified - it should still show
    up even on a run where some leads DID qualify, so the user always sees
    the full picture of who's close behind the qualified ones."""
    qualified = [{"company_name": "Acme Corp", "icp_score": 90, "signal_type": "BOTH"}]
    watchlist = [{"company_name": "Runner Up Inc", "icp_score": 55, "signal_type": "TIMING", "score_breakdown": {}}]

    embed = discord.build_sdr_digest_embed(
        {"date": "2026-07-13", "qualified_leads": qualified, "watchlist": watchlist}
    )

    titles = [e["title"] for e in embed["embeds"]]
    assert any("Top Prospects to Watch" in t for t in titles)


def test_watchlist_field_has_no_platform_storage_fields():
    """Unlike a qualified lead, nothing has been written anywhere for a
    watchlist entry - no HubSpot write, no Sheet row, no leads row - so
    its field value must not reference any of those."""
    field = discord._watchlist_field({"company_name": "X", "icp_score": 30, "signal_type": "TIMING"})

    assert "HubSpot" not in field["value"]
    assert "Sheet" not in field["value"]
    assert "Database" not in field["value"]


def test_summarize_breakdown_skips_empty_buckets_and_formats_contributions():
    breakdown = {
        "timing": {"funding_recency": 25},
        "intent": {},
        "demographic": {},
        "deductions": {},
        "both_signal_bonus": 0,
    }

    result = discord._summarize_breakdown(breakdown)

    assert result == "TIMING: funding_recency=25"


def test_send_sdr_digest_requires_webhook_url(monkeypatch):
    monkeypatch.delenv("DISCORD_SDR_DIGEST_WEBHOOK_URL", raising=False)

    with pytest.raises(RuntimeError, match="DISCORD_SDR_DIGEST_WEBHOOK_URL"):
        discord.send_sdr_digest({"date": "2026-07-13", "qualified_leads": []})


def test_send_sdr_digest_posts_to_configured_url(monkeypatch):
    monkeypatch.setenv("DISCORD_SDR_DIGEST_WEBHOOK_URL", "https://discord.com/api/webhooks/digest/fake")
    mock_response = MagicMock(status_code=204)
    mock_post = MagicMock(return_value=mock_response)
    monkeypatch.setattr(discord.requests, "post", mock_post)

    discord.send_sdr_digest({"date": "2026-07-13", "qualified_leads": []})

    args, kwargs = mock_post.call_args
    assert args[0] == "https://discord.com/api/webhooks/digest/fake"
    assert "embeds" in kwargs["json"]


# ---------------------------------------------------------------------------
# Redesign v2, Tier 5: Clay human-in-the-loop notification
# ---------------------------------------------------------------------------


def test_send_clay_enrichment_request_requires_webhook_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL", raising=False)
    csv_path = tmp_path / "export.csv"
    csv_path.write_text("company_id,company_name\n1,Acme\n")

    with pytest.raises(RuntimeError, match="DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL"):
        discord.send_clay_enrichment_request("domain", 1, str(csv_path))


def test_send_clay_enrichment_request_posts_with_file_attached(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL", "https://discord.com/api/webhooks/clay/fake")
    mock_response = MagicMock(status_code=200)
    mock_post = MagicMock(return_value=mock_response)
    monkeypatch.setattr(discord.requests, "post", mock_post)
    csv_path = tmp_path / "clay_export_20260713.csv"
    csv_path.write_text("company_id,company_name\n1,Acme\n")

    discord.send_clay_enrichment_request("domain", 5, str(csv_path))

    args, kwargs = mock_post.call_args
    assert args[0] == "https://discord.com/api/webhooks/clay/fake"
    assert "files" in kwargs
    assert kwargs["files"]["file"][0] == "clay_export_20260713.csv"
    payload = json.loads(kwargs["data"]["payload_json"])
    assert "5 companies need domain enrichment" in payload["content"]
    assert "incoming_domain" in payload["content"]
