"""Path-tree analysis for progressive spam/flood hotspot narrowing."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

# Typical RF hop distance without an MQTT gateway bridge.
DEFAULT_MAX_HOP_DISTANCE_KM = 10.0
DEFAULT_TOP_HOTSPOTS = 5
DEFAULT_GEO_MERGE_RADIUS_KM = 35.0

RecordT = TypeVar("RecordT")
ClusterT = TypeVar("ClusterT")


@dataclass(frozen=True)
class NarrowedPrefix:
    """Deepest high-traffic path prefix for a packet cluster."""

    hop_tokens: tuple[str, ...]
    packet_count: int
    traffic_share: float
    concentration: float
    narrowing_depth: int


@dataclass(frozen=True)
class OriginEstimate:
    """Geo estimate for the spam source side of a narrowed prefix."""

    hop: str
    name: str | None
    public_key: str | None
    lat: float | None
    lon: float | None
    geo_chain_valid: bool


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    radius_km = 6371.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def format_route(hop_tokens: list[str] | tuple[str, ...]) -> str:
    if not hop_tokens:
        return "Direct"
    return " -> ".join(hop_tokens)


def narrow_dominant_prefix(
    paths: list[tuple[str, ...]],
    *,
    min_share: float = 0.15,
) -> NarrowedPrefix | None:
    """Find the deepest prefix that still captures a meaningful traffic share.

    Scoring favors deeper prefixes with concentrated traffic (depth * share^2).
    This progressively walks the shared path tree toward the likely source.
    """
    if not paths:
        return None

    total = len(paths)
    prefix_counts: Counter[tuple[str, ...]] = Counter()
    for path in paths:
        if not path:
            continue
        for depth in range(1, len(path) + 1):
            prefix_counts[tuple(path[:depth])] += 1

    if not prefix_counts:
        return None

    best: NarrowedPrefix | None = None
    best_score = -1.0
    for prefix, count in prefix_counts.items():
        share = count / total
        if share < min_share:
            continue
        depth = len(prefix)
        parent = prefix[:-1]
        parent_count = prefix_counts.get(parent, total) if parent else total
        child_concentration = count / parent_count if parent_count else 1.0
        # Skip fake deepening where every parent-path child continues unchanged.
        if depth > 1 and child_concentration >= 0.99:
            continue
        score = depth * (share**2)
        if score <= best_score:
            continue
        parent_share = parent_count / total if total else 0.0
        concentration = share / parent_share if parent_share > 0 else 1.0
        best_score = score
        best = NarrowedPrefix(
            hop_tokens=prefix,
            packet_count=count,
            traffic_share=share,
            concentration=concentration,
            narrowing_depth=depth,
        )
    return best


def split_path_clusters(
    records: list[RecordT],
    *,
    min_cluster_size: int,
    min_share: float,
    get_path: Callable[[RecordT], tuple[str, ...]],
) -> list[tuple[NarrowedPrefix, list[RecordT]]]:
    """Iteratively peel off dominant narrowed prefixes until nothing qualifies."""
    remaining = list(records)
    clusters: list[tuple[NarrowedPrefix, list[RecordT]]] = []

    while remaining:
        paths = [get_path(record) for record in remaining]
        narrowed = narrow_dominant_prefix(paths, min_share=min_share)
        if narrowed is None:
            break

        prefix = narrowed.hop_tokens
        matched = [record for record in remaining if get_path(record)[: len(prefix)] == prefix]
        if len(matched) < min_cluster_size:
            break

        clusters.append((narrowed, matched))
        matched_ids = {id(record) for record in matched}
        remaining = [record for record in remaining if id(record) not in matched_ids]

    return clusters


def split_entry_partitioned_clusters(
    records: list[RecordT],
    *,
    min_cluster_size: int,
    min_share: float,
    get_path: Callable[[RecordT], tuple[str, ...]],
    max_clusters: int = 3,
) -> list[tuple[NarrowedPrefix, list[RecordT]]]:
    """Narrow path prefixes independently within each ingress hop.

    Used when a coordinated flood splits across multiple sources so no single
    prefix reaches ``min_share`` globally, but routes within one ingress hop
    still share a deeper trunk.
    """
    total = len(records)
    if total == 0:
        return []

    by_entry: dict[str, list[RecordT]] = {}
    for record in records:
        path = get_path(record)
        if not path:
            continue
        by_entry.setdefault(path[0], []).append(record)

    candidates: list[tuple[NarrowedPrefix, list[RecordT]]] = []
    for entry_records in by_entry.values():
        if len(entry_records) < min_cluster_size:
            continue
        paths = [get_path(record) for record in entry_records]
        narrowed = narrow_dominant_prefix(paths, min_share=min_share)
        if narrowed is None:
            continue
        prefix = narrowed.hop_tokens
        matched = [
            record
            for record in entry_records
            if get_path(record)[: len(prefix)] == prefix
        ]
        if len(matched) < min_cluster_size:
            continue
        parent = prefix[:-1]
        parent_count = sum(
            1 for record in entry_records if get_path(record)[: len(parent)] == parent
        ) if parent else len(entry_records)
        parent_share = parent_count / len(entry_records) if entry_records else 0.0
        concentration = (
            (len(matched) / len(entry_records)) / parent_share if parent_share > 0 else 1.0
        )
        candidates.append(
            (
                NarrowedPrefix(
                    hop_tokens=prefix,
                    packet_count=len(matched),
                    traffic_share=len(matched) / total,
                    concentration=concentration,
                    narrowing_depth=len(prefix),
                ),
                matched,
            )
        )

    candidates.sort(
        key=lambda item: (
            -len(item[1]),
            -item[0].narrowing_depth,
            item[0].hop_tokens[0],
        )
    )
    return candidates[:max_clusters]


def estimate_origin_geo(
    hop_tokens: list[str] | tuple[str, ...],
    hop_geos: dict[str, dict[str, Any]],
    *,
    max_hop_distance_km: float = DEFAULT_MAX_HOP_DISTANCE_KM,
) -> OriginEstimate | None:
    """Pick the source-nearest hop with valid coordinates in the narrowed prefix.

    Walks from ingress (index 0) toward the radio. Earlier hops are preferred
    when coordinates form a geographically plausible chain.
    """
    if not hop_tokens:
        return None

    resolved: list[tuple[str, float, float, str | None, str | None]] = []
    chain_valid = True
    previous_coords: tuple[float, float] | None = None

    for hop in hop_tokens:
        geo = hop_geos.get(hop)
        if geo is None:
            continue
        lat = geo.get("lat")
        lon = geo.get("lon")
        if lat is None or lon is None:
            continue
        lat_f = float(lat)
        lon_f = float(lon)
        if lat_f == 0.0 and lon_f == 0.0:
            continue
        if previous_coords is not None:
            distance_km = haversine_distance_km(previous_coords[0], previous_coords[1], lat_f, lon_f)
            if distance_km > max_hop_distance_km:
                chain_valid = False
        resolved.append((hop, lat_f, lon_f, geo.get("name"), geo.get("public_key")))
        previous_coords = (lat_f, lon_f)

    if not resolved:
        return None

    # Prefer the earliest hop with coords (closest to spam source on the path).
    hop, lat, lon, name, public_key = resolved[0]
    return OriginEstimate(
        hop=hop,
        name=name,
        public_key=public_key,
        lat=lat,
        lon=lon,
        geo_chain_valid=chain_valid,
    )


def cluster_confidence(
    *,
    traffic_share: float,
    narrowing_depth: int,
    concentration: float,
    has_origin_geo: bool,
    geo_chain_valid: bool,
) -> int:
    """Composite 0-100 confidence for a narrowed hotspot."""
    depth_factor = min(1.0, narrowing_depth / 4.0)
    geo_factor = 1.0 if has_origin_geo and geo_chain_valid else 0.5 if has_origin_geo else 0.0
    raw = (
        0.35 * traffic_share
        + 0.25 * depth_factor
        + 0.20 * min(1.0, concentration)
        + 0.20 * geo_factor
    )
    return max(0, min(100, int(round(raw * 100))))


def best_prefix_for_hop(
    hop: str,
    observations: list[tuple[str, ...]],
) -> str:
    """Most common path prefix ending at this hop across observations."""
    prefix_counts: Counter[tuple[str, ...]] = Counter()
    for tokens in observations:
        if hop not in tokens:
            continue
        index = tokens.index(hop)
        prefix_counts[tuple(tokens[: index + 1])] += 1
    if not prefix_counts:
        return ""
    best_prefix, _ = prefix_counts.most_common(1)[0]
    return format_route(best_prefix)


def hop_suspect_score(
    hop: str,
    observations: list[tuple[str, ...]],
) -> float:
    """Score how likely a hop is source-proximate across historical path observations."""
    if not observations:
        return 0.0

    weighted_hits = 0.0
    first_position_hits = 0
    appearances = 0
    prefix_counts: Counter[tuple[str, ...]] = Counter()

    for tokens in observations:
        if hop not in tokens:
            continue
        index = tokens.index(hop)
        appearances += 1
        weighted_hits += 1.0 / (index + 1)
        if index == 0:
            first_position_hits += 1
        prefix_counts[tuple(tokens[: index + 1])] += 1

    if appearances == 0:
        return 0.0

    position_score = weighted_hits / appearances
    source_ratio = first_position_hits / appearances
    dominant_prefix_count = max(prefix_counts.values()) if prefix_counts else 0
    prefix_concentration = dominant_prefix_count / appearances
    return round(
        min(
            1.0,
            0.45 * position_score + 0.35 * source_ratio + 0.20 * prefix_concentration,
        ),
        4,
    )


def cluster_geo_point(cluster: object) -> tuple[float, float] | None:
    """Return the best available lat/lon for a flood hotspot cluster."""
    origin_lat = getattr(cluster, "origin_lat", None)
    origin_lon = getattr(cluster, "origin_lon", None)
    if origin_lat is not None and origin_lon is not None:
        if float(origin_lat) != 0.0 or float(origin_lon) != 0.0:
            return (float(origin_lat), float(origin_lon))

    lat = getattr(cluster, "lat", None)
    lon = getattr(cluster, "lon", None)
    if lat is not None and lon is not None:
        if float(lat) != 0.0 or float(lon) != 0.0:
            return (float(lat), float(lon))
    return None


def geo_weighted_centroid(clusters: list[object]) -> tuple[float, float] | None:
    """Traffic-weighted geographic center of flood hotspots with coordinates."""
    weighted: list[tuple[tuple[float, float], int]] = []
    for cluster in clusters:
        point = cluster_geo_point(cluster)
        packet_count = int(getattr(cluster, "packet_count", 0) or 0)
        if point is not None and packet_count > 0:
            weighted.append((point, packet_count))
    if not weighted:
        return None
    total_weight = sum(weight for _, weight in weighted)
    lat = sum(point[0] * weight for point, weight in weighted) / total_weight
    lon = sum(point[1] * weight for point, weight in weighted) / total_weight
    return (lat, lon)


def _sort_clusters_for_geo_consolidation(clusters: list[object]) -> list[object]:
    """Prefer high-traffic hotspots near the geographic center of the flood."""
    centroid = geo_weighted_centroid(clusters)
    if centroid is None:
        return sorted(
            clusters,
            key=lambda cluster: (
                -int(getattr(cluster, "packet_count", 0) or 0),
                -int(getattr(cluster, "confidence", 0) or 0),
            ),
        )

    def sort_key(cluster: object) -> tuple[int, float, int]:
        packet_count = int(getattr(cluster, "packet_count", 0) or 0)
        confidence = int(getattr(cluster, "confidence", 0) or 0)
        point = cluster_geo_point(cluster)
        if point is None:
            return (-packet_count, 9999.0, -confidence)
        distance_km = haversine_distance_km(centroid[0], centroid[1], point[0], point[1])
        return (-packet_count, distance_km, -confidence)

    return sorted(clusters, key=sort_key)


def consolidate_geo_hotspots(
    clusters: list[ClusterT],
    *,
    max_clusters: int = DEFAULT_TOP_HOTSPOTS,
    merge_radius_km: float = DEFAULT_GEO_MERGE_RADIUS_KM,
) -> list[ClusterT]:
    """Merge nearby ingress hotspots and cap the focused report list.

    Lightweight geo focus: no ML, just traffic-weighted centroid + radius merge.
    """
    if not clusters:
        return []

    limit = max_clusters if max_clusters > 0 else DEFAULT_TOP_HOTSPOTS
    remaining = list(_sort_clusters_for_geo_consolidation(clusters))
    merged: list[ClusterT] = []

    while remaining and len(merged) < limit:
        primary = remaining.pop(0)
        primary_point = cluster_geo_point(primary)
        group = [primary]

        if primary_point is not None:
            still_remaining: list[ClusterT] = []
            for candidate in remaining:
                point = cluster_geo_point(candidate)
                if (
                    point is not None
                    and haversine_distance_km(
                        primary_point[0],
                        primary_point[1],
                        point[0],
                        point[1],
                    )
                    <= merge_radius_km
                ):
                    group.append(candidate)
                else:
                    still_remaining.append(candidate)
            remaining = still_remaining

        if len(group) == 1:
            merged.append(primary)
            continue

        total_packets = sum(int(getattr(item, "packet_count", 0) or 0) for item in group)
        total_share = sum(float(getattr(item, "traffic_share", 0.0) or 0.0) for item in group)
        best_confidence = max(int(getattr(item, "confidence", 0) or 0) for item in group)
        last_seen = max(int(getattr(item, "last_seen", 0) or 0) for item in group)

        labels: list[str] = []
        for item in group:
            label = (
                getattr(item, "entry_name", None)
                or getattr(item, "origin_name", None)
                or getattr(item, "entry_hop", "")
            )
            if label and label not in labels:
                labels.append(str(label))

        entry_name = getattr(primary, "entry_name", None)
        if len(labels) > 1:
            entry_name = f"{labels[0]} (+{len(labels) - 1} nearby)"
        elif labels:
            entry_name = labels[0]

        merged.append(
            primary.model_copy(
                update={
                    "entry_name": entry_name,
                    "packet_count": total_packets,
                    "traffic_share": round(total_share, 4),
                    "confidence": best_confidence,
                    "last_seen": last_seen,
                    "cluster_mode": "geo_merged",
                }
            )
        )

    return merged[:limit]
