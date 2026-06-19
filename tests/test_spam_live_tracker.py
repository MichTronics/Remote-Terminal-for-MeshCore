"""Tests for live DM spam flood tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models import ContactUpsert
from app.repository import ContactRepository
from app.repository.spam_flood_episodes import SpamFloodEpisodeRepository
from app.services.spam_live_tracker import SpamLiveTracker

GWNL_GATEWAY = "1228d131fa4b13c78a7aefee124e5c7fe51a8555115220d64d1df749b5a7de8c"


def _make_tracker(**overrides) -> SpamLiveTracker:
    tracker = SpamLiveTracker()
    tracker.window_secs = overrides.get("window_secs", 30)
    tracker.packet_threshold = overrides.get("packet_threshold", 5)
    tracker.cluster_min_ratio = overrides.get("cluster_min_ratio", 0.15)
    tracker.broadcast_cooldown_secs = overrides.get("broadcast_cooldown_secs", 0)
    tracker.hold_secs = overrides.get("hold_secs", 300)
    tracker.fluke_max_packets = overrides.get("fluke_max_packets", 0)
    tracker.fluke_max_duration_secs = overrides.get("fluke_max_duration_secs", 300)
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
async def test_spam_live_tracker_narrows_shared_prefix_beyond_entry_hop():
    tracker = _make_tracker(packet_threshold=6, cluster_min_ratio=0.15, gateway_pubkeys=frozenset())

    for offset in range(5):
        await tracker.observe_and_maybe_alert(
            path_hex="AA" + "BB" + "CC",
            path_len=3,
            observed_at=1_700_000_000 + offset,
        )
    for offset in range(5, 7):
        await tracker.observe_and_maybe_alert(
            path_hex="AA" + "FF" + "GG",
            path_len=3,
            observed_at=1_700_000_000 + offset,
        )

    status = await tracker.get_live_status()
    assert status.active is True
    assert len(status.clusters) == 1
    cluster = status.clusters[0]
    assert cluster.entry_hop == "AA"
    assert cluster.refined_hop_tokens == ["AA", "BB"]
    assert cluster.narrowing_depth == 2
    assert cluster.traffic_share == pytest.approx(0.7143, rel=0.01)
    assert cluster.confidence > 0


@pytest.mark.asyncio
async def test_spam_live_tracker_falls_back_to_entry_hop_when_paths_are_dispersed():
    tracker = _make_tracker(packet_threshold=15, cluster_min_ratio=0.15, gateway_pubkeys=frozenset())
    base = 1_700_000_000.0
    ingress_hops = ["AA", "BB", "CC", "DD", "EE"]

    # Fifteen packets across five ingress hops, all with distinct suffix routes.
    for offset in range(15):
        hop = ingress_hops[offset % len(ingress_hops)]
        suffix = format(offset, "02X")
        await tracker.observe_and_maybe_alert(
            path_hex=hop + "11" + suffix,
            path_len=2,
            observed_at=base + offset,
        )

    narrowed = tracker._cluster_packets_narrowed()
    assert narrowed == []

    clusters = tracker._cluster_packets()
    assert len(clusters) == 5
    assert all(cluster["cluster_mode"] == "partitioned" for cluster in clusters)
    assert all(cluster["narrowing_depth"] >= 2 for cluster in clusters)


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
async def test_spam_live_tracker_preserves_peak_share_after_source_stops_during_hold():
    tracker = _make_tracker(packet_threshold=3, hold_secs=300, cluster_min_ratio=0.15, gateway_pubkeys=frozenset())
    base = 1_700_000_000.0

    for offset in range(3):
        await tracker.observe_and_maybe_alert(
            path_hex="AABB",
            path_len=2,
            observed_at=base + offset,
        )

    status_after_aa = await tracker.get_live_status()
    assert status_after_aa.active
    aa_cluster = next(cluster for cluster in status_after_aa.clusters if cluster.entry_hop == "AA")
    peak_aa_share = aa_cluster.traffic_share
    assert peak_aa_share == pytest.approx(1.0)

    for offset in range(10):
        await tracker.observe_and_maybe_alert(
            path_hex="BBCC",
            path_len=2,
            observed_at=base + 40 + offset,
        )

    status_during_hold = await tracker.get_live_status()
    assert status_during_hold.active
    aa_clusters = [cluster for cluster in status_during_hold.clusters if cluster.entry_hop == "AA"]
    assert len(aa_clusters) == 1
    assert aa_clusters[0].traffic_share >= peak_aa_share
    assert aa_clusters[0].packet_count == 3


@pytest.mark.asyncio
async def test_spam_live_tracker_persists_multiple_clusters_at_end(test_db):
    tracker = _make_tracker(packet_threshold=6, cluster_min_ratio=0.15, hold_secs=30)

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

    tracker._sync_active_state(1_700_000_040)
    await tracker._end_episode(1_700_000_040)

    episodes = await SpamFloodEpisodeRepository.list_recent(limit=10)
    assert len(episodes) == 1
    episode = episodes[0]
    assert len(episode.clusters) == 2
    entry_hops = {cluster.entry_hop for cluster in episode.clusters}
    assert entry_hops == {"AA", "BB"}
    assert episode.primary_entry_hop == "AA"


@pytest.mark.asyncio
async def test_spam_live_tracker_resolves_entry_geo(test_db):
    await ContactRepository.upsert(
        ContactUpsert(
            public_key="aa11" + "22" * 31,
            name="Ingress Repeater",
            type=2,
            lat=52.12345,
            lon=4.56789,
        )
    )

    tracker = _make_tracker(packet_threshold=2, gateway_pubkeys=frozenset())
    await tracker.observe_and_maybe_alert(path_hex="AA11CCDD", path_len=2, observed_at=1_700_000_000)
    await tracker.observe_and_maybe_alert(path_hex="AA11EEFF", path_len=2, observed_at=1_700_000_001)

    status = await tracker.get_live_status()
    assert status.active is True
    assert len(status.clusters) == 1
    cluster = status.clusters[0]
    assert cluster.entry_name == "Ingress Repeater"
    assert cluster.lat == pytest.approx(52.12345)
    assert cluster.lon == pytest.approx(4.56789)
    assert cluster.longest_route_tokens[0] == "AA11"
    assert cluster.hop_names_by_token.get("AA11") == "Ingress Repeater"


@pytest.mark.asyncio
async def test_spam_live_tracker_skips_one_byte_hop_names_even_when_unique(test_db):
    await ContactRepository.upsert(
        ContactUpsert(
            public_key="f6" + "11" * 31,
            name="Should Not Label",
            type=2,
            lat=52.0,
            lon=4.0,
        )
    )

    tracker = _make_tracker(packet_threshold=2, gateway_pubkeys=frozenset())
    await tracker.observe_and_maybe_alert(path_hex="F611", path_len=2, observed_at=1_700_000_000)
    await tracker.observe_and_maybe_alert(path_hex="F622", path_len=2, observed_at=1_700_000_001)

    status = await tracker.get_live_status()
    cluster = status.clusters[0]
    assert cluster.entry_hop == "F6"
    assert cluster.entry_name is None
    assert "F6" not in cluster.hop_names_by_token


@pytest.mark.asyncio
async def test_spam_live_tracker_skips_two_byte_hop_names_when_prefix_is_ambiguous(test_db):
    await ContactRepository.upsert(
        ContactUpsert(
            public_key="aa11" + "22" * 31,
            name="Repeater A",
            type=2,
        )
    )
    await ContactRepository.upsert(
        ContactUpsert(
            public_key="aa11" + "33" * 31,
            name="Repeater B",
            type=2,
        )
    )

    tracker = _make_tracker(packet_threshold=2, gateway_pubkeys=frozenset())
    await tracker.observe_and_maybe_alert(path_hex="AA11CCDD", path_len=2, observed_at=1_700_000_000)
    await tracker.observe_and_maybe_alert(path_hex="AA11EEFF", path_len=2, observed_at=1_700_000_001)

    status = await tracker.get_live_status()
    cluster = status.clusters[0]
    assert cluster.entry_hop == "AA11"
    assert cluster.entry_name is None
    assert "AA11" not in cluster.hop_names_by_token


@pytest.mark.asyncio
async def test_spam_live_tracker_schedules_repeater_commands_on_episode_lifecycle(test_db):
    tracker = _make_tracker(packet_threshold=2, hold_secs=30, gateway_pubkeys=frozenset())
    with (
        patch(
            "app.services.spam_live_tracker.schedule_spam_flood_repeater_commands",
        ) as mock_schedule,
        patch(
            "app.services.spam_live_tracker.SpamBaselineService.get_packets_per_window",
            new_callable=AsyncMock,
            return_value=1.0,
        ),
    ):
        await tracker.observe_and_maybe_alert(path_hex="AABB", path_len=2, observed_at=1_700_000_000)
        await tracker.observe_and_maybe_alert(path_hex="AACC", path_len=2, observed_at=1_700_000_001)
        mock_schedule.assert_called_once_with("start")

        tracker._sync_active_state(1_700_000_040)
        await tracker._end_episode(1_700_000_040)
        assert mock_schedule.call_args_list[-1].args == ("end",)


@pytest.mark.asyncio
async def test_spam_live_tracker_longest_route_tokens_use_max_hop_path():
    tracker = _make_tracker(packet_threshold=2, cluster_min_ratio=0.15, gateway_pubkeys=frozenset())
    await tracker.observe_and_maybe_alert(path_hex="AA11", path_len=2, observed_at=1_700_000_000)
    await tracker.observe_and_maybe_alert(path_hex="AA1122BB", path_len=4, observed_at=1_700_000_001)

    clusters = tracker._cluster_packets()
    assert len(clusters) == 1
    assert clusters[0]["longest_path_tokens"] == ["AA", "11", "22", "BB"]


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


@pytest.mark.asyncio
async def test_spam_live_tracker_discards_fluke_episode_from_history(test_db):
    tracker = _make_tracker(
        packet_threshold=3,
        hold_secs=30,
        fluke_max_packets=35,
        fluke_max_duration_secs=300,
        gateway_pubkeys=frozenset(),
    )
    base = 1_700_000_000.0
    with patch(
        "app.services.spam_live_tracker.SpamBaselineService.get_packets_per_window",
        new_callable=AsyncMock,
        return_value=1.0,
    ):
        for offset in range(3):
            await tracker.observe_and_maybe_alert(
                path_hex="AABB",
                path_len=2,
                observed_at=base + offset,
            )
        assert tracker._episode_db_id is not None
        episode_id = tracker._episode_db_id

        tracker._sync_active_state(base + 40)
        await tracker._end_episode(base + 40)

    assert tracker._episode_db_id is None
    episodes = await SpamFloodEpisodeRepository.list_recent()
    assert all(episode.id != episode_id for episode in episodes)


@pytest.mark.asyncio
async def test_spam_live_tracker_keeps_episode_when_packet_cap_reached(test_db):
    tracker = _make_tracker(
        packet_threshold=1,
        hold_secs=30,
        fluke_max_packets=35,
        fluke_max_duration_secs=300,
        gateway_pubkeys=frozenset(),
    )
    base = 1_700_000_000.0
    with patch(
        "app.services.spam_live_tracker.SpamBaselineService.get_packets_per_window",
        new_callable=AsyncMock,
        return_value=1.0,
    ):
        for offset in range(35):
            await tracker.observe_and_maybe_alert(
                path_hex="AABB",
                path_len=2,
                observed_at=base + offset,
            )
        episode_id = tracker._episode_db_id
        assert episode_id is not None

        tracker._sync_active_state(base + 40)
        await tracker._end_episode(base + 40)

    episodes = await SpamFloodEpisodeRepository.list_recent()
    kept = next((episode for episode in episodes if episode.id == episode_id), None)
    assert kept is not None
    assert kept.total_packets == 35
    assert kept.ended_at is not None
