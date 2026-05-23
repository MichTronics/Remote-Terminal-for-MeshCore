import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Create regions table for MeshCore transport region management."""
    # Check if table already exists
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='regions'"
    )
    table_exists = await cursor.fetchone() is not None

    if not table_exists:
        await conn.execute("""
            CREATE TABLE regions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                key BLOB,
                is_public INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                CHECK(is_public IN (0, 1))
            )
        """)
        
        # Create index on name for fast lookup
        await conn.execute(
            "CREATE INDEX idx_regions_name ON regions(name)"
        )
        
        logger.info("Created regions table")

    await conn.commit()
