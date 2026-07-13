"""Tests for utils/discord_bot.py - Redesign v2, Tier 6's real Discord bot.

Only handle_upload() and create_bot_task()'s missing-credentials short
circuit are tested here - the on_message wiring inside create_bot_task()
is a thin discord.py adapter (mirrors how api/main.py's HTTP endpoints
stay thin wrappers around already-tested Python), not re-tested by mocking
discord.Client/Message/Attachment.

No pytest-asyncio dependency in this project yet - handle_upload() is a
coroutine, so each test runs it via asyncio.run() from an ordinary sync
test function rather than adding a new plugin for four tests.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import discord_bot  # noqa: E402


def test_handle_upload_recognized_domain_header_saves_and_resumes(monkeypatch):
    monkeypatch.setattr(
        discord_bot.enrichment, "save_incoming_enrichment_file", MagicMock(return_value="data/clay/incoming_domain/x.csv")
    )
    monkeypatch.setattr(
        discord_bot.full_pipeline_run,
        "resume_after_enrichment",
        MagicMock(return_value={"qualified_count": 2, "companies_evaluated": 114}),
    )
    reply_fn = AsyncMock()

    asyncio.run(discord_bot.handle_upload(["company_id", "company_name", "Domain"], "export.csv", b"content", reply_fn))

    discord_bot.enrichment.save_incoming_enrichment_file.assert_called_once_with("domain", "export.csv", b"content")
    messages = " | ".join(call.args[0] for call in reply_fn.call_args_list)
    assert "Got it" in messages
    assert "domain" in messages
    assert "2 qualified" in messages


def test_handle_upload_recognized_demographics_header_saves_and_resumes(monkeypatch):
    monkeypatch.setattr(discord_bot.enrichment, "save_incoming_enrichment_file", MagicMock(return_value="x.csv"))
    monkeypatch.setattr(
        discord_bot.full_pipeline_run,
        "resume_after_enrichment",
        MagicMock(return_value={"qualified_count": 0, "companies_evaluated": 114}),
    )
    reply_fn = AsyncMock()

    asyncio.run(
        discord_bot.handle_upload(
            ["company_id", "company_name", "domain", "Employee Count", "Industry"], "export.csv", b"content", reply_fn
        )
    )

    discord_bot.enrichment.save_incoming_enrichment_file.assert_called_once_with("demographics", "export.csv", b"content")


def test_handle_upload_unrecognized_header_does_not_save_or_resume(monkeypatch):
    mock_save = MagicMock()
    mock_resume = MagicMock()
    monkeypatch.setattr(discord_bot.enrichment, "save_incoming_enrichment_file", mock_save)
    monkeypatch.setattr(discord_bot.full_pipeline_run, "resume_after_enrichment", mock_resume)
    reply_fn = AsyncMock()

    asyncio.run(discord_bot.handle_upload(["company_id", "company_name"], "notes.csv", b"content", reply_fn))

    mock_save.assert_not_called()
    mock_resume.assert_not_called()
    reply_fn.assert_called_once()
    assert "wasn't recognized" in reply_fn.call_args[0][0]


def test_handle_upload_reports_when_nothing_new_was_actually_found(monkeypatch):
    """A real edge case: the file was saved and looked recognized, but the
    subsequent resume found nothing new (e.g. an empty/header-only CSV) -
    must say so honestly rather than claiming success."""
    monkeypatch.setattr(discord_bot.enrichment, "save_incoming_enrichment_file", MagicMock(return_value="x.csv"))
    monkeypatch.setattr(discord_bot.full_pipeline_run, "resume_after_enrichment", MagicMock(return_value=None))
    reply_fn = AsyncMock()

    asyncio.run(discord_bot.handle_upload(["company_id", "Domain"], "export.csv", b"content", reply_fn))

    messages = " | ".join(call.args[0] for call in reply_fn.call_args_list)
    assert "nothing new" in messages


def test_create_bot_task_returns_none_when_token_missing(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_CLAY_CHANNEL_ID", "12345")

    assert discord_bot.create_bot_task() is None


def test_create_bot_task_returns_none_when_channel_id_missing(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.delenv("DISCORD_CLAY_CHANNEL_ID", raising=False)

    assert discord_bot.create_bot_task() is None
