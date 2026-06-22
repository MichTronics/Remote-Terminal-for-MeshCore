"""Per-packet-category flood episode state for the live spam tracker."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.models import SpamFloodCluster
from app.services.spam_path_analysis import SourceFilterPlan


@dataclass
class CategoryFloodState:
    """Rolling window + episode state for one spam timeline category (dm, request, etc.)."""

    category: str
    history: deque = field(default_factory=deque)
    active: bool = False
    detected_at: float | None = None
    hold_until: float | None = None
    last_broadcast_at: float = 0.0
    episode_db_id: int | None = None
    episode_total_packets: int = 0
    episode_peak_window: int = 0
    episode_baseline: float | None = None
    episode_started_at: int | None = None
    episode_last_clusters: list[SpamFloodCluster] = field(default_factory=list)
    episode_packet_records: list[Any] = field(default_factory=list)
    episode_peak_clusters: dict[str, SpamFloodCluster] = field(default_factory=dict)
    episode_likely_source: dict[str, Any] | None = None
    episode_source_filter: SourceFilterPlan | None = None
    episode_open: bool = False

    def reset_episode(self) -> None:
        self.episode_open = False
        self.episode_db_id = None
        self.episode_total_packets = 0
        self.episode_peak_window = 0
        self.episode_baseline = None
        self.episode_started_at = None
        self.episode_last_clusters = []
        self.episode_packet_records = []
        self.episode_peak_clusters = {}
        self.episode_likely_source = None
        self.episode_source_filter = None
