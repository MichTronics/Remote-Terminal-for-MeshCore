"""Send configured repeater CLI commands when spam flood episodes start or end."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import HTTPException

from app.models import CONTACT_TYPE_REPEATER
from app.repository import AppSettingsRepository, ContactRepository
from app.radio import RadioDisconnectedError, RadioOperationBusyError

logger = logging.getLogger(__name__)

SpamFloodPhase = Literal["start", "end"]

# Send each command twice by default so one lost in flood traffic still lands.
DEFAULT_COMMAND_ATTEMPTS = 2
DEFAULT_COMMAND_RETRY_DELAY_SECS = 5.0


def schedule_spam_flood_repeater_commands(phase: SpamFloodPhase) -> None:
    """Fire-and-forget repeater command dispatch for a spam flood phase transition."""
    asyncio.create_task(_dispatch_spam_flood_repeater_commands(phase))


async def _send_command_with_retries(
    *,
    phase: SpamFloodPhase,
    contact,
    command: str,
    attempts: int,
    retry_delay_secs: float,
) -> None:
    from app.routers.server_control import send_contact_cli_command

    label = contact.name or contact.public_key[:12]
    prefix = contact.public_key[:12]
    operation_name = f"spam_flood_{phase}"

    for attempt in range(1, attempts + 1):
        try:
            logger.info(
                "Spam flood %s command attempt %d/%d to %s (%s): %s",
                phase,
                attempt,
                attempts,
                label,
                prefix,
                command,
            )
            response = await send_contact_cli_command(
                contact,
                command,
                operation_name=operation_name,
            )
            logger.info(
                "Spam flood %s command attempt %d/%d acknowledged by %s (%s): %s",
                phase,
                attempt,
                attempts,
                label,
                prefix,
                (response.response or "")[:120],
            )
        except RadioDisconnectedError:
            logger.warning(
                "Spam flood %s command attempt %d/%d skipped: radio disconnected",
                phase,
                attempt,
                attempts,
            )
            return
        except RadioOperationBusyError as exc:
            logger.warning(
                "Spam flood %s command attempt %d/%d skipped: %s",
                phase,
                attempt,
                attempts,
                exc,
            )
        except HTTPException as exc:
            logger.warning(
                "Spam flood %s command attempt %d/%d failed for %s (%s): %s",
                phase,
                attempt,
                attempts,
                label,
                prefix,
                exc.detail,
            )
        except Exception:
            logger.exception(
                "Spam flood %s command attempt %d/%d failed for repeater %s",
                phase,
                attempt,
                attempts,
                prefix,
            )

        if attempt < attempts and retry_delay_secs > 0:
            await asyncio.sleep(retry_delay_secs)


async def _dispatch_spam_flood_repeater_commands(phase: SpamFloodPhase) -> None:
    settings = await AppSettingsRepository.get()
    if not settings.spam_flood_automation_enabled:
        logger.info("Spam flood %s command dispatch skipped: automation disabled", phase)
        return

    command = (
        settings.spam_flood_start_command
        if phase == "start"
        else settings.spam_flood_end_command
    ).strip()
    if not command:
        logger.info("Spam flood %s command dispatch skipped: command not configured", phase)
        return

    keys = settings.spam_flood_repeater_keys
    if not keys:
        logger.info("Spam flood %s command dispatch skipped: no repeaters selected", phase)
        return

    logger.info(
        "Dispatching spam flood %s command %r to %d repeater(s)",
        phase,
        command,
        len(keys),
    )

    for public_key in keys:
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

        await _send_command_with_retries(
            phase=phase,
            contact=contact,
            command=command,
            attempts=DEFAULT_COMMAND_ATTEMPTS,
            retry_delay_secs=DEFAULT_COMMAND_RETRY_DELAY_SECS,
        )
