"""Path-tree analysis for progressive spam/flood hotspot narrowing."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

# Typical RF hop distance without an MQTT gateway bridge.
DEFAULT_MAX_HOP_DISTANCE_KM = 10.0

RecordT = TypeVar("RecordT")


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
