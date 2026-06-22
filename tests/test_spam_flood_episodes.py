"""Tests for spam flood episode persistence and baseline."""

from __future__ import annotations

import time

import pytest

from app.models import ContactUpsert, SpamFloodCluster
from app.repository import ContactRepository
from app.repository.spam_flood_episodes import SpamFloodEpisodeRepository
from app.services.spam_baseline import SpamBaselineService
from app.services.spam_live_tracker import SpamLiveTracker

GWNL_GATEWAY = "1228d131fa4b13c78a7aefee124e5c7fe51a8555115220d64d1df749b5a7de8c"


def _test_base(offset: float = 0.0) -> float:
    return time.time() + offset


def _make_tracker(**overrides) -> SpamLiveTracker:
    tracker = SpamLiveTracker()
    tracker.window_secs = overrides.get("window_secs", 30)
    tracker.packet_threshold = overrides.get("packet_threshold", 3)
    tracker.cluster_min_ratio = overrides.get("cluster_min_ratio", 0.15)
    tracker.broadcast_cooldown_secs = overrides.get("broadcast_cooldown_secs", 0)
    tracker.hold_secs = overrides.get("hold_secs", 60)
    tracker.episode_retention_secs = overrides.get("episode_retention_secs", 60)
    tracker.fluke_max_packets = overrides.get("fluke_max_packets", 0)
    tracker.fluke_max_duration_secs = overrides.get("fluke_max_duration_secs", 300)
    tracker._gateway_pubkeys = overrides.get("gateway_pubkeys", frozenset())
    return tracker


def _cat(tracker: SpamLiveTracker, category: str = "dm"):
    return tracker._category_state(category)


@pytest.mark.asyncio
async def test_spam_baseline_counts_packet_observations(test_db):
    async with test_db.tx() as conn:
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (1_699_000_000, b"\x02\x00"),
        )
        await conn.execute(
            "INSERT INTO raw_packets (timestamp, data) VALUES (?, ?)",
            (1_699_000_010, b"\x00\x01AA"),
        )

    count = await SpamBaselineService.count_packet_observations(
        since=1_698_999_000,
        until=1_699_001_000,
    )
    assert count == 2

    rate = await SpamBaselineService.get_packets_per_window(
        window_secs=30,
        lookback_days=14,
        until=1_699_001_000,
    )
    assert rate > 0


@pytest.mark.asyncio
async def test_spam_live_tracker_persists_flood_episode(test_db):
    await ContactRepository.upsert(
        ContactUpsert(
            public_key="aa" + "11" * 31,
            name="Ingress Repeater",
            type=2,
            lat=52.12345,
            lon=4.56789,
        )
    )

    tracker = _make_tracker(packet_threshold=2, hold_secs=30)
    base = _test_base()

    for offset in range(2):
        await tracker.observe_and_maybe_alert(
            path_hex="AA11CC",
            path_len=2,
            observed_at=base + offset,
        )

    assert _cat(tracker).episode_db_id is not None
    assert _cat(tracker).episode_total_packets == 2

    state = _cat(tracker)
    tracker._sync_active_state(state, base + 35)
    await tracker._end_episode(state, base + 35)
    tracker._cancel_episode_watchdog()

    episodes = await SpamFloodEpisodeRepository.list_recent(limit=10)
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.started_at in {int(base), int(base) + 1}
    assert episode.ended_at == int(base + 35)
    assert episode.duration_secs in {34, 35}
    assert episode.total_packets == 2
    assert episode.primary_entry_hop == "AA"
    assert episode.primary_category == "dm"
    assert episode.category_counts["dm"] == 2
    assert episode.clusters


@pytest.mark.asyncio
async def test_spam_flood_episodes_delete_endpoint(client, test_db):
    episode_id = await SpamFloodEpisodeRepository.create_started(
        started_at=1_700_000_000,
        baseline_packets_per_window=1.5,
        packet_threshold=15,
        window_secs=30,
    )

    response = await client.delete(f"/api/messages/spam/episodes/{episode_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert await SpamFloodEpisodeRepository.list_recent(limit=10) == []


@pytest.mark.asyncio
async def test_spam_flood_episodes_close_open_on_startup(test_db):
    episode_id = await SpamFloodEpisodeRepository.create_started(
        started_at=1_700_000_000,
        baseline_packets_per_window=1.5,
        packet_threshold=15,
        window_secs=30,
    )
    closed = await SpamFloodEpisodeRepository.close_open_episodes(ended_at=1_700_000_120)
    assert closed == 1
    episodes = await SpamFloodEpisodeRepository.list_recent(limit=10)
    assert len(episodes) == 1
    assert episodes[0].id == episode_id
    assert episodes[0].ended_at == 1_700_000_120
    assert episodes[0].duration_secs == 120


@pytest.mark.asyncio
async def test_spam_flood_episodes_endpoint(client, test_db):
    started_at = int(_test_base())
    ended_at = started_at + 120
    episode_id = await SpamFloodEpisodeRepository.create_started(
        started_at=started_at,
        baseline_packets_per_window=1.5,
        packet_threshold=15,
        window_secs=30,
    )
    await SpamFloodEpisodeRepository.finalize(
        episode_id=episode_id,
        started_at=started_at,
        ended_at=ended_at,
        total_packets=42,
        peak_packets_per_window=18,
        baseline_packets_per_window=1.5,
        clusters=[
            SpamFloodCluster(
                entry_hop="EE",
                packet_count=42,
                dominant_route="EE -> FF",
                hop_tokens=["EE", "FF"],
                refined_route="EE -> FF",
                refined_hop_tokens=["EE", "FF"],
                confidence=72,
                last_seen=ended_at - 20,
            )
        ],
        category_counts={"dm": 42},
    )

    response = await client.get("/api/messages/spam/episodes")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["episodes"]) == 1
    assert payload["episodes"][0]["total_packets"] == 42
    assert payload["episodes"][0]["duration_secs"] == 120
    assert payload["episodes"][0]["primary_refined_route"] == "EE -> FF"
    assert payload["episodes"][0]["primary_category"] == "dm"
