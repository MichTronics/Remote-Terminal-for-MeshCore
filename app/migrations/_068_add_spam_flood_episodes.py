import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    """Persist DM flood episode history for post-hoc review."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS spam_flood_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            duration_secs INTEGER,
            total_packets INTEGER NOT NULL DEFAULT 0,
            peak_packets_per_window INTEGER NOT NULL DEFAULT 0,
            baseline_packets_per_window REAL,
            anomaly_ratio REAL,
            packet_threshold INTEGER NOT NULL,
            window_secs INTEGER NOT NULL,
            primary_entry_hop TEXT,
            primary_entry_name TEXT,
            primary_origin_hop TEXT,
            primary_origin_name TEXT,
            primary_origin_lat REAL,
            primary_origin_lon REAL,
            primary_refined_route TEXT,
            primary_confidence INTEGER,
            clusters_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_spam_flood_episodes_started
            ON spam_flood_episodes (started_at DESC)
        """
    )
    await conn.commit()
