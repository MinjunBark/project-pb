"""Redesign v2, Tier 6: a real Discord bot that watches #clay-enrichment
for the user's enriched CSV upload directly - the faster, more natural
counterpart to Tier 5's local-folder + 60s poller (utils/discord.py's
send_clay_enrichment_request() posts the request out via a webhook; this
file is what reads the reply back in, which a webhook can't do at all).

Explicitly additive: the local-folder convention (python/enrichment.py's
CLAY_INCOMING_DOMAIN_DIR/CLAY_INCOMING_DEMOGRAPHICS_DIR + the 60s poller in
api/main.py) still works exactly as before and is untouched - this bot is
just a second, faster way for a real upload to land in the same known
folders. If DISCORD_BOT_TOKEN/DISCORD_CLAY_CHANNEL_ID aren't configured,
create_bot_task() returns None and the rest of the pipeline is completely
unaffected (the bot is an enhancement, not a requirement).

All real decision logic (which enrichment queue a file belongs to, where
it gets written, whether to trigger an immediate resume) lives in
handle_upload() below - a plain async function with no discord.py types in
its signature, so it's testable without mocking discord.Client/Message.
The on_message wiring at the bottom is a thin, untested-by-design
adapter, mirroring how api/main.py's HTTP endpoints stay thin wrappers
around already-tested Python.
"""
import asyncio
import csv
import io
import os
import sys
from pathlib import Path

import discord

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import enrichment  # noqa: E402
import full_pipeline_run  # noqa: E402


async def handle_upload(header: list[str], filename: str, content: bytes, reply_fn) -> None:
    """The real logic behind a real CSV attachment landing in
    #clay-enrichment: detect which known-folder queue it belongs to (by
    real header content, not filename - see enrichment._detect_enrichment_kind()),
    save it there, and immediately trigger an auto-resume check instead of
    waiting up to 60s for the next poll tick. `reply_fn` is an async
    callable(str) -> None (in practice, a Discord channel's .send) - kept
    generic here so this function needs no discord.py types to test."""
    kind = enrichment._detect_enrichment_kind(header)
    if kind is None:
        await reply_fn(
            "⚠️ That CSV wasn't recognized as either a domain- or demographics-enriched "
            "export - nothing was imported. Make sure you're uploading the real exported "
            "result from the Clay table linked in the original request, not a different file."
        )
        return

    enrichment.save_incoming_enrichment_file(kind, filename, content)
    await reply_fn(f"✅ Got it — {kind} enrichment file received, importing now...")

    result = await asyncio.to_thread(full_pipeline_run.resume_after_enrichment)
    if result is None:
        await reply_fn(
            "⚠️ Import ran but the pipeline found nothing new to pick up - double check "
            "the file actually has real rows in it."
        )
    else:
        await reply_fn(
            f"🔄 Pipeline auto-resumed: {result['qualified_count']} qualified lead(s) out of "
            f"{result['companies_evaluated']} companies evaluated. Full digest posted in #sdr-digest."
        )


def _read_header(content: bytes) -> list[str]:
    text = content.decode("utf-8", errors="replace")
    return next(csv.reader(io.StringIO(text)), [])


def create_bot_task() -> "asyncio.Task | None":
    """Launches the bot inside the caller's existing asyncio event loop -
    same 'reuse the already-running uvicorn process, no new process' choice
    Tier 5's poller made. Returns None (does not raise) if the real bot
    credentials aren't configured - a missing/not-yet-set-up bot must not
    block FastAPI from starting, since the local-folder path works fully
    independently."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id_raw = os.environ.get("DISCORD_CLAY_CHANNEL_ID")
    if not token or not channel_id_raw:
        return None
    channel_id = int(channel_id_raw)

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot or message.channel.id != channel_id:
            return
        for attachment in message.attachments:
            if not attachment.filename.lower().endswith(".csv"):
                continue
            content = await attachment.read()
            header = _read_header(content)
            await handle_upload(header, attachment.filename, content, message.channel.send)

    return asyncio.create_task(client.start(token))
