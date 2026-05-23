#!/usr/bin/env python3
"""One-time script to backfill region_name for existing packets."""
import asyncio
import logging

from app.database import get_db_connection
from app.packet_processor import identify_packet_region, parse_packet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill_regions():
    """Identify and set region_name for all packets with transport_codes but no region_name."""
    async with get_db_connection() as db:
        # Get packets that have transport codes but no region name
        cursor = await db.execute(
            """
            SELECT id, data, transport_codes
            FROM raw_packets
            WHERE transport_codes IS NOT NULL
              AND region_name IS NULL
            ORDER BY id
            """
        )
        rows = await cursor.fetchall()
        
        if not rows:
            logger.info("No packets need region backfill")
            return
        
        logger.info("Found %d packets to backfill", len(rows))
        updated = 0
        
        for row in rows:
            packet_id = row[0]
            data_hex = row[1]
            
            # Parse packet to get packet_info
            raw_bytes = bytes.fromhex(data_hex)
            packet_info = parse_packet(raw_bytes)
            
            if not packet_info or not packet_info.transport_codes:
                continue
            
            # Identify region
            region_name = await identify_packet_region(packet_info)
            
            if region_name:
                await db.execute(
                    "UPDATE raw_packets SET region_name = ? WHERE id = ?",
                    (region_name, packet_id)
                )
                updated += 1
                if updated % 100 == 0:
                    logger.info("Backfilled %d packets so far...", updated)
        
        await db.commit()
        logger.info("Backfill complete: %d/%d packets identified", updated, len(rows))


if __name__ == "__main__":
    asyncio.run(backfill_regions())
