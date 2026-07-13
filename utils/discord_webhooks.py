"""Phase 9: Discord webhook notifications - one message per qualified lead,
color-coded by signal_type per the original blueprint's design (green=BOTH,
yellow=TIMING, blue=INTENT).

Renamed from discord.py (Redesign v2, Tier 6): a real naming collision with
the pip-installed `discord.py` library (also imported as `discord`) - once
utils/discord_bot.py needed the real SDK, our own same-named module shadowed
it on sys.path (utils/ is inserted at the front by every caller) and crashed
with `AttributeError: module 'discord' has no attribute 'Intents'`. Every
call site still imports this as `import discord_webhooks as discord`, so
every existing discord.send_*()/discord.build_*() call is unchanged.
"""
import json
import os

import requests

# Discord embed colors are decimal integers, not hex strings.
SIGNAL_TYPE_COLORS = {
    "BOTH": 0x2ECC71,  # green - highest priority
    "TIMING": 0xF1C40F,  # yellow
    "INTENT": 0x3498DB,  # blue
}
DEFAULT_COLOR = 0x95A5A6  # grey fallback for an unexpected signal_type


def _google_sheet_link() -> str | None:
    """The real, full URL to the Leads sheet's first tab - matches the
    exact address-bar format Google Sheets itself uses (.../edit?gid=0#gid=0),
    not just the bare .../edit URL, so it's the literal link a user would
    get by opening the sheet themselves. A bare URL (not markdown-masked)
    is used everywhere this is embedded, since Discord auto-links plain
    URLs in both message content and embed fields/descriptions - the most
    reliably-clickable form across every place it appears."""
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID")
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit?gid=0#gid=0" if sheet_id else None


def _platform_storage_fields(lead: dict) -> list[dict]:
    """Redesign v2, Tier 3: shows exactly where this lead's data was
    written, so the user can go look at it directly on the platform
    itself. HubSpot is a real, verifiable ID (searchable in HubSpot) rather
    than a fabricated deep link - the account's hub/portal ID isn't stored
    anywhere in this codebase, so a guaranteed-correct URL can't be built.
    The Google Sheet link IS real and clickable (GOOGLE_SHEETS_ID is a real
    env var). Database is the real Postgres leads.id."""
    fields = []
    hubspot_id = lead.get("hubspot_company_id")
    if hubspot_id:
        fields.append({"name": "HubSpot", "value": f"Company ID: {hubspot_id}", "inline": True})

    sheet_link = _google_sheet_link()
    if sheet_link:
        fields.append({"name": "Google Sheet", "value": sheet_link, "inline": True})

    lead_id = lead.get("lead_id")
    if lead_id:
        fields.append({"name": "Database", "value": f"Supabase leads.id: {lead_id}", "inline": True})

    return fields


def build_lead_embed(lead: dict) -> dict:
    """Builds a Discord embed payload for one qualified lead."""
    signal_type = lead.get("signal_type", "")
    return {
        "embeds": [
            {
                "title": f"New lead: {lead.get('company_name')}",
                "description": lead.get("priority_summary") or "",
                "color": SIGNAL_TYPE_COLORS.get(signal_type, DEFAULT_COLOR),
                "fields": [
                    {"name": "ICP Score", "value": str(lead.get("icp_score", "")), "inline": True},
                    {"name": "Signal Type", "value": signal_type or "unknown", "inline": True},
                    {"name": "Domain", "value": lead.get("domain") or "unknown", "inline": True},
                    *_platform_storage_fields(lead),
                ],
            }
        ]
    }


def send_lead_notification(lead: dict) -> None:
    """POSTs a color-coded embed to DISCORD_WEBHOOK_URL for one qualified
    lead. Raises RuntimeError if the webhook URL isn't configured."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL must be set in .env")

    resp = requests.post(webhook_url, json=build_lead_embed(lead), timeout=15)
    resp.raise_for_status()


# Redesign v2, Tier 2: a separate ops-progress channel (low-ceremony status
# noise while a full run is happening) and a separate sdr-digest channel
# (one clean final summary) - two new webhooks, distinct from
# DISCORD_WEBHOOK_URL above, which keeps firing per-lead notifications
# unchanged.


def send_progress_update(message: str) -> None:
    """Plain-text status line to the ops-progress channel - no embed, just
    content, since this is meant to be quick and frequent (posted once per
    phase boundary during python/full_pipeline_run.py's live run). Same
    fail-loud convention as send_lead_notification: raise immediately if
    the webhook isn't configured, rather than silently running a full live
    pipeline cycle with no visibility at all."""
    webhook_url = os.environ.get("DISCORD_PROGRESS_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_PROGRESS_WEBHOOK_URL must be set in .env")

    resp = requests.post(webhook_url, json={"content": message}, timeout=15)
    resp.raise_for_status()


# Redesign v2: a single, live-editing progress message for #ops-progress
# instead of a new message per phase (~10-15 messages per run before this).
# Discord webhooks support editing a message they posted - POST with
# ?wait=true returns the created message's real id; PATCH
# .../messages/{id} edits that same message in place. No bot token needed,
# reuses the existing DISCORD_PROGRESS_WEBHOOK_URL.
PROGRESS_BAR_SEGMENTS = 20


def _build_progress_bar_text(current_step: int, total_steps: int, label: str) -> str:
    """Pure, no network - e.g. "[████████░░░░░░░░░░░░] 40% — ✅ Branch A
    (funding): 22 signals landed." total_steps=0 (shouldn't happen in
    practice, but avoids a divide-by-zero) renders an empty bar at 0%."""
    fraction = (current_step / total_steps) if total_steps else 0
    filled = round(fraction * PROGRESS_BAR_SEGMENTS)
    bar = "█" * filled + "░" * (PROGRESS_BAR_SEGMENTS - filled)
    percent = round(fraction * 100)
    return f"[{bar}] {percent}% — {label}"


def send_progress_bar_update(current_step: int, total_steps: int, label: str, message_id: str | None = None) -> str:
    """Posts a NEW live-progress message (message_id=None - uses ?wait=true
    to capture the real Discord message id in the response) or edits an
    EXISTING one (message_id given - PATCH). Returns the message id either
    way, so a caller threads it into the next call to keep editing the
    same message. Raises RuntimeError if DISCORD_PROGRESS_WEBHOOK_URL isn't
    set (same convention as every other send_* function)."""
    webhook_url = os.environ.get("DISCORD_PROGRESS_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_PROGRESS_WEBHOOK_URL must be set in .env")

    content = _build_progress_bar_text(current_step, total_steps, label)

    if message_id is None:
        resp = requests.post(webhook_url, params={"wait": "true"}, json={"content": content}, timeout=15)
        resp.raise_for_status()
        return resp.json()["id"]

    resp = requests.patch(f"{webhook_url}/messages/{message_id}", json={"content": content}, timeout=15)
    resp.raise_for_status()
    return message_id


# Discord hard limits: max 25 fields per embed, max 10 embeds per message,
# ~6000 total characters across all embeds in one message. These constants
# keep a real digest comfortably under those limits even though every real
# live run so far has qualified 0 leads (see docs/PROGRESS.md) - handled
# rather than assumed away.
DIGEST_LEADS_PER_EMBED = 20
DIGEST_MAX_LEADS = 200
PRIORITY_SUMMARY_MAX_CHARS = 300

DIGEST_ZERO_LEADS_COLOR = 0x95A5A6  # grey - "nothing today" should read as normal, not broken
DIGEST_QUALIFIED_COLOR = 0x2ECC71  # green - reuses the per-lead BOTH color, this is always good news
DIGEST_WATCHLIST_COLOR = 0x3498DB  # blue - distinct from qualified/zero, reuses the per-lead INTENT color

WATCHLIST_LEADS_PER_EMBED = DIGEST_LEADS_PER_EMBED


def _truncate_priority_summary(text: str | None) -> str:
    text = text or ""
    if len(text) <= PRIORITY_SUMMARY_MAX_CHARS:
        return text
    return text[: PRIORITY_SUMMARY_MAX_CHARS - 1] + "…"


def _summarize_breakdown(breakdown: dict | None) -> str:
    """Redesign v2, Tier 3: turns a raw score_breakdown dict into a short
    human-readable "why this score" line for the watchlist - e.g.
    'TIMING: pm_posting_count=15, product_ops_posting=10 | INTENT:
    buying_intent_language=10'. Skips empty buckets entirely."""
    breakdown = breakdown or {}
    parts = []
    for bucket in ("timing", "intent", "demographic", "deductions"):
        detail = breakdown.get(bucket) or {}
        if detail:
            items = ", ".join(f"{k}={v}" for k, v in detail.items())
            parts.append(f"{bucket.upper()}: {items}")
    bonus = breakdown.get("both_signal_bonus")
    if bonus:
        parts.append(f"BOTH bonus: +{bonus}")
    return " | ".join(parts) if parts else "(no contributing signals yet)"


def _lead_field(lead: dict) -> dict:
    signal_type = lead.get("signal_type", "unknown")
    domain = lead.get("domain") or "unknown"
    summary = _truncate_priority_summary(lead.get("priority_summary"))
    value = f"Signal: {signal_type}\nDomain: {domain}\n{summary}"

    # Redesign v2, Tier 3: platform-storage tracking - show exactly where
    # this lead's data was written, same reasoning as build_lead_embed's
    # per-lead notification (HubSpot ID is real/searchable, not a
    # fabricated deep link; the Sheet link is real via GOOGLE_SHEETS_ID).
    platform_bits = []
    if lead.get("hubspot_company_id"):
        platform_bits.append(f"HubSpot: {lead['hubspot_company_id']}")
    if lead.get("lead_id"):
        platform_bits.append(f"DB id: {lead['lead_id']}")
    sheet_link = _google_sheet_link()
    if sheet_link:
        platform_bits.append(f"Sheet: {sheet_link}")
    if platform_bits:
        value += "\n" + " | ".join(platform_bits)

    return {"name": f"{lead.get('company_name', 'Unknown company')} — {lead.get('icp_score', '?')}", "value": value, "inline": False}


def _watchlist_field(entry: dict) -> dict:
    """Redesign v2, Tier 3: a top-scoring-but-not-yet-qualified company.
    No platform-storage fields - nothing has been written anywhere for
    these (no outreach generated, no HubSpot/Sheet/leads-row write), so
    there's nothing real to point to yet, unlike a qualified lead."""
    signal_type = entry.get("signal_type", "unknown")
    domain = entry.get("domain") or "unknown"
    reason = _summarize_breakdown(entry.get("score_breakdown"))
    return {
        "name": f"{entry.get('company_name', 'Unknown company')} — {entry.get('icp_score', '?')}",
        "value": f"Signal: {signal_type}\nDomain: {domain}\n{reason}",
        "inline": False,
    }


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_sdr_digest_embed(summary: dict) -> dict:
    """Pure/testable. summary = {"date": "2026-07-12", "qualified_leads": [...],
    "watchlist": [...]}. qualified_leads are shaped like process_qualified_lead()'s
    "processed" result; watchlist entries are shaped like its "not_qualified"
    result (company_name, icp_score, signal_type, domain, score_breakdown).

    The watchlist section is ALWAYS rendered when non-empty, regardless of
    whether anything qualified this run - the digest should never look
    empty, and showing the closest-but-not-qualified companies is honest
    (clearly no outreach/platform writes happened for them) rather than
    inflating the qualified count to avoid an empty-looking message."""
    date_str = summary.get("date", "")
    leads = sorted(summary.get("qualified_leads") or [], key=lambda lead: lead.get("icp_score", 0), reverse=True)
    watchlist = sorted(summary.get("watchlist") or [], key=lambda w: w.get("icp_score", 0), reverse=True)

    # Real, clickable link to the actual sheet - always shown at the top of
    # the digest (not just referenced by name), regardless of whether
    # anything qualified this run.
    sheet_link = _google_sheet_link()
    sheet_line = f"\n\n📊 Full spreadsheet: {sheet_link}" if sheet_link else ""

    embeds = []

    if not leads:
        embeds.append(
            {
                "title": f"SDR Digest — {date_str}",
                "description": (
                    "No new qualified leads today. Every branch ran; nothing cleared the "
                    "ICP threshold. See Top Prospects to Watch below for the closest ones."
                    f"{sheet_line}"
                ),
                "color": DIGEST_ZERO_LEADS_COLOR,
            }
        )
    else:
        overflow_count = 0
        if len(leads) > DIGEST_MAX_LEADS:
            overflow_count = len(leads) - DIGEST_MAX_LEADS
            leads = leads[:DIGEST_MAX_LEADS]

        chunks = _chunk(leads, DIGEST_LEADS_PER_EMBED)
        embeds.append(
            {
                "title": f"SDR Digest — {date_str}",
                "description": f"{len(summary.get('qualified_leads') or [])} qualified lead(s) today. Full detail below.{sheet_line}",
                "color": DIGEST_QUALIFIED_COLOR,
                "fields": [_lead_field(lead) for lead in chunks[0]],
            }
        )
        for page, chunk in enumerate(chunks[1:], start=2):
            embeds.append(
                {
                    "title": f"SDR Digest — {date_str} (cont'd, page {page})",
                    "color": DIGEST_QUALIFIED_COLOR,
                    "fields": [_lead_field(lead) for lead in chunk],
                }
            )

        if overflow_count:
            embeds.append(
                {
                    "title": "More leads not shown",
                    "description": f"...and {overflow_count} more lower-priority leads not shown here — see the Leads spreadsheet for the full list.",
                    "color": DIGEST_QUALIFIED_COLOR,
                }
            )

    if watchlist:
        watchlist_chunks = _chunk(watchlist, WATCHLIST_LEADS_PER_EMBED)
        embeds.append(
            {
                "title": "🔎 Top Prospects to Watch",
                "description": (
                    f"{len(watchlist)} compan{'y' if len(watchlist) == 1 else 'ies'} closest to qualifying "
                    "this run - not yet crossed the ICP threshold, so no outreach was generated and nothing "
                    "was written to HubSpot/Sheet/leads yet. Shown for visibility, not action."
                ),
                "color": DIGEST_WATCHLIST_COLOR,
                "fields": [_watchlist_field(entry) for entry in watchlist_chunks[0]],
            }
        )
        for page, chunk in enumerate(watchlist_chunks[1:], start=2):
            embeds.append(
                {
                    "title": f"🔎 Top Prospects to Watch (cont'd, page {page})",
                    "color": DIGEST_WATCHLIST_COLOR,
                    "fields": [_watchlist_field(entry) for entry in chunk],
                }
            )

    return {"embeds": embeds}


def send_sdr_digest(summary: dict) -> None:
    """POSTs build_sdr_digest_embed(summary) to DISCORD_SDR_DIGEST_WEBHOOK_URL.
    Raises RuntimeError if the webhook isn't configured (same convention as
    send_lead_notification / send_progress_update)."""
    webhook_url = os.environ.get("DISCORD_SDR_DIGEST_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_SDR_DIGEST_WEBHOOK_URL must be set in .env")

    resp = requests.post(webhook_url, json=build_sdr_digest_embed(summary), timeout=15)
    resp.raise_for_status()


# Redesign v2, Tier 5/6: Discord-driven Clay human-in-the-loop. The user
# drops the enriched CSV into the known folder (see python/enrichment.py's
# CLAY_INCOMING_ENRICHMENT_DIR) or uploads it directly to #clay-enrichment
# (utils/discord_bot.py) - no script invocation needed, api/main.py's
# background poller (or the next full run) detects and imports it
# automatically. Consolidated 2026-07-13 from two separate queues (domain,
# demographics) into one, since Clay's real "Company Enrichment" waterfall
# already returns domain + employee count + industry in a single pass.
CLAY_INCOMING_ENRICHMENT_DIR = "data/clay/incoming_enrichment"


def send_clay_enrichment_request(count: int, csv_path: str) -> None:
    """POSTs to DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL with the real export CSV attached
    as a file (Discord webhooks support multipart file uploads via
    payload_json + files, not just JSON), plus exact instructions for the
    manual Clay round-trip and precisely where to drop the result so it's
    picked up automatically. Raises RuntimeError if the webhook isn't
    configured (same convention as every other send_* function)."""
    webhook_url = os.environ.get("DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_CLAY_ENRICHMENT_WEBHOOK_URL must be set in .env")

    message = (
        f"🧩 {count} companies need enrichment.\n\n"
        f"1. Download the attached CSV and import it into your Clay table.\n"
        f"2. Run the \"Company Enrichment\" waterfall, then export the result.\n"
        f"3. Drop the exported file into `{CLAY_INCOMING_ENRICHMENT_DIR}/` on this machine "
        f"(or upload it here in #clay-enrichment).\n"
        f"4. The pipeline automatically detects and imports it within about a minute - "
        f"no need to re-run anything yourself."
    )

    with open(csv_path, "rb") as f:
        resp = requests.post(
            webhook_url,
            data={"payload_json": json.dumps({"content": message})},
            files={"file": (os.path.basename(csv_path), f, "text/csv")},
            timeout=30,
        )
    resp.raise_for_status()
