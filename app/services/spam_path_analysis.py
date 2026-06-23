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
DEFAULT_ONE_BYTE_GEO_MATCH_KM = 75.0
DEFAULT_LIKELY_SOURCE_GEO_MATCH_KM = 20.0
DEFAULT_LIKELY_SOURCE_MIN_SHARE = 0.5
DEFAULT_MULTI_SOURCE_MIN_SHARE = 0.25
DEFAULT_MULTI_SOURCE_COMBINED_SHARE = 0.85
DEFAULT_ROTATION_MIN_UNIQUE = 4
DEFAULT_ROTATION_MAX_TOP_SHARE = 0.35

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


def contact_has_valid_coords(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and not (lat == 0.0 and lon == 0.0)


def pick_nearest_coords_to_point(
    points: list[tuple[Any, float, float]],
    ref_lat: float,
    ref_lon: float,
) -> tuple[Any, float] | None:
    """Return the nearest item and its distance in km from (ref_lat, ref_lon)."""
    best_item: Any | None = None
    best_distance = float("inf")
    for item, lat, lon in points:
        distance_km = haversine_distance_km(ref_lat, ref_lon, lat, lon)
        if distance_km < best_distance:
            best_distance = distance_km
            best_item = item
    if best_item is None:
        return None
    return best_item, best_distance


def nearest_named_chain_landmark(
    hop_tokens: list[str] | tuple[str, ...],
    hop_geos: dict[str, dict[str, Any]],
    ref_lat: float,
    ref_lon: float,
    *,
    exclude_hop: str | None = None,
) -> str | None:
    """Nearest resolved hop name along the path to a reference coordinate."""
    best_name: str | None = None
    best_distance = float("inf")
    for hop in hop_tokens:
        if hop == exclude_hop:
            continue
        geo = hop_geos.get(hop)
        if geo is None:
            continue
        name = geo.get("name")
        lat = geo.get("lat")
        lon = geo.get("lon")
        if not name or not contact_has_valid_coords(lat, lon):
            continue
        distance_km = haversine_distance_km(ref_lat, ref_lon, float(lat), float(lon))
        if distance_km < best_distance:
            best_distance = distance_km
            best_name = str(name)
    return best_name


def build_one_byte_geo_hint(
    name: str,
    hop: str,
    distance_km: float,
    landmark_name: str | None,
) -> str:
    rounded_km = max(1, int(round(distance_km)))
    if landmark_name and landmark_name.casefold() != name.casefold():
        return (
            f"{name} ({hop}) seems near {landmark_name} "
            f"(~{rounded_km} km from estimated source)"
        )
    return f"{name} ({hop}) is ~{rounded_km} km from the estimated source"


def build_possibly_from_geo_hint(name: str, hop: str, distance_km: float) -> str:
    """Human-readable hint when a 1-byte hop is geo-matched near a known repeater."""
    rounded_km = max(1, int(round(distance_km)))
    return f"Possibly from {name} ({hop}, ~{rounded_km} km from nearby repeater)"


@dataclass(frozen=True)
class DominantSourceCandidate:
    """A sender identity that stays constant across most of a flood episode."""

    source_key: str
    source_label: str
    packet_count: int
    traffic_share: float
    kind: str  # "packet" or "path"


def detect_dominant_packet_source(
    source_keys: list[str | None],
    *,
    min_share: float = DEFAULT_LIKELY_SOURCE_MIN_SHARE,
    min_count: int = 3,
) -> DominantSourceCandidate | None:
    """Pick a packet-level sender when the same source key dominates the episode."""
    keyed = [key for key in source_keys if key]
    if not keyed:
        return None

    counts = Counter(keyed)
    top_key, top_count = counts.most_common(1)[0]
    share = top_count / len(keyed)
    if top_count < min_count or share < min_share:
        return None

    label = top_key.split(":", 1)[-1]
    if top_key.startswith("hash1:"):
        label = top_key.split(":", 1)[1]
    elif len(top_key) >= 12:
        label = top_key[:12]

    return DominantSourceCandidate(
        source_key=top_key,
        source_label=label,
        packet_count=top_count,
        traffic_share=share,
        kind="packet",
    )


def detect_dominant_path_source(
    paths: list[tuple[str, ...]],
    *,
    min_share: float = DEFAULT_LIKELY_SOURCE_MIN_SHARE,
    min_count: int = 3,
) -> DominantSourceCandidate | None:
    """Fallback: deepest shared RF prefix when packet sender identity is unavailable."""
    if not paths:
        return None

    narrowed = narrow_dominant_prefix(paths, min_share=min_share)
    if narrowed is None or narrowed.packet_count < min_count:
        return None

    hop = narrowed.hop_tokens[-1]
    return DominantSourceCandidate(
        source_key=f"path:{hop}",
        source_label=hop,
        packet_count=narrowed.packet_count,
        traffic_share=narrowed.traffic_share,
        kind="path",
    )


@dataclass(frozen=True)
class SourceFilterPlan:
    """How episode path clustering should narrow by packet sender identity."""

    mode: str  # none, single, multi, rotating
    sources: tuple[DominantSourceCandidate, ...] = ()
    excluded_packets: int = 0


def _dominant_source_candidate_from_key(key: str, count: int, total: int) -> DominantSourceCandidate:
    label = key.split(":", 1)[-1]
    if key.startswith("hash1:"):
        label = key.split(":", 1)[1]
    elif len(key) >= 12:
        label = key[:12]
    return DominantSourceCandidate(
        source_key=key,
        source_label=label,
        packet_count=count,
        traffic_share=count / total if total else 0.0,
        kind="packet",
    )


def is_rotating_sender_identity(
    source_keys: list[str | None],
    *,
    min_share: float = DEFAULT_LIKELY_SOURCE_MIN_SHARE,
    min_unique: int = DEFAULT_ROTATION_MIN_UNIQUE,
    max_top_share: float = DEFAULT_ROTATION_MAX_TOP_SHARE,
) -> bool:
    """True when many distinct sender keys appear with no stable dominant identity."""
    keyed = [key for key in source_keys if key]
    if len(keyed) < min_unique:
        return False

    counts = Counter(keyed)
    top_count = counts.most_common(1)[0][1]
    top_share = top_count / len(keyed)
    unique = len(counts)
    if unique >= min_unique and top_share < min_share:
        return True
    if unique >= len(keyed) * 0.35 and top_share < max_top_share:
        return True
    return False


def build_source_filter_plan(
    source_keys: list[str | None],
    *,
    min_share: float = DEFAULT_LIKELY_SOURCE_MIN_SHARE,
    min_count: int = 3,
    multi_min_share: float = DEFAULT_MULTI_SOURCE_MIN_SHARE,
    multi_combined_share: float = DEFAULT_MULTI_SOURCE_COMBINED_SHARE,
    max_sources: int = 2,
) -> SourceFilterPlan:
    """Plan sender-focused filtering for flood path clustering and reports."""
    keyed = [key for key in source_keys if key]
    total = len(keyed)
    if total == 0:
        return SourceFilterPlan(mode="none")

    if is_rotating_sender_identity(source_keys, min_share=min_share):
        return SourceFilterPlan(mode="rotating")

    counts = Counter(keyed)
    ranked = counts.most_common(max_sources + 1)
    top_key, top_count = ranked[0]
    top_share = top_count / total
    if top_count < min_count or top_share < min_share:
        return SourceFilterPlan(mode="none")

    primary = _dominant_source_candidate_from_key(top_key, top_count, total)
    if len(ranked) >= 2:
        second_key, second_count = ranked[1]
        second_share = second_count / total
        if (
            second_count >= min_count
            and second_share >= multi_min_share
            and (top_share + second_share) >= multi_combined_share
        ):
            secondary = _dominant_source_candidate_from_key(second_key, second_count, total)
            return SourceFilterPlan(
                mode="multi",
                sources=(primary, secondary),
                excluded_packets=total - top_count - second_count,
            )

    return SourceFilterPlan(
        mode="single",
        sources=(primary,),
        excluded_packets=total - top_count,
    )


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


def path_contains_segment(path: tuple[str, ...], segment: tuple[str, ...]) -> bool:
    """True when *segment* appears as consecutive hops inside *path*."""
    if not segment or len(segment) > len(path):
        return False
    width = len(segment)
    for index in range(len(path) - width + 1):
        if path[index : index + width] == segment:
            return True
    return False


def count_segment_occurrences(path: tuple[str, ...], segment: tuple[str, ...]) -> int:
    if not segment or len(segment) > len(path):
        return 0
    width = len(segment)
    return sum(1 for index in range(len(path) - width + 1) if path[index : index + width] == segment)


@dataclass(frozen=True)
class BlockCandidateSegment:
    """A consecutive hop segment that appears often enough to consider blocking."""

    hop_tokens: tuple[str, ...]
    segment_len: int
    route: str
    packet_count: int
    occurrence_count: int
    traffic_share: float


def greedy_combined_coverage(
    paths: list[tuple[str, ...]],
    segments: list[tuple[str, ...]],
    *,
    max_segments: int = 3,
) -> tuple[float, list[tuple[str, ...]]]:
    """Greedy union coverage when blocking up to *max_segments* path segments."""
    if not paths or not segments or max_segments <= 0:
        return 0.0, []

    selected: list[tuple[str, ...]] = []
    best_coverage = 0.0
    remaining = list(segments)
    for _ in range(max_segments):
        best_segment: tuple[str, ...] | None = None
        best_new_coverage = best_coverage
        for segment in remaining:
            trial = selected + [segment]
            matched = sum(
                1 for path in paths if any(path_contains_segment(path, part) for part in trial)
            )
            coverage = matched / len(paths)
            if coverage > best_new_coverage:
                best_new_coverage = coverage
                best_segment = segment
        if best_segment is None:
            break
        selected.append(best_segment)
        remaining.remove(best_segment)
        best_coverage = best_new_coverage
    return best_coverage, selected


def rank_block_candidates(
    paths: list[tuple[str, ...]],
    *,
    segment_lengths: tuple[int, ...] = (2, 3),
    min_paths: int = 5,
    min_packets: int = 2,
    min_share: float = 0.08,
    max_results: int = 8,
) -> tuple[list[BlockCandidateSegment], float | None]:
    """Rank frequent 2- and 3-hop segments for repeater block rules.

    Returns ranked candidates plus greedy combined coverage for the top picks.
    """
    filtered = [tuple(path) for path in paths if path]
    total_paths = len(filtered)
    if total_paths < min_paths:
        return [], None

    occurrence_counter: Counter[tuple[str, ...]] = Counter()
    for path in filtered:
        for segment_len in segment_lengths:
            if segment_len < 2 or segment_len > len(path):
                continue
            for index in range(len(path) - segment_len + 1):
                occurrence_counter[tuple(path[index : index + segment_len])] += 1

    candidates: list[BlockCandidateSegment] = []
    for segment, occurrence_count in occurrence_counter.items():
        packet_count = sum(1 for path in filtered if path_contains_segment(path, segment))
        share = packet_count / total_paths
        if packet_count < min_packets or share < min_share:
            continue
        candidates.append(
            BlockCandidateSegment(
                hop_tokens=segment,
                segment_len=len(segment),
                route=format_route(segment),
                packet_count=packet_count,
                occurrence_count=occurrence_count,
                traffic_share=share,
            )
        )

    candidates.sort(
        key=lambda item: (
            -item.packet_count,
            -item.occurrence_count,
            item.segment_len,
            item.route,
        )
    )
    ranked = candidates[:max_results]
    if not ranked:
        return [], None

    ordered_segments = [item.hop_tokens for item in ranked]
    combined_coverage, _ = greedy_combined_coverage(filtered, ordered_segments, max_segments=3)
    return ranked, combined_coverage if combined_coverage > 0 else None


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
        matching_paths = [path for path in paths if path[:depth] == prefix]
        # Skip fake deepening only when the prefix already spans every matched path.
        if (
            depth > 1
            and child_concentration >= 0.99
            and all(len(path) <= depth for path in matching_paths)
        ):
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
