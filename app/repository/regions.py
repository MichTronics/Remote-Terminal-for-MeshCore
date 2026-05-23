import time

from app.database import db
from app.models import Region


class RegionRepository:
    """Repository for managing MeshCore transport regions."""

    @staticmethod
    async def create(name: str, key: bytes | None, is_public: bool) -> Region:
        """Create a new region."""
        created_at = int(time.time())
        async with db.tx() as conn:
            async with conn.execute(
                """
                INSERT INTO regions (name, key, is_public, created_at)
                VALUES (?, ?, ?, ?)
                RETURNING id
                """,
                (name, key, is_public, created_at),
            ) as cursor:
                row = await cursor.fetchone()
                region_id = row["id"]

        return Region(
            id=region_id,
            name=name,
            key=key.hex() if key else None,
            is_public=is_public,
            created_at=created_at,
        )

    @staticmethod
    async def get_by_name(name: str) -> Region | None:
        """Get a region by name."""
        async with db.readonly() as conn:
            async with conn.execute(
                """
                SELECT id, name, key, is_public, created_at
                FROM regions
                WHERE name = ?
                """,
                (name,),
            ) as cursor:
                row = await cursor.fetchone()

        if row:
            return Region(
                id=row["id"],
                name=row["name"],
                key=row["key"].hex() if row["key"] else None,
                is_public=bool(row["is_public"]),
                created_at=row["created_at"],
            )
        return None

    @staticmethod
    async def get_all() -> list[Region]:
        """Get all regions ordered by name."""
        async with db.readonly() as conn:
            async with conn.execute(
                """
                SELECT id, name, key, is_public, created_at
                FROM regions
                ORDER BY name
                """
            ) as cursor:
                rows = await cursor.fetchall()

        return [
            Region(
                id=row["id"],
                name=row["name"],
                key=row["key"].hex() if row["key"] else None,
                is_public=bool(row["is_public"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    @staticmethod
    async def delete(name: str) -> bool:
        """Delete a region by name. Returns True if deleted, False if not found."""
        async with db.tx() as conn:
            async with conn.execute(
                "DELETE FROM regions WHERE name = ?", (name,)
            ) as cursor:
                return cursor.rowcount > 0

    @staticmethod
    async def get_region_key_bytes(name: str) -> bytes | None:
        """Get the region key as bytes (for derived keys, returns the cached key)."""
        async with db.readonly() as conn:
            async with conn.execute(
                """
                SELECT key
                FROM regions
                WHERE name = ?
                """,
                (name,),
            ) as cursor:
                row = await cursor.fetchone()

        return row["key"] if row and row["key"] else None
