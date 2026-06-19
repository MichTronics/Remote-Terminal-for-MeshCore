import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Add live spam-detection tuning fields to app_settings."""
    tables_cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    if "app_settings" not in {row[0] for row in await tables_cursor.fetchall()}:
        await conn.commit()
        return

    col_cursor = await conn.execute("PRAGMA table_info(app_settings)")
    columns = {row[1] for row in await col_cursor.fetchall()}

    added = False
    if "spam_gateway_keys" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_gateway_keys TEXT DEFAULT ''"
        )
        added = True
    if "spam_live_window_secs" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_window_secs INTEGER DEFAULT 30"
        )
        added = True
    if "spam_live_packet_threshold" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_packet_threshold INTEGER DEFAULT 15"
        )
        added = True
    if "spam_live_cluster_min_ratio" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_cluster_min_ratio REAL DEFAULT 0.15"
        )
        added = True
    if "spam_live_broadcast_cooldown_secs" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_broadcast_cooldown_secs INTEGER DEFAULT 10"
        )
        added = True
    if "spam_live_hold_secs" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_hold_secs INTEGER DEFAULT 300"
        )
        added = True
    if "spam_live_episode_retention_secs" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_episode_retention_secs INTEGER DEFAULT 0"
        )
        added = True
    if "spam_live_max_report_clusters" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_max_report_clusters INTEGER DEFAULT 0"
        )
        added = True

    if added:
        from app.config import settings as cfg

        await conn.execute(
            """
            UPDATE app_settings SET
                spam_gateway_keys = ?,
                spam_live_window_secs = ?,
                spam_live_packet_threshold = ?,
                spam_live_cluster_min_ratio = ?,
                spam_live_broadcast_cooldown_secs = ?,
                spam_live_hold_secs = ?,
                spam_live_episode_retention_secs = ?,
                spam_live_max_report_clusters = ?
            WHERE id = 1
            """,
            (
                cfg.spam_gateway_keys,
                cfg.spam_live_window_secs,
                cfg.spam_live_packet_threshold,
                cfg.spam_live_cluster_min_ratio,
                cfg.spam_live_broadcast_cooldown_secs,
                cfg.spam_live_hold_secs,
                cfg.spam_live_episode_retention_secs,
                cfg.spam_live_max_report_clusters,
            ),
        )
        logger.info("Seeded spam detection tuning from environment/config defaults")

    await conn.commit()
