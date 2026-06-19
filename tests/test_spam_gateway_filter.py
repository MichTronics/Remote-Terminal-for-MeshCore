"""Tests for gateway-bridge MQTT path filtering."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.fanout.mqtt_community import _publish_community_packet
from app.services.spam_gateway_filter import (
    gateway_pubkeys_from_configured,
    is_gateway_hop,
    path_last_hop_is_gateway,
    raw_packet_last_hop_is_gateway,
    should_skip_mqtt_raw_packet_broadcast,
)
from app.services.spam_live_tracker import spam_live_tracker

GWNL_GATEWAY = "1228d131fa4b13c78a7aefee124e5c7fe51a8555115220d64d1df749b5a7de8c"
DB_GATEWAY = "db371c0634d23dd4dc72556366f6cd19578ac91eb85257ea259af8f8bb1d14e0"


def test_gateway_pubkeys_from_configured_defaults():
    assert GWNL_GATEWAY in gateway_pubkeys_from_configured("")


def test_gateway_pubkeys_from_configured_none():
    assert gateway_pubkeys_from_configured("none") == frozenset()


def test_is_gateway_hop_matches_prefix():
    pubkeys = frozenset({DB_GATEWAY.lower()})
    assert is_gateway_hop("db", pubkeys)
    assert is_gateway_hop("db37", pubkeys)
    assert not is_gateway_hop("aa", pubkeys)


def test_path_last_hop_is_gateway():
    pubkeys = frozenset({GWNL_GATEWAY.lower()})
    assert path_last_hop_is_gateway("AA12", 2, pubkeys)
    assert not path_last_hop_is_gateway("12AA", 2, pubkeys)


def test_raw_packet_last_hop_is_gateway_direct_route():
    pubkeys = frozenset({GWNL_GATEWAY.lower()})
    # DIRECT route, 2 hops (AA, 12), payload CC
    assert raw_packet_last_hop_is_gateway("0202AA12CC", pubkeys)
    assert not raw_packet_last_hop_is_gateway("0202AAbbCC", pubkeys)


def test_should_skip_mqtt_raw_packet_broadcast_uses_live_tracker_settings():
    original = spam_live_tracker._gateway_pubkeys
    try:
        spam_live_tracker._gateway_pubkeys = frozenset({DB_GATEWAY.lower()})
        data = {"data": "0202AADBCC"}
        assert should_skip_mqtt_raw_packet_broadcast(data) is True
        data = {"data": "0202AABBCC"}
        assert should_skip_mqtt_raw_packet_broadcast(data) is False
    finally:
        spam_live_tracker._gateway_pubkeys = original


@pytest.mark.asyncio
async def test_community_mqtt_skips_gateway_terminated_paths():
    publisher = AsyncMock()
    publisher.connected = True
    publisher._settings = object()
    publisher.publish = AsyncMock()

    original = spam_live_tracker._gateway_pubkeys
    try:
        spam_live_tracker._gateway_pubkeys = frozenset({GWNL_GATEWAY.lower()})
        data = {"data": "0202AA12CC", "snr": 1.0, "rssi": -70}
        await _publish_community_packet(
            publisher,
            {"iata": "LAX", "topic_template": "meshcore/{IATA}/{PUBLIC_KEY}/packets"},
            data,
        )
        publisher.publish.assert_not_called()
    finally:
        spam_live_tracker._gateway_pubkeys = original
