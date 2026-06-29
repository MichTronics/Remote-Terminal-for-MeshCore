import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Add map_contact_max_days to app_settings (default 7)."""
    tables_cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    if "app_settings" not in {row[0] for row in await tables_cursor.fetchall()}:
        await conn.commit()
        return
    col_cursor = await conn.execute("PRAGMA table_info(app_settings)")
    columns = {row[1] for row in await col_cursor.fetchall()}
    if "map_contact_max_days" not in columns:
        await conn.execute(
            "ALTER TABLE app_settings ADD COLUMN map_contact_max_days INTEGER DEFAULT 7"
        )
        await conn.commit()
