"""Tests for spam packet timeline aggregation."""

from __future__ import annotations

import pytest

import time

from app.services.spam_packet_timeline import (
    CATEGORY_LABELS,
    classify_packet_header,
    SpamPacketTimelineService,
)


def _header(route_type: int, payload_type: int, version: int = 0) -> int:
    return (version << 6) | (payload_type << 2) | route_type


def test_classify_packet_header_splits_transport_text_message():
    transport_pm = _header(route_type=0x00, payload_type=0x02)
    direct_dm = _header(route_type=0x02, payload_type=0x02)
    assert classify_packet_header(transport_pm) == "pm_transport"
    assert classify_packet_header(direct_dm) == "dm"


def test_category_labels_match_raw_packet_feed_names():
    assert CATEGORY_LABELS["pm_transport"] == "DM"
    assert CATEGORY_LABELS["dm"] == "DM"
    assert CATEGORY_LABELS["group_transport"] == "GT"
    assert CATEGORY_LABELS["group_text"] == "GT"
    assert CATEGORY_LABELS["ack"] == "ACK"
    assert CATEGORY_LABELS["other"] == "Unknown"


def test_classify_packet_header_splits_transport_group_text():
    transport_group = _header(route_type=0x03, payload_type=0x05)
    flood_group = _header(route_type=0x01, payload_type=0x05)
    assert classify_packet_header(transport_group) == "group_transport"
    assert classify_packet_header(flood_group) == "group_text"


def test_classify_packet_header_maps_common_payload_types():
    assert classify_packet_header(_header(0x01, 0x01)) == "response"
    assert classify_packet_header(_header(0x01, 0x00)) == "request"
    assert classify_packet_header(_header(0x01, 0x08)) == "path"


@pytest.mark.asyncio
async def test_spam_packet_timeline_buckets_last_24h(test_db):
    now = 1_700_100_000
    async with test_db.tx() as conn:
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (now - 1800, bytes([_header(0x00, 0x02)] + [0] * 8)),
        )
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (now - 1200, bytes([_header(0x01, 0x05)] + [0] * 8)),
        )
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (now - 600, bytes([_header(0x02, 0x02)] + [0] * 8)),
        )

    result = await SpamPacketTimelineService.get_timeline(
        window_hours=24,
        bucket_minutes=30,
        now=now,
    )
    assert result["total_packets"] == 3
    assert result["totals_by_category"]["pm_transport"] == 1
    assert result["totals_by_category"]["group_text"] == 1
    assert result["totals_by_category"]["dm"] == 1
    assert "pm_transport" in result["category_labels"]
    assert result["category_labels"]["pm_transport"] == CATEGORY_LABELS["pm_transport"]
    assert len(result["buckets"]) >= 1


@pytest.mark.asyncio
async def test_spam_packet_timeline_endpoint(client, test_db):
    now = int(time.time())
    async with test_db.tx() as conn:
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (now - 300, bytes([_header(0x01, 0x08)] + [0] * 8)),
        )

    response = await client.get("/api/messages/spam/packet-timeline?window_hours=24&bucket_minutes=30")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_packets"] >= 1
    assert "path" in payload["totals_by_category"]


@pytest.mark.asyncio
async def test_spam_packet_timeline_sql_aggregation_handles_many_rows(test_db):
    now = 1_700_200_000
    header = bytes([_header(0x01, 0x05)] + [0] * 8)
    async with test_db.tx() as conn:
        for offset in range(250):
            await conn.execute(
                "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
                (now - 600 - offset, header),
            )

    result = await SpamPacketTimelineService.get_timeline(
        window_hours=24,
        bucket_minutes=30,
        now=now,
    )
    assert result["total_packets"] == 250
    assert result["totals_by_category"]["group_text"] == 250
