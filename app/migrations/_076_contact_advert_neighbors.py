"""Advert first-hop neighbors for spam triangulation."""

from __future__ import annotations

import logging

import aiosqlite

from app.path_utils import first_hop_hex, hash_mode_from_hop_token

logger = logging.getLogger(__name__)


def _infer_path_hash_mode(path_hex: str, path_len: int, neighbor_hop: str) -> int:
    if path_len > 0 and path_hex:
        chars_per_hop = len(path_hex) // path_len
        if chars_per_hop in (2, 4, 6):
            return (chars_per_hop // 2) - 1
    mode = hash_mode_from_hop_token(neighbor_hop)
    return mode if mode is not None else 0


async def migrate(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_advert_neighbors (
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
        """
        SELECT public_key, path_hex, path_len, first_seen, last_seen, heard_count
        FROM contact_advert_paths
        """
    )
    rows = await cursor.fetchall()
    backfilled = 0
    for row in rows:
        path_hex = row["path_hex"] or ""
        path_len = int(row["path_len"] or 0)
        neighbor_hop = first_hop_hex(path_hex, path_len)
        if not neighbor_hop:
            continue
        path_hash_mode = _infer_path_hash_mode(path_hex, path_len, neighbor_hop)
        await conn.execute(
            """
            INSERT INTO contact_advert_neighbors
                (public_key, neighbor_hop, path_hash_mode,
                 first_seen, last_seen, heard_count)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(public_key, neighbor_hop, path_hash_mode) DO UPDATE SET
                first_seen = MIN(contact_advert_neighbors.first_seen, excluded.first_seen),
                last_seen = MAX(contact_advert_neighbors.last_seen, excluded.last_seen),
                heard_count = MAX(contact_advert_neighbors.heard_count, excluded.heard_count)
            """,
            (
                row["public_key"].lower(),
                neighbor_hop.upper(),
                path_hash_mode,
                int(row["first_seen"]),
                int(row["last_seen"]),
                int(row["heard_count"]),
            ),
        )
        backfilled += 1

    await conn.commit()
    logger.info(
        "Ensured contact_advert_neighbors table (backfilled %d rows from advert paths)",
        backfilled,
    )
