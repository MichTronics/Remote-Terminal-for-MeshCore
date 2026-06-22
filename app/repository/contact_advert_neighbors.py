"""Persist first-hop advert neighbors for mesh triangulation hints."""

from __future__ import annotations

import app.database as database
from app.models import Contact
from app.path_utils import (
    first_hop_hex,
    first_hop_hex_for_hash_size,
    hash_mode_from_hash_size,
    hash_mode_from_hop_token,
)
from app.repository.contacts import ContactRepository

ADVERT_NEIGHBOR_TTL_SECS = 7 * 24 * 3600


class ContactAdvertNeighborRepository:
    @staticmethod
    def _normalize_path_hash_mode(path_hash_mode: int | None) -> int | None:
        if path_hash_mode is None:
            return None
        mode = int(path_hash_mode)
        if mode < 0 or mode > 2:
            return None
        return mode

    @staticmethod
    async def record_observation(
        *,
        public_key: str,
        path_hex: str,
        hop_count: int,
        timestamp: int,
        path_hash_size: int | None = None,
        path_hash_mode: int | None = None,
    ) -> bool:
        """Upsert the advertiser's first RF hop neighbor. Returns True when recorded."""
        resolved_mode = ContactAdvertNeighborRepository._normalize_path_hash_mode(path_hash_mode)
        if resolved_mode is None and path_hash_size is not None:
            resolved_mode = hash_mode_from_hash_size(int(path_hash_size))

        if path_hash_size is not None and resolved_mode is not None:
            neighbor_hop = first_hop_hex_for_hash_size(path_hex, hop_count, int(path_hash_size))
        else:
            neighbor_hop = first_hop_hex(path_hex, hop_count)
            if resolved_mode is None and neighbor_hop is not None:
                resolved_mode = hash_mode_from_hop_token(neighbor_hop)

        if not neighbor_hop or resolved_mode is None:
            return False

        normalized_key = public_key.lower()
        normalized_hop = neighbor_hop.upper()

        async with database.db.tx() as conn:
            await conn.execute(
                """
                INSERT INTO contact_advert_neighbors
                    (public_key, neighbor_hop, path_hash_mode,
                     first_seen, last_seen, heard_count)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(public_key, neighbor_hop, path_hash_mode) DO UPDATE SET
                    last_seen = MAX(contact_advert_neighbors.last_seen, excluded.last_seen),
                    heard_count = contact_advert_neighbors.heard_count + 1
                """,
                (normalized_key, normalized_hop, resolved_mode, timestamp, timestamp),
            )
            cutoff = timestamp - ADVERT_NEIGHBOR_TTL_SECS
            await conn.execute(
                "DELETE FROM contact_advert_neighbors WHERE last_seen < ?",
                (cutoff,),
            )
        return True

    @staticmethod
    async def list_contacts_for_neighbor_hop(
        neighbor_hop: str,
        *,
        path_hash_mode: int | None = None,
        now: int | None = None,
        limit: int = 25,
    ) -> list[Contact]:
        """Contacts whose adverts were heard with this first-hop neighbor."""
        import time

        cutoff = (now if now is not None else int(time.time())) - ADVERT_NEIGHBOR_TTL_SECS
        normalized_hop = neighbor_hop.strip().upper()
        if not normalized_hop:
            return []

        resolved_mode = ContactAdvertNeighborRepository._normalize_path_hash_mode(
            path_hash_mode
        )
        if resolved_mode is None:
            resolved_mode = hash_mode_from_hop_token(normalized_hop)

        async with database.db.readonly() as conn:
            if resolved_mode is None:
                query = """
                    SELECT c.*
                    FROM contact_advert_neighbors n
                    INNER JOIN contacts c ON c.public_key = n.public_key
                    WHERE n.neighbor_hop = ?
                      AND n.last_seen >= ?
                    ORDER BY n.heard_count DESC, n.last_seen DESC, c.public_key ASC
                    LIMIT ?
                """
                params = (normalized_hop, cutoff, limit)
            else:
                query = """
                    SELECT c.*
                    FROM contact_advert_neighbors n
                    INNER JOIN contacts c ON c.public_key = n.public_key
                    WHERE n.neighbor_hop = ?
                      AND n.path_hash_mode = ?
                      AND n.last_seen >= ?
                    ORDER BY n.heard_count DESC, n.last_seen DESC, c.public_key ASC
                    LIMIT ?
                """
                params = (normalized_hop, resolved_mode, cutoff, limit)

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()

        return [ContactRepository._row_to_contact(row) for row in rows]

    @staticmethod
    async def count_stored() -> int:
        """Return the number of stored advert first-hop neighbor rows."""
        async with database.db.readonly() as conn:
            async with conn.execute("SELECT COUNT(*) AS cnt FROM contact_advert_neighbors") as cursor:
                row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    @staticmethod
    async def prune_stale(*, now: int | None = None) -> int:
        """Remove neighbor rows older than the retention window."""
        import time

        cutoff = (now if now is not None else int(time.time())) - ADVERT_NEIGHBOR_TTL_SECS
        async with database.db.tx() as conn:
            cursor = await conn.execute(
                "DELETE FROM contact_advert_neighbors WHERE last_seen < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount if cursor.rowcount is not None and cursor.rowcount >= 0 else 0
        return deleted
