"""Live DM flood detection with RF ingress clustering and gateway stripping."""

from __future__ import annotations

import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.models import SpamFloodCluster, SpamLiveStatus
from app.path_utils import split_path_hex
from app.repository.contacts import ContactRepository

logger = logging.getLogger(__name__)

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

    _history: deque[_PacketRecord] = field(default_factory=deque, init=False)
    _gateway_pubkeys: frozenset[str] = field(default_factory=_effective_gateway_pubkeys, init=False)
    _active: bool = field(default=False, init=False)
    _detected_at: float | None = field(default=None, init=False)
    _hold_until: float | None = field(default=None, init=False)
    _last_broadcast_at: float = field(default=0.0, init=False)
    _last_status: SpamLiveStatus | None = field(default=None, init=False)

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
        self._history.append(
            _PacketRecord(
                timestamp=current_time,
                entry_node=rf_only[0],
                full_rf_path=tuple(rf_only),
            )
        )

        was_active = self._active
        self._sync_active_state(current_time)
        return self._should_broadcast(current_time, was_active)

    def _trim_window(self, current_time: float) -> None:
        cutoff = current_time - self.window_secs
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()

    def _sync_active_state(self, current_time: float) -> None:
        """Apply rolling-window trim and threshold/hold logic."""
        self._trim_window(current_time)
        above_threshold = len(self._history) >= self.packet_threshold
        if above_threshold:
            if self._detected_at is None:
                self._detected_at = current_time
            if self.hold_secs > 0:
                self._hold_until = current_time + self.hold_secs

        if above_threshold or (
            self.hold_secs > 0
            and self._hold_until is not None
            and current_time < self._hold_until
        ):
            self._active = True
            return

        self._active = False
        self._detected_at = None
        self._hold_until = None

    def _should_broadcast(self, current_time: float, was_active: bool) -> bool:
        if not self._active:
            return was_active
        return (
            not was_active
            or current_time - self._last_broadcast_at >= self.broadcast_cooldown_secs
        )

    def _cluster_packets(self) -> list[dict[str, Any]]:
        clusters: dict[str, list[_PacketRecord]] = {}
        for record in self._history:
            clusters.setdefault(record.entry_node, []).append(record)

        min_cluster_size = max(1, int(self.packet_threshold * self.cluster_min_ratio))
        results: list[dict[str, Any]] = []
        for entry_node, records in clusters.items():
            if len(records) < min_cluster_size:
                continue
            path_counts = Counter(record.full_rf_path for record in records)
            dominant_path, _ = path_counts.most_common(1)[0]
            results.append(
                {
                    "entry_hop": entry_node,
                    "packet_count": len(records),
                    "dominant_path_tokens": list(dominant_path),
                    "last_seen": max(record.timestamp for record in records),
                }
            )

        results.sort(key=lambda item: (-item["packet_count"], -item["last_seen"], item["entry_hop"]))
        return results

    async def get_live_status(self) -> SpamLiveStatus:
        current_time = time.time()
        self._sync_active_state(current_time)
        clusters = self._cluster_packets() if self._active and self._history else []
        status = await self._build_status_async(current_time, clusters)
        self._last_status = status
        return status

    async def _build_status_async(
        self, current_time: float, clusters: list[dict[str, Any]]
    ) -> SpamLiveStatus:
        enriched_clusters: list[SpamFloodCluster] = []
        for cluster in clusters:
            geo = await self._lookup_entry_geo(cluster["entry_hop"])
            enriched_clusters.append(
                SpamFloodCluster(
                    entry_hop=cluster["entry_hop"],
                    entry_name=geo.get("name"),
                    entry_public_key=geo.get("public_key"),
                    lat=geo.get("lat"),
                    lon=geo.get("lon"),
                    packet_count=cluster["packet_count"],
                    dominant_route=self._format_route(cluster["dominant_path_tokens"]),
                    hop_tokens=cluster["dominant_path_tokens"],
                    last_seen=int(cluster["last_seen"]),
                )
            )

        return SpamLiveStatus(
            active=self._active,
            window_secs=int(self.window_secs),
            packet_threshold=self.packet_threshold,
            total_packets=len(self._history),
            detected_at=int(self._detected_at) if self._detected_at is not None else None,
            clusters=enriched_clusters,
        )

    @staticmethod
    def _format_route(hop_tokens: list[str]) -> str:
        if not hop_tokens:
            return "Direct"
        return " -> ".join(hop_tokens)

    @staticmethod
    async def _lookup_entry_geo(entry_hop: str) -> dict[str, Any]:
        contact = await ContactRepository.get_by_key_prefix(entry_hop)
        if contact is None:
            return {}
        lat = contact.lat
        lon = contact.lon
        has_coords = lat is not None and lon is not None and not (lat == 0.0 and lon == 0.0)
        return {
            "name": contact.name,
            "public_key": contact.public_key,
            "lat": float(lat) if has_coords else None,
            "lon": float(lon) if has_coords else None,
        }

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
        should_broadcast = self.observe_dm_path(
            path_hex=path_hex,
            path_len=path_len,
            observed_at=observed_at,
        )
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
        return status


spam_live_tracker = SpamLiveTracker()
