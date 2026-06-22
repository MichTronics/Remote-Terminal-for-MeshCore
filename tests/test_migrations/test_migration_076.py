"""Tests for migration 076: contact advert neighbors."""

import aiosqlite
import pytest

from app.migrations._076_contact_advert_neighbors import migrate


class TestMigration076:
    @pytest.mark.asyncio
    async def test_creates_table_and_backfills_from_advert_paths(self):
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        try:
            await conn.execute(
                """
                CREATE TABLE contacts (
                    public_key TEXT PRIMARY KEY,
                    name TEXT
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE contact_advert_paths (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_key TEXT NOT NULL,
                    path_hex TEXT NOT NULL,
                    path_len INTEGER NOT NULL,
                    first_seen INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL,
                    heard_count INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(public_key, path_hex, path_len)
                )
                """
            )
            contact_key = "aa" * 32
            await conn.execute(
                "INSERT INTO contacts (public_key, name) VALUES (?, ?)",
                (contact_key, "Repeater"),
            )
            await conn.execute(
                """
                INSERT INTO contact_advert_paths
                    (public_key, path_hex, path_len, first_seen, last_seen, heard_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (contact_key, "0F1122", 2, 1000, 1010, 3),
            )
            await conn.commit()

            await migrate(conn)

            cursor = await conn.execute(
                """
                SELECT neighbor_hop, path_hash_mode, first_seen, last_seen, heard_count
                FROM contact_advert_neighbors
                WHERE public_key = ?
                """,
                (contact_key,),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row["neighbor_hop"] == "0F"
            assert row["path_hash_mode"] == 0
            assert row["first_seen"] == 1000
            assert row["last_seen"] == 1010
            assert row["heard_count"] == 3
        finally:
            await conn.close()
