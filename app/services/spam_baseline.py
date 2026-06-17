"""Historical DM path-rate baseline for flood anomaly context."""

from __future__ import annotations

import time

from app.database import db
from app.decoder import PayloadType, parse_packet

DEFAULT_BASELINE_LOOKBACK_DAYS = 14


class SpamBaselineService:
    @staticmethod
    async def count_dm_path_observations(
        *,
        since: int,
        until: int | None = None,
    ) -> int:
        """Count DM/response path observations in a time range."""
        until_ts = until if until is not None else int(time.time())

        message_where = [
            "messages.type = 'PRIV'",
            "messages.paths IS NOT NULL",
            "messages.received_at >= ?",
            "messages.received_at < ?",
        ]
        message_params = [since, until_ts]

        raw_where = [
            "message_id IS NULL",
            "timestamp >= ?",
            "timestamp < ?",
        ]
        raw_params = [since, until_ts]

        async with db.readonly() as conn:
            async with conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM messages, json_each(COALESCE(messages.paths, '[]')) AS path_entry
                WHERE {' AND '.join(message_where)}
                """,
                message_params,
            ) as cursor:
                message_row = await cursor.fetchone()
            message_count = int(message_row["count"] if message_row else 0)

            async with conn.execute(
                f"""
                SELECT data
                FROM raw_packets
                WHERE {' AND '.join(raw_where)}
                """,
                raw_params,
            ) as cursor:
                raw_rows = await cursor.fetchall()

        raw_count = 0
        for row in raw_rows:
            packet_info = parse_packet(bytes(row["data"]))
            if packet_info is None or packet_info.payload_type not in {
                PayloadType.TEXT_MESSAGE,
                PayloadType.RESPONSE,
            }:
                continue
            if packet_info.path_length <= 0:
                continue
            raw_count += 1

        return message_count + raw_count

    @staticmethod
    async def get_packets_per_window(
        *,
        window_secs: int,
        lookback_days: int = DEFAULT_BASELINE_LOOKBACK_DAYS,
        until: int | None = None,
    ) -> float:
        """Average DM path observations per rolling window over historical data."""
        until_ts = until if until is not None else int(time.time())
        since = until_ts - lookback_days * 86400
        if since >= until_ts:
            return 0.0

        total = await SpamBaselineService.count_dm_path_observations(since=since, until=until_ts)
        elapsed_secs = until_ts - since
        return (total / elapsed_secs) * window_secs
