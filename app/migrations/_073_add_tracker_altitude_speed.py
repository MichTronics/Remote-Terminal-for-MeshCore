import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Persist last-known tracker altitude and speed on contacts for map display."""
    await conn.execute(
        """
        ALTER TABLE contacts ADD COLUMN tracker_altitude INTEGER
        """
    )
    await conn.execute(
        """
        ALTER TABLE contacts ADD COLUMN tracker_speed REAL
        """
    )
    logger.debug("Added contacts.tracker_altitude and contacts.tracker_speed columns")
