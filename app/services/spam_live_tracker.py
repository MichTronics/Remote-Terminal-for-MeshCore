"""Live DM flood detection with RF ingress clustering and gateway stripping."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.models import SpamFloodCluster, SpamLiveStatus
from app.path_utils import split_path_hex, hop_allows_prefix_name_lookup
from app.repository.contacts import ContactRepository
from app.repository.spam_flood_episodes import SpamFloodEpisodeRepository
from app.services.spam_baseline import SpamBaselineService
from app.services.spam_path_analysis import (
    cluster_confidence,
    estimate_origin_geo,
    format_route,
    split_entry_partitioned_clusters,
    split_path_clusters,
)

logger = logging.getLogger(__name__)

_MAX_DISPLAY_ROUTE_HOPS = 10

# Default GWNL / community MQTT bridge gateways (full public keys, lowercase).
_DEFAULT_GATEWAY_PUBKEYS: tuple[str, ...] = (
    "1228d131fa4b13c78a7aefee124e5c7fe51a8555115220d64d1df749b5a7de8c",
    "753c3a558d71c52669cf59d67dd9be41725efd8af113b2f2f36925bde002f5b1",
    "db371c0634d23dd4dc72556366f6cd19578ac91eb85257ea259af8f8bb1d14e0",
    "40b8bacb92538bdaa3d45abb759dd8cfcefaefc5a8f1e77d0f3dc6b7b5452429",
    "82e422e3a9d279d31df8794439dd92803db0658c9d6579cc717bbc0f266070dd",
    "2092ae5d57ff8836f2047a1f74f695084247aac2b85cdc5d4ecf7cb9f2ad3c0e",
    "8fb483861e77a9e8021ed546510ba6deb9e7708dd2330c407f05e085a8f6e31a",
    "d26506b1ed9c8a839bfca3b1ab0afe64a6e30fb47cb0d742d2f81efbee2a17e2",
    "7d5abd286e07f4995dda8a220d044ef2f13949fcc4f3621e4a69bfc20519259a",
    "eb46b319cd2dac975ae178d07d57806fd6b8a4d5301027d76fbd3b3f8df3e3f8",
    "66cca85f210d7af515f8c5760aa222ba1072762446b7fddaef36308a3a12513b",
    "049314d147f018f44633be5b8a4852279295bb5eced77488c451ec83ebc28afa",
)


def _parse_gateway_pubkeys(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset()
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def _effective_gateway_pubkeys() -> frozenset[str]:
    configured = settings.spam_gateway_keys.strip()
    if configured.lower() == "none":
        return frozenset()
    if configured:
        parsed = _parse_gateway_pubkeys(configured)
        return parsed if parsed else frozenset(_DEFAULT_GATEWAY_PUBKEYS)
    return frozenset(_DEFAULT_GATEWAY_PUBKEYS)


@dataclass
class _PacketRecord:
    timestamp: float
    entry_node: str
    full_rf_path: tuple[str, ...]


@dataclass
class SpamLiveTracker:
    """Rolling-window DM flood tracker with multi-ingress clustering."""

    window_secs: float = field(default_factory=lambda: float(settings.spam_live_window_secs))
    packet_threshold: int = field(default_factory=lambda: settings.spam_live_packet_threshold)
    cluster_min_ratio: float = field(default_factory=lambda: settings.spam_live_cluster_min_ratio)
    broadcast_cooldown_secs: float = field(
        default_factory=lambda: float(settings.spam_live_broadcast_cooldown_secs)
    )
    hold_secs: float = field(default_factory=lambda: float(settings.spam_live_hold_secs))
    episode_retention_secs: float = field(
        default_factory=lambda: float(settings.spam_live_episode_retention_secs)
    )

    _history: deque[_PacketRecord] = field(default_factory=deque, init=False)
    _gateway_pubkeys: frozenset[str] = field(default_factory=_effective_gateway_pubkeys, init=False)
    _active: bool = field(default=False, init=False)
    _detected_at: float | None = field(default=None, init=False)
    _hold_until: float | None = field(default=None, init=False)
    _last_broadcast_at: float = field(default=0.0, init=False)
    _last_status: SpamLiveStatus | None = field(default=None, init=False)
    _episode_db_id: int | None = field(default=None, init=False)
    _episode_total_packets: int = field(default=0, init=False)
    _episode_peak_window: int = field(default=0, init=False)
    _episode_baseline: float | None = field(default=None, init=False)
    _episode_started_at: int | None = field(default=None, init=False)
    _episode_last_clusters: list[SpamFloodCluster] = field(default_factory=list, init=False)
    _episode_packet_records: list[_PacketRecord] = field(default_factory=list, init=False)
    _episode_peak_clusters: dict[str, SpamFloodCluster] = field(default_factory=dict, init=False)

    def reload_gateway_pubkeys(self) -> None:
        self._gateway_pubkeys = _effective_gateway_pubkeys()

    def _is_gateway_hop(self, hop: str) -> bool:
        if not self._gateway_pubkeys:
            return False
        hop_lower = hop.lower()
        return any(gateway.startswith(hop_lower) for gateway in self._gateway_pubkeys)

    @staticmethod
    def _rf_path_tokens(path_hex: str, path_len: int) -> list[str]:
        if not path_hex or path_len <= 0:
            return []
        return [token.upper() for token in split_path_hex(path_hex.upper(), path_len)]

    def _strip_to_rf_path(self, hop_tokens: list[str]) -> list[str]:
        rf_only: list[str] = []
        for hop in hop_tokens:
            if self._is_gateway_hop(hop):
                break
            rf_only.append(hop)
        return rf_only

    def observe_dm_path(
        self,
        *,
        path_hex: str | None,
        path_len: int | None,
        observed_at: int | float | None = None,
    ) -> bool:
        """Record a direct-message path observation; return True when state may have changed."""
        tokens = self._rf_path_tokens(path_hex or "", int(path_len or 0))
        rf_only = self._strip_to_rf_path(tokens)
        if not rf_only:
            return False

        current_time = float(observed_at if observed_at is not None else time.time())
        record = _PacketRecord(
            timestamp=current_time,
            entry_node=rf_only[0],
            full_rf_path=tuple(rf_only),
        )
        self._history.append(record)
        if self._detected_at is not None or self._episode_db_id is not None:
            self._episode_packet_records.append(record)

        was_active = self._active
        self._sync_active_state(current_time)
        return self._should_broadcast(current_time, was_active)

    def _episode_retention_horizon(self) -> float:
        configured = self.episode_retention_secs
        if configured > 0:
            return configured
        return max(self.hold_secs, self.window_secs)

    def _retention_cutoff(self, current_time: float) -> float:
        if self._detected_at is not None:
            horizon = self._episode_retention_horizon()
            return max(self._detected_at, current_time - horizon)
        return current_time - self.window_secs

    def _trim_window(self, current_time: float) -> None:
        cutoff = self._retention_cutoff(current_time)
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()

    def _trigger_window_count(self, current_time: float) -> int:
        cutoff = current_time - self.window_secs
        return sum(1 for record in self._history if record.timestamp >= cutoff)

    def _sync_active_state(self, current_time: float) -> None:
        """Apply retention trim and threshold/hold logic."""
        above_threshold = self._trigger_window_count(current_time) >= self.packet_threshold
        if above_threshold:
            if self._detected_at is None:
                self._detected_at = current_time
            if self.hold_secs > 0:
                self._hold_until = current_time + self.hold_secs

        in_hold = (
            self.hold_secs > 0
            and self._hold_until is not None
            and current_time < self._hold_until
        )
        self._active = above_threshold or in_hold
        self._trim_window(current_time)

        if not self._active:
            self._detected_at = None
            self._hold_until = None
            self._trim_window(current_time)

    def _should_broadcast(self, current_time: float, was_active: bool) -> bool:
        if not self._active:
            return was_active
        return (
            not was_active
            or current_time - self._last_broadcast_at >= self.broadcast_cooldown_secs
        )

    def _min_cluster_size(self) -> int:
        return max(1, int(self.packet_threshold * self.cluster_min_ratio))

    def _max_report_clusters(self) -> int | None:
        limit = settings.spam_live_max_report_clusters
        if limit <= 0:
            return None
        return limit

    def _apply_report_limit(self, clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        limit = self._max_report_clusters()
        if limit is None:
            return clusters
        return clusters[:limit]

    def _apply_report_limit_models(self, clusters: list[SpamFloodCluster]) -> list[SpamFloodCluster]:
        limit = self._max_report_clusters()
        if limit is None:
            return clusters
        return clusters[:limit]

    @staticmethod
    def _cluster_identity_key(cluster: SpamFloodCluster) -> str:
        refined = cluster.refined_hop_tokens or cluster.hop_tokens
        suffix = "/".join(refined) if refined else cluster.entry_hop
        return f"{cluster.entry_hop}:{suffix}"

    def _update_episode_peak_clusters(self, clusters: list[SpamFloodCluster]) -> None:
        for cluster in clusters:
            key = self._cluster_identity_key(cluster)
            existing = self._episode_peak_clusters.get(key)
            if existing is None:
                self._episode_peak_clusters[key] = cluster
                continue
            self._episode_peak_clusters[key] = existing.model_copy(
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

    def _episode_peak_clusters_display(self) -> list[SpamFloodCluster]:
        clusters = self._sorted_peak_clusters()
        return self._apply_report_limit_models(clusters)

    def _all_episode_peak_clusters(self) -> list[SpamFloodCluster]:
        return self._sorted_peak_clusters()

    def _sorted_peak_clusters(self) -> list[SpamFloodCluster]:
        clusters = list(self._episode_peak_clusters.values())
        clusters.sort(
            key=lambda cluster: (
                -cluster.packet_count,
                -cluster.traffic_share,
                -cluster.last_seen,
                cluster.entry_hop,
            )
        )
        return clusters

    def _clustering_records(self) -> list[_PacketRecord]:
        if self._episode_packet_records:
            return list(self._episode_packet_records)
        return list(self._history)

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
        max_clusters = self._max_report_clusters() or len(records)
        partitioned_clusters = split_entry_partitioned_clusters(
            records,
            min_cluster_size=min_cluster_size,
            min_share=self.cluster_min_ratio,
            get_path=lambda record: record.full_rf_path,
            max_clusters=max_clusters,
        )
        return self._build_cluster_results(partitioned_clusters, cluster_mode="partitioned")

    def _cluster_packets_narrowed(self) -> list[dict[str, Any]]:
        return self._cluster_packets_narrowed_from(self._clustering_records())

    def _fallback_entry_clusters_from(self, records: list[_PacketRecord]) -> list[dict[str, Any]]:
        """Best-effort ingress hops when traffic is high but too dispersed to narrow."""
        if not records:
            return []

        min_cluster_size = self._min_cluster_size()
        by_entry: dict[str, list[_PacketRecord]] = {}
        for record in records:
            by_entry.setdefault(record.entry_node, []).append(record)

        total = len(records)
        results: list[dict[str, Any]] = []
        for entry_hop, matched_records in sorted(by_entry.items(), key=lambda item: -len(item[1])):
            if len(matched_records) < min_cluster_size:
                continue
            path_counts = Counter(record.full_rf_path for record in matched_records)
            dominant_path, _ = path_counts.most_common(1)[0]
            results.append(
                {
                    "entry_hop": entry_hop,
                    "packet_count": len(matched_records),
                    "dominant_path_tokens": list(dominant_path),
                    "longest_path_tokens": self._longest_path_tokens(matched_records),
                    "refined_hop_tokens": [entry_hop],
                    "traffic_share": len(matched_records) / total if total else 0.0,
                    "concentration": 1.0,
                    "narrowing_depth": 1,
                    "last_seen": max(record.timestamp for record in matched_records),
                    "cluster_mode": "entry_fallback",
                }
            )
        return self._apply_report_limit(results)

    def _fallback_entry_clusters(self) -> list[dict[str, Any]]:
        return self._fallback_entry_clusters_from(self._clustering_records())

    def _cluster_packets_from(self, records: list[_PacketRecord]) -> list[dict[str, Any]]:
        narrowed = self._cluster_packets_narrowed_from(records)
        if narrowed:
            return narrowed
        partitioned = self._cluster_packets_partitioned_from(records)
        if partitioned:
            return partitioned
        return self._fallback_entry_clusters_from(records)

    def _cluster_packets(self) -> list[dict[str, Any]]:
        return self._cluster_packets_from(self._clustering_records())

    async def get_live_status(self) -> SpamLiveStatus:
        current_time = time.time()
        was_active = self._active
        self._sync_active_state(current_time)
        if was_active and not self._active:
            await self._end_episode(current_time)
        clusters = self._cluster_packets() if self._active and self._clustering_records() else []
        status = await self._build_status_async(current_time, clusters)
        self._last_status = status
        return status

    async def _enrich_clusters(self, clusters: list[dict[str, Any]]) -> list[SpamFloodCluster]:
        enriched_clusters: list[SpamFloodCluster] = []
        for cluster in clusters:
            refined_tokens = cluster.get("refined_hop_tokens") or cluster["dominant_path_tokens"]
            longest_tokens = cluster.get("longest_path_tokens") or cluster["dominant_path_tokens"]
            lookup_tokens = list(
                dict.fromkeys([*refined_tokens, *longest_tokens[:_MAX_DISPLAY_ROUTE_HOPS]])
            )
            hop_geos = await self._lookup_prefix_geos(lookup_tokens)
            entry_geo = hop_geos.get(cluster["entry_hop"], {})
            origin = estimate_origin_geo(refined_tokens, hop_geos)
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
                    last_seen=int(cluster["last_seen"]),
                    cluster_mode=cluster.get("cluster_mode"),
                )
            )
        return enriched_clusters

    async def _build_status_async(
        self, current_time: float, clusters: list[dict[str, Any]]
    ) -> SpamLiveStatus:
        enriched_clusters = await self._enrich_clusters(clusters)
        clusters_stale = False
        if enriched_clusters:
            self._update_episode_peak_clusters(enriched_clusters)
            self._episode_last_clusters = list(enriched_clusters)
            enriched_clusters = self._episode_peak_clusters_display()
        elif self._active and self._episode_peak_clusters:
            enriched_clusters = self._episode_peak_clusters_display()
            clusters_stale = True
        elif self._active and self._episode_last_clusters:
            enriched_clusters = [
                cluster.model_copy(update={"cluster_mode": cluster.cluster_mode or "sticky"})
                for cluster in self._episode_last_clusters
            ]
            clusters_stale = True
        peak_window = self._trigger_window_count(current_time)
        if self._episode_db_id is not None:
            self._episode_peak_window = max(self._episode_peak_window, peak_window)

        anomaly_ratio = None
        if self._episode_baseline and self._episode_baseline > 0:
            anomaly_ratio = round(
                max(self._episode_peak_window, peak_window) / self._episode_baseline,
                2,
            )

        return SpamLiveStatus(
            active=self._active,
            window_secs=int(self.window_secs),
            packet_threshold=self.packet_threshold,
            total_packets=peak_window,
            episode_packets=len(self._episode_packet_records) or len(self._history),
            episode_window_secs=int(self._episode_retention_horizon()),
            detected_at=int(self._detected_at) if self._detected_at is not None else None,
            baseline_packets_per_window=(
                round(self._episode_baseline, 2) if self._episode_baseline is not None else None
            ),
            anomaly_ratio=anomaly_ratio,
            episode_id=self._episode_db_id,
            cluster_min_share=self.cluster_min_ratio,
            clusters_stale=clusters_stale,
            clusters=enriched_clusters,
        )

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

    async def _start_episode(self, current_time: float) -> None:
        started_at = int(self._detected_at or current_time)
        try:
            baseline = await SpamBaselineService.get_packets_per_window(
                window_secs=int(self.window_secs),
                until=started_at,
            )
            episode_id = await SpamFloodEpisodeRepository.create_started(
                started_at=started_at,
                baseline_packets_per_window=round(baseline, 4),
                packet_threshold=self.packet_threshold,
                window_secs=int(self.window_secs),
            )
        except Exception:
            logger.exception("Failed to start spam flood episode log")
            return

        self._episode_db_id = episode_id
        self._episode_started_at = started_at
        self._episode_baseline = baseline
        self._episode_total_packets = 1
        self._episode_peak_window = self._trigger_window_count(current_time)
        self._episode_last_clusters = []
        self._episode_peak_clusters = {}

    def _schedule_episode_progress(self) -> None:
        if self._episode_db_id is None:
            return
        asyncio.create_task(self._persist_episode_progress())

    async def _persist_episode_progress(self) -> None:
        if self._episode_db_id is None:
            return
        cluster_raw = self._cluster_packets_from(self._episode_packet_records)
        if cluster_raw:
            enriched = await self._enrich_clusters(cluster_raw)
            self._update_episode_peak_clusters(enriched)
            self._episode_last_clusters = self._all_episode_peak_clusters()
        try:
            await SpamFloodEpisodeRepository.update_progress(
                episode_id=self._episode_db_id,
                total_packets=self._episode_total_packets,
                peak_packets_per_window=self._episode_peak_window,
                clusters=self._episode_last_clusters,
            )
        except Exception:
            logger.exception("Failed to update spam flood episode %s", self._episode_db_id)

    async def _end_episode(self, current_time: float) -> None:
        if self._episode_db_id is None:
            return
        episode_id = self._episode_db_id
        started_at = self._episode_started_at or int(current_time)
        cluster_raw = self._cluster_packets_from(self._episode_packet_records)
        if cluster_raw:
            final_clusters = await self._enrich_clusters(cluster_raw)
            self._update_episode_peak_clusters(final_clusters)
            final_clusters = self._all_episode_peak_clusters()
        elif self._episode_peak_clusters:
            final_clusters = self._all_episode_peak_clusters()
        elif self._episode_last_clusters:
            final_clusters = self._apply_report_limit_models(self._episode_last_clusters)
        else:
            final_clusters = []
        try:
            await SpamFloodEpisodeRepository.finalize(
                episode_id=episode_id,
                started_at=started_at,
                ended_at=int(current_time),
                total_packets=self._episode_total_packets,
                peak_packets_per_window=self._episode_peak_window,
                baseline_packets_per_window=self._episode_baseline,
                clusters=final_clusters,
            )
        except Exception:
            logger.exception("Failed to finalize spam flood episode %s", episode_id)
        finally:
            self._episode_db_id = None
            self._episode_total_packets = 0
            self._episode_peak_window = 0
            self._episode_baseline = None
            self._episode_started_at = None
            self._episode_last_clusters = []
            self._episode_packet_records = []
            self._episode_peak_clusters = {}

    async def observe_and_maybe_alert(
        self,
        *,
        path_hex: str | None,
        path_len: int | None,
        observed_at: int | float | None = None,
    ) -> SpamLiveStatus | None:
        """Observe a DM path and return enriched status when an alert should fire."""
        current_time = float(observed_at if observed_at is not None else time.time())
        was_active = self._active
        had_db_episode = self._episode_db_id is not None
        should_broadcast = self.observe_dm_path(
            path_hex=path_hex,
            path_len=path_len,
            observed_at=observed_at,
        )

        if self._active and self._episode_db_id is None:
            await self._start_episode(current_time)
        elif self._active and had_db_episode:
            self._episode_total_packets += 1
            self._episode_peak_window = max(
                self._episode_peak_window,
                self._trigger_window_count(current_time),
            )

        if was_active and not self._active:
            await self._end_episode(current_time)

        if not should_broadcast and not (was_active and not self._active):
            return None

        if not self._active:
            status = await self._build_status_async(current_time, clusters=[])
            self._last_status = status
            self._last_broadcast_at = 0.0
            return status

        self._last_broadcast_at = current_time
        clusters = self._cluster_packets()
        status = await self._build_status_async(current_time, clusters)
        self._last_status = status
        self._schedule_episode_progress()
        return status


spam_live_tracker = SpamLiveTracker()
