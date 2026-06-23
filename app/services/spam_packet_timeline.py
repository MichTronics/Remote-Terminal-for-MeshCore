"""Historical raw-packet timeline by payload/route category for spam analysis."""

from __future__ import annotations

import time
from typing import Any

from app.database import db
from app.decoder import PacketInfo, PayloadType, RouteType

# Display order for stacked chart (bottom to top).
CATEGORY_ORDER: tuple[str, ...] = (
    "pm_transport",
    "dm",
    "group_transport",
    "group_text",
    "response",
    "request",
    "path",
    "ack",
    "advert",
    "anon_request",
    "trace",
    "control",
    "other",
)

# Display names match Raw Packet Feed summaries (DM, GT, ACK, …).
CATEGORY_LABELS: dict[str, str] = {
    "pm_transport": "DM",
    "dm": "DM",
    "group_transport": "GT",
    "group_text": "GT",
    "request": "Request",
    "response": "Response",
    "path": "Path",
    "ack": "ACK",
    "advert": "Advert",
    "anon_request": "AnonRequest",
    "trace": "Trace",
    "control": "Control",
    "other": "Unknown",
}

_PAYLOAD_CATEGORY: dict[int, str] = {
    PayloadType.REQUEST: "request",
    PayloadType.RESPONSE: "response",
    PayloadType.ACK: "ack",
    PayloadType.ADVERT: "advert",
    PayloadType.GROUP_DATA: "other",
    PayloadType.ANON_REQUEST: "anon_request",
    PayloadType.PATH: "path",
    PayloadType.TRACE: "trace",
    PayloadType.MULTIPART: "other",
    PayloadType.CONTROL: "control",
    PayloadType.ATLAS: "other",
    PayloadType.LOCATION: "other",
    PayloadType.RAW_CUSTOM: "other",
}


def _classify_route_payload(*, route_type: int, payload_type: int) -> str:
    is_transport = route_type in (RouteType.TRANSPORT_FLOOD, RouteType.TRANSPORT_DIRECT)

    if payload_type == PayloadType.TEXT_MESSAGE:
        return "pm_transport" if is_transport else "dm"
    if payload_type == PayloadType.GROUP_TEXT:
        return "group_transport" if is_transport else "group_text"

    try:
        return _PAYLOAD_CATEGORY.get(PayloadType(payload_type), "other")
    except ValueError:
        return "other"


def classify_packet_header(header: int) -> str:
    """Map the first packet byte to a chart category."""
    route_type = header & 0x03
    payload_type = (header >> 2) & 0x0F
    return _classify_route_payload(route_type=route_type, payload_type=payload_type)


def classify_packet_info(packet_info: PacketInfo) -> str:
    """Map parsed packet header fields to a chart/live-flood category."""
    return _classify_route_payload(
        route_type=int(packet_info.route_type),
        payload_type=int(packet_info.payload_type),
    )


def primary_category_from_counts(counts: dict[str, int]) -> str | None:
    """Pick the dominant category; ties break using chart display order."""
    if not counts:
        return None
    order_index = {category: index for index, category in enumerate(CATEGORY_ORDER)}
    return max(
        counts.keys(),
        key=lambda category: (counts[category], -order_index.get(category, 999)),
    )


def _category_from_header_hex(header_hex: str | None) -> str:
    if not header_hex:
        return "other"
    try:
        header_value = int(header_hex, 16)
    except ValueError:
        return "other"
    return classify_packet_header(header_value)


class SpamPacketTimelineService:
    @staticmethod
    async def get_timeline(
        *,
        window_hours: int = 24,
        bucket_minutes: int = 30,
        now: int | None = None,
    ) -> dict[str, Any]:
        now_ts = now if now is not None else int(time.time())
        bucket_secs = max(60, bucket_minutes * 60)
        since = now_ts - window_hours * 3600
        bucket_start = (since // bucket_secs) * bucket_secs

        async with db.readonly() as conn:
            async with conn.execute(
                """
                SELECT
                    CAST(CAST(timestamp AS INTEGER) / ? AS INTEGER) * ? AS bucket_ts,
                    substr(hex(data), 1, 2) AS header_hex,
                    COUNT(*) AS packet_count
                FROM raw_packets
                WHERE timestamp >= ?
                GROUP BY bucket_ts, header_hex
                """,
                (bucket_secs, bucket_secs, since),
            ) as cursor:
                rows = await cursor.fetchall()

        bucket_counts: dict[int, dict[str, int]] = {}
        totals_by_category: dict[str, int] = {key: 0 for key in CATEGORY_ORDER}

        for row in rows:
            bucket_ts = int(row["bucket_ts"])
            category = _category_from_header_hex(row["header_hex"])
            packet_count = int(row["packet_count"])
            counts = bucket_counts.setdefault(bucket_ts, {key: 0 for key in CATEGORY_ORDER})
            counts[category] = counts.get(category, 0) + packet_count
            totals_by_category[category] = totals_by_category.get(category, 0) + packet_count

        end_bucket = (now_ts // bucket_secs) * bucket_secs
        buckets: list[dict[str, Any]] = []
        current = bucket_start
        while current <= end_bucket:
            counts = bucket_counts.get(current, {key: 0 for key in CATEGORY_ORDER})
            buckets.append(
                {
                    "timestamp": current,
                    "counts": counts,
                    "total": sum(counts.values()),
                }
            )
            current += bucket_secs

        active_categories = [
            category
            for category in CATEGORY_ORDER
            if totals_by_category.get(category, 0) > 0
        ]

        return {
            "window_hours": window_hours,
            "bucket_minutes": bucket_minutes,
            "generated_at": now_ts,
            "categories": active_categories,
            "category_labels": {key: CATEGORY_LABELS[key] for key in active_categories},
            "buckets": buckets,
            "totals_by_category": {
                key: totals_by_category.get(key, 0)
                for key in active_categories
            },
            "total_packets": sum(totals_by_category.values()),
        }
