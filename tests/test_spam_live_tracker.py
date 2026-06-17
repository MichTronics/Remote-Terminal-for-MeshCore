"""Tests for live DM spam flood tracking."""

from __future__ import annotations

import pytest

from app.models import ContactUpsert
from app.repository import ContactRepository
from app.services.spam_live_tracker import SpamLiveTracker

GWNL_GATEWAY = "1228d131fa4b13c78a7aefee124e5c7fe51a8555115220d64d1df749b5a7de8c"


def _make_tracker(**overrides) -> SpamLiveTracker:
    tracker = SpamLiveTracker()
    tracker.window_secs = overrides.get("window_secs", 30)
    tracker.packet_threshold = overrides.get("packet_threshold", 5)
    tracker.cluster_min_ratio = overrides.get("cluster_min_ratio", 0.15)
    tracker.broadcast_cooldown_secs = overrides.get("broadcast_cooldown_secs", 0)
    tracker.hold_secs = overrides.get("hold_secs", 300)
    tracker._gateway_pubkeys = overrides.get("gateway_pubkeys", frozenset({GWNL_GATEWAY.lower()}))
    return tracker


@pytest.mark.asyncio
async def test_spam_live_tracker_strips_gateway_hops_before_clustering():
    tracker = _make_tracker(packet_threshold=3)

    # AA -> 12(gateway prefix) -> BB becomes RF-only [AA]
    for offset in range(3):
        await tracker.observe_and_maybe_alert(
            path_hex="AA12BB",
            path_len=3,
            observed_at=1_700_000_000 + offset,
        )

    status = await tracker.get_live_status()
    assert status.active is True
    assert status.total_packets == 3
    assert len(status.clusters) == 1
    assert status.clusters[0].entry_hop == "AA"
    assert status.clusters[0].dominant_route == "AA"


@pytest.mark.asyncio
async def test_spam_live_tracker_clusters_multiple_ingress_points(test_db):
    tracker = _make_tracker(packet_threshold=6, cluster_min_ratio=0.15)

    for offset in range(4):
        await tracker.observe_and_maybe_alert(
            path_hex="AA" + "CC" * 2,
            path_len=2,
            observed_at=1_700_000_000 + offset,
        )
    for offset in range(4, 8):
        await tracker.observe_and_maybe_alert(
            path_hex="BB" + "DD" * 2,
            path_len=2,
            observed_at=1_700_000_000 + offset,
        )

    status = await tracker.get_live_status()
    assert status.active is True
    assert status.total_packets == 8
    assert len(status.clusters) == 2
    entry_hops = {cluster.entry_hop for cluster in status.clusters}
    assert entry_hops == {"AA", "BB"}


@pytest.mark.asyncio
async def test_spam_live_tracker_resolves_entry_geo(test_db):
    await ContactRepository.upsert(
        ContactUpsert(
            public_key="aa" + "11" * 31,
            name="Ingress Repeater",
            type=2,
            lat=52.12345,
            lon=4.56789,
        )
    )

    tracker = _make_tracker(packet_threshold=2, gateway_pubkeys=frozenset())
    await tracker.observe_and_maybe_alert(path_hex="AA11CC", path_len=2, observed_at=1_700_000_000)
    await tracker.observe_and_maybe_alert(path_hex="AA11DD", path_len=2, observed_at=1_700_000_001)

    status = await tracker.get_live_status()
    assert status.active is True
    assert len(status.clusters) == 1
    cluster = status.clusters[0]
    assert cluster.entry_name == "Ingress Repeater"
    assert cluster.lat == pytest.approx(52.12345)
    assert cluster.lon == pytest.approx(4.56789)


@pytest.mark.asyncio
async def test_spam_live_status_endpoint(client, test_db):
    tracker = _make_tracker(packet_threshold=2, gateway_pubkeys=frozenset())
    for offset in range(2):
        await tracker.observe_and_maybe_alert(
            path_hex="EE" + "FF" * 2,
            path_len=2,
            observed_at=1_700_000_100 + offset,
        )

    from app.services import spam_live_tracker as spam_live_tracker_module

    original = spam_live_tracker_module.spam_live_tracker
    spam_live_tracker_module.spam_live_tracker = tracker
    try:
        response = await client.get("/api/messages/spam/live")
        assert response.status_code == 200
        payload = response.json()
        assert payload["active"] is True
        assert payload["total_packets"] == 2
        assert payload["clusters"][0]["entry_hop"] == "EE"
    finally:
        spam_live_tracker_module.spam_live_tracker = original


@pytest.mark.asyncio
async def test_spam_live_tracker_holds_alarm_after_threshold_drops():
    tracker = _make_tracker(packet_threshold=3, hold_secs=300, gateway_pubkeys=frozenset())
    base = 1_700_000_000.0

    for offset in range(3):
        await tracker.observe_and_maybe_alert(
            path_hex="AABB",
            path_len=2,
            observed_at=base + offset,
        )

    tracker._sync_active_state(base + 35)
    assert tracker._active is True
    assert tracker._trigger_window_count(base + 35) == 0
    assert len(tracker._history) == 3

    tracker._sync_active_state(base + 302)
    assert tracker._active is False
    assert len(tracker._history) == 0


@pytest.mark.asyncio
async def test_spam_live_status_exposes_episode_packet_counts():
    tracker = _make_tracker(packet_threshold=3, hold_secs=300, gateway_pubkeys=frozenset())
    base = 1_700_000_000.0

    for offset in range(3):
        await tracker.observe_and_maybe_alert(
            path_hex="AABB",
            path_len=2,
            observed_at=base + offset,
        )

    tracker._sync_active_state(base + 35)
    status = await tracker._build_status_async(base + 35, tracker._cluster_packets())
    assert status.active is True
    assert status.total_packets == 0
    assert status.episode_packets == 3
    assert status.episode_window_secs == 300
    assert len(status.clusters) == 1
