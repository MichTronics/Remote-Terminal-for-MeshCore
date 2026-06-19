from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.path_utils import normalize_contact_route, normalize_route_override

# Valid MeshCore contact types: 0=unknown, 1=client, 2=repeater, 3=room, 4=sensor.
# Corrupted radio data can produce values outside this range.
_VALID_CONTACT_TYPES = frozenset({0, 1, 2, 3, 4})


class ContactRoute(BaseModel):
    """A normalized contact route."""

    path: str = Field(description="Hex-encoded path bytes (empty string for direct/flood)")
    path_len: int = Field(description="Hop count (-1=flood, 0=direct, >0=explicit route)")
    path_hash_mode: int = Field(
        description="Path hash mode (-1=flood, 0=1-byte, 1=2-byte, 2=3-byte hop identifiers)"
    )


class ContactUpsert(BaseModel):
    """Typed write contract for contacts persisted to SQLite."""

    public_key: str = Field(description="Public key (64-char hex)")
    name: str | None = None
    type: int = 0
    flags: int = 0
    direct_path: str | None = None
    direct_path_len: int | None = None
    direct_path_hash_mode: int | None = None
    direct_path_updated_at: int | None = None
    route_override_path: str | None = None
    route_override_len: int | None = None
    route_override_hash_mode: int | None = None
    last_advert: int | None = None
    lat: float | None = None
    lon: float | None = None
    last_seen: int | None = None
    on_radio: bool | None = None
    last_contacted: int | None = None
    first_seen: int | None = None
    is_tracker: bool | None = None
    tracker_name: str | None = None
    tracker_heading: float | None = None

    @classmethod
    def from_contact(cls, contact: Contact, **changes) -> ContactUpsert:
        return cls.model_validate(
            {
                **contact.model_dump(exclude={"last_read_at"}),
                **changes,
            }
        )

    @classmethod
    def from_radio_dict(
        cls, public_key: str, radio_data: dict, on_radio: bool = False
    ) -> ContactUpsert:
        """Convert radio contact data to the contact-row write shape."""
        direct_path, direct_path_len, direct_path_hash_mode = normalize_contact_route(
            radio_data.get("out_path"),
            radio_data.get("out_path_len", -1),
            radio_data.get(
                "out_path_hash_mode",
                -1 if radio_data.get("out_path_len", -1) == -1 else 0,
            ),
        )
        # Clamp invalid contact types to 0 (unknown) — corrupted radio data
        # can produce values like 111 or 240 that break downstream branching.
        raw_type = radio_data.get("type", 0)
        contact_type = raw_type if raw_type in _VALID_CONTACT_TYPES else 0

        # Null out impossible coordinates — the contact is still ingested,
        # but garbage lat/lon (e.g. 1953.7) is discarded rather than stored.
        lat = radio_data.get("adv_lat")
        lon = radio_data.get("adv_lon")
        if lat is not None and not (-90 <= lat <= 90):
            lat = None
        if lon is not None and not (-180 <= lon <= 180):
            lon = None

        return cls(
            public_key=public_key,
            name=radio_data.get("adv_name"),
            type=contact_type,
            flags=radio_data.get("flags", 0),
            direct_path=direct_path,
            direct_path_len=direct_path_len,
            direct_path_hash_mode=direct_path_hash_mode,
            lat=lat,
            lon=lon,
            last_advert=radio_data.get("last_advert"),
            on_radio=on_radio,
        )


class Contact(BaseModel):
    public_key: str = Field(description="Public key (64-char hex)")
    name: str | None = None
    type: int = 0  # 0=unknown, 1=client, 2=repeater, 3=room, 4=sensor
    flags: int = 0
    direct_path: str | None = None
    direct_path_len: int = -1
    direct_path_hash_mode: int = -1
    direct_path_updated_at: int | None = None
    route_override_path: str | None = None
    route_override_len: int | None = None
    route_override_hash_mode: int | None = None
    last_advert: int | None = None
    lat: float | None = None
    lon: float | None = None
    last_seen: int | None = None
    on_radio: bool = False
    favorite: bool = False
    last_contacted: int | None = None  # Last time we sent/received a message
    last_read_at: int | None = None  # Server-side read state tracking
    first_seen: int | None = None
    is_tracker: bool = False  # True if this contact sends LOCATION packets
    tracker_name: str | None = None  # Name from LOCATION packet
    tracker_heading: float | None = None  # Last known heading in degrees (LOCATION packets)
    effective_route: ContactRoute | None = None
    effective_route_source: Literal["override", "direct", "flood"] = "flood"
    direct_route: ContactRoute | None = None
    route_override: ContactRoute | None = None

    def model_post_init(self, __context) -> None:
        direct_path, direct_path_len, direct_path_hash_mode = normalize_contact_route(
            self.direct_path,
            self.direct_path_len,
            self.direct_path_hash_mode,
        )
        self.direct_path = direct_path or None
        self.direct_path_len = direct_path_len
        self.direct_path_hash_mode = direct_path_hash_mode

        route_override_path, route_override_len, route_override_hash_mode = (
            normalize_route_override(
                self.route_override_path,
                self.route_override_len,
                self.route_override_hash_mode,
            )
        )
        self.route_override_path = route_override_path or None
        self.route_override_len = route_override_len
        self.route_override_hash_mode = route_override_hash_mode
        if (
            route_override_path is not None
            and route_override_len is not None
            and route_override_hash_mode is not None
        ):
            self.route_override = ContactRoute(
                path=route_override_path,
                path_len=route_override_len,
                path_hash_mode=route_override_hash_mode,
            )
        else:
            self.route_override = None

        if direct_path_len >= 0:
            self.direct_route = ContactRoute(
                path=direct_path,
                path_len=direct_path_len,
                path_hash_mode=direct_path_hash_mode,
            )
        else:
            self.direct_route = None

        path, path_len, path_hash_mode = self.effective_route_tuple()
        if self.has_route_override():
            self.effective_route_source = "override"
        elif self.direct_route is not None:
            self.effective_route_source = "direct"
        else:
            self.effective_route_source = "flood"
        self.effective_route = ContactRoute(
            path=path,
            path_len=path_len,
            path_hash_mode=path_hash_mode,
        )

    def has_route_override(self) -> bool:
        return self.route_override_len is not None

    def effective_route_tuple(self) -> tuple[str, int, int]:
        if self.has_route_override():
            return normalize_contact_route(
                self.route_override_path,
                self.route_override_len,
                self.route_override_hash_mode,
            )
        if self.direct_path_len >= 0:
            return normalize_contact_route(
                self.direct_path,
                self.direct_path_len,
                self.direct_path_hash_mode,
            )
        return "", -1, -1

    def to_radio_dict(self) -> dict:
        """Convert to the dict format expected by meshcore radio commands.

        The radio API uses different field names (adv_name, out_path, etc.)
        than our database schema (name, direct_path, etc.).
        """
        effective_path, effective_path_len, effective_path_hash_mode = self.effective_route_tuple()
        return {
            "public_key": self.public_key,
            "adv_name": self.name or "",
            "type": self.type,
            "flags": self.flags,
            "out_path": effective_path,
            "out_path_len": effective_path_len,
            "out_path_hash_mode": effective_path_hash_mode,
            "adv_lat": self.lat if self.lat is not None else 0.0,
            "adv_lon": self.lon if self.lon is not None else 0.0,
            "last_advert": self.last_advert if self.last_advert is not None else 0,
        }

    def to_upsert(self, **changes) -> ContactUpsert:
        """Convert the stored contact to the repository's write contract."""
        return ContactUpsert.from_contact(self, **changes)


class CreateContactRequest(BaseModel):
    """Request to create a new contact."""

    public_key: str = Field(min_length=64, max_length=64, description="Public key (64-char hex)")
    name: str | None = Field(default=None, description="Display name for the contact")
    type: int = Field(
        default=0, ge=0, le=3, description="Contact type (0=unknown, 1=client, 2=repeater, 3=room)"
    )
    try_historical: bool = Field(
        default=False,
        description="Attempt to decrypt historical DM packets for this contact",
    )


class ContactRoutingOverrideRequest(BaseModel):
    """Request to set, force, or clear a contact routing override."""

    route: str = Field(
        description=(
            "Blank clears the override, "
            '"-1" forces flood, "0" forces direct, and explicit routes are '
            "comma-separated 1/2/3-byte hop hex values"
        )
    )


# Contact type constants
CONTACT_TYPE_REPEATER = 2
CONTACT_TYPE_ROOM = 3


class ContactAdvertPath(BaseModel):
    """A unique advert path observed for a contact."""

    path: str = Field(description="Hex-encoded routing path (empty string for direct)")
    path_len: int = Field(description="Number of hops in the path")
    next_hop: str | None = Field(
        default=None,
        description="First hop toward us as a full hop identifier, or null for direct",
    )
    first_seen: int = Field(description="Unix timestamp of first observation")
    last_seen: int = Field(description="Unix timestamp of most recent observation")
    heard_count: int = Field(description="Number of times this unique path was heard")


class ContactAdvertPathSummary(BaseModel):
    """Recent unique advertisement paths for a single contact."""

    public_key: str = Field(description="Contact public key (64-char hex)")
    paths: list[ContactAdvertPath] = Field(
        default_factory=list, description="Most recent unique advert paths"
    )


class ContactNameHistory(BaseModel):
    """A historical name used by a contact."""

    name: str
    first_seen: int
    last_seen: int


class ContactActiveRoom(BaseModel):
    """A channel where a contact has been active."""

    channel_key: str
    channel_name: str
    message_count: int


class NearestRepeater(BaseModel):
    """A repeater that has relayed a contact's advertisements."""

    public_key: str
    name: str | None = None
    path_len: int
    last_seen: int
    heard_count: int


class ContactAnalyticsHourlyBucket(BaseModel):
    """A single hourly activity bucket for contact analytics."""

    bucket_start: int = Field(description="Unix timestamp for the start of the hour bucket")
    last_24h_count: int = 0
    last_week_average: float = 0
    all_time_average: float = 0


class ContactAnalyticsWeeklyBucket(BaseModel):
    """A single weekly activity bucket for contact analytics."""

    bucket_start: int = Field(description="Unix timestamp for the start of the 7-day bucket")
    message_count: int = 0


class ContactAnalytics(BaseModel):
    """Unified contact analytics payload for keyed and name-only lookups."""

    lookup_type: Literal["contact", "name"]
    name: str
    contact: Contact | None = None
    name_first_seen_at: int | None = None
    name_history: list[ContactNameHistory] = Field(default_factory=list)
    dm_message_count: int = 0
    channel_message_count: int = 0
    includes_direct_messages: bool = False
    most_active_rooms: list[ContactActiveRoom] = Field(default_factory=list)
    advert_paths: list[ContactAdvertPath] = Field(default_factory=list)
    advert_frequency: float | None = Field(
        default=None,
        description="Advert observations per hour (includes multi-path arrivals of same advert)",
    )
    nearest_repeaters: list[NearestRepeater] = Field(default_factory=list)
    hourly_activity: list[ContactAnalyticsHourlyBucket] = Field(default_factory=list)
    weekly_activity: list[ContactAnalyticsWeeklyBucket] = Field(default_factory=list)


class LocationHistory(BaseModel):
    """A timestamped location update from a tracker."""

    id: int
    contact_public_key: str = Field(description="Public key (64-char hex)")
    lat: float
    lon: float
    altitude: int | None = None
    speed: float | None = None
    heading: float | None = None
    satellites: int | None = None
    battery: int | None = None
    timestamp: int = Field(description="Unix timestamp from LOCATION packet")
    received_at: int = Field(description="Server receive timestamp")


class Channel(BaseModel):
    key: str = Field(description="Channel key (32-char hex)")
    name: str
    is_hashtag: bool = False
    on_radio: bool = False
    flood_scope_override: str | None = Field(
        default=None,
        description="Per-channel outbound flood scope override (null = use global app setting)",
    )
    path_hash_mode_override: int | None = Field(
        default=None,
        description="Per-channel path hash mode override (0=1-byte, 1=2-byte, 2=3-byte, null = use radio default)",
    )
    last_read_at: int | None = None  # Server-side read state tracking
    favorite: bool = False
    muted: bool = False


class ChannelMessageCounts(BaseModel):
    """Time-windowed message counts for a channel."""

    last_1h: int = 0
    last_24h: int = 0
    last_48h: int = 0
    last_7d: int = 0
    all_time: int = 0


class ChannelTopSender(BaseModel):
    """A top sender in a channel over the last 24 hours."""

    sender_name: str
    sender_key: str | None = None
    message_count: int


class PathHashWidthStats(BaseModel):
    """Hop byte width distribution for parsed raw packets."""

    total_packets: int = 0
    single_byte: int = 0
    double_byte: int = 0
    triple_byte: int = 0
    single_byte_pct: float = 0.0
    double_byte_pct: float = 0.0
    triple_byte_pct: float = 0.0


class Region(BaseModel):
    """MeshCore transport region configuration."""

    id: int
    name: str = Field(description="Region identifier (e.g., 'us', 'nl', 'bayarea', 'nl-fr')")
    key: str | None = Field(
        default=None,
        description="Hex-encoded 16-byte region key (NULL for public/derived regions)",
    )
    is_public: bool = Field(
        default=True,
        description="True if region key is derived from name, False for custom key",
    )
    created_at: int


class RegionCreate(BaseModel):
    """Request payload for creating a new region."""

    name: str = Field(
        min_length=1,
        max_length=50,
        description="Region identifier (e.g., 'us', 'nl-fr', 'bayarea')",
    )
    key: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{32}$",
        description="Hex-encoded 16-byte region key (omit for public/derived regions)",
    )
    is_public: bool = Field(
        default=True,
        description="True to derive key from name, False to use explicit key",
    )


class RegionUsageItem(BaseModel):
    """A single region usage count."""

    region: str  # Region name (e.g., "us", "nl") or hex code if unidentified (e.g., "FFFF")
    count: int


class RegionUsageStats(BaseModel):
    """Primary region usage distribution for raw packets with transport codes."""

    total_packets: int = 0
    regions: list[RegionUsageItem] = []


class ChannelDetail(BaseModel):
    """Comprehensive channel profile data."""

    channel: Channel
    message_counts: ChannelMessageCounts = Field(default_factory=ChannelMessageCounts)
    first_message_at: int | None = None
    unique_sender_count: int = 0
    top_senders_24h: list[ChannelTopSender] = Field(default_factory=list)
    path_hash_width_24h: PathHashWidthStats = Field(default_factory=PathHashWidthStats)


class MessagePath(BaseModel):
    """A single path that a message took to reach us."""

    path: str = Field(description="Hex-encoded routing path")
    received_at: int = Field(description="Unix timestamp when this path was received")
    path_len: int | None = Field(
        default=None,
        description="Hop count. None = legacy (infer as len(path)//2, i.e. 1-byte hops)",
    )
    rssi: int | None = Field(default=None, description="Last-hop RSSI in dBm")
    snr: float | None = Field(default=None, description="Last-hop SNR in dB")


class Message(BaseModel):
    id: int
    type: str = Field(description="PRIV or CHAN")
    conversation_key: str = Field(description="User pubkey for PRIV, channel key for CHAN")
    text: str
    sender_timestamp: int | None = None
    received_at: int
    paths: list[MessagePath] | None = Field(
        default=None, description="List of routing paths this message arrived via"
    )
    txt_type: int = 0
    signature: str | None = None
    sender_key: str | None = None
    outgoing: bool = False
    acked: int = 0
    sender_name: str | None = None
    channel_name: str | None = None
    packet_id: int | None = Field(
        default=None,
        description="Representative raw packet row ID when archival raw bytes exist",
    )


class MessagesAroundResponse(BaseModel):
    messages: list[Message]
    has_older: bool
    has_newer: bool


class SpamRouteStat(BaseModel):
    """Aggregated route usage for direct-message traffic."""

    path: str = Field(description="Hex-encoded path bytes; empty string means direct")
    path_len: int = Field(description="Hop count for this observed route")
    hop_count: int = Field(description="Alias for path_len for frontend display")
    hop_tokens: list[str] = Field(description="Path split into hop identifiers")
    route: str = Field(description="Human-readable route label")
    observation_count: int = Field(description="Number of path observations")
    message_count: int = Field(description="Number of distinct messages seen on this route")
    conversation_count: int = Field(description="Number of DM conversations using this route")
    first_seen: int | None = Field(description="First route observation timestamp")
    last_seen: int | None = Field(description="Most recent route observation timestamp")
    avg_rssi: float | None = Field(default=None, description="Average RSSI in dBm")
    avg_snr: float | None = Field(default=None, description="Average SNR in dB")


class SpamRepeaterStat(BaseModel):
    """Aggregated hop/repeater identifier usage for direct-message traffic."""

    hop: str = Field(description="Observed hop/repeater identifier")
    observation_count: int = Field(description="Number of DM path observations containing this hop")
    route_count: int = Field(description="Number of distinct routes containing this hop")
    message_count: int = Field(description="Number of distinct messages containing this hop")
    conversation_count: int = Field(description="Number of DM conversations containing this hop")
    source_side_count: int = Field(
        description="Times this hop was first in the stored path; often closest to the sender"
    )
    radio_side_count: int = Field(
        description="Times this hop was last in the stored path; often closest to this radio"
    )
    middle_count: int = Field(description="Times this hop appeared between the path ends")
    suspect_score: float = Field(
        default=0.0,
        description="0-1 score combining path position, source-side ratio, and prefix concentration",
    )
    narrowed_prefix: str = Field(
        default="",
        description="Most common shared path prefix ending at this hop",
    )
    contact_name: str | None = Field(default=None, description="Resolved repeater name when known")
    lat: float | None = Field(default=None, description="Resolved latitude when available")
    lon: float | None = Field(default=None, description="Resolved longitude when available")
    first_seen: int | None = Field(description="First route observation timestamp")
    last_seen: int | None = Field(description="Most recent route observation timestamp")
    avg_rssi: float | None = Field(default=None, description="Average RSSI in dBm")
    avg_snr: float | None = Field(default=None, description="Average SNR in dB")


class SpamRouteStatsResponse(BaseModel):
    """Route usage summary for direct-message traffic."""

    window_hours: int | None = Field(description="Lookback window in hours; null means all time")
    total_observations: int
    total_messages: int
    repeaters: list[SpamRepeaterStat]
    routes: list[SpamRouteStat]


class SpamFloodCluster(BaseModel):
    """A live clustered ingress hotspot for coordinated DM floods."""

    entry_hop: str = Field(description="First RF hop identifier for this cluster")
    entry_name: str | None = Field(default=None, description="Resolved contact name when known")
    entry_public_key: str | None = Field(
        default=None, description="Resolved contact public key when prefix is unique"
    )
    lat: float | None = Field(default=None, description="Resolved latitude when available")
    lon: float | None = Field(default=None, description="Resolved longitude when available")
    packet_count: int = Field(description="Packets in this cluster during the live window")
    dominant_route: str = Field(description="Most common RF-only route label for this cluster")
    hop_tokens: list[str] = Field(description="Hop tokens for the dominant RF-only route")
    longest_route_tokens: list[str] = Field(
        default_factory=list,
        description="Longest observed RF path in this cluster, capped at 10 hops",
    )
    hop_names_by_token: dict[str, str] = Field(
        default_factory=dict,
        description="Resolved contact names keyed by hop token along the display route",
    )
    refined_route: str = Field(
        default="",
        description="Progressively narrowed shared-prefix route for this cluster",
    )
    refined_hop_tokens: list[str] = Field(
        default_factory=list,
        description="Hop tokens for the narrowed hotspot prefix",
    )
    traffic_share: float = Field(
        default=0.0,
        description="Fraction of episode packets sharing the refined prefix",
    )
    concentration: float = Field(
        default=1.0,
        description="How much traffic concentrates when deepening from parent prefix to refined prefix",
    )
    narrowing_depth: int = Field(
        default=1,
        description="Number of hops in the refined hotspot prefix",
    )
    confidence: int = Field(
        default=0,
        description="0-100 composite confidence for the narrowed hotspot estimate",
    )
    origin_hop: str | None = Field(
        default=None,
        description="Source-nearest hop with resolved coordinates in the refined prefix",
    )
    origin_name: str | None = Field(default=None, description="Resolved name for origin_hop when known")
    origin_public_key: str | None = Field(
        default=None, description="Resolved public key for origin_hop when known"
    )
    origin_lat: float | None = Field(
        default=None, description="Estimated spam-origin latitude from narrowed prefix geo chain"
    )
    origin_lon: float | None = Field(
        default=None, description="Estimated spam-origin longitude from narrowed prefix geo chain"
    )
    last_seen: int = Field(description="Unix timestamp of the newest packet in this cluster")
    cluster_mode: str | None = Field(
        default=None,
        description="narrowed, partitioned, entry_fallback, or sticky when cluster confidence is degraded",
    )


class SpamLiveStatus(BaseModel):
    """Live rolling-window flood detection status."""

    active: bool = Field(
        description="True while flood volume exceeds threshold or within the post-flood hold period"
    )
    window_secs: int = Field(description="Trigger window size in seconds (rate threshold)")
    packet_threshold: int = Field(description="Packet count that triggers an active flood alert")
    total_packets: int = Field(
        description="Packet count inside the trigger window (used for threshold comparison)"
    )
    episode_packets: int = Field(
        default=0,
        description="Packets retained for the current flood episode (cluster analysis)",
    )
    episode_window_secs: int = Field(
        default=0,
        description="Retention horizon in seconds for episode packet history while alarm is active",
    )
    detected_at: int | None = Field(
        default=None, description="Unix timestamp when the current flood episode started"
    )
    baseline_packets_per_window: float | None = Field(
        default=None,
        description="Historical average DM path observations per trigger window (14-day baseline)",
    )
    anomaly_ratio: float | None = Field(
        default=None,
        description="Peak window packet count divided by baseline_packets_per_window",
    )
    episode_id: int | None = Field(
        default=None,
        description="Database ID for the current or most recent persisted flood episode",
    )
    cluster_min_share: float = Field(
        default=0.15,
        description="Minimum traffic share required for a narrowed ingress cluster",
    )
    clusters_stale: bool = Field(
        default=False,
        description="True when displayed clusters are the last known snapshot, not a fresh match",
    )
    clusters: list[SpamFloodCluster] = Field(default_factory=list)


class SpamFloodEpisode(BaseModel):
    """Persisted DM flood episode for post-hoc review."""

    id: int
    started_at: int
    ended_at: int | None = None
    duration_secs: int | None = None
    total_packets: int = 0
    peak_packets_per_window: int = 0
    baseline_packets_per_window: float | None = None
    anomaly_ratio: float | None = None
    packet_threshold: int
    window_secs: int
    primary_entry_hop: str | None = None
    primary_entry_name: str | None = None
    primary_origin_hop: str | None = None
    primary_origin_name: str | None = None
    primary_origin_lat: float | None = None
    primary_origin_lon: float | None = None
    primary_refined_route: str | None = None
    primary_confidence: int | None = None
    clusters: list[SpamFloodCluster] = Field(default_factory=list)


class SpamFloodEpisodesResponse(BaseModel):
    episodes: list[SpamFloodEpisode]


class SpamPacketTimelineBucket(BaseModel):
    timestamp: int
    counts: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class SpamPacketTimelineResponse(BaseModel):
    window_hours: int
    bucket_minutes: int
    generated_at: int
    categories: list[str]
    category_labels: dict[str, str]
    buckets: list[SpamPacketTimelineBucket]
    totals_by_category: dict[str, int]
    total_packets: int


class ResendChannelMessageResponse(BaseModel):
    status: str
    message_id: int
    message: Message | None = None


class RawPacketDecryptedInfo(BaseModel):
    """Decryption info for a raw packet (when successfully decrypted)."""

    channel_name: str | None = None
    sender: str | None = None
    channel_key: str | None = None
    contact_key: str | None = None
    sender_timestamp: int | None = None
    message: str | None = None
    speed: float | None = Field(
        default=None, description="Tracker speed in m/s for LOCATION packets"
    )
    heading: float | None = Field(
        default=None, description="Tracker heading in degrees for LOCATION packets"
    )


class RawPacketBroadcast(BaseModel):
    """Raw packet payload broadcast via WebSocket.

    This extends the database model with runtime-computed fields
    like payload_type, snr, rssi, and decryption info.
    """

    id: int
    observation_id: int = Field(
        description=(
            "Monotonic per-process ID for this RF observation (distinct from the DB packet row ID)"
        )
    )
    timestamp: int
    data: str = Field(description="Hex-encoded packet data")
    payload_type: str = Field(description="Packet type name (e.g., GROUP_TEXT, ADVERT)")
    snr: float | None = Field(default=None, description="Signal-to-noise ratio in dB")
    rssi: int | None = Field(default=None, description="Received signal strength in dBm")
    transport_codes: str | None = Field(
        default=None, description="Hex-encoded 4-byte transport/region codes for TRANSPORT routes"
    )
    region_name: str | None = Field(
        default=None, description="Identified region name from transport code matching"
    )
    decrypted: bool = False
    decrypted_info: RawPacketDecryptedInfo | None = None


class RawPacketDetail(BaseModel):
    """Stored raw-packet detail returned by the packet API."""

    id: int
    timestamp: int
    data: str = Field(description="Hex-encoded packet data")
    payload_type: str = Field(description="Packet type name (e.g. GROUP_TEXT, ADVERT)")
    snr: float | None = Field(default=None, description="Signal-to-noise ratio in dB if available")
    rssi: int | None = Field(
        default=None, description="Received signal strength in dBm if available"
    )
    transport_codes: str | None = Field(
        default=None, description="Hex-encoded 4-byte transport/region codes for TRANSPORT routes"
    )
    region_name: str | None = Field(
        default=None,
        description="Identified region name (e.g., 'us', 'nl') if matched against known regions",
    )
    decrypted: bool = False
    decrypted_info: RawPacketDecryptedInfo | None = None


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1)


class SendDirectMessageRequest(SendMessageRequest):
    destination: str = Field(
        description="Recipient public key (64-char hex preferred; prefix must resolve uniquely)"
    )


class SendChannelMessageRequest(SendMessageRequest):
    channel_key: str = Field(description="Channel key (32-char hex)")


class RepeaterLoginRequest(BaseModel):
    """Request to log in to a repeater."""

    password: str = Field(
        default="", description="Repeater password (empty string for guest login)"
    )


class RepeaterLoginResponse(BaseModel):
    """Response from repeater login."""

    status: str = Field(description="Login result status")
    authenticated: bool = Field(description="Whether repeater authentication was confirmed")
    message: str | None = Field(
        default=None,
        description="Optional warning or error message when authentication was not confirmed",
    )


class RepeaterStatusResponse(BaseModel):
    """Status telemetry from a repeater (single attempt, no retries)."""

    battery_volts: float = Field(description="Battery voltage in volts")
    tx_queue_len: int = Field(description="Transmit queue length")
    noise_floor_dbm: int = Field(description="Noise floor in dBm")
    last_rssi_dbm: int = Field(description="Last RSSI in dBm")
    last_snr_db: float = Field(description="Last SNR in dB")
    packets_received: int = Field(description="Total packets received")
    packets_sent: int = Field(description="Total packets sent")
    airtime_seconds: int = Field(description="TX airtime in seconds")
    rx_airtime_seconds: int = Field(description="RX airtime in seconds")
    uptime_seconds: int = Field(description="Uptime in seconds")
    sent_flood: int = Field(description="Flood packets sent")
    sent_direct: int = Field(description="Direct packets sent")
    recv_flood: int = Field(description="Flood packets received")
    recv_direct: int = Field(description="Direct packets received")
    flood_dups: int = Field(description="Duplicate flood packets")
    direct_dups: int = Field(description="Duplicate direct packets")
    full_events: int = Field(description="Full event queue count")
    recv_errors: int | None = Field(default=None, description="Radio-level RX packet errors")
    telemetry_history: list[TelemetryHistoryEntry] = Field(
        default_factory=list, description="Recent telemetry history snapshots"
    )


class RepeaterNodeInfoResponse(BaseModel):
    """Identity/location info from a repeater (small CLI batch)."""

    name: str | None = Field(default=None, description="Repeater name")
    lat: str | None = Field(default=None, description="Latitude")
    lon: str | None = Field(default=None, description="Longitude")
    clock_utc: str | None = Field(default=None, description="Repeater clock in UTC")


class RepeaterRadioSettingsResponse(BaseModel):
    """Radio settings from a repeater (radio/config CLI batch)."""

    firmware_version: str | None = Field(default=None, description="Firmware version string")
    radio: str | None = Field(default=None, description="Radio settings (freq,bw,sf,cr)")
    tx_power: str | None = Field(default=None, description="TX power in dBm")
    airtime_factor: str | None = Field(default=None, description="Airtime factor")
    repeat_enabled: str | None = Field(default=None, description="Repeat mode enabled")
    flood_max: str | None = Field(default=None, description="Max flood hops")


class RepeaterAdvertIntervalsResponse(BaseModel):
    """Advertisement intervals from a repeater."""

    advert_interval: str | None = Field(default=None, description="Local advert interval")
    flood_advert_interval: str | None = Field(default=None, description="Flood advert interval")


class RepeaterOwnerInfoResponse(BaseModel):
    """Owner info and guest password from a repeater."""

    owner_info: str | None = Field(default=None, description="Owner info string")
    guest_password: str | None = Field(default=None, description="Guest password")


class LppSensor(BaseModel):
    """A single CayenneLPP sensor reading from req_telemetry_sync."""

    channel: int = Field(description="LPP channel number")
    type_name: str = Field(description="Sensor type name (e.g. temperature, humidity)")
    value: float | dict = Field(
        description="Scalar value or dict for multi-value sensors (GPS, accel)"
    )


class RepeaterLppTelemetryResponse(BaseModel):
    """CayenneLPP sensor telemetry from a repeater."""

    sensors: list[LppSensor] = Field(default_factory=list, description="List of sensor readings")


class ContactTelemetryResponse(BaseModel):
    """On-demand CayenneLPP telemetry snapshot from any contact."""

    sensors: list[LppSensor] = Field(default_factory=list, description="List of sensor readings")
    fetched_at: int = Field(description="Unix timestamp when this telemetry was fetched")
    telemetry_history: list[TelemetryHistoryEntry] = Field(
        default_factory=list, description="Recent telemetry history entries"
    )


class NeighborInfo(BaseModel):
    """Information about a neighbor seen by a repeater."""

    pubkey_prefix: str = Field(description="Public key prefix (4-12 chars)")
    name: str | None = Field(default=None, description="Resolved contact name if known")
    snr: float = Field(description="Signal-to-noise ratio in dB")
    last_heard_seconds: int = Field(description="Seconds since last heard")


class AclEntry(BaseModel):
    """Access control list entry for a repeater."""

    pubkey_prefix: str = Field(description="Public key prefix (12 chars)")
    name: str | None = Field(default=None, description="Resolved contact name if known")
    permission: int = Field(
        description="Permission level: 0=Guest, 1=Read-only, 2=Read-write, 3=Admin"
    )
    permission_name: str = Field(description="Human-readable permission name")


class RepeaterNeighborsResponse(BaseModel):
    """Neighbors list from a repeater."""

    neighbors: list[NeighborInfo] = Field(
        default_factory=list, description="List of neighbors seen by repeater"
    )


class RepeaterAclResponse(BaseModel):
    """ACL list from a repeater."""

    acl: list[AclEntry] = Field(default_factory=list, description="Access control list")


class TraceResponse(BaseModel):
    """Result of a direct (zero-hop) trace to a contact."""

    remote_snr: float | None = Field(
        default=None, description="SNR at which the target heard us (dB)"
    )
    local_snr: float | None = Field(
        default=None, description="SNR at which we heard the target on the bounce-back (dB)"
    )
    path_len: int = Field(description="Number of hops in the trace path")


class RadioTraceHopRequest(BaseModel):
    """One requested hop in a radio trace path."""

    public_key: str | None = Field(
        default=None,
        description="Full repeater public key when this hop maps to a known repeater",
    )
    hop_hex: str | None = Field(
        default=None,
        description="Raw hop hash hex when using a custom repeater prefix",
    )


class RadioTraceRequest(BaseModel):
    """Ordered trace path for a radio trace loop."""

    hop_hash_bytes: Literal[1, 2, 4] = Field(
        default=4,
        description="Hash width in bytes for every hop in this trace path",
    )
    hops: list[RadioTraceHopRequest] = Field(
        min_length=1,
        description="Ordered repeater hops, using either known repeater keys or custom hop hex",
    )


class RadioTraceNode(BaseModel):
    """One resolved node in a radio trace result."""

    role: Literal["repeater", "custom", "local"] = Field(description="Node role in the trace")
    public_key: str | None = Field(
        default=None,
        description="Resolved full public key for this node when known",
    )
    name: str | None = Field(default=None, description="Display name for this node when known")
    observed_hash: str | None = Field(
        default=None,
        description="Observed 4-byte trace hash for this node as hex",
    )
    snr: float | None = Field(default=None, description="Reported SNR for this node in dB")


class RadioTraceResponse(BaseModel):
    """Resolved multi-hop radio trace result."""

    path_len: int = Field(description="Number of hashed nodes returned by the trace response")
    timeout_seconds: float = Field(description="Timeout window used while waiting for the trace")
    nodes: list[RadioTraceNode] = Field(
        default_factory=list,
        description="Ordered trace nodes: repeater hops followed by the terminal local radio",
    )


class PathDiscoveryRoute(BaseModel):
    """One resolved route returned by contact path discovery."""

    path: str = Field(description="Hex-encoded path bytes")
    path_len: int = Field(description="Hop count for this route")
    path_hash_mode: int = Field(
        description="Path hash mode (0=1-byte, 1=2-byte, 2=3-byte hop identifiers)"
    )


class PathDiscoveryResponse(BaseModel):
    """Round-trip routing data for a contact path discovery request."""

    contact: Contact = Field(
        description="Updated contact row after saving the learned forward path"
    )
    forward_path: PathDiscoveryRoute = Field(
        description="Route used from the local radio to the target contact"
    )
    return_path: PathDiscoveryRoute = Field(
        description="Route used from the target contact back to the local radio"
    )


class CommandRequest(BaseModel):
    """Request to send a CLI command to a repeater."""

    command: str = Field(min_length=1, description="CLI command to send")


class CommandResponse(BaseModel):
    """Response from a repeater CLI command."""

    command: str = Field(description="The command that was sent")
    response: str = Field(description="Response from the repeater")
    sender_timestamp: int | None = Field(
        default=None, description="Timestamp from the repeater's response"
    )


class RadioDiscoveryRequest(BaseModel):
    """Request to discover nearby mesh nodes from the local radio."""

    target: Literal["repeaters", "sensors", "all"] = Field(
        default="all",
        description="Which node classes to discover over the mesh",
    )


class RadioDiscoveryResult(BaseModel):
    """One mesh node heard during a discovery sweep."""

    public_key: str = Field(description="Discovered node public key as hex")
    name: str | None = Field(
        default=None,
        description="Known name for this node from contacts DB, if any",
    )
    node_type: Literal["repeater", "sensor"] = Field(description="Discovered node class")
    heard_count: int = Field(default=1, description="How many responses were heard from this node")
    local_snr: float | None = Field(
        default=None,
        description="SNR at which the local radio heard the response (dB)",
    )
    local_rssi: int | None = Field(
        default=None,
        description="RSSI at which the local radio heard the response (dBm)",
    )
    remote_snr: float | None = Field(
        default=None,
        description="SNR reported by the remote node while hearing our discovery request (dB)",
    )


class RadioDiscoveryResponse(BaseModel):
    """Response payload for a mesh discovery sweep."""

    target: Literal["repeaters", "sensors", "all"] = Field(
        description="Which node classes were requested"
    )
    duration_seconds: float = Field(description="How long the sweep listened for responses")
    results: list[RadioDiscoveryResult] = Field(
        default_factory=list,
        description="Deduplicated discovery responses heard during the sweep",
    )


class UnreadCounts(BaseModel):
    """Aggregated unread counts, mention flags, and last message times for all conversations."""

    counts: dict[str, int] = Field(
        default_factory=dict, description="Map of stateKey -> unread count"
    )
    mentions: dict[str, bool] = Field(
        default_factory=dict, description="Map of stateKey -> has mention"
    )
    last_message_times: dict[str, int] = Field(
        default_factory=dict, description="Map of stateKey -> last message timestamp"
    )
    last_read_ats: dict[str, int | None] = Field(
        default_factory=dict, description="Map of stateKey -> server-side last_read_at boundary"
    )


class AppSettings(BaseModel):
    """Application settings stored in the database."""

    max_radio_contacts: int = Field(
        default=200,
        description=(
            "Configured radio contact capacity used for maintenance thresholds; "
            "favorites reload first, then background fill targets about 80% of this value"
        ),
    )
    auto_decrypt_dm_on_advert: bool = Field(
        default=True,
        description="Whether to attempt historical DM decryption on new contact advertisement",
    )
    last_message_times: dict[str, int] = Field(
        default_factory=dict,
        description="Map of conversation state keys to last message timestamps",
    )
    advert_interval: int = Field(
        default=0,
        description="Periodic advertisement interval in seconds (0 = disabled)",
    )
    last_advert_time: int = Field(
        default=0,
        description="Unix timestamp of last advertisement sent (0 = never)",
    )
    flood_scope: str = Field(
        default="",
        description="Outbound flood scope / region name (empty = disabled, no tagging)",
    )
    blocked_keys: list[str] = Field(
        default_factory=list,
        description="Public keys whose messages are hidden from the UI",
    )
    blocked_names: list[str] = Field(
        default_factory=list,
        description="Display names whose messages are hidden from the UI",
    )
    discovery_blocked_types: list[int] = Field(
        default_factory=list,
        description=(
            "Contact type codes (1=Client, 2=Repeater, 3=Room, 4=Sensor) whose "
            "advertisements should not create new contacts; existing contacts are still updated"
        ),
    )
    tracked_telemetry_repeaters: list[str] = Field(
        default_factory=list,
        description="Public keys of repeaters opted into periodic telemetry collection (max 8)",
    )
    tracked_telemetry_contacts: list[str] = Field(
        default_factory=list,
        description="Public keys of contacts opted into periodic LPP telemetry collection (max 8)",
    )
    telemetry_interval_hours: int = Field(
        default=8,
        description=(
            "User-preferred telemetry collection interval in hours. The backend "
            "clamps this up to the shortest legal interval given the number of "
            "tracked repeaters and contacts so daily checks stay under a 24/day ceiling."
        ),
    )
    telemetry_routed_hourly: bool = Field(
        default=False,
        description=(
            "When enabled, tracked repeaters/contacts with a direct or routed (non-flood) "
            "path are polled every hour instead of on the normal scheduled interval."
        ),
    )
    auto_resend_channel: bool = Field(
        default=False,
        description=(
            "When enabled, outgoing channel messages that receive no echo within 2 seconds "
            "are automatically byte-perfect resent once (within the 30-second dedup window)"
        ),
    )
    tracker_history_hours: int = Field(
        default=12,
        ge=1,
        le=168,
        description="Tracker location history retention window in hours (1-168, default 12)",
    )
    spam_gateway_keys: str = Field(
        default="",
        description=(
            "Comma-separated full public keys for internet/MQTT gateway repeaters. "
            "Empty uses built-in GWNL defaults. Set to 'none' to disable gateway stripping."
        ),
    )
    spam_live_window_secs: int = Field(default=30, ge=5, le=300)
    spam_live_packet_threshold: int = Field(default=15, ge=5, le=1000)
    spam_live_cluster_min_ratio: float = Field(default=0.15, ge=0.05, le=1.0)
    spam_live_broadcast_cooldown_secs: int = Field(default=10, ge=1, le=120)
    spam_live_hold_secs: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="Keep flood alarms active this many seconds after the last above-threshold observation.",
    )
    spam_live_episode_retention_secs: int = Field(
        default=0,
        ge=0,
        le=3600,
        description=(
            "How long to retain flood episode packets for clustering while an alarm is active. "
            "0 means match hold_secs."
        ),
    )
    spam_live_max_report_clusters: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Maximum hotspot candidates in live UI and persisted reports (0 = unlimited).",
    )
    spam_live_fluke_max_packets: int = Field(
        default=35,
        ge=0,
        le=1000,
        description="Drop ended episodes from flood history when total packets stay below this (0 = off).",
    )
    spam_live_fluke_max_duration_secs: int = Field(
        default=300,
        ge=0,
        le=3600,
        description="Only episodes ending within this many seconds may be discarded as flukes (0 = ignore duration).",
    )
    spam_flood_automation_enabled: bool = Field(
        default=False,
        description="When enabled, send configured CLI commands to selected repeaters on spam flood start/end",
    )
    spam_flood_repeater_keys: list[str] = Field(
        default_factory=list,
        description="Favorite repeaters to receive spam-flood automation CLI commands",
    )
    spam_flood_start_command: str = Field(
        default="",
        description="CLI command sent when a spam flood episode starts (for example set repeat off)",
    )
    spam_flood_end_command: str = Field(
        default="",
        description="CLI command sent when a spam flood episode ends (for example set repeat on)",
    )


class BusyChannel(BaseModel):
    channel_key: str
    channel_name: str
    message_count: int


class ContactActivityCounts(BaseModel):
    last_hour: int
    last_24_hours: int
    last_week: int


class NoiseFloorSample(BaseModel):
    timestamp: int = Field(description="Unix timestamp of the sampled reading")
    noise_floor_dbm: int = Field(description="Noise floor in dBm")


class NoiseFloorHistoryStats(BaseModel):
    sample_interval_seconds: int = Field(description="Expected spacing between samples")
    coverage_seconds: int = Field(description="How much of the last 24 hours is represented")
    latest_noise_floor_dbm: int | None = Field(
        default=None, description="Most recent sampled noise floor in dBm"
    )
    latest_timestamp: int | None = Field(
        default=None, description="Unix timestamp of the most recent sample"
    )
    samples: list[NoiseFloorSample] = Field(default_factory=list)


class PacketsPerHourBucket(BaseModel):
    timestamp: int = Field(description="Unix timestamp at the start of the hour")
    count: int = Field(description="Number of packets received in that hour")


class StatisticsResponse(BaseModel):
    busiest_channels_24h: list[BusyChannel]
    contact_count: int
    repeater_count: int
    channel_count: int
    total_packets: int
    decrypted_packets: int
    undecrypted_packets: int
    total_dms: int
    total_channel_messages: int
    total_outgoing: int
    contacts_heard: ContactActivityCounts
    repeaters_heard: ContactActivityCounts
    known_channels_active: ContactActivityCounts
    path_hash_width_24h: PathHashWidthStats
    primary_regions_24h: RegionUsageStats
    packets_per_hour_72h: list[PacketsPerHourBucket]
    noise_floor_24h: NoiseFloorHistoryStats


class TelemetryHistoryEntry(BaseModel):
    timestamp: int
    data: dict
