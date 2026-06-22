"""Add path_hash_mode to contact_advert_neighbors for multibyte hop matching."""

from __future__ import annotations

import logging

import aiosqlite

from app.path_utils import hash_mode_from_hop_token

logger = logging.getLogger(__name__)


async def migrate(conn: aiosqlite.Connection) -> None:
    cursor = await conn.execute("PRAGMA table_info(contact_advert_neighbors)")
    columns = {row[1] for row in await cursor.fetchall()}
    if not columns:
        logger.info("contact_advert_neighbors missing; migration 076 will create it")
        return
    if "path_hash_mode" in columns:
        logger.info("contact_advert_neighbors.path_hash_mode already present")
        return

    await conn.execute(
        """
        CREATE TABLE contact_advert_neighbors_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_key TEXT NOT NULL,
            neighbor_hop TEXT NOT NULL,
            path_hash_mode INTEGER NOT NULL DEFAULT 0,
            first_seen INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            heard_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(public_key, neighbor_hop, path_hash_mode),
            FOREIGN KEY (public_key) REFERENCES contacts(public_key) ON DELETE CASCADE
        )
        """
    )
    await conn.execute(
        """
        INSERT INTO contact_advert_neighbors_new
            (id, public_key, neighbor_hop, path_hash_mode,
             first_seen, last_seen, heard_count)
        SELECT
            id,
            public_key,
            neighbor_hop,
            CASE
                WHEN LENGTH(neighbor_hop) = 2 THEN 0
                WHEN LENGTH(neighbor_hop) = 4 THEN 1
                WHEN LENGTH(neighbor_hop) = 6 THEN 2
                ELSE 0
            END,
            first_seen,
            last_seen,
            heard_count
        FROM contact_advert_neighbors
        """
    )
    await conn.execute("DROP TABLE contact_advert_neighbors")
    await conn.execute("ALTER TABLE contact_advert_neighbors_new RENAME TO contact_advert_neighbors")
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contact_advert_neighbors_hop_recent
        ON contact_advert_neighbors(neighbor_hop, path_hash_mode, last_seen DESC)
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contact_advert_neighbors_contact_recent
        ON contact_advert_neighbors(public_key, last_seen DESC)
        """
    )

    cursor = await conn.execute(
        "SELECT id, neighbor_hop FROM contact_advert_neighbors WHERE path_hash_mode = 0"
    )
    for row in await cursor.fetchall():
        mode = hash_mode_from_hop_token(row["neighbor_hop"] or "")
        if mode is not None and mode != 0:
            await conn.execute(
                "UPDATE contact_advert_neighbors SET path_hash_mode = ? WHERE id = ?",
                (mode, row["id"]),
            )

    await conn.commit()
    logger.info("Added path_hash_mode to contact_advert_neighbors")
