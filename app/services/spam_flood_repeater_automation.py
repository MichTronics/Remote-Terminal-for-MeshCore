"""Send configured repeater CLI commands when spam flood episodes start or end."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import HTTPException
from meshcore import EventType

from app.models import CONTACT_TYPE_REPEATER
from app.repository import AppSettingsRepository, ContactRepository
from app.radio import RadioDisconnectedError, RadioOperationBusyError

logger = logging.getLogger(__name__)

SpamFloodPhase = Literal["start", "end"]

# During floods, send more than twice — the radio lock and RF congestion can swallow attempts.
DEFAULT_COMMAND_ATTEMPTS = 5
DEFAULT_COMMAND_RETRY_DELAY_SECS = 10.0
CLI_RESPONSE_TIMEOUT_SECS = 8.0
CLI_LOGIN_TIMEOUT_SECS = 8.0


def schedule_spam_flood_repeater_commands(phase: SpamFloodPhase) -> None:
    """Fire-and-forget repeater command dispatch for a spam flood phase transition."""
    asyncio.create_task(_dispatch_spam_flood_repeater_commands(phase))


async def _send_spam_flood_cli_command(
    *,
    contact,
    command: str,
    operation_name: str,
    repeater_password: str,
) -> str | None:
    """Login (when configured), send a CLI command, and return response text if heard."""
    from app.routers.contacts import _ensure_on_radio
    from app.routers.server_control import (
        extract_response_text,
        fetch_contact_cli_response,
        prepare_authenticated_contact_connection,
    )
    from app.services.radio_runtime import radio_runtime as radio_manager

    label = contact.name or contact.public_key[:12]
    prefix = contact.public_key[:12]

    async with radio_manager.radio_operation(
        operation_name,
        pause_polling=True,
        suspend_auto_fetch=True,
    ) as mc:
        password = repeater_password.strip()
        if password:
            login_result = await prepare_authenticated_contact_connection(
                mc,
                contact,
                password,
                response_timeout=CLI_LOGIN_TIMEOUT_SECS,
            )
            if not login_result.authenticated:
                logger.warning(
                    "Spam flood CLI login not confirmed for %s (%s): %s",
                    label,
                    prefix,
                    login_result.message or login_result.status,
                )
        else:
            logger.info(
                "Spam flood CLI sending without auto-login for %s (%s); "
                "configure a repeater password in Spam Defense if privileged commands fail",
                label,
                prefix,
            )
            await _ensure_on_radio(mc, contact)
            await asyncio.sleep(0.5)

        await asyncio.sleep(0.5)
        logger.info("Sending spam flood CLI to %s (%s): %s", label, prefix, command)
        send_result = await mc.commands.send_cmd(contact.public_key, command)
        if send_result.type == EventType.ERROR:
            raise HTTPException(
                status_code=422,
                detail=f"Failed to send command: {send_result.payload}",
            )

        response_event = await fetch_contact_cli_response(
            mc,
            prefix,
            timeout=CLI_RESPONSE_TIMEOUT_SECS,
        )
        if response_event is None:
            logger.warning(
                "Spam flood CLI sent to %s (%s) but no response heard within %.0fs "
                "(command may still have been processed)",
                label,
                prefix,
                CLI_RESPONSE_TIMEOUT_SECS,
            )
            return None

        response_text = extract_response_text(response_event)
        logger.info(
            "Spam flood CLI response from %s (%s): %s",
            label,
            prefix,
            response_text[:120],
        )
        return response_text


async def _send_command_with_retries(
    *,
    phase: SpamFloodPhase,
    contact,
    command: str,
    attempts: int,
    retry_delay_secs: float,
    repeater_password: str,
) -> None:
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
            await _send_spam_flood_cli_command(
                contact=contact,
                command=command,
                operation_name=operation_name,
                repeater_password=repeater_password,
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

    repeater_password = settings.spam_flood_repeater_password or ""

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
            repeater_password=repeater_password,
        )
