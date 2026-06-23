"""Tests for progressive spam path narrowing helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.spam_path_analysis import (
    build_one_byte_geo_hint,
    consolidate_geo_hotspots,
    estimate_origin_geo,
    format_block_segment_label,
    format_block_segment_route,
    hop_suspect_score,
    narrow_dominant_prefix,
    rank_block_candidates,
    split_entry_partitioned_clusters,
    split_path_clusters,
)


@dataclass
class _PathRecord:
    full_rf_path: tuple[str, ...]


def test_narrow_dominant_prefix_deepens_when_paths_share_prefix():
    paths = [
        ("AA", "BB", "CC"),
        ("AA", "BB", "DD"),
        ("AA", "BB", "EE"),
        ("AA", "FF", "GG"),
    ]
    narrowed = narrow_dominant_prefix(paths, min_share=0.15)
    assert narrowed is not None
    assert narrowed.hop_tokens == ("AA", "BB")
    assert narrowed.packet_count == 3
    assert narrowed.traffic_share == pytest.approx(0.75)
    assert narrowed.narrowing_depth == 2


def test_split_path_clusters_peels_multiple_hotspots():
    records = [
        _PathRecord(("AA", "BB")),
        _PathRecord(("AA", "BB", "CC")),
        _PathRecord(("AA", "BB", "DD")),
        _PathRecord(("XX", "YY")),
        _PathRecord(("XX", "YY", "ZZ")),
        _PathRecord(("XX", "YY", "ZZ")),
    ]
    clusters = split_path_clusters(
        records,
        min_cluster_size=2,
        min_share=0.15,
        get_path=lambda record: record.full_rf_path,
    )
    assert len(clusters) == 2
    first_prefix = clusters[0][0].hop_tokens
    second_prefix = clusters[1][0].hop_tokens
    assert first_prefix[0] in {"AA", "XX"}
    assert second_prefix[0] in {"AA", "XX"}
    assert first_prefix != second_prefix


def test_split_entry_partitioned_clusters_handles_multi_source_floods():
    records = [
        _PathRecord(("AA", "11", "00")),
        _PathRecord(("AA", "11", "01")),
        _PathRecord(("AA", "11", "02")),
        _PathRecord(("BB", "22", "10")),
        _PathRecord(("BB", "22", "11")),
        _PathRecord(("BB", "22", "12")),
        _PathRecord(("CC", "33", "20")),
        _PathRecord(("CC", "33", "21")),
        _PathRecord(("CC", "33", "22")),
    ]
    clusters = split_entry_partitioned_clusters(
        records,
        min_cluster_size=3,
        min_share=0.15,
        get_path=lambda record: record.full_rf_path,
        max_clusters=3,
    )
    assert len(clusters) == 3
    prefixes = {cluster[0].hop_tokens for cluster in clusters}
    assert ("AA", "11") in prefixes
    assert ("BB", "22") in prefixes
    assert ("CC", "33") in prefixes
    assert all(cluster[0].traffic_share == pytest.approx(1 / 3) for cluster in clusters)


def test_estimate_origin_geo_prefers_source_side_hop():
    hop_geos = {
        "AA": {"lat": 52.0, "lon": 4.0, "name": "Ingress", "public_key": "aa" * 32},
        "BB": {"lat": 52.05, "lon": 4.05, "name": "Mid", "public_key": "bb" * 32},
    }
    origin = estimate_origin_geo(("AA", "BB"), hop_geos, max_hop_distance_km=10.0)
    assert origin is not None
    assert origin.hop == "AA"
    assert origin.name == "Ingress"
    assert origin.geo_chain_valid is True


def test_consolidate_geo_hotspots_merges_nearby_ingress_witnesses():
    from app.models import SpamFloodCluster

    # Ten ingress witnesses around Amsterdam-ish coords — should collapse to one focus area.
    clusters = [
        SpamFloodCluster(
            entry_hop=f"H{i:02X}",
            entry_name=f"Repeater-{i}",
            lat=52.37 + (i * 0.01),
            lon=4.90 + (i * 0.01),
            packet_count=4,
            dominant_route=f"H{i:02X}",
            hop_tokens=[f"H{i:02X}"],
            traffic_share=0.1,
            confidence=40,
            last_seen=1_700_000_000,
            cluster_mode="entry_fallback",
        )
        for i in range(10)
    ]
    focused = consolidate_geo_hotspots(clusters, max_clusters=5, merge_radius_km=35.0)
    assert len(focused) == 1
    assert focused[0].cluster_mode == "geo_merged"
    assert focused[0].packet_count == 40
    assert "nearby" in (focused[0].entry_name or "")


def test_consolidate_geo_hotspots_keeps_distant_regions_separate():
    from app.models import SpamFloodCluster

    north = SpamFloodCluster(
        entry_hop="AA",
        entry_name="North",
        lat=53.2,
        lon=6.5,
        packet_count=20,
        dominant_route="AA",
        hop_tokens=["AA"],
        traffic_share=0.5,
        confidence=60,
        last_seen=1_700_000_000,
    )
    south = SpamFloodCluster(
        entry_hop="BB",
        entry_name="South",
        lat=51.4,
        lon=5.4,
        packet_count=18,
        dominant_route="BB",
        hop_tokens=["BB"],
        traffic_share=0.45,
        confidence=55,
        last_seen=1_700_000_000,
    )
    focused = consolidate_geo_hotspots([north, south], max_clusters=5, merge_radius_km=35.0)
    assert len(focused) == 2


def test_hop_suspect_score_favors_source_side_hops():
    observations = [
        ("AA", "BB"),
        ("AA", "CC"),
        ("BB", "AA"),
    ]
    assert hop_suspect_score("AA", observations) > hop_suspect_score("BB", observations)


def test_build_one_byte_geo_hint_mentions_landmark_when_present():
    hint = build_one_byte_geo_hint("Orinen", "F6", 8.2, "City-Repeater")
    assert "Orinen" in hint
    assert "F6" in hint
    assert "City-Repeater" in hint
    assert "8 km" in hint


def test_build_one_byte_geo_hint_without_landmark():
    hint = build_one_byte_geo_hint("Orinen", "F6", 12.6, None)
    assert hint == "Orinen (F6) is ~13 km from the estimated source"


def test_rank_block_candidates_prefers_frequent_two_hop_segments():
    paths = [
        ("C3", "91", "77", "AB", "DB"),
        ("C3", "91", "77", "AB", "DB", "23"),
        ("C3", "91", "77", "AB", "DB"),
        ("C3", "91", "77", "AB", "DB"),
        ("C3", "91", "77", "AB", "DB"),
        ("XX", "YY", "ZZ"),
    ]
    ranked, combined = rank_block_candidates(paths, min_paths=5, min_packets=2, min_share=0.5)
    assert ranked
    assert ranked[0].hop_tokens == ("77", "AB")
    assert ranked[0].route == "77 ⇢ AB"
    assert ranked[0].route_label == "77 ⇢ AB (⇢ DB)"
    assert ranked[0].last_hop == "DB"
    assert ranked[0].source_hop == "AB"
    assert ranked[0].db_hop == "77"
    assert ranked[0].packet_count == 4
    assert ranked[0].traffic_share == pytest.approx(4 / 6)
    assert combined is not None
    assert combined >= 5 / 6


def test_rank_block_candidates_splits_same_segment_by_last_hop():
    paths = [
        ("C3", "91", "77", "AB", "DB"),
        ("C3", "91", "77", "AB", "DB"),
        ("C3", "91", "77", "AB", "DB"),
        ("C3", "91", "77", "AB", "F6"),
        ("C3", "91", "77", "AB", "F6"),
        ("XX", "YY", "ZZ"),
    ]
    ranked, _combined = rank_block_candidates(paths, min_paths=5, min_packets=2, min_share=0.25)
    by_last_hop = {
        item.last_hop: item
        for item in ranked
        if item.hop_tokens == ("77", "AB")
    }
    assert by_last_hop["DB"].packet_count == 3
    assert by_last_hop["F6"].packet_count == 2
    assert by_last_hop["DB"].route_label == "77 ⇢ AB (⇢ DB)"
    assert ranked[0].last_hop == "DB"


def test_rank_block_candidates_tracks_multiple_ingress_hops():
    paths = [
        ("F6", "64", "B5"),
        ("AB", "64", "B5"),
        ("F6", "64", "B5", "A0"),
        ("F6", "64", "B5", "A0"),
        ("AB", "64", "B5", "CC"),
        ("AB", "64", "B5", "CC"),
        ("AB", "64", "B5", "DD"),
        ("AB", "64", "B5", "DD"),
        ("ZZ", "YY"),
    ]
    ranked, _combined = rank_block_candidates(paths, min_paths=5, min_packets=2, min_share=0.15)
    by_last_hop = {
        item.last_hop: item
        for item in ranked
        if item.hop_tokens == ("64", "B5")
    }
    assert {"B5", "A0", "CC"}.issubset(set(by_last_hop))
    if "DD" in by_last_hop:
        assert by_last_hop["DD"].route_label == "64 ⇢ B5 (⇢ DD)"
    assert format_block_segment_label(("64", "B5"), last_hop="DB") == "64 ⇢ B5 (⇢ DB)"


def test_rank_block_candidates_uses_dominant_path_last_hop_in_label():
    paths = [
        ("C3", "91", "77", "AB", "F6"),
        ("C3", "91", "77", "AB", "F6"),
        ("C3", "91", "77", "AB", "F6"),
        ("D1", "91", "77", "AB", "F6"),
        ("E2", "91", "77", "AB", "F6"),
        ("XX", "YY", "ZZ"),
    ]
    ranked, _combined = rank_block_candidates(paths, min_paths=5, min_packets=2, min_share=0.5)
    top = ranked[0]
    assert top.hop_tokens == ("77", "AB")
    assert top.last_hop == "F6"
    assert top.route_label == "77 ⇢ AB (⇢ F6)"


def test_rank_block_candidates_empty_until_enough_paths():
    paths = [("77", "AB"), ("77", "AB")]
    ranked, combined = rank_block_candidates(paths, min_paths=5)
    assert ranked == []
    assert combined is None
