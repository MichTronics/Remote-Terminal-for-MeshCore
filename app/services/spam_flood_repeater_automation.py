"""Send configured repeater CLI commands when spam flood episodes start or end."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from app.models import CONTACT_TYPE_REPEATER
from app.repository import AppSettingsRepository, ContactRepository
from app.routers.server_control import send_contact_cli_command

logger = logging.getLogger(__name__)

SpamFloodPhase = Literal["start", "end"]


def schedule_spam_flood_repeater_commands(phase: SpamFloodPhase) -> None:
    """Fire-and-forget repeater command dispatch for a spam flood phase transition."""
    asyncio.create_task(_dispatch_spam_flood_repeater_commands(phase))


async def _dispatch_spam_flood_repeater_commands(phase: SpamFloodPhase) -> None:
    settings = await AppSettingsRepository.get()
    if not settings.spam_flood_automation_enabled:
        return

    command = (
        settings.spam_flood_start_command
        if phase == "start"
        else settings.spam_flood_end_command
    ).strip()
    if not command:
        return

    keys = settings.spam_flood_repeater_keys
    if not keys:
        return

    for public_key in keys:
        try:
            contact = await ContactRepository.get_by_key(public_key)
            if contact is None:
                logger.warning(
                    "Spam flood %s command skipped: repeater %s not found",
                    phase,
                    public_key[:12],
                )
                continue
            if contact.type != CONTACT_TYPE_REPEATER:
                logger.warning(
                    "Spam flood %s command skipped: %s is not a repeater (type=%s)",
                    phase,
                    public_key[:12],
                    contact.type,
                )
                continue

            response = await send_contact_cli_command(
                contact,
                command,
                operation_name=f"spam_flood_{phase}",
            )
            logger.info(
                "Spam flood %s command sent to %s (%s): %s",
                phase,
                contact.name or public_key[:12],
                public_key[:12],
                (response.response or "")[:120],
            )
        except Exception:
            logger.exception(
                "Spam flood %s command failed for repeater %s",
                phase,
                public_key[:12],
            )
