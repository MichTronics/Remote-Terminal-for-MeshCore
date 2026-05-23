import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Add region_name column to raw_packets table for identified region."""
    # Check if column already exists
    col_cursor = await conn.execute("PRAGMA table_info(raw_packets)")
    columns = {row[1] for row in await col_cursor.fetchall()}

    if "region_name" not in columns:
        await conn.execute(
            "ALTER TABLE raw_packets ADD COLUMN region_name TEXT"
        )
        
        # Create index for statistics queries
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_packets_region_name ON raw_packets(region_name) WHERE region_name IS NOT NULL"
        )
        
        logger.info("Added region_name column to raw_packets table")

    await conn.commit()
