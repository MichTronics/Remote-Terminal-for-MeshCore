import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Add transport_codes column to raw_packets table for region information."""
    # Check if column already exists
    col_cursor = await conn.execute("PRAGMA table_info(raw_packets)")
    columns = {row[1] for row in await col_cursor.fetchall()}

    if "transport_codes" not in columns:
        await conn.execute(
            "ALTER TABLE raw_packets ADD COLUMN transport_codes BLOB"
        )
        logger.info("Added transport_codes column to raw_packets table")

    await conn.commit()
