"""Live packet flood detection with RF ingress clustering and gateway stripping."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from app.models import SpamBlockCandidate, SpamCategoryFloodStatus, SpamFloodCluster, SpamLiveStatus
from app.path_utils import (
    hash_mode_from_hop_token,
    hop_allows_prefix_name_lookup,
    split_path_hex,
    split_path_hex_for_hash_size,
)
from app.repository.contact_advert_neighbors import ContactAdvertNeighborRepository
from app.repository.contacts import ContactRepository
from app.repository.spam_flood_episodes import SpamFloodEpisodeRepository
from app.services.spam_advert_neighbors import enrich_hop_geos_from_advert_neighbors
from app.services.spam_baseline import SpamBaselineService
from app.services.spam_detection_settings import is_fluke_episode
from app.services.spam_category_flood_state import CategoryFloodState
from app.services.spam_flood_repeater_automation import schedule_spam_flood_repeater_commands
from app.services.spam_gateway_filter import (
    gateway_pubkeys_from_configured,
    is_gateway_hop,
)
from app.services.spam_packet_timeline import (
    CATEGORY_LABELS,
    primary_category_from_counts,
)
from app.services.spam_path_analysis import (
    build_one_byte_geo_hint,
    build_possibly_from_geo_hint,
    build_source_filter_plan,
    cluster_confidence,
    consolidate_geo_hotspots,
    contact_has_valid_coords,
    detect_dominant_packet_source,
    detect_dominant_path_source,
    estimate_origin_geo,
    format_route,
    geo_weighted_centroid,
    hop_suspect_score,
    nearest_named_chain_landmark,
    pick_nearest_coords_to_point,
    rank_block_candidates,
    split_entry_partitioned_clusters,
    split_path_clusters,
    SourceFilterPlan,
    DEFAULT_LIKELY_SOURCE_GEO_MATCH_KM,
    DEFAULT_LIKELY_SOURCE_MIN_SHARE,
    DEFAULT_ONE_BYTE_GEO_MATCH_KM,
)

logger = logging.getLogger(__name__)

_MAX_DISPLAY_ROUTE_HOPS = 10


@dataclass
class _PacketRecord:
    timestamp: float
    entry_node: str
    full_rf_path: tuple[str, ...]
    category: str
    path_hash_mode: int | None = None
    source_key: str | None = None
    source_label: str | None = None


@dataclass
class SpamLiveTracker:
    """Rolling-window packet flood tracker with multi-ingress clustering."""

    spam_gateway_keys: str = ""
    window_secs: float = 30.0
    packet_threshold: int = 15
    cluster_min_ratio: float = 0.15
    broadcast_cooldown_secs: float = 10.0
    hold_secs: float = 300.0
    episode_retention_secs: float = 0.0
    max_report_clusters: int = 0
    fluke_max_packets: int = 35
    fluke_max_duration_secs: int = 300

    _category_states: dict[str, CategoryFloodState] = field(default_factory=dict, init=False)
    _gateway_pubkeys: frozenset[str] = field(
        default_factory=lambda: gateway_pubkeys_from_configured(""),
        init=False,
    )
    _last_status: SpamLiveStatus | None = field(default=None, init=False)
    _repeater_start_dispatched: bool = field(default=False, init=False)
    _episode_watchdog_task: asyncio.Task[None] | None = field(default=None, init=False)
    _episode_lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def gateway_pubkeys(self) -> frozenset[str]:
        return self._gateway_pubkeys

    def reload_gateway_pubkeys(self) -> None:
        self._gateway_pubkeys = gateway_pubkeys_from_configured(self.spam_gateway_keys)

    def _category_state(self, category: str) -> CategoryFloodState:
        state = self._category_states.get(category)
        if state is None:
            state = CategoryFloodState(category=category)
            self._category_states[category] = state
        return state

    def _any_category_active(self) -> bool:
        return any(state.active for state in self._category_states.values())

    def _any_episode_open(self) -> bool:
        return any(state.episode_open for state in self._category_states.values())

    def _sync_repeater_automation(self) -> None:
        """Send repeater start once when any category flood is open; end when all are done."""
        if self._any_episode_open():
            if not self._repeater_start_dispatched:
                schedule_spam_flood_repeater_commands("start")
                self._repeater_start_dispatched = True
        elif self._repeater_start_dispatched:
            schedule_spam_flood_repeater_commands("end")
            self._repeater_start_dispatched = False

    def apply_runtime_settings(
        self,
        *,
        spam_gateway_keys: str,
        window_secs: float,
        packet_threshold: int,
        cluster_min_ratio: float,
        broadcast_cooldown_secs: float,
        hold_secs: float,
        episode_retention_secs: float,
        max_report_clusters: int,
        fluke_max_packets: int,
        fluke_max_duration_secs: int,
    ) -> None:
        """Apply live tuning from app_settings without restarting the process."""
        gateway_changed = spam_gateway_keys != self.spam_gateway_keys
        self.spam_gateway_keys = spam_gateway_keys
        self.window_secs = float(window_secs)
        self.packet_threshold = int(packet_threshold)
        self.cluster_min_ratio = float(cluster_min_ratio)
        self.broadcast_cooldown_secs = float(broadcast_cooldown_secs)
        self.hold_secs = float(hold_secs)
        self.episode_retention_secs = float(episode_retention_secs)
        self.max_report_clusters = int(max_report_clusters)
        self.fluke_max_packets = int(fluke_max_packets)
        self.fluke_max_duration_secs = int(fluke_max_duration_secs)
        if gateway_changed:
            self.reload_gateway_pubkeys()

    def _is_gateway_hop(self, hop: str) -> bool:
        return is_gateway_hop(hop, self._gateway_pubkeys)

    @staticmethod
    def _rf_path_tokens(
        path_hex: str,
        path_len: int,
        *,
        path_hash_size: int | None = None,
    ) -> list[str]:
        if not path_hex or path_len <= 0:
            return []
        if path_hash_size is not None and 1 <= int(path_hash_size) <= 3:
            return [
                token.upper()
                for token in split_path_hex_for_hash_size(
                    path_hex.upper(),
                    path_len,
                    int(path_hash_size),
                )
            ]
        return [token.upper() for token in split_path_hex(path_hex.upper(), path_len)]

    def _strip_to_rf_path(self, hop_tokens: list[str]) -> list[str]:
        rf_only: list[str] = []
        for hop in hop_tokens:
            if self._is_gateway_hop(hop):
                break
            rf_only.append(hop)
        return rf_only

    def observe_packet(
        self,
        *,
        category: str,
        path_hex: str | None,
        path_len: int | None,
        path_hash_size: int | None = None,
        observed_at: int | float | None = None,
        source_key: str | None = None,
        source_label: str | None = None,
    ) -> bool:
        """Record a packet observation; return True when state may have changed."""
        current_time = float(observed_at if observed_at is not None else time.time())
        hash_size = int(path_hash_size) if path_hash_size is not None else None
        tokens = self._rf_path_tokens(
            path_hex or "",
            int(path_len or 0),
            path_hash_size=hash_size,
        )
        rf_only = self._strip_to_rf_path(tokens)
        path_hash_mode = None
        if hash_size is not None and 1 <= hash_size <= 3:
            path_hash_mode = hash_size - 1

        record = _PacketRecord(
            timestamp=current_time,
            entry_node=rf_only[0] if rf_only else "",
            full_rf_path=tuple(rf_only),
            category=category,
            path_hash_mode=path_hash_mode,
            source_key=source_key,
            source_label=source_label,
        )
        state = self._category_state(category)
        state.history.append(record)

        was_active = state.active
        self._sync_active_state(state, current_time)
        if state.active:
            if not was_active:
                cutoff = current_time - self.window_secs
                state.episode_packet_records = [
                    existing for existing in state.history if existing.timestamp >= cutoff
                ]
            else:
                state.episode_packet_records.append(record)
        return self._should_broadcast(state, current_time, was_active)

    def observe_dm_path(
        self,
        *,
        path_hex: str | None,
        path_len: int | None,
        observed_at: int | float | None = None,
        category: str = "dm",
    ) -> bool:
        """Backward-compatible alias for DM path observations."""
        return self.observe_packet(
            category=category,
            path_hex=path_hex,
            path_len=path_len,
            observed_at=observed_at,
        )

    def _episode_retention_horizon(self) -> float:
        configured = self.episode_retention_secs
        if configured > 0:
            return configured
        return max(self.hold_secs, self.window_secs)

    def _retention_cutoff(self, state: CategoryFloodState, current_time: float) -> float:
        if state.detected_at is not None:
            horizon = self._episode_retention_horizon()
            episode_floor = state.detected_at - self.window_secs
            episode_horizon = current_time - horizon
            return min(episode_floor, episode_horizon)
        return current_time - self.window_secs

    def _trim_window(self, state: CategoryFloodState, current_time: float) -> None:
        cutoff = self._retention_cutoff(state, current_time)
        while state.history and state.history[0].timestamp < cutoff:
            state.history.popleft()

    def _trigger_window_count(self, state: CategoryFloodState, current_time: float) -> int:
        cutoff = current_time - self.window_secs
        return sum(1 for record in state.history if record.timestamp >= cutoff)

    def _sync_active_state(self, state: CategoryFloodState, current_time: float) -> None:
        """Apply retention trim and threshold/hold logic for one packet category."""
        above_threshold = self._trigger_window_count(state, current_time) >= self.packet_threshold
        if above_threshold:
            if state.detected_at is None:
                state.detected_at = current_time
            if self.hold_secs > 0:
                state.hold_until = current_time + self.hold_secs

        in_hold = (
            self.hold_secs > 0
            and state.hold_until is not None
            and current_time < state.hold_until
        )
        state.active = above_threshold or in_hold
        self._trim_window(state, current_time)

        if not state.active:
            state.detected_at = None
            state.hold_until = None
            self._trim_window(state, current_time)

    def _should_broadcast(
        self,
        state: CategoryFloodState,
        current_time: float,
        was_active: bool,
    ) -> bool:
        if not state.active:
            return was_active
        return (
            not was_active
            or current_time - state.last_broadcast_at >= self.broadcast_cooldown_secs
        )

    def _min_cluster_size(self) -> int:
        return max(1, int(self.packet_threshold * self.cluster_min_ratio))

    def _max_report_clusters(self) -> int:
        if self.max_report_clusters <= 0:
            return 5
        return self.max_report_clusters

    def _apply_report_limit(self, clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return clusters[: self._max_report_clusters()]

    def _apply_report_limit_models(self, clusters: list[SpamFloodCluster]) -> list[SpamFloodCluster]:
        return clusters[: self._max_report_clusters()]

    @staticmethod
    def _cluster_identity_key(cluster: SpamFloodCluster) -> str:
        refined = cluster.refined_hop_tokens or cluster.hop_tokens
        suffix = "/".join(refined) if refined else cluster.entry_hop
        return f"{cluster.entry_hop}:{suffix}"

    def _update_episode_peak_clusters(
        self,
        state: CategoryFloodState,
        clusters: list[SpamFloodCluster],
    ) -> None:
        for cluster in clusters:
            key = self._cluster_identity_key(cluster)
            existing = state.episode_peak_clusters.get(key)
            if existing is None:
                state.episode_peak_clusters[key] = cluster
                continue
            state.episode_peak_clusters[key] = existing.model_copy(
                update={
                    "packet_count": max(existing.packet_count, cluster.packet_count),
                    "traffic_share": max(existing.traffic_share, cluster.traffic_share),
                    "confidence": max(existing.confidence, cluster.confidence),
                    "last_seen": max(existing.last_seen, cluster.last_seen),
                    "entry_name": cluster.entry_name or existing.entry_name,
                    "entry_public_key": cluster.entry_public_key or existing.entry_public_key,
                    "lat": cluster.lat if cluster.lat is not None else existing.lat,
                    "lon": cluster.lon if cluster.lon is not None else existing.lon,
                    "origin_hop": cluster.origin_hop or existing.origin_hop,
                    "origin_name": cluster.origin_name or existing.origin_name,
                    "origin_public_key": cluster.origin_public_key or existing.origin_public_key,
                    "origin_lat": cluster.origin_lat if cluster.origin_lat is not None else existing.origin_lat,
                    "origin_lon": cluster.origin_lon if cluster.origin_lon is not None else existing.origin_lon,
                    "origin_geo_hint": cluster.origin_geo_hint or existing.origin_geo_hint,
                    "dominant_route": cluster.dominant_route or existing.dominant_route,
                    "hop_tokens": cluster.hop_tokens or existing.hop_tokens,
                    "refined_route": cluster.refined_route or existing.refined_route,
                    "refined_hop_tokens": cluster.refined_hop_tokens or existing.refined_hop_tokens,
                    "longest_route_tokens": (
                        cluster.longest_route_tokens
                        if len(cluster.longest_route_tokens) >= len(existing.longest_route_tokens)
                        else existing.longest_route_tokens
                    ),
                    "hop_names_by_token": {
                        **existing.hop_names_by_token,
                        **cluster.hop_names_by_token,
                    },
                    "narrowing_depth": max(existing.narrowing_depth, cluster.narrowing_depth),
                    "concentration": max(existing.concentration, cluster.concentration),
                    "cluster_mode": cluster.cluster_mode or existing.cluster_mode,
                }
            )

    def _episode_peak_clusters_display(self, state: CategoryFloodState) -> list[SpamFloodCluster]:
        clusters = self._sorted_peak_clusters(state)
        return self._apply_report_limit_models(clusters)

    def _sorted_peak_clusters(self, state: CategoryFloodState) -> list[SpamFloodCluster]:
        clusters = list(state.episode_peak_clusters.values())
        clusters.sort(
            key=lambda cluster: (
                -cluster.packet_count,
                -cluster.traffic_share,
                -cluster.last_seen,
                cluster.entry_hop,
            )
        )
        return clusters

    def _episode_records(self, state: CategoryFloodState) -> list[_PacketRecord]:
        if state.episode_packet_records:
            return list(state.episode_packet_records)
        return list(state.history)

    def _source_filter_plan(
        self,
        state: CategoryFloodState,
        records: list[_PacketRecord],
    ) -> SourceFilterPlan:
        plan = build_source_filter_plan(
            [record.source_key for record in records],
            min_share=DEFAULT_LIKELY_SOURCE_MIN_SHARE,
            min_count=self._likely_source_min_count(),
        )
        if plan.mode not in {"single", "multi"}:
            return plan

        allowed = {source.source_key for source in plan.sources}
        excluded = sum(
            1
            for record in records
            if record.full_rf_path and record.source_key not in allowed
        )
        return SourceFilterPlan(
            mode=plan.mode,
            sources=plan.sources,
            excluded_packets=excluded,
        )

    @staticmethod
    def _records_for_source_filter(
        records: list[_PacketRecord],
        plan: SourceFilterPlan,
    ) -> list[_PacketRecord]:
        with_path = [record for record in records if record.full_rf_path]
        if plan.mode == "single" and plan.sources:
            allowed = plan.sources[0].source_key
            return [record for record in with_path if record.source_key == allowed]
        if plan.mode == "multi":
            allowed = {source.source_key for source in plan.sources}
            return [record for record in with_path if record.source_key in allowed]
        return with_path

    def _clustering_records(self, state: CategoryFloodState) -> list[_PacketRecord]:
        records = self._episode_records(state)
        plan = self._source_filter_plan(state, records)
        state.episode_source_filter = plan
        return self._records_for_source_filter(records, plan)

    @staticmethod
    def _longest_path_tokens(
        records: list[_PacketRecord],
        *,
        max_hops: int = _MAX_DISPLAY_ROUTE_HOPS,
    ) -> list[str]:
        if not records:
            return []
        max_len = max(len(record.full_rf_path) for record in records)
        longest_records = [record for record in records if len(record.full_rf_path) == max_len]
        path_counts = Counter(record.full_rf_path for record in longest_records)
        longest_path, _ = path_counts.most_common(1)[0]
        return list(longest_path)[:max_hops]

    @staticmethod
    def _dominant_path_hash_mode(records: list[_PacketRecord]) -> int | None:
        modes = [record.path_hash_mode for record in records if record.path_hash_mode is not None]
        if not modes:
            return None
        return Counter(modes).most_common(1)[0][0]

    def _build_cluster_results(
        self,
        narrowed_clusters: list[tuple[Any, list[_PacketRecord]]],
        *,
        cluster_mode: str,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for narrowed, matched_records in narrowed_clusters:
            path_counts = Counter(record.full_rf_path for record in matched_records)
            dominant_path, _ = path_counts.most_common(1)[0]
            results.append(
                {
                    "entry_hop": narrowed.hop_tokens[0],
                    "packet_count": len(matched_records),
                    "dominant_path_tokens": list(dominant_path),
                    "longest_path_tokens": self._longest_path_tokens(matched_records),
                    "refined_hop_tokens": list(narrowed.hop_tokens),
                    "path_hash_mode": self._dominant_path_hash_mode(matched_records),
                    "traffic_share": narrowed.traffic_share,
                    "concentration": narrowed.concentration,
                    "narrowing_depth": narrowed.narrowing_depth,
                    "last_seen": max(record.timestamp for record in matched_records),
                    "cluster_mode": cluster_mode,
                }
            )

        results.sort(
            key=lambda item: (
                -item["packet_count"],
                -item["narrowing_depth"],
                -item["last_seen"],
                item["entry_hop"],
            )
        )
        return self._apply_report_limit(results)

    def _cluster_packets_narrowed_from(self, records: list[_PacketRecord]) -> list[dict[str, Any]]:
        min_cluster_size = self._min_cluster_size()
        narrowed_clusters = split_path_clusters(
            records,
            min_cluster_size=min_cluster_size,
            min_share=self.cluster_min_ratio,
            get_path=lambda record: record.full_rf_path,
        )
        return self._build_cluster_results(narrowed_clusters, cluster_mode="narrowed")

    def _cluster_packets_partitioned_from(self, records: list[_PacketRecord]) -> list[dict[str, Any]]:
        min_cluster_size = self._min_cluster_size()
        partitioned_clusters = split_entry_partitioned_clusters(
            records,
            min_cluster_size=min_cluster_size,
            min_share=self.cluster_min_ratio,
            get_path=lambda record: record.full_rf_path,
            max_clusters=self._max_report_clusters(),
        )
        return self._build_cluster_results(partitioned_clusters, cluster_mode="partitioned")

    def _cluster_packets_narrowed(self, state: CategoryFloodState) -> list[dict[str, Any]]:
        return self._cluster_packets_narrowed_from(self._clustering_records(state))

    def _fallback_entry_clusters_from(self, records: list[_PacketRecord]) -> list[dict[str, Any]]:
        """Best-effort ingress hops when traffic is high but too dispersed to narrow."""
        if not records:
            return []

        min_cluster_size = self._min_cluster_size()
        by_entry: dict[str, list[_PacketRecord]] = {}
        for record in records:
            by_entry.setdefault(record.entry_node, []).append(record)

        total = len(records)
        path_observations = [record.full_rf_path for record in records]
        scored_entries: list[tuple[float, str, list[_PacketRecord]]] = []
        for entry_hop, matched_records in by_entry.items():
            if len(matched_records) < min_cluster_size:
                continue
            witness_score = hop_suspect_score(entry_hop, path_observations)
            score = len(matched_records) * (1.0 + witness_score)
            scored_entries.append((score, entry_hop, matched_records))

        scored_entries.sort(key=lambda item: (-item[0], item[1]))
        results: list[dict[str, Any]] = []
        for _, entry_hop, matched_records in scored_entries[: self._max_report_clusters()]:
            path_counts = Counter(record.full_rf_path for record in matched_records)
            dominant_path, _ = path_counts.most_common(1)[0]
            results.append(
                {
                    "entry_hop": entry_hop,
                    "packet_count": len(matched_records),
                    "dominant_path_tokens": list(dominant_path),
                    "longest_path_tokens": self._longest_path_tokens(matched_records),
                    "refined_hop_tokens": [entry_hop],
                    "path_hash_mode": self._dominant_path_hash_mode(matched_records),
                    "traffic_share": len(matched_records) / total if total else 0.0,
                    "concentration": 1.0,
                    "narrowing_depth": 1,
                    "last_seen": max(record.timestamp for record in matched_records),
                    "cluster_mode": "entry_fallback",
                }
            )
        return results

    def _fallback_entry_clusters(self, state: CategoryFloodState) -> list[dict[str, Any]]:
        return self._fallback_entry_clusters_from(self._clustering_records(state))

    def _cluster_packets_from(self, records: list[_PacketRecord]) -> list[dict[str, Any]]:
        narrowed = self._cluster_packets_narrowed_from(records)
        if narrowed:
            return narrowed
        partitioned = self._cluster_packets_partitioned_from(records)
        if partitioned:
            return partitioned
        return self._fallback_entry_clusters_from(records)

    def _cluster_packets(self, state: CategoryFloodState) -> list[dict[str, Any]]:
        records = self._episode_records(state)
        plan = self._source_filter_plan(state, records)
        state.episode_source_filter = plan

        if plan.mode == "multi":
            clusters: list[dict[str, Any]] = []
            per_source_limit = max(1, self._max_report_clusters() // len(plan.sources))
            for source in plan.sources:
                subset = [
                    record
                    for record in records
                    if record.full_rf_path and record.source_key == source.source_key
                ]
                for cluster in self._cluster_packets_from(subset)[:per_source_limit]:
                    cluster["flood_source_key"] = source.source_key
                    cluster["flood_source_label"] = source.source_label
                    clusters.append(cluster)
            return self._apply_report_limit(clusters)

        filtered = self._records_for_source_filter(records, plan)
        clusters = self._cluster_packets_from(filtered)
        if plan.mode == "single" and plan.sources:
            source = plan.sources[0]
            for cluster in clusters:
                cluster["flood_source_key"] = source.source_key
                cluster["flood_source_label"] = source.source_label
        return clusters

    async def get_live_status(self) -> SpamLiveStatus:
        current_time = time.time()
        async with self._episode_lifecycle_lock:
            for state in list(self._category_states.values()):
                was_active = state.active
                self._sync_active_state(state, current_time)
                await self._apply_category_lifecycle_transitions(
                    state,
                    current_time,
                    was_active=was_active,
                )
            self._sync_repeater_automation()
            if not self._any_episode_open():
                self._cancel_episode_watchdog()
            if not self._any_episode_open() and not self._any_category_active():
                await self._close_stale_open_episode_rows(current_time)
        return await self._build_aggregate_status_async(current_time)

    async def _apply_one_byte_geo_resolution(
        self,
        hop_tokens: list[str],
        hop_geos: dict[str, dict[str, Any]],
        *,
        ref_lat: float | None,
        ref_lon: float | None,
        priority_hops: list[str],
        default_path_hash_mode: int | None = None,
    ) -> str | None:
        """Resolve 1-byte hop tokens via nearest known contact to the reference geo."""
        if ref_lat is None or ref_lon is None:
            return None

        origin_geo_hint: str | None = None
        for hop in hop_tokens:
            if hop_geos.get(hop, {}).get("name"):
                continue
            unique = await ContactRepository.get_by_key_prefix(hop)
            if unique is not None:
                continue

            candidates = await ContactRepository.list_geo_by_key_prefix(hop)
            candidate_points = [
                (contact, float(contact.lat), float(contact.lon))
                for contact in candidates
                if contact_has_valid_coords(contact.lat, contact.lon)
            ]
            if not candidate_points:
                hop_hash_mode = hash_mode_from_hop_token(hop)
                if hop_hash_mode is None:
                    hop_hash_mode = default_path_hash_mode
                try:
                    advert_neighbors = (
                        await ContactAdvertNeighborRepository.list_contacts_for_neighbor_hop(
                            hop,
                            path_hash_mode=hop_hash_mode,
                        )
                    )
                except RuntimeError:
                    advert_neighbors = []
                candidate_points = [
                    (contact, float(contact.lat), float(contact.lon))
                    for contact in advert_neighbors
                    if contact_has_valid_coords(contact.lat, contact.lon)
                ]
            nearest = pick_nearest_coords_to_point(candidate_points, ref_lat, ref_lon)
            if nearest is None:
                continue
            contact, distance_km = nearest
            if distance_km > DEFAULT_ONE_BYTE_GEO_MATCH_KM:
                continue

            hop_geos[hop] = {
                "name": contact.name,
                "public_key": contact.public_key,
                "lat": float(contact.lat),
                "lon": float(contact.lon),
            }

            if origin_geo_hint is None and hop in priority_hops:
                landmark = nearest_named_chain_landmark(
                    hop_tokens,
                    hop_geos,
                    ref_lat,
                    ref_lon,
                    exclude_hop=hop,
                )
                origin_geo_hint = build_one_byte_geo_hint(
                    contact.name or hop,
                    hop,
                    distance_km,
                    landmark,
                )

        return origin_geo_hint

    async def _enrich_clusters(self, clusters: list[dict[str, Any]]) -> list[SpamFloodCluster]:
        enriched_clusters: list[SpamFloodCluster] = []
        for cluster in clusters:
            refined_tokens = cluster.get("refined_hop_tokens") or cluster["dominant_path_tokens"]
            longest_tokens = cluster.get("longest_path_tokens") or cluster["dominant_path_tokens"]
            lookup_tokens = list(
                dict.fromkeys([*refined_tokens, *longest_tokens[:_MAX_DISPLAY_ROUTE_HOPS]])
            )
            hop_geos = await self._lookup_prefix_geos(lookup_tokens)
            cluster_hash_mode = cluster.get("path_hash_mode")
            await enrich_hop_geos_from_advert_neighbors(
                lookup_tokens,
                hop_geos,
                default_path_hash_mode=cluster_hash_mode,
            )
            preliminary_origin = estimate_origin_geo(refined_tokens, hop_geos)
            ref_lat = preliminary_origin.lat if preliminary_origin is not None else None
            ref_lon = preliminary_origin.lon if preliminary_origin is not None else None
            if ref_lat is None or ref_lon is None:
                chain_origin = estimate_origin_geo(lookup_tokens, hop_geos)
                if chain_origin is not None:
                    ref_lat = chain_origin.lat
                    ref_lon = chain_origin.lon
            if ref_lat is None or ref_lon is None:
                entry_geo = hop_geos.get(cluster["entry_hop"], {})
                ref_lat = entry_geo.get("lat")
                ref_lon = entry_geo.get("lon")
            priority_hops = list(
                dict.fromkeys(
                    [
                        *( [preliminary_origin.hop] if preliminary_origin and preliminary_origin.hop else [] ),
                        cluster["entry_hop"],
                        *(refined_tokens[:1] if refined_tokens else []),
                    ]
                )
            )
            origin_geo_hint = await self._apply_one_byte_geo_resolution(
                lookup_tokens,
                hop_geos,
                ref_lat=ref_lat,
                ref_lon=ref_lon,
                priority_hops=priority_hops,
                default_path_hash_mode=cluster_hash_mode,
            )
            origin = estimate_origin_geo(refined_tokens, hop_geos)
            entry_geo = hop_geos.get(cluster["entry_hop"], {})
            hop_names_by_token = {
                hop: geo["name"]
                for hop, geo in hop_geos.items()
                if geo.get("name")
            }
            entry_name = entry_geo.get("name") or hop_names_by_token.get(cluster["entry_hop"])
            confidence = cluster_confidence(
                traffic_share=float(cluster.get("traffic_share", 0.0)),
                narrowing_depth=int(cluster.get("narrowing_depth", 1)),
                concentration=float(cluster.get("concentration", 1.0)),
                has_origin_geo=origin is not None and origin.lat is not None,
                geo_chain_valid=origin.geo_chain_valid if origin is not None else False,
            )
            enriched_clusters.append(
                SpamFloodCluster(
                    entry_hop=cluster["entry_hop"],
                    entry_name=entry_name,
                    entry_public_key=entry_geo.get("public_key"),
                    lat=entry_geo.get("lat"),
                    lon=entry_geo.get("lon"),
                    packet_count=cluster["packet_count"],
                    dominant_route=format_route(cluster["dominant_path_tokens"]),
                    hop_tokens=cluster["dominant_path_tokens"],
                    longest_route_tokens=list(longest_tokens)[:_MAX_DISPLAY_ROUTE_HOPS],
                    hop_names_by_token=hop_names_by_token,
                    refined_route=format_route(refined_tokens),
                    refined_hop_tokens=refined_tokens,
                    traffic_share=round(float(cluster.get("traffic_share", 0.0)), 4),
                    concentration=round(float(cluster.get("concentration", 1.0)), 4),
                    narrowing_depth=int(cluster.get("narrowing_depth", 1)),
                    confidence=confidence,
                    origin_hop=origin.hop if origin is not None else None,
                    origin_name=origin.name if origin is not None else None,
                    origin_public_key=origin.public_key if origin is not None else None,
                    origin_lat=origin.lat if origin is not None else None,
                    origin_lon=origin.lon if origin is not None else None,
                    origin_geo_hint=origin_geo_hint,
                    last_seen=int(cluster["last_seen"]),
                    cluster_mode=cluster.get("cluster_mode"),
                    flood_source_key=cluster.get("flood_source_key"),
                    flood_source_label=cluster.get("flood_source_label"),
                )
            )
        return enriched_clusters

    def _focus_geo_clusters(self, clusters: list[SpamFloodCluster]) -> list[SpamFloodCluster]:
        return consolidate_geo_hotspots(clusters, max_clusters=self._max_report_clusters())

    def _category_source_records(self, state: CategoryFloodState) -> list[_PacketRecord]:
        records = self._episode_records(state)
        plan = state.episode_source_filter or self._source_filter_plan(state, records)
        if plan.mode in {"single", "multi"}:
            return self._records_for_source_filter(records, plan)
        return records

    def _category_breakdown(self, records: list[_PacketRecord]) -> dict[str, int]:
        return dict(Counter(record.category for record in records))

    def _category_labels_for(self, counts: dict[str, int]) -> dict[str, str]:
        return {key: CATEGORY_LABELS.get(key, key) for key in counts.keys()}

    def _episode_category_state(
        self,
        state: CategoryFloodState,
    ) -> tuple[str | None, dict[str, int], dict[str, str]]:
        records = self._category_source_records(state)
        counts = self._category_breakdown(records)
        labels = self._category_labels_for(counts)
        primary = primary_category_from_counts(counts) or state.category
        return primary, counts, labels

    def _likely_source_min_count(self) -> int:
        return max(3, self._min_cluster_size())

    def _detect_likely_source_candidate(self, records: list[_PacketRecord]):
        min_count = self._likely_source_min_count()
        packet_candidate = detect_dominant_packet_source(
            [record.source_key for record in records],
            min_share=DEFAULT_LIKELY_SOURCE_MIN_SHARE,
            min_count=min_count,
        )
        if packet_candidate is not None:
            return packet_candidate
        return detect_dominant_path_source(
            [record.full_rf_path for record in records if record.full_rf_path],
            min_share=DEFAULT_LIKELY_SOURCE_MIN_SHARE,
            min_count=min_count,
        )

    async def _resolve_likely_source(
        self,
        candidate,
        *,
        ref_lat: float | None,
        ref_lon: float | None,
    ) -> dict[str, Any]:
        hop = candidate.source_label
        if candidate.source_key.startswith("path:"):
            hop = candidate.source_key.split(":", 1)[1]

        resolved_name: str | None = None
        resolved_public_key: str | None = None
        resolved_lat: float | None = None
        resolved_lon: float | None = None
        geo_hint: str | None = None

        lookup_key = candidate.source_key
        if lookup_key.startswith("hash1:"):
            hop = lookup_key.split(":", 1)[1]
            contact = await ContactRepository.get_by_key_prefix(hop)
            if contact is not None:
                resolved_name = contact.name
                resolved_public_key = contact.public_key
                if contact_has_valid_coords(contact.lat, contact.lon):
                    resolved_lat = float(contact.lat)
                    resolved_lon = float(contact.lon)
            elif ref_lat is not None and ref_lon is not None:
                candidates = await ContactRepository.list_geo_by_key_prefix(hop)
                candidate_points = [
                    (item, float(item.lat), float(item.lon))
                    for item in candidates
                    if contact_has_valid_coords(item.lat, item.lon)
                ]
                nearest = pick_nearest_coords_to_point(candidate_points, ref_lat, ref_lon)
                if nearest is not None:
                    contact, distance_km = nearest
                    if distance_km <= DEFAULT_LIKELY_SOURCE_GEO_MATCH_KM:
                        resolved_name = contact.name
                        resolved_public_key = contact.public_key
                        resolved_lat = float(contact.lat)
                        resolved_lon = float(contact.lon)
                        geo_hint = build_possibly_from_geo_hint(
                            contact.name or hop,
                            hop,
                            distance_km,
                        )
        elif lookup_key.startswith("path:"):
            if hop_allows_prefix_name_lookup(hop):
                contact = await ContactRepository.get_by_key_prefix(hop)
                if contact is not None:
                    resolved_name = contact.name
                    resolved_public_key = contact.public_key
                    if contact_has_valid_coords(contact.lat, contact.lon):
                        resolved_lat = float(contact.lat)
                        resolved_lon = float(contact.lon)
                elif ref_lat is not None and ref_lon is not None:
                    candidates = await ContactRepository.list_geo_by_key_prefix(hop)
                    candidate_points = [
                        (item, float(item.lat), float(item.lon))
                        for item in candidates
                        if contact_has_valid_coords(item.lat, item.lon)
                    ]
                    nearest = pick_nearest_coords_to_point(candidate_points, ref_lat, ref_lon)
                    if nearest is not None:
                        contact, distance_km = nearest
                        if distance_km <= DEFAULT_LIKELY_SOURCE_GEO_MATCH_KM:
                            resolved_name = contact.name
                            resolved_public_key = contact.public_key
                            resolved_lat = float(contact.lat)
                            resolved_lon = float(contact.lon)
                            geo_hint = build_possibly_from_geo_hint(
                                contact.name or hop,
                                hop,
                                distance_km,
                            )
        else:
            contact = await ContactRepository.get_by_key_prefix(lookup_key[:12])
            if contact is None and len(lookup_key) >= 64:
                contact = await ContactRepository.get_by_key(lookup_key)
            if contact is not None:
                resolved_name = contact.name
                resolved_public_key = contact.public_key
                if contact_has_valid_coords(contact.lat, contact.lon):
                    resolved_lat = float(contact.lat)
                    resolved_lon = float(contact.lon)

        return {
            "likely_source_key": candidate.source_key,
            "likely_source_label": candidate.source_label,
            "likely_source_name": resolved_name,
            "likely_source_public_key": resolved_public_key,
            "likely_source_lat": resolved_lat,
            "likely_source_lon": resolved_lon,
            "likely_source_geo_hint": geo_hint,
            "likely_source_traffic_share": round(candidate.traffic_share, 4),
            "likely_source_packet_count": candidate.packet_count,
            "likely_source_kind": candidate.kind,
        }

    async def _refresh_likely_source(
        self,
        state: CategoryFloodState,
        clusters: list[SpamFloodCluster],
    ) -> dict[str, Any]:
        records = self._category_source_records(state)
        candidate = self._detect_likely_source_candidate(records)
        if candidate is None:
            state.episode_likely_source = None
            return self._empty_likely_source_fields()

        centroid = geo_weighted_centroid(clusters)
        ref_lat = centroid[0] if centroid is not None else None
        ref_lon = centroid[1] if centroid is not None else None
        if ref_lat is None or ref_lon is None:
            for record in records:
                if not record.full_rf_path:
                    continue
                hop_geos = await self._lookup_prefix_geos(list(record.full_rf_path[:3]))
                origin = estimate_origin_geo(record.full_rf_path, hop_geos)
                if origin is not None and origin.lat is not None and origin.lon is not None:
                    ref_lat = origin.lat
                    ref_lon = origin.lon
                    break

        resolved = await self._resolve_likely_source(
            candidate,
            ref_lat=ref_lat,
            ref_lon=ref_lon,
        )
        state.episode_likely_source = resolved
        return resolved

    @staticmethod
    def _empty_likely_source_fields() -> dict[str, Any]:
        return {
            "likely_source_key": None,
            "likely_source_label": None,
            "likely_source_name": None,
            "likely_source_public_key": None,
            "likely_source_lat": None,
            "likely_source_lon": None,
            "likely_source_geo_hint": None,
            "likely_source_traffic_share": None,
            "likely_source_packet_count": None,
            "likely_source_kind": None,
        }

    def _source_filter_fields(self, state: CategoryFloodState) -> dict[str, Any]:
        plan = state.episode_source_filter
        if plan is None or plan.mode in {"none", "rotating"}:
            return {
                "source_filter_active": False,
                "source_filter_mode": plan.mode if plan is not None else None,
                "source_filter_excluded_packets": 0,
                "source_filter_labels": [],
            }
        return {
            "source_filter_active": True,
            "source_filter_mode": plan.mode,
            "source_filter_excluded_packets": plan.excluded_packets,
            "source_filter_labels": [source.source_label for source in plan.sources],
        }

    def _likely_source_fields(self, state: CategoryFloodState) -> dict[str, Any]:
        if state.episode_likely_source:
            return dict(state.episode_likely_source)
        return self._empty_likely_source_fields()

    def _block_candidates(self, state: CategoryFloodState) -> tuple[list[SpamBlockCandidate], float | None]:
        if not state.active:
            return [], None
        records = self._clustering_records(state)
        paths = [record.full_rf_path for record in records if record.full_rf_path]
        if len(paths) < 5:
            return [], None
        ranked, combined_coverage = rank_block_candidates(
            paths,
            min_paths=5,
            min_packets=2,
            min_share=max(0.08, self.cluster_min_ratio * 0.5),
        )
        return (
            [
                SpamBlockCandidate(
                    route=item.route,
                    hop_tokens=list(item.hop_tokens),
                    segment_len=item.segment_len,
                    packet_count=item.packet_count,
                    occurrence_count=item.occurrence_count,
                    traffic_share=round(item.traffic_share, 4),
                )
                for item in ranked
            ],
            round(combined_coverage, 4) if combined_coverage is not None else None,
        )

    async def _build_category_status_async(
        self,
        state: CategoryFloodState,
        current_time: float,
        clusters: list[dict[str, Any]],
    ) -> SpamCategoryFloodStatus:
        enriched_clusters = self._focus_geo_clusters(await self._enrich_clusters(clusters))
        clusters_stale = False
        if enriched_clusters:
            self._update_episode_peak_clusters(state, enriched_clusters)
            state.episode_last_clusters = list(enriched_clusters)
            enriched_clusters = self._episode_peak_clusters_display(state)
        elif state.active and state.episode_peak_clusters:
            enriched_clusters = self._episode_peak_clusters_display(state)
            clusters_stale = True
        elif state.active and state.episode_last_clusters:
            enriched_clusters = [
                cluster.model_copy(update={"cluster_mode": cluster.cluster_mode or "sticky"})
                for cluster in state.episode_last_clusters
            ]
            clusters_stale = True
        peak_window = self._trigger_window_count(state, current_time)
        if state.episode_db_id is not None:
            state.episode_peak_window = max(state.episode_peak_window, peak_window)

        anomaly_ratio = None
        if state.episode_baseline and state.episode_baseline > 0:
            anomaly_ratio = round(
                max(state.episode_peak_window, peak_window) / state.episode_baseline,
                2,
            )

        primary_category, category_counts, category_labels = self._episode_category_state(state)
        if state.active:
            likely_source = await self._refresh_likely_source(state, enriched_clusters)
        else:
            likely_source = self._empty_likely_source_fields()

        block_candidates, block_candidates_combined_coverage = self._block_candidates(state)

        return SpamCategoryFloodStatus(
            category=state.category,
            category_label=CATEGORY_LABELS.get(state.category, state.category),
            active=state.active,
            window_secs=int(self.window_secs),
            packet_threshold=self.packet_threshold,
            total_packets=peak_window,
            episode_packets=len(state.episode_packet_records) or len(state.history),
            episode_window_secs=int(self._episode_retention_horizon()),
            detected_at=int(state.detected_at) if state.detected_at is not None else None,
            baseline_packets_per_window=(
                round(state.episode_baseline, 2) if state.episode_baseline is not None else None
            ),
            anomaly_ratio=anomaly_ratio,
            episode_id=state.episode_db_id,
            cluster_min_share=self.cluster_min_ratio,
            clusters_stale=clusters_stale,
            primary_category=primary_category,
            category_counts=category_counts,
            category_labels=category_labels,
            **self._source_filter_fields(state),
            **likely_source,
            block_candidates=block_candidates,
            block_candidates_combined_coverage=block_candidates_combined_coverage,
            clusters=enriched_clusters,
        )

    async def _build_aggregate_status_async(self, current_time: float) -> SpamLiveStatus:
        category_statuses: list[SpamCategoryFloodStatus] = []
        for state in self._category_states.values():
            if not state.history:
                continue
            clusters = (
                self._cluster_packets(state)
                if state.active and self._clustering_records(state)
                else []
            )
            category_statuses.append(
                await self._build_category_status_async(state, current_time, clusters)
            )

        category_statuses.sort(
            key=lambda item: (
                -int(item.active),
                -item.total_packets,
                -item.episode_packets,
                item.category,
            )
        )
        active_statuses = [status for status in category_statuses if status.active]
        primary = active_statuses[0] if active_statuses else (
            category_statuses[0] if category_statuses else None
        )

        if primary is None:
            status = SpamLiveStatus(
                active=False,
                window_secs=int(self.window_secs),
                packet_threshold=self.packet_threshold,
                total_packets=0,
                episode_packets=0,
                episode_window_secs=int(self._episode_retention_horizon()),
                cluster_min_share=self.cluster_min_ratio,
                category_floods=[],
            )
        else:
            status = SpamLiveStatus(
                active=bool(active_statuses),
                window_secs=primary.window_secs,
                packet_threshold=primary.packet_threshold,
                total_packets=primary.total_packets,
                episode_packets=primary.episode_packets,
                episode_window_secs=primary.episode_window_secs,
                detected_at=primary.detected_at,
                baseline_packets_per_window=primary.baseline_packets_per_window,
                anomaly_ratio=primary.anomaly_ratio,
                episode_id=primary.episode_id,
                cluster_min_share=primary.cluster_min_share,
                clusters_stale=primary.clusters_stale,
                primary_category=primary.primary_category,
                category_counts=primary.category_counts,
                category_labels=primary.category_labels,
                likely_source_key=primary.likely_source_key,
                likely_source_label=primary.likely_source_label,
                likely_source_name=primary.likely_source_name,
                likely_source_public_key=primary.likely_source_public_key,
                likely_source_lat=primary.likely_source_lat,
                likely_source_lon=primary.likely_source_lon,
                likely_source_geo_hint=primary.likely_source_geo_hint,
                likely_source_traffic_share=primary.likely_source_traffic_share,
                likely_source_packet_count=primary.likely_source_packet_count,
                likely_source_kind=primary.likely_source_kind,
                source_filter_active=primary.source_filter_active,
                source_filter_mode=primary.source_filter_mode,
                source_filter_excluded_packets=primary.source_filter_excluded_packets,
                source_filter_labels=primary.source_filter_labels,
                clusters=primary.clusters,
                category_floods=category_statuses,
            )
        self._last_status = status
        return status

    async def _build_status_async(
        self, current_time: float, clusters: list[dict[str, Any]]
    ) -> SpamLiveStatus:
        """Backward-compatible alias used by watchdog broadcast paths."""
        return await self._build_aggregate_status_async(current_time)

    @staticmethod
    async def _lookup_prefix_geos(hop_tokens: list[str]) -> dict[str, dict[str, Any]]:
        geos: dict[str, dict[str, Any]] = {}
        for hop in hop_tokens:
            if hop in geos:
                continue
            if not hop_allows_prefix_name_lookup(hop):
                geos[hop] = {}
                continue
            contact = await ContactRepository.get_by_key_prefix(hop)
            if contact is None:
                geos[hop] = {}
                continue
            lat = contact.lat
            lon = contact.lon
            has_coords = lat is not None and lon is not None and not (lat == 0.0 and lon == 0.0)
            geos[hop] = {
                "name": contact.name,
                "public_key": contact.public_key,
                "lat": float(lat) if has_coords else None,
                "lon": float(lon) if has_coords else None,
            }
        return geos

    async def _start_episode(self, state: CategoryFloodState, current_time: float) -> None:
        started_at = int(state.detected_at or current_time)
        try:
            baseline = await SpamBaselineService.get_packets_per_window(
                window_secs=int(self.window_secs),
                until=started_at,
                category=state.category,
            )
            episode_id = await SpamFloodEpisodeRepository.create_started(
                started_at=started_at,
                baseline_packets_per_window=round(baseline, 4),
                packet_threshold=self.packet_threshold,
                window_secs=int(self.window_secs),
            )
        except Exception:
            logger.exception("Failed to start spam flood episode log for %s", state.category)
            return

        if not state.episode_open:
            try:
                deleted = await SpamFloodEpisodeRepository.delete(episode_id)
                if deleted:
                    logger.info(
                        "Discarded stale %s spam flood episode %s created after flood ended",
                        state.category,
                        episode_id,
                    )
            except Exception:
                logger.exception("Failed to discard stale spam flood episode %s", episode_id)
            return

        state.episode_db_id = episode_id
        state.episode_baseline = baseline
        state.episode_peak_window = self._trigger_window_count(state, current_time)
        state.episode_last_clusters = []
        if not state.episode_packet_records:
            state.episode_packet_records = []
        state.episode_peak_clusters = {}

    def _open_flood_episode(self, state: CategoryFloodState, current_time: float) -> None:
        """Begin per-category episode tracking once per flood."""
        if state.episode_open:
            return
        state.episode_open = True
        state.episode_started_at = int(state.detected_at or current_time)
        state.episode_total_packets = len(state.episode_packet_records) or self._trigger_window_count(
            state,
            current_time,
        )
        self._ensure_episode_watchdog()

    def _cancel_episode_watchdog(self) -> None:
        task = self._episode_watchdog_task
        self._episode_watchdog_task = None
        if task is not None and not task.done():
            task.cancel()

    def _ensure_episode_watchdog(self) -> None:
        task = self._episode_watchdog_task
        if task is not None and not task.done():
            return
        self._episode_watchdog_task = asyncio.create_task(self._run_episode_watchdog())

    async def _run_episode_watchdog(self) -> None:
        """End flood episodes when hold windows expire even if no new packets arrive."""
        try:
            while self._any_episode_open():
                await asyncio.sleep(2.0)
                if not self._any_episode_open():
                    return
                await self._maybe_finalize_expired_episodes()
        except asyncio.CancelledError:
            return

    async def _maybe_finalize_expired_episodes(self) -> None:
        current_time = time.time()
        should_broadcast = False
        async with self._episode_lifecycle_lock:
            for state in list(self._category_states.values()):
                was_active = state.active
                self._sync_active_state(state, current_time)
                if was_active and not state.active:
                    should_broadcast = True
                await self._apply_category_lifecycle_transitions(
                    state,
                    current_time,
                    was_active=was_active,
                )
            self._sync_repeater_automation()
            if not self._any_episode_open():
                self._cancel_episode_watchdog()
        if not should_broadcast:
            return
        from app.websocket import broadcast_event

        status = await self._build_aggregate_status_async(current_time)
        broadcast_event("spam_flood_alert", status.model_dump())

    async def _apply_category_lifecycle_transitions(
        self,
        state: CategoryFloodState,
        current_time: float,
        *,
        was_active: bool,
    ) -> None:
        """Open, progress, or end one category flood episode. Caller must hold lock."""
        if state.active:
            if not state.episode_open:
                self._open_flood_episode(state, current_time)
                await self._start_episode(state, current_time)
            else:
                state.episode_peak_window = max(
                    state.episode_peak_window,
                    self._trigger_window_count(state, current_time),
                )
            state.episode_total_packets = len(state.episode_packet_records)
            if state.episode_db_id is not None:
                self._schedule_episode_progress(state)

        if was_active and not state.active:
            await self._end_episode(state, current_time)
        elif not state.active and state.episode_db_id is not None:
            await self._end_episode(state, current_time, force=True)

    async def _close_stale_open_episode_rows(self, current_time: float) -> None:
        """Close DB rows left open when in-memory episode state was lost."""
        try:
            closed = await SpamFloodEpisodeRepository.close_open_episodes(
                ended_at=int(current_time),
            )
            if closed:
                logger.info("Closed %d stale in-progress spam flood episode(s)", closed)
        except Exception:
            logger.exception("Failed to close stale in-progress spam flood episodes")

    def _reset_episode_state(self, state: CategoryFloodState) -> None:
        state.reset_episode()

    def _schedule_episode_progress(self, state: CategoryFloodState) -> None:
        if state.episode_db_id is None:
            return
        asyncio.create_task(self._persist_episode_progress(state))

    async def _persist_episode_progress(self, state: CategoryFloodState) -> None:
        if state.episode_db_id is None:
            return
        cluster_raw = self._cluster_packets(state)
        if cluster_raw:
            enriched = self._focus_geo_clusters(await self._enrich_clusters(cluster_raw))
            self._update_episode_peak_clusters(state, enriched)
            state.episode_last_clusters = self._episode_peak_clusters_display(state)
            await self._refresh_likely_source(state, state.episode_last_clusters)
        _, category_counts, _ = self._episode_category_state(state)
        likely_source = self._likely_source_fields(state)
        try:
            await SpamFloodEpisodeRepository.update_progress(
                episode_id=state.episode_db_id,
                total_packets=state.episode_total_packets,
                peak_packets_per_window=state.episode_peak_window,
                clusters=state.episode_last_clusters,
                category_counts=category_counts,
                likely_source=likely_source,
            )
        except Exception:
            logger.exception("Failed to update spam flood episode %s", state.episode_db_id)

    async def _end_episode(
        self,
        state: CategoryFloodState,
        current_time: float,
        *,
        force: bool = False,
    ) -> None:
        if not state.episode_open:
            if not force or state.episode_db_id is None:
                return
            state.episode_open = False
        else:
            state.episode_open = False

        episode_id = state.episode_db_id
        started_at = state.episode_started_at or int(current_time)
        ended_at = int(current_time)
        duration_secs = max(0, ended_at - started_at)
        total_packets = state.episode_total_packets
        cluster_raw = self._cluster_packets(state)
        if cluster_raw:
            final_clusters = self._focus_geo_clusters(await self._enrich_clusters(cluster_raw))
            self._update_episode_peak_clusters(state, final_clusters)
            final_clusters = self._episode_peak_clusters_display(state)
        elif state.episode_peak_clusters:
            final_clusters = self._episode_peak_clusters_display(state)
        elif state.episode_last_clusters:
            final_clusters = self._apply_report_limit_models(state.episode_last_clusters)
        else:
            final_clusters = []

        primary_category, category_counts, category_labels = self._episode_category_state(state)
        likely_source = self._likely_source_fields(state)
        if likely_source.get("likely_source_key") is None and final_clusters:
            likely_source = await self._refresh_likely_source(state, final_clusters)

        try:
            if episode_id is not None:
                if is_fluke_episode(
                    total_packets=total_packets,
                    duration_secs=duration_secs,
                    max_packets=self.fluke_max_packets,
                    max_duration_secs=self.fluke_max_duration_secs,
                ):
                    deleted = await SpamFloodEpisodeRepository.delete(episode_id)
                    if deleted:
                        logger.info(
                            "Discarded fluke %s spam flood episode %s (%d packets in %ds)",
                            state.category,
                            episode_id,
                            total_packets,
                            duration_secs,
                        )
                else:
                    await SpamFloodEpisodeRepository.finalize(
                        episode_id=episode_id,
                        started_at=started_at,
                        ended_at=ended_at,
                        total_packets=total_packets,
                        peak_packets_per_window=state.episode_peak_window,
                        baseline_packets_per_window=state.episode_baseline,
                        clusters=final_clusters,
                        category_counts=category_counts,
                        likely_source=likely_source,
                    )
        except Exception:
            logger.exception("Failed to finalize spam flood episode %s", episode_id)
        finally:
            self._reset_episode_state(state)

    def clear_episode_if_deleted(self, episode_id: int) -> None:
        for state in self._category_states.values():
            if state.episode_db_id == episode_id:
                state.reset_episode()

    async def observe_and_maybe_alert(
        self,
        *,
        category: str = "dm",
        path_hex: str | None,
        path_len: int | None,
        path_hash_size: int | None = None,
        observed_at: int | float | None = None,
        source_key: str | None = None,
        source_label: str | None = None,
    ) -> SpamLiveStatus | None:
        """Observe a packet and return enriched status when an alert should fire."""
        current_time = float(observed_at if observed_at is not None else time.time())
        state = self._category_state(category)
        async with self._episode_lifecycle_lock:
            was_active = state.active
            should_broadcast = self.observe_packet(
                category=category,
                path_hex=path_hex,
                path_len=path_len,
                path_hash_size=path_hash_size,
                observed_at=observed_at,
                source_key=source_key,
                source_label=source_label,
            )
            await self._apply_category_lifecycle_transitions(
                state,
                current_time,
                was_active=was_active,
            )
            self._sync_repeater_automation()
            ended_transition = was_active and not state.active

        if not should_broadcast and not ended_transition:
            return None

        if state.active:
            state.last_broadcast_at = current_time

        status = await self._build_aggregate_status_async(current_time)
        if not status.active:
            for cat_state in self._category_states.values():
                cat_state.last_broadcast_at = 0.0
        if state.active:
            self._schedule_episode_progress(state)
        return status


spam_live_tracker = SpamLiveTracker()
