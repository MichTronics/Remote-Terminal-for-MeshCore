"""Runtime spam-detection tuning loaded from app_settings."""

from __future__ import annotations

from app.models import AppSettings
from app.repository import AppSettingsRepository

# Bounds mirror app/config.py Field constraints.
SPAM_LIVE_WINDOW_SECS_MIN = 5
SPAM_LIVE_WINDOW_SECS_MAX = 300
SPAM_LIVE_PACKET_THRESHOLD_MIN = 5
SPAM_LIVE_PACKET_THRESHOLD_MAX = 1000
SPAM_LIVE_CLUSTER_MIN_RATIO_MIN = 0.05
SPAM_LIVE_CLUSTER_MIN_RATIO_MAX = 1.0
SPAM_LIVE_BROADCAST_COOLDOWN_SECS_MIN = 1
SPAM_LIVE_BROADCAST_COOLDOWN_SECS_MAX = 120
SPAM_LIVE_HOLD_SECS_MAX = 3600
SPAM_LIVE_EPISODE_RETENTION_SECS_MAX = 3600
SPAM_LIVE_MAX_REPORT_CLUSTERS_MAX = 100
SPAM_LIVE_FLUKE_MAX_PACKETS_MAX = 1000
SPAM_LIVE_FLUKE_MAX_DURATION_SECS_MAX = 3600
MAX_SPAM_GATEWAY_KEYS_LEN = 4096


def is_fluke_episode(
    *,
    total_packets: int,
    duration_secs: int,
    max_packets: int,
    max_duration_secs: int,
) -> bool:
    """Return True when an ended episode should be dropped from flood alert history."""
    if max_packets <= 0:
        return False
    if total_packets >= max_packets:
        return False
    if max_duration_secs > 0 and duration_secs > max_duration_secs:
        return False
    return True


def tracker_kwargs_from_app_settings(settings: AppSettings) -> dict[str, object]:
    """Map persisted app settings to SpamLiveTracker runtime fields."""
    return {
        "spam_gateway_keys": settings.spam_gateway_keys,
        "window_secs": float(settings.spam_live_window_secs),
        "packet_threshold": settings.spam_live_packet_threshold,
        "cluster_min_ratio": float(settings.spam_live_cluster_min_ratio),
        "broadcast_cooldown_secs": float(settings.spam_live_broadcast_cooldown_secs),
        "hold_secs": float(settings.spam_live_hold_secs),
        "episode_retention_secs": float(settings.spam_live_episode_retention_secs),
        "max_report_clusters": settings.spam_live_max_report_clusters,
        "fluke_max_packets": settings.spam_live_fluke_max_packets,
        "fluke_max_duration_secs": settings.spam_live_fluke_max_duration_secs,
    }


async def refresh_spam_live_tracker_from_db() -> None:
    """Load spam-detection tuning from app_settings into the live tracker."""
    from app.services.spam_live_tracker import spam_live_tracker

    settings = await AppSettingsRepository.get()
    spam_live_tracker.apply_runtime_settings(**tracker_kwargs_from_app_settings(settings))
