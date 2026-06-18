import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Add spam-flood repeater automation settings to app_settings."""
    tables_cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    if "app_settings" not in {row[0] for row in await tables_cursor.fetchall()}:
        await conn.commit()
        return

    col_cursor = await conn.execute("PRAGMA table_info(app_settings)")
    columns = {row[1] for row in await col_cursor.fetchall()}

    if "spam_flood_automation_enabled" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_flood_automation_enabled INTEGER DEFAULT 0"
        )
    if "spam_flood_repeater_keys" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_flood_repeater_keys TEXT DEFAULT '[]'"
        )
    if "spam_flood_start_command" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_flood_start_command TEXT DEFAULT ''"
        )
    if "spam_flood_end_command" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN spam_flood_end_command TEXT DEFAULT ''"
        )

    await conn.commit()
