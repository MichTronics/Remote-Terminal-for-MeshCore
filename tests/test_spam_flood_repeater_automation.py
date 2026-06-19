"""Tests for spam-flood repeater automation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models import ContactUpsert
from app.repository import ContactRepository
from app.repository.settings import AppSettingsRepository
from app.services.spam_flood_repeater_automation import (
    DEFAULT_COMMAND_ATTEMPTS,
    _dispatch_spam_flood_repeater_commands,
)


@pytest.mark.asyncio
async def test_spam_flood_repeater_automation_sends_start_command(test_db):
    repeater_key = "aa" + "11" * 31
    await ContactRepository.upsert(
        ContactUpsert(public_key=repeater_key, name="Border Repeater", type=2)
    )
    await AppSettingsRepository.update(
        spam_flood_automation_enabled=True,
        spam_flood_repeater_keys=[repeater_key],
        spam_flood_start_command="set repeat off",
        spam_flood_end_command="set repeat on",
    )

    with (
        patch(
            "app.routers.server_control.send_contact_cli_command",
            new_callable=AsyncMock,
        ) as mock_send,
        patch(
            "app.services.spam_flood_repeater_automation.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        mock_send.return_value = type("Resp", (), {"response": "ok"})()
        await _dispatch_spam_flood_repeater_commands("start")

    assert mock_send.await_count == DEFAULT_COMMAND_ATTEMPTS
    assert mock_send.await_args.args[1] == "set repeat off"


@pytest.mark.asyncio
async def test_spam_flood_repeater_automation_skips_when_disabled(test_db):
    repeater_key = "bb" + "22" * 31
    await ContactRepository.upsert(
        ContactUpsert(public_key=repeater_key, name="Other Repeater", type=2)
    )
    await AppSettingsRepository.update(
        spam_flood_automation_enabled=False,
        spam_flood_repeater_keys=[repeater_key],
        spam_flood_start_command="set repeat off",
    )

    with patch(
        "app.routers.server_control.send_contact_cli_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await _dispatch_spam_flood_repeater_commands("start")

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_spam_flood_repeater_automation_sends_end_command(test_db):
    repeater_key = "cc" + "33" * 31
    await ContactRepository.upsert(
        ContactUpsert(public_key=repeater_key, name="Restore Repeater", type=2)
    )
    await AppSettingsRepository.update(
        spam_flood_automation_enabled=True,
        spam_flood_repeater_keys=[repeater_key],
        spam_flood_end_command="set repeat on",
    )

    with (
        patch(
            "app.routers.server_control.send_contact_cli_command",
            new_callable=AsyncMock,
        ) as mock_send,
        patch(
            "app.services.spam_flood_repeater_automation.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        mock_send.return_value = type("Resp", (), {"response": "ok"})()
        await _dispatch_spam_flood_repeater_commands("end")

    assert mock_send.await_count == DEFAULT_COMMAND_ATTEMPTS
    assert mock_send.await_args.args[1] == "set repeat on"
