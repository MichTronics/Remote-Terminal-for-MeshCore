"""Tests for DM spam/path route analysis."""

import pytest

from app.repository import MessageRepository
from app.database import db


@pytest.mark.asyncio
async def test_spam_route_stats_rank_repeater_hops_by_dm_path_usage(test_db):
    contact_a = "aa" * 32
    contact_b = "bb" * 32

    first_id = await MessageRepository.create(
        "PRIV",
        "spam one",
        received_at=1_700_000_000,
        conversation_key=contact_a,
        path="AABB",
        path_len=2,
        rssi=-80,
        snr=7.0,
    )
    assert first_id is not None

    second_id = await MessageRepository.create(
        "PRIV",
        "spam two",
        received_at=1_700_000_010,
        conversation_key=contact_b,
        path="AACC",
        path_len=2,
        rssi=-90,
        snr=5.0,
    )
    assert second_id is not None

    direct_id = await MessageRepository.create(
        "PRIV",
        "direct",
        received_at=1_700_000_020,
        conversation_key=contact_a,
        path="",
        path_len=0,
    )
    assert direct_id is not None

    result = await MessageRepository.get_spam_route_stats(window_hours=24, now=1_700_000_100)

    assert result.total_observations == 3
    assert result.total_messages == 3
    assert result.repeaters[0].hop == "AA"
    assert result.repeaters[0].observation_count == 2
    assert result.repeaters[0].source_side_count == 2
    assert result.repeaters[0].conversation_count == 2
    assert [route.route for route in result.routes] == ["Direct", "AA -> CC", "AA -> BB"]


@pytest.mark.asyncio
async def test_spam_route_stats_include_raw_dm_and_response_packets(test_db):
    dm_hex = (
        "0854D100000C1164B5CC669DEB94653329406311A97E61E337979261E52488E"
        "473E169323532AB648DCCF409F23A3F9236120DBF70F8"
    )
    response_hex = "04D612000002402975E25EE4D72DCBCA2D79A82CCC2B36F2C8FA94B8"

    async with db.tx() as conn:
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (1_700_000_000, bytes.fromhex(dm_hex)),
        )
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (1_700_000_010, bytes.fromhex(response_hex)),
        )

    result = await MessageRepository.get_spam_route_stats(window_hours=24, now=1_700_000_100)

    assert result.total_observations == 2
    assert result.total_messages == 2
    assert result.repeaters[0].hop == "40"
    assert result.repeaters[0].observation_count == 2
    assert any(
        route.route == "11 -> 64 -> B5 -> CC -> 66 -> 9D -> EB -> 94 -> 65 -> 33 -> 29 -> 40"
        for route in result.routes
    )
    assert any(route.route == "40 -> 29" for route in result.routes)
