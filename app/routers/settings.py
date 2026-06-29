import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models import CONTACT_TYPE_REPEATER, AppSettings
from app.region_scope import normalize_region_scope
from app.repository import AppSettingsRepository, ChannelRepository, ContactRepository
from app.telemetry_interval import (
    DEFAULT_TELEMETRY_INTERVAL_HOURS,
    TELEMETRY_INTERVAL_OPTIONS_HOURS,
    clamp_telemetry_interval,
    legal_interval_options,
    next_run_timestamp_utc,
)
from app.services.spam_detection_settings import (
    MAX_SPAM_GATEWAY_KEYS_LEN,
    SPAM_LIVE_BROADCAST_COOLDOWN_SECS_MAX,
    SPAM_LIVE_BROADCAST_COOLDOWN_SECS_MIN,
    SPAM_LIVE_CLUSTER_MIN_RATIO_MAX,
    SPAM_LIVE_CLUSTER_MIN_RATIO_MIN,
    SPAM_LIVE_EPISODE_RETENTION_SECS_MAX,
    SPAM_LIVE_HOLD_SECS_MAX,
    SPAM_LIVE_MAX_REPORT_CLUSTERS_MAX,
    SPAM_LIVE_PACKET_THRESHOLD_MAX,
    SPAM_LIVE_PACKET_THRESHOLD_MIN,
    SPAM_LIVE_WINDOW_SECS_MAX,
    SPAM_LIVE_WINDOW_SECS_MIN,
    SPAM_LIVE_FLUKE_MAX_DURATION_SECS_MAX,
    SPAM_LIVE_FLUKE_MAX_PACKETS_MAX,
    refresh_spam_live_tracker_from_db,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

MAX_TRACKED_TELEMETRY_REPEATERS = 8
MAX_TRACKED_TELEMETRY_CONTACTS = 8
MAX_SPAM_FLOOD_REPEATERS = 16
MAX_SPAM_FLOOD_COMMAND_LEN = 256
MAX_SPAM_FLOOD_REPEATER_PASSWORD_LEN = 256

SPAM_TUNING_UPDATE_FIELDS = (
    "spam_gateway_keys",
    "spam_live_window_secs",
    "spam_live_packet_threshold",
    "spam_live_cluster_min_ratio",
    "spam_live_broadcast_cooldown_secs",
    "spam_live_hold_secs",
    "spam_live_episode_retention_secs",
    "spam_live_max_report_clusters",
    "spam_live_fluke_max_packets",
    "spam_live_fluke_max_duration_secs",
)


class AppSettingsUpdate(BaseModel):
    max_radio_contacts: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description=(
            "Configured radio contact capacity used for maintenance thresholds and "
            "background refill behavior"
        ),
    )
    auto_decrypt_dm_on_advert: bool | None = Field(
        default=None,
        description="Whether to attempt historical DM decryption on new contact advertisement",
    )
    advert_interval: int | None = Field(
        default=None,
        ge=0,
        description="Periodic advertisement interval in seconds (0 = disabled, minimum 3600)",
    )
    flood_scope: str | None = Field(
        default=None,
        description="Outbound flood scope / region name (empty = disabled)",
    )
    blocked_keys: list[str] | None = Field(
        default=None,
        description="Public keys whose messages are hidden from the UI",
    )
    blocked_names: list[str] | None = Field(
        default=None,
        description="Display names whose messages are hidden from the UI",
    )
    discovery_blocked_types: list[int] | None = Field(
        default=None,
        description=(
            "Contact type codes (1=Client, 2=Repeater, 3=Room, 4=Sensor) whose "
            "advertisements should not create new contacts"
        ),
    )
    auto_resend_channel: bool | None = Field(
        default=None,
        description="Auto-resend channel messages once if no echo heard within 2 seconds",
    )
    telemetry_interval_hours: int | None = Field(
        default=None,
        description=(
            "Preferred tracked-repeater telemetry interval in hours. "
            f"Must be one of {list(TELEMETRY_INTERVAL_OPTIONS_HOURS)}. "
            "Effective interval is clamped up to the shortest legal value "
            "based on the current tracked-repeater count."
        ),
    )
    telemetry_routed_hourly: bool | None = Field(
        default=None,
        description=(
            "When enabled, tracked repeaters with a direct or routed (non-flood) "
            "path are polled every hour instead of on the normal scheduled interval."
        ),
    )
    tracker_history_hours: int | None = Field(
        default=None,
        ge=1,
        le=168,
        description="Retention period for tracker location history in hours (1-168, default 12)",
    )
    map_contact_max_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description=(
            "How many days back to show contacts with GPS on the Node Map "
            "(display-only; does not delete data)"
        ),
    )
    spam_gateway_keys: str | None = Field(
        default=None,
        max_length=MAX_SPAM_GATEWAY_KEYS_LEN,
        description=(
            "Comma-separated gateway repeater public keys for RF path stripping. "
            "Empty uses built-in defaults; 'none' disables stripping."
        ),
    )
    spam_live_window_secs: int | None = Field(default=None, ge=5, le=300)
    spam_live_packet_threshold: int | None = Field(default=None, ge=5, le=1000)
    spam_live_cluster_min_ratio: float | None = Field(default=None, ge=0.05, le=1.0)
    spam_live_broadcast_cooldown_secs: int | None = Field(default=None, ge=1, le=120)
    spam_live_hold_secs: int | None = Field(default=None, ge=0, le=3600)
    spam_live_episode_retention_secs: int | None = Field(default=None, ge=0, le=3600)
    spam_live_max_report_clusters: int | None = Field(default=None, ge=0, le=100)
    spam_live_fluke_max_packets: int | None = Field(default=None, ge=0, le=1000)
    spam_live_fluke_max_duration_secs: int | None = Field(default=None, ge=0, le=3600)
    spam_flood_automation_enabled: bool | None = Field(
        default=None,
        description="Send configured repeater CLI commands when spam flood episodes start/end",
    )
    spam_flood_repeater_keys: list[str] | None = Field(
        default=None,
        description="Repeater public keys that receive spam-flood automation commands",
    )
    spam_flood_start_command: str | None = Field(
        default=None,
        max_length=MAX_SPAM_FLOOD_COMMAND_LEN,
        description="CLI command sent when a spam flood episode starts",
    )
    spam_flood_end_command: str | None = Field(
        default=None,
        max_length=MAX_SPAM_FLOOD_COMMAND_LEN,
        description="CLI command sent when a spam flood episode ends",
    )
    spam_flood_repeater_password: str | None = Field(
        default=None,
        max_length=MAX_SPAM_FLOOD_REPEATER_PASSWORD_LEN,
        description="Optional repeater login password for spam-flood CLI automation",
    )


class BlockKeyRequest(BaseModel):
    key: str = Field(description="Public key to toggle block status")


class BlockNameRequest(BaseModel):
    name: str = Field(description="Display name to toggle block status")


class FavoriteRequest(BaseModel):
    type: Literal["channel", "contact"] = Field(description="'channel' or 'contact'")
    id: str = Field(description="Channel key or contact public key")


class FavoriteToggleResponse(BaseModel):
    type: Literal["channel", "contact"]
    id: str
    favorite: bool


class MuteChannelRequest(BaseModel):
    key: str = Field(description="Channel key to toggle mute status")


class MuteChannelToggleResponse(BaseModel):
    key: str
    muted: bool


class TrackedTelemetryRequest(BaseModel):
    public_key: str = Field(description="Public key of the repeater to toggle tracking")


class TelemetrySchedule(BaseModel):
    """Surface of telemetry scheduling derivations for the UI.

    ``preferred_hours`` is the stored user choice. ``effective_hours`` is the
    value the scheduler actually uses (preferred, clamped up to the shortest
    legal interval given the current tracked-repeater count). ``options``
    lists the subset of the menu that is legal at the current count; the UI
    should hide anything not in this list. ``next_run_at`` is the Unix
    timestamp (seconds, UTC) of the next scheduled cycle, or ``None`` when
    no repeaters are tracked (nothing to schedule).
    """

    preferred_hours: int = Field(description="User's saved telemetry interval preference")
    effective_hours: int = Field(description="Scheduler's clamped interval")
    options: list[int] = Field(description="Legal interval choices at the current count")
    tracked_count: int = Field(description="Number of repeaters currently tracked")
    max_tracked: int = Field(description="Maximum number of repeaters that can be tracked")
    next_run_at: int | None = Field(
        default=None,
        description="Unix timestamp (UTC seconds) of the next scheduled flood cycle",
    )
    routed_hourly: bool = Field(
        default=False,
        description="Whether hourly routed/direct-path telemetry is enabled",
    )
    next_routed_run_at: int | None = Field(
        default=None,
        description=(
            "Unix timestamp (UTC seconds) of the next hourly routed/direct check, "
            "or None when routed_hourly is off or no repeaters are tracked"
        ),
    )


class TrackedTelemetryResponse(BaseModel):
    tracked_telemetry_repeaters: list[str] = Field(
        description="Current list of tracked repeater public keys"
    )
    names: dict[str, str] = Field(
        description="Map of public key to display name for tracked repeaters"
    )
    schedule: TelemetrySchedule = Field(description="Current scheduling state")


def _build_schedule(
    tracked_count: int,
    preferred_hours: int | None,
    routed_hourly: bool = False,
) -> TelemetrySchedule:
    pref = (
        preferred_hours
        if preferred_hours in TELEMETRY_INTERVAL_OPTIONS_HOURS
        else DEFAULT_TELEMETRY_INTERVAL_HOURS
    )
    effective = clamp_telemetry_interval(pref, tracked_count)
    has_tracked = tracked_count > 0
    return TelemetrySchedule(
        preferred_hours=pref,
        effective_hours=effective,
        options=legal_interval_options(tracked_count),
        tracked_count=tracked_count,
        max_tracked=MAX_TRACKED_TELEMETRY_REPEATERS,
        next_run_at=next_run_timestamp_utc(effective) if has_tracked else None,
        routed_hourly=routed_hourly,
        next_routed_run_at=(next_run_timestamp_utc(1) if has_tracked and routed_hourly else None),
    )


@router.get("", response_model=AppSettings)
async def get_settings() -> AppSettings:
    """Get current application settings."""
    return await AppSettingsRepository.get()


@router.patch("", response_model=AppSettings)
async def update_settings(update: AppSettingsUpdate) -> AppSettings:
    """Update application settings.

    Settings are persisted to the database and survive restarts.
    """
    kwargs = {}
    if update.max_radio_contacts is not None:
        logger.info("Updating max_radio_contacts to %d", update.max_radio_contacts)
        kwargs["max_radio_contacts"] = update.max_radio_contacts

    if update.auto_decrypt_dm_on_advert is not None:
        logger.info("Updating auto_decrypt_dm_on_advert to %s", update.auto_decrypt_dm_on_advert)
        kwargs["auto_decrypt_dm_on_advert"] = update.auto_decrypt_dm_on_advert

    if update.advert_interval is not None:
        # Enforce minimum 1-hour interval; 0 means disabled
        interval = update.advert_interval
        if 0 < interval < 3600:
            interval = 3600
        logger.info("Updating advert_interval to %d", interval)
        kwargs["advert_interval"] = interval

    # Block lists
    if update.blocked_keys is not None:
        kwargs["blocked_keys"] = [k.lower() for k in update.blocked_keys]
    if update.blocked_names is not None:
        kwargs["blocked_names"] = update.blocked_names

    # Discovery blocked types
    if update.discovery_blocked_types is not None:
        # Only allow valid contact type codes (1-4)
        valid = [t for t in update.discovery_blocked_types if t in (1, 2, 3, 4)]
        kwargs["discovery_blocked_types"] = sorted(set(valid))

    # Auto-resend channel
    if update.auto_resend_channel is not None:
        kwargs["auto_resend_channel"] = update.auto_resend_channel

    # Telemetry interval preference. Invalid values fall back to default
    # rather than 400-ing so a stale client can't brick settings saves.
    if update.telemetry_interval_hours is not None:
        raw_interval = update.telemetry_interval_hours
        if raw_interval not in TELEMETRY_INTERVAL_OPTIONS_HOURS:
            logger.warning(
                "telemetry_interval_hours=%r is not in the menu; defaulting to %d",
                raw_interval,
                DEFAULT_TELEMETRY_INTERVAL_HOURS,
            )
            raw_interval = DEFAULT_TELEMETRY_INTERVAL_HOURS
        logger.info("Updating telemetry_interval_hours to %d", raw_interval)
        kwargs["telemetry_interval_hours"] = raw_interval

    # Telemetry routed hourly
    if update.telemetry_routed_hourly is not None:
        logger.info("Updating telemetry_routed_hourly to %s", update.telemetry_routed_hourly)
        kwargs["telemetry_routed_hourly"] = update.telemetry_routed_hourly

    # Tracker history retention
    if update.tracker_history_hours is not None:
        logger.info("Updating tracker_history_hours to %d", update.tracker_history_hours)
        kwargs["tracker_history_hours"] = update.tracker_history_hours

    if update.map_contact_max_days is not None:
        logger.info("Updating map_contact_max_days to %d", update.map_contact_max_days)
        kwargs["map_contact_max_days"] = update.map_contact_max_days

    if update.spam_gateway_keys is not None:
        kwargs["spam_gateway_keys"] = update.spam_gateway_keys.strip()

    if update.spam_live_window_secs is not None:
        value = update.spam_live_window_secs
        if not SPAM_LIVE_WINDOW_SECS_MIN <= value <= SPAM_LIVE_WINDOW_SECS_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"spam_live_window_secs must be between "
                    f"{SPAM_LIVE_WINDOW_SECS_MIN} and {SPAM_LIVE_WINDOW_SECS_MAX}"
                ),
            )
        kwargs["spam_live_window_secs"] = value

    if update.spam_live_packet_threshold is not None:
        value = update.spam_live_packet_threshold
        if not SPAM_LIVE_PACKET_THRESHOLD_MIN <= value <= SPAM_LIVE_PACKET_THRESHOLD_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"spam_live_packet_threshold must be between "
                    f"{SPAM_LIVE_PACKET_THRESHOLD_MIN} and {SPAM_LIVE_PACKET_THRESHOLD_MAX}"
                ),
            )
        kwargs["spam_live_packet_threshold"] = value

    if update.spam_live_cluster_min_ratio is not None:
        value = update.spam_live_cluster_min_ratio
        if not SPAM_LIVE_CLUSTER_MIN_RATIO_MIN <= value <= SPAM_LIVE_CLUSTER_MIN_RATIO_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"spam_live_cluster_min_ratio must be between "
                    f"{SPAM_LIVE_CLUSTER_MIN_RATIO_MIN} and {SPAM_LIVE_CLUSTER_MIN_RATIO_MAX}"
                ),
            )
        kwargs["spam_live_cluster_min_ratio"] = value

    if update.spam_live_broadcast_cooldown_secs is not None:
        value = update.spam_live_broadcast_cooldown_secs
        if not SPAM_LIVE_BROADCAST_COOLDOWN_SECS_MIN <= value <= SPAM_LIVE_BROADCAST_COOLDOWN_SECS_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"spam_live_broadcast_cooldown_secs must be between "
                    f"{SPAM_LIVE_BROADCAST_COOLDOWN_SECS_MIN} and {SPAM_LIVE_BROADCAST_COOLDOWN_SECS_MAX}"
                ),
            )
        kwargs["spam_live_broadcast_cooldown_secs"] = value

    if update.spam_live_hold_secs is not None:
        value = update.spam_live_hold_secs
        if not 0 <= value <= SPAM_LIVE_HOLD_SECS_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"spam_live_hold_secs must be between 0 and {SPAM_LIVE_HOLD_SECS_MAX}",
            )
        kwargs["spam_live_hold_secs"] = value

    if update.spam_live_episode_retention_secs is not None:
        value = update.spam_live_episode_retention_secs
        if not 0 <= value <= SPAM_LIVE_EPISODE_RETENTION_SECS_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"spam_live_episode_retention_secs must be between "
                    f"0 and {SPAM_LIVE_EPISODE_RETENTION_SECS_MAX}"
                ),
            )
        kwargs["spam_live_episode_retention_secs"] = value

    if update.spam_live_max_report_clusters is not None:
        value = update.spam_live_max_report_clusters
        if not 0 <= value <= SPAM_LIVE_MAX_REPORT_CLUSTERS_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"spam_live_max_report_clusters must be between "
                    f"0 and {SPAM_LIVE_MAX_REPORT_CLUSTERS_MAX}"
                ),
            )
        kwargs["spam_live_max_report_clusters"] = value

    if update.spam_live_fluke_max_packets is not None:
        value = update.spam_live_fluke_max_packets
        if not 0 <= value <= SPAM_LIVE_FLUKE_MAX_PACKETS_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"spam_live_fluke_max_packets must be between "
                    f"0 and {SPAM_LIVE_FLUKE_MAX_PACKETS_MAX}"
                ),
            )
        kwargs["spam_live_fluke_max_packets"] = value

    if update.spam_live_fluke_max_duration_secs is not None:
        value = update.spam_live_fluke_max_duration_secs
        if not 0 <= value <= SPAM_LIVE_FLUKE_MAX_DURATION_SECS_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"spam_live_fluke_max_duration_secs must be between "
                    f"0 and {SPAM_LIVE_FLUKE_MAX_DURATION_SECS_MAX}"
                ),
            )
        kwargs["spam_live_fluke_max_duration_secs"] = value

    if update.spam_flood_automation_enabled is not None:
        kwargs["spam_flood_automation_enabled"] = update.spam_flood_automation_enabled

    if update.spam_flood_repeater_keys is not None:
        if len(update.spam_flood_repeater_keys) > MAX_SPAM_FLOOD_REPEATERS:
            raise HTTPException(
                status_code=400,
                detail=f"At most {MAX_SPAM_FLOOD_REPEATERS} repeaters can be selected",
            )
        normalized_keys: list[str] = []
        for public_key in update.spam_flood_repeater_keys:
            key = public_key.lower()
            contact = await ContactRepository.get_by_key(key)
            if contact is None:
                raise HTTPException(status_code=404, detail=f"Repeater not found: {key[:12]}")
            if contact.type != CONTACT_TYPE_REPEATER:
                raise HTTPException(
                    status_code=400,
                    detail=f"Contact is not a repeater: {key[:12]}",
                )
            normalized_keys.append(key)
        kwargs["spam_flood_repeater_keys"] = normalized_keys

    if update.spam_flood_start_command is not None:
        kwargs["spam_flood_start_command"] = update.spam_flood_start_command.strip()

    if update.spam_flood_end_command is not None:
        kwargs["spam_flood_end_command"] = update.spam_flood_end_command.strip()

    if update.spam_flood_repeater_password is not None:
        kwargs["spam_flood_repeater_password"] = update.spam_flood_repeater_password.strip()

    # Flood scope
    flood_scope_changed = False
    if update.flood_scope is not None:
        kwargs["flood_scope"] = normalize_region_scope(update.flood_scope)
        flood_scope_changed = True

    if kwargs:
        spam_tuning_changed = any(getattr(update, field) is not None for field in SPAM_TUNING_UPDATE_FIELDS)
        result = await AppSettingsRepository.update(**kwargs)

        if spam_tuning_changed:
            await refresh_spam_live_tracker_from_db()

        # Apply flood scope to radio immediately if changed
        if flood_scope_changed:
            from app.services.radio_runtime import radio_runtime as radio_manager

            if radio_manager.is_connected:
                try:
                    scope = result.flood_scope
                    async with radio_manager.radio_operation("set_flood_scope") as mc:
                        await mc.commands.set_flood_scope(scope if scope else "")
                        logger.info("Applied flood_scope=%r to radio", scope or "(disabled)")
                except Exception as e:
                    logger.warning("Failed to apply flood_scope to radio: %s", e)

        return result

    return await AppSettingsRepository.get()


@router.post("/favorites/toggle", response_model=FavoriteToggleResponse)
async def toggle_favorite(request: FavoriteRequest) -> FavoriteToggleResponse:
    """Toggle a conversation's favorite status."""
    if request.type == "contact":
        contact = await ContactRepository.get_by_key(request.id)
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        new_value = not contact.favorite
        await ContactRepository.set_favorite(request.id, new_value)
        logger.info("%s contact favorite: %s", "Added" if new_value else "Removed", request.id[:12])
        # When newly favorited, load to radio immediately for DM ACK support
        if new_value:
            from app.radio_sync import ensure_contact_on_radio

            asyncio.create_task(ensure_contact_on_radio(request.id, force=True))
    else:
        channel = await ChannelRepository.get_by_key(request.id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        new_value = not channel.favorite
        await ChannelRepository.set_favorite(request.id, new_value)
        logger.info("%s channel favorite: %s", "Added" if new_value else "Removed", request.id[:12])

    return FavoriteToggleResponse(type=request.type, id=request.id, favorite=new_value)


@router.post("/muted-channels/toggle", response_model=MuteChannelToggleResponse)
async def toggle_muted_channel(request: MuteChannelRequest) -> MuteChannelToggleResponse:
    """Toggle a channel's muted status."""
    channel = await ChannelRepository.get_by_key(request.key)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    new_value = not channel.muted
    await ChannelRepository.set_muted(request.key, new_value)
    logger.info("%s channel mute: %s", "Muted" if new_value else "Unmuted", request.key[:12])

    refreshed = await ChannelRepository.get_by_key(request.key)
    if refreshed:
        from app.websocket import broadcast_event

        broadcast_event("channel", refreshed.model_dump())

    return MuteChannelToggleResponse(key=request.key, muted=new_value)


@router.post("/blocked-keys/toggle", response_model=AppSettings)
async def toggle_blocked_key(request: BlockKeyRequest) -> AppSettings:
    """Toggle a public key's blocked status."""
    logger.info("Toggling blocked key: %s", request.key[:12])
    return await AppSettingsRepository.toggle_blocked_key(request.key)


@router.post("/blocked-names/toggle", response_model=AppSettings)
async def toggle_blocked_name(request: BlockNameRequest) -> AppSettings:
    """Toggle a display name's blocked status."""
    logger.info("Toggling blocked name: %s", request.name)
    return await AppSettingsRepository.toggle_blocked_name(request.name)


@router.post("/tracked-telemetry/toggle", response_model=TrackedTelemetryResponse)
async def toggle_tracked_telemetry(request: TrackedTelemetryRequest) -> TrackedTelemetryResponse:
    """Toggle periodic telemetry collection for a repeater.

    Max 8 repeaters may be tracked. Returns 409 if the limit is reached and
    the requested repeater is not already tracked.
    """
    key = request.public_key.lower()
    settings = await AppSettingsRepository.get()
    current = settings.tracked_telemetry_repeaters

    async def _resolve_names(keys: list[str]) -> dict[str, str]:
        names: dict[str, str] = {}
        for k in keys:
            contact = await ContactRepository.get_by_key(k)
            names[k] = contact.name if contact and contact.name else k[:12]
        return names

    if key in current:
        # Remove
        new_list = [k for k in current if k != key]
        logger.info("Removing repeater %s from tracked telemetry", key[:12])
        await AppSettingsRepository.update(tracked_telemetry_repeaters=new_list)
        return TrackedTelemetryResponse(
            tracked_telemetry_repeaters=new_list,
            names=await _resolve_names(new_list),
            schedule=_build_schedule(
                len(new_list),
                settings.telemetry_interval_hours,
                settings.telemetry_routed_hourly,
            ),
        )

    # Validate it's a repeater
    contact = await ContactRepository.get_by_key(key)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if contact.type != CONTACT_TYPE_REPEATER:
        raise HTTPException(status_code=400, detail="Contact is not a repeater")

    if len(current) >= MAX_TRACKED_TELEMETRY_REPEATERS:
        names = await _resolve_names(current)
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Limit of {MAX_TRACKED_TELEMETRY_REPEATERS} tracked repeaters reached",
                "tracked_telemetry_repeaters": current,
                "names": names,
            },
        )

    new_list = current + [key]
    logger.info("Adding repeater %s to tracked telemetry", key[:12])
    await AppSettingsRepository.update(tracked_telemetry_repeaters=new_list)
    return TrackedTelemetryResponse(
        tracked_telemetry_repeaters=new_list,
        names=await _resolve_names(new_list),
        schedule=_build_schedule(
            len(new_list),
            settings.telemetry_interval_hours,
            settings.telemetry_routed_hourly,
        ),
    )


@router.get("/tracked-telemetry/schedule", response_model=TelemetrySchedule)
async def get_telemetry_schedule() -> TelemetrySchedule:
    """Return the current telemetry scheduling derivation.

    The UI uses this to render the interval dropdown (legal options),
    surface saved-vs-effective when they differ, and show the next-run-at
    timestamp so users know when the next cycle will fire.

    """
    app_settings = await AppSettingsRepository.get()
    return _build_schedule(
        len(app_settings.tracked_telemetry_repeaters),
        app_settings.telemetry_interval_hours,
        app_settings.telemetry_routed_hourly,
    )


# ---------------------------------------------------------------------------
# Tracked contact telemetry (non-repeater LPP telemetry collection)
# ---------------------------------------------------------------------------


class TrackedTelemetryContactsResponse(BaseModel):
    tracked_telemetry_contacts: list[str] = Field(
        description="Current list of tracked contact public keys"
    )
    names: dict[str, str] = Field(
        description="Map of public key to display name for tracked contacts"
    )
    schedule: TelemetrySchedule = Field(description="Current scheduling state")


@router.post("/tracked-telemetry-contacts/toggle", response_model=TrackedTelemetryContactsResponse)
async def toggle_tracked_telemetry_contact(
    request: TrackedTelemetryRequest,
) -> TrackedTelemetryContactsResponse:
    """Toggle periodic LPP telemetry collection for any contact.

    Max 8 contacts may be tracked. The daily check ceiling is shared with
    tracked repeaters.
    """
    key = request.public_key.lower()
    settings = await AppSettingsRepository.get()
    current = settings.tracked_telemetry_contacts

    async def _resolve_names(keys: list[str]) -> dict[str, str]:
        names: dict[str, str] = {}
        for k in keys:
            contact = await ContactRepository.get_by_key(k)
            names[k] = contact.name if contact and contact.name else k[:12]
        return names

    if key in current:
        # Remove
        new_list = [k for k in current if k != key]
        logger.info("Removing contact %s from tracked telemetry", key[:12])
        await AppSettingsRepository.update(tracked_telemetry_contacts=new_list)
        return TrackedTelemetryContactsResponse(
            tracked_telemetry_contacts=new_list,
            names=await _resolve_names(new_list),
            schedule=_build_schedule(
                len(new_list),
                settings.telemetry_interval_hours,
                settings.telemetry_routed_hourly,
            ),
        )

    # Validate contact exists and is not a repeater (repeaters use tracked_telemetry_repeaters)
    contact = await ContactRepository.get_by_key(key)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if contact.type == CONTACT_TYPE_REPEATER:
        raise HTTPException(
            status_code=400,
            detail="Repeaters use the dedicated repeater telemetry tracking list",
        )

    if len(current) >= MAX_TRACKED_TELEMETRY_CONTACTS:
        names = await _resolve_names(current)
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Limit of {MAX_TRACKED_TELEMETRY_CONTACTS} tracked contacts reached",
                "tracked_telemetry_contacts": current,
                "names": names,
            },
        )

    new_list = current + [key]
    logger.info("Adding contact %s to tracked telemetry", key[:12])
    await AppSettingsRepository.update(tracked_telemetry_contacts=new_list)
    return TrackedTelemetryContactsResponse(
        tracked_telemetry_contacts=new_list,
        names=await _resolve_names(new_list),
        schedule=_build_schedule(
            len(new_list),
            settings.telemetry_interval_hours,
            settings.telemetry_routed_hourly,
        ),
    )


@router.get("/tracked-telemetry-contacts/schedule", response_model=TelemetrySchedule)
async def get_contact_telemetry_schedule() -> TelemetrySchedule:
    """Return the current telemetry scheduling derivation for contacts."""
    app_settings = await AppSettingsRepository.get()
    return _build_schedule(
        len(app_settings.tracked_telemetry_contacts),
        app_settings.telemetry_interval_hours,
        app_settings.telemetry_routed_hourly,
    )
