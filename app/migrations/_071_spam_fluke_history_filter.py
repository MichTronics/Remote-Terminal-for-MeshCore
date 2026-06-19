import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Add fluke-episode history filter settings to app_settings."""
    tables_cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    if "app_settings" not in {row[0] for row in await tables_cursor.fetchall()}:
        await conn.commit()
        return

    col_cursor = await conn.execute("PRAGMA table_info(app_settings)")
    columns = {row[1] for row in await col_cursor.fetchall()}

    added = False
    if "spam_live_fluke_max_packets" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_fluke_max_packets INTEGER DEFAULT 35"
        )
        added = True
    if "spam_live_fluke_max_duration_secs" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_live_fluke_max_duration_secs INTEGER DEFAULT 300"
        )
        added = True

    if added:
        from app.config import settings as cfg

        await conn.execute(
            """
            UPDATE app_settings SET
                spam_live_fluke_max_packets = ?,
                spam_live_fluke_max_duration_secs = ?
            WHERE id = 1
            """,
            (
                cfg.spam_live_fluke_max_packets,
                cfg.spam_live_fluke_max_duration_secs,
            ),
        )
        logger.info("Seeded spam fluke history filter defaults from config")

    await conn.commit()
