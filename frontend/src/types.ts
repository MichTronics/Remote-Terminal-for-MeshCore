interface RadioSettings {
  freq: number;
  bw: number;
  sf: number;
  cr: number;
}

export interface RadioConfig {
  public_key: string;
  name: string;
  lat: number;
  lon: number;
  tx_power: number;
  max_tx_power: number;
  radio: RadioSettings;
  path_hash_mode: number;
  path_hash_mode_supported: boolean;
  advert_location_source?: 'off' | 'current';
  multi_acks_enabled?: boolean;
  telemetry_mode_base?: number;
  telemetry_mode_loc?: number;
  telemetry_mode_env?: number;
}

export interface RadioConfigUpdate {
  name?: string;
  lat?: number;
  lon?: number;
  tx_power?: number;
  radio?: RadioSettings;
  path_hash_mode?: number;
  advert_location_source?: 'off' | 'current';
  multi_acks_enabled?: boolean;
  telemetry_mode_base?: number;
  telemetry_mode_loc?: number;
  telemetry_mode_env?: number;
}

export type RadioDiscoveryTarget = 'repeaters' | 'sensors' | 'all';

export interface RadioDiscoveryResult {
  public_key: string;
  name: string | null;
  node_type: 'repeater' | 'sensor';
  heard_count: number;
  local_snr: number | null;
  local_rssi: number | null;
  remote_snr: number | null;
}

export interface RadioDiscoveryResponse {
  target: RadioDiscoveryTarget;
  duration_seconds: number;
  results: RadioDiscoveryResult[];
}

export type RadioAdvertMode = 'flood' | 'zero_hop';

export interface FanoutStatusEntry {
  name: string;
  type: string;
  status: string;
  last_error?: string | null;
}

export interface AppInfo {
  version: string;
  commit_hash: string | null;
}

export interface RadioStatsSnapshot {
  timestamp: number | null;
  battery_mv: number | null;
  uptime_secs: number | null;
  queue_len: number | null;
  errors: number | null;
  noise_floor: number | null;
  last_rssi: number | null;
  last_snr: number | null;
  tx_air_secs: number | null;
  rx_air_secs: number | null;
  packets_recv: number | null;
  packets_sent: number | null;
  flood_tx: number | null;
  direct_tx: number | null;
  flood_rx: number | null;
  direct_rx: number | null;
}

export interface HealthStatus {
  status: string;
  radio_connected: boolean;
  radio_initializing: boolean;
  radio_state?: 'connected' | 'initializing' | 'connecting' | 'disconnected' | 'paused';
  connection_info: string | null;
  app_info?: AppInfo | null;
  radio_device_info?: {
    model: string | null;
    firmware_build: string | null;
    firmware_version: string | null;
    max_contacts: number | null;
    max_channels: number | null;
  } | null;
  radio_stats?: RadioStatsSnapshot | null;
  database_size_mb: number;
  oldest_undecrypted_timestamp: number | null;
  fanout_statuses: Record<string, FanoutStatusEntry>;
  bots_disabled: boolean;
  bots_disabled_source?: 'env' | 'until_restart' | null;
  basic_auth_enabled?: boolean;
}

export interface FanoutConfig {
  id: string;
  type: string;
  name: string;
  enabled: boolean;
  config: Record<string, unknown>;
  scope: Record<string, unknown>;
  sort_order: number;
  created_at: number;
}

export interface MaintenanceResult {
  packets_deleted: number;
  vacuumed: boolean;
}

export interface Contact {
  public_key: string;
  name: string | null;
  type: number;
  flags: number;
  direct_path: string | null;
  direct_path_len: number;
  direct_path_hash_mode: number;
  direct_path_updated_at?: number | null;
  route_override_path?: string | null;
  route_override_len?: number | null;
  route_override_hash_mode?: number | null;
  effective_route?: ContactRoute | null;
  effective_route_source?: 'override' | 'direct' | 'flood';
  direct_route?: ContactRoute | null;
  route_override?: ContactRoute | null;
  last_advert: number | null;
  lat: number | null;
  lon: number | null;
  last_seen: number | null;
  on_radio: boolean;
  favorite: boolean;
  last_contacted: number | null;
  last_read_at: number | null;
  first_seen: number | null;
  is_tracker: boolean;
  tracker_name: string | null;
  /** Last known heading in degrees from tracker GROUP_DATA packets (0 = north, clockwise). */
  tracker_heading?: number | null;
  /** Last known altitude in metres from the most recent tracker packet. */
  tracker_altitude?: number | null;
  /** Last known speed in m/s from the most recent tracker packet. */
  tracker_speed?: number | null;
}

export interface LocationHistory {
  id: number;
  contact_public_key: string;
  lat: number;
  lon: number;
  altitude: number | null;
  speed: number | null;
  heading: number | null;
  satellites: number | null;
  battery: number | null;
  timestamp: number;
  received_at: number;
}

export interface ContactRoute {
  path: string;
  path_len: number;
  path_hash_mode: number;
}

export interface ContactAdvertPath {
  path: string;
  path_len: number;
  next_hop: string | null;
  first_seen: number;
  last_seen: number;
  heard_count: number;
}

export interface ContactAdvertPathSummary {
  public_key: string;
  paths: ContactAdvertPath[];
}

export interface ContactNameHistory {
  name: string;
  first_seen: number;
  last_seen: number;
}

export interface ContactActiveRoom {
  channel_key: string;
  channel_name: string;
  message_count: number;
}

export interface NearestRepeater {
  public_key: string;
  name: string | null;
  path_len: number;
  last_seen: number;
  heard_count: number;
}

export interface ContactAnalyticsHourlyBucket {
  bucket_start: number;
  last_24h_count: number;
  last_week_average: number;
  all_time_average: number;
}

export interface ContactAnalyticsWeeklyBucket {
  bucket_start: number;
  message_count: number;
}

export interface ContactAnalytics {
  lookup_type: 'contact' | 'name';
  name: string;
  contact: Contact | null;
  name_first_seen_at: number | null;
  name_history: ContactNameHistory[];
  dm_message_count: number;
  channel_message_count: number;
  includes_direct_messages: boolean;
  most_active_rooms: ContactActiveRoom[];
  advert_paths: ContactAdvertPath[];
  advert_frequency: number | null;
  nearest_repeaters: NearestRepeater[];
  hourly_activity: ContactAnalyticsHourlyBucket[];
  weekly_activity: ContactAnalyticsWeeklyBucket[];
}

export interface Channel {
  key: string;
  name: string;
  is_hashtag: boolean;
  on_radio: boolean;
  flood_scope_override?: string | null;
  path_hash_mode_override?: number | null;
  last_read_at: number | null;
  favorite: boolean;
  muted: boolean;
}

export interface Region {
  id: number;
  name: string;
  key: string; // 32-character hex (16 bytes)
  is_public: boolean;
  created_at: number;
}

export interface ChannelMessageCounts {
  last_1h: number;
  last_24h: number;
  last_48h: number;
  last_7d: number;
  all_time: number;
}

export interface ChannelTopSender {
  sender_name: string;
  sender_key: string | null;
  message_count: number;
}

export interface BulkCreateHashtagChannelsResult {
  created_channels: Channel[];
  existing_count: number;
  invalid_names: string[];
  decrypt_started: boolean;
  decrypt_total_packets: number;
  message: string;
}

export interface BulkHashtagChannelInput {
  name: string;
  key?: string;
}

export interface PathHashWidthStats {
  total_packets: number;
  single_byte: number;
  double_byte: number;
  triple_byte: number;
  single_byte_pct: number;
  double_byte_pct: number;
  triple_byte_pct: number;
}

export interface RegionUsageItem {
  region: string; // Primary region hex (2 bytes, e.g., "FFFF")
  count: number;
}

export interface RegionUsageStats {
  total_packets: number;
  regions: RegionUsageItem[];
}

export interface ChannelDetail {
  channel: Channel;
  message_counts: ChannelMessageCounts;
  first_message_at: number | null;
  unique_sender_count: number;
  top_senders_24h: ChannelTopSender[];
  path_hash_width_24h: PathHashWidthStats;
}

/** A single path that a message took to reach us */
export interface MessagePath {
  /** Hex-encoded routing path */
  path: string;
  /** Unix timestamp when this path was received */
  received_at: number;
  /** Hop count (number of intermediate nodes). Null for legacy data (infer as len(path)/2). */
  path_len?: number | null;
  /** Last-hop RSSI in dBm (null if not available, e.g. older data) */
  rssi?: number | null;
  /** Last-hop SNR in dB (null if not available, e.g. older data) */
  snr?: number | null;
}

export interface Message {
  id: number;
  type: 'PRIV' | 'CHAN';
  /** For PRIV: sender's PublicKey (or prefix). For CHAN: ChannelKey */
  conversation_key: string;
  text: string;
  sender_timestamp: number | null;
  received_at: number;
  /** List of routing paths this message arrived via. Null for outgoing messages. */
  paths: MessagePath[] | null;
  txt_type: number;
  signature: string | null;
  sender_key: string | null;
  outgoing: boolean;
  /** ACK count: 0 = not acked, 1+ = number of acks/flood echoes received */
  acked: number;
  sender_name: string | null;
  channel_name?: string | null;
  packet_id?: number | null;
}

export interface MessagesAroundResponse {
  messages: Message[];
  has_older: boolean;
  has_newer: boolean;
}

export interface ResendChannelMessageResponse {
  status: string;
  message_id: number;
  message?: Message;
}

export interface SpamRepeaterStat {
  hop: string;
  observation_count: number;
  route_count: number;
  message_count: number;
  conversation_count: number;
  source_side_count: number;
  radio_side_count: number;
  middle_count: number;
  suspect_score: number;
  narrowed_prefix: string;
  contact_name: string | null;
  lat: number | null;
  lon: number | null;
  first_seen: number | null;
  last_seen: number | null;
  avg_rssi: number | null;
  avg_snr: number | null;
}

export interface SpamRouteStat {
  path: string;
  path_len: number;
  hop_count: number;
  hop_tokens: string[];
  route: string;
  observation_count: number;
  message_count: number;
  conversation_count: number;
  first_seen: number | null;
  last_seen: number | null;
  avg_rssi: number | null;
  avg_snr: number | null;
}

export interface SpamRouteStatsResponse {
  window_hours: number | null;
  total_observations: number;
  total_messages: number;
  repeaters: SpamRepeaterStat[];
  routes: SpamRouteStat[];
}

export interface SpamFloodCluster {
  entry_hop: string;
  entry_name: string | null;
  entry_public_key: string | null;
  lat: number | null;
  lon: number | null;
  packet_count: number;
  dominant_route: string;
  hop_tokens: string[];
  longest_route_tokens?: string[];
  hop_names_by_token?: Record<string, string>;
  refined_route: string;
  refined_hop_tokens: string[];
  traffic_share: number;
  concentration: number;
  narrowing_depth: number;
  confidence: number;
  origin_hop: string | null;
  origin_name: string | null;
  origin_public_key: string | null;
  origin_lat: number | null;
  origin_lon: number | null;
  origin_geo_hint?: string | null;
  last_seen: number;
  cluster_mode: string | null;
  flood_source_key?: string | null;
  flood_source_label?: string | null;
}

export interface SpamBlockCandidate {
  route: string;
  hop_tokens: string[];
  segment_len: number;
  packet_count: number;
  occurrence_count: number;
  traffic_share: number;
}

export interface SpamCategoryFloodStatus {
  category: string;
  category_label: string;
  active: boolean;
  window_secs: number;
  packet_threshold: number;
  total_packets: number;
  episode_packets: number;
  episode_window_secs: number;
  detected_at: number | null;
  baseline_packets_per_window: number | null;
  anomaly_ratio: number | null;
  episode_id: number | null;
  cluster_min_share: number;
  clusters_stale: boolean;
  primary_category: string | null;
  category_counts: Record<string, number>;
  category_labels: Record<string, string>;
  likely_source_key: string | null;
  likely_source_label: string | null;
  likely_source_name: string | null;
  likely_source_public_key: string | null;
  likely_source_lat: number | null;
  likely_source_lon: number | null;
  likely_source_geo_hint?: string | null;
  likely_source_traffic_share: number | null;
  likely_source_packet_count: number | null;
  likely_source_kind: string | null;
  source_filter_active?: boolean;
  source_filter_mode?: string | null;
  source_filter_excluded_packets?: number;
  source_filter_labels?: string[];
  block_candidates?: SpamBlockCandidate[];
  block_candidates_combined_coverage?: number | null;
  clusters: SpamFloodCluster[];
}

export interface SpamLiveStatus {
  active: boolean;
  window_secs: number;
  packet_threshold: number;
  total_packets: number;
  episode_packets: number;
  episode_window_secs: number;
  detected_at: number | null;
  baseline_packets_per_window: number | null;
  anomaly_ratio: number | null;
  episode_id: number | null;
  cluster_min_share: number;
  clusters_stale: boolean;
  primary_category: string | null;
  category_counts: Record<string, number>;
  category_labels: Record<string, string>;
  likely_source_key: string | null;
  likely_source_label: string | null;
  likely_source_name: string | null;
  likely_source_public_key: string | null;
  likely_source_lat: number | null;
  likely_source_lon: number | null;
  likely_source_geo_hint?: string | null;
  likely_source_traffic_share: number | null;
  likely_source_packet_count: number | null;
  likely_source_kind: string | null;
  source_filter_active?: boolean;
  source_filter_mode?: string | null;
  source_filter_excluded_packets?: number;
  source_filter_labels?: string[];
  clusters: SpamFloodCluster[];
  category_floods?: SpamCategoryFloodStatus[];
}

export interface SpamFloodEpisode {
  id: number;
  started_at: number;
  ended_at: number | null;
  duration_secs: number | null;
  total_packets: number;
  peak_packets_per_window: number;
  baseline_packets_per_window: number | null;
  anomaly_ratio: number | null;
  packet_threshold: number;
  window_secs: number;
  primary_entry_hop: string | null;
  primary_entry_name: string | null;
  primary_origin_hop: string | null;
  primary_origin_name: string | null;
  primary_origin_lat: number | null;
  primary_origin_lon: number | null;
  primary_refined_route: string | null;
  primary_confidence: number | null;
  primary_category: string | null;
  category_counts: Record<string, number>;
  category_labels: Record<string, string>;
  likely_source_key: string | null;
  likely_source_label: string | null;
  likely_source_name: string | null;
  likely_source_public_key: string | null;
  likely_source_lat: number | null;
  likely_source_lon: number | null;
  likely_source_geo_hint?: string | null;
  likely_source_traffic_share: number | null;
  likely_source_packet_count: number | null;
  likely_source_kind: string | null;
  clusters: SpamFloodCluster[];
}

export interface SpamFloodEpisodesResponse {
  episodes: SpamFloodEpisode[];
}

export interface SpamPacketTimelineBucket {
  timestamp: number;
  counts: Record<string, number>;
  total: number;
}

export interface SpamPacketTimelineResponse {
  window_hours: number;
  bucket_minutes: number;
  generated_at: number;
  categories: string[];
  category_labels: Record<string, string>;
  buckets: SpamPacketTimelineBucket[];
  totals_by_category: Record<string, number>;
  total_packets: number;
}

type ConversationType =
  | 'contact'
  | 'channel'
  | 'raw'
  | 'map'
  | 'visualizer'
  | 'search'
  | 'node-search'
  | 'trace'
  | 'spam';

export interface Conversation {
  type: ConversationType;
  /** PublicKey for contacts, ChannelKey for channels, 'raw'/'map' for special views */
  id: string;
  name: string;
  /** For map view: public key prefix to focus on */
  mapFocusKey?: string;
}

export interface RawPacket {
  id: number;
  /** Per-observation WS identity (unique per RF arrival, may be absent in older payloads) */
  observation_id?: number;
  timestamp: number;
  data: string; // hex
  payload_type: string;
  snr: number | null; // Signal-to-noise ratio in dB
  rssi: number | null; // Received signal strength in dBm
  transport_codes: string | null; // Hex-encoded 4-byte transport/region codes for TRANSPORT routes
  region_name: string | null; // Identified region name (e.g., 'us', 'nl') if matched against known regions
  decrypted: boolean;
  decrypted_info: {
    channel_name: string | null;
    sender: string | null;
    channel_key: string | null;
    contact_key: string | null;
    sender_timestamp: number | null;
    message: string | null;
    speed?: number | null;
    heading?: number | null;
    node_id?: string | null;
    is_tracker?: boolean | null;
  } | null;
  /** Client-only: distinct RF paths already seen for this stored packet row. */
  feed_seen_paths?: string[];
}

export interface AppSettings {
  max_radio_contacts: number;
  auto_decrypt_dm_on_advert: boolean;
  last_message_times: Record<string, number>;
  advert_interval: number;
  last_advert_time: number;
  flood_scope: string;
  blocked_keys: string[];
  blocked_names: string[];
  discovery_blocked_types: number[];
  tracked_telemetry_repeaters: string[];
  tracked_telemetry_contacts: string[];
  auto_resend_channel: boolean;
  telemetry_interval_hours: number;
  telemetry_routed_hourly: boolean;
  spam_gateway_keys: string;
  spam_live_window_secs: number;
  spam_live_packet_threshold: number;
  spam_live_cluster_min_ratio: number;
  spam_live_broadcast_cooldown_secs: number;
  spam_live_hold_secs: number;
  spam_live_episode_retention_secs: number;
  spam_live_max_report_clusters: number;
  spam_live_fluke_max_packets: number;
  spam_live_fluke_max_duration_secs: number;
  spam_flood_automation_enabled: boolean;
  spam_flood_repeater_keys: string[];
  spam_flood_start_command: string;
  spam_flood_end_command: string;
  spam_flood_repeater_password: string;
}

export interface AppSettingsUpdate {
  max_radio_contacts?: number;
  auto_decrypt_dm_on_advert?: boolean;
  advert_interval?: number;
  auto_resend_channel?: boolean;
  flood_scope?: string;
  blocked_keys?: string[];
  blocked_names?: string[];
  discovery_blocked_types?: number[];
  telemetry_interval_hours?: number;
  telemetry_routed_hourly?: boolean;
  spam_gateway_keys?: string;
  spam_live_window_secs?: number;
  spam_live_packet_threshold?: number;
  spam_live_cluster_min_ratio?: number;
  spam_live_broadcast_cooldown_secs?: number;
  spam_live_hold_secs?: number;
  spam_live_episode_retention_secs?: number;
  spam_live_max_report_clusters?: number;
  spam_live_fluke_max_packets?: number;
  spam_live_fluke_max_duration_secs?: number;
  spam_flood_automation_enabled?: boolean;
  spam_flood_repeater_keys?: string[];
  spam_flood_start_command?: string;
  spam_flood_end_command?: string;
  spam_flood_repeater_password?: string;
}

export interface TelemetrySchedule {
  preferred_hours: number;
  effective_hours: number;
  options: number[];
  tracked_count: number;
  max_tracked: number;
  next_run_at: number | null;
  routed_hourly: boolean;
  next_routed_run_at: number | null;
}

export interface TrackedTelemetryResponse {
  tracked_telemetry_repeaters: string[];
  names: Record<string, string>;
  schedule: TelemetrySchedule;
}

/** Contact type constants */
export const CONTACT_TYPE_REPEATER = 2;
export const CONTACT_TYPE_ROOM = 3;

export interface NeighborInfo {
  pubkey_prefix: string;
  name: string | null;
  snr: number;
  last_heard_seconds: number;
}

export interface AclEntry {
  pubkey_prefix: string;
  name: string | null;
  permission: number;
  permission_name: string;
}

export interface CommandResponse {
  command: string;
  response: string;
  sender_timestamp: number | null;
}

// --- Granular repeater endpoint types ---

export interface RepeaterLoginResponse {
  status: string;
  authenticated: boolean;
  message: string | null;
}

export interface RepeaterStatusResponse {
  battery_volts: number;
  tx_queue_len: number;
  noise_floor_dbm: number;
  last_rssi_dbm: number;
  last_snr_db: number;
  packets_received: number;
  packets_sent: number;
  airtime_seconds: number;
  rx_airtime_seconds: number;
  uptime_seconds: number;
  sent_flood: number;
  sent_direct: number;
  recv_flood: number;
  recv_direct: number;
  flood_dups: number;
  direct_dups: number;
  full_events: number;
  recv_errors: number | null;
  telemetry_history: TelemetryHistoryEntry[];
}

export interface RepeaterNeighborsResponse {
  neighbors: NeighborInfo[];
}

export interface RepeaterAclResponse {
  acl: AclEntry[];
}

export interface RepeaterNodeInfoResponse {
  name: string | null;
  lat: string | null;
  lon: string | null;
  clock_utc: string | null;
}

export interface RepeaterRadioSettingsResponse {
  firmware_version: string | null;
  radio: string | null;
  tx_power: string | null;
  airtime_factor: string | null;
  repeat_enabled: string | null;
  flood_max: string | null;
}

export interface RepeaterAdvertIntervalsResponse {
  advert_interval: string | null;
  flood_advert_interval: string | null;
}

export interface RepeaterOwnerInfoResponse {
  owner_info: string | null;
  guest_password: string | null;
}

export interface LppSensor {
  channel: number;
  type_name: string;
  value: number | Record<string, number>;
}

export interface RepeaterLppTelemetryResponse {
  sensors: LppSensor[];
}

export interface ContactTelemetryResponse {
  sensors: LppSensor[];
  fetched_at: number;
  telemetry_history: TelemetryHistoryEntry[];
}

export interface TrackedTelemetryContactsResponse {
  tracked_telemetry_contacts: string[];
  names: Record<string, string>;
  schedule: TelemetrySchedule;
}

export type PaneName =
  | 'status'
  | 'nodeInfo'
  | 'neighbors'
  | 'acl'
  | 'radioSettings'
  | 'advertIntervals'
  | 'ownerInfo'
  | 'lppTelemetry';

export interface PaneState {
  loading: boolean;
  attempt: number;
  error: string | null;
  fetched_at?: number | null;
}

export interface TelemetryLppSensor {
  channel: number;
  type_name: string;
  value: number;
}

export interface TelemetryHistoryEntry {
  timestamp: number;
  data: Record<string, number> & { lpp_sensors?: TelemetryLppSensor[] };
}

export interface PushSubscriptionInfo {
  id: string;
  endpoint: string;
  p256dh: string;
  auth: string;
  label: string;
  created_at: number;
  last_success_at: number | null;
  failure_count: number;
}

export interface TraceResponse {
  remote_snr: number | null;
  local_snr: number | null;
  path_len: number;
}

export interface RadioTraceNode {
  role: 'repeater' | 'custom' | 'local';
  public_key: string | null;
  name: string | null;
  observed_hash: string | null;
  snr: number | null;
}

export interface RadioTraceHopRequest {
  public_key?: string | null;
  hop_hex?: string | null;
}

export interface RadioTraceResponse {
  path_len: number;
  timeout_seconds: number;
  nodes: RadioTraceNode[];
}

export interface PathDiscoveryRoute {
  path: string;
  path_len: number;
  path_hash_mode: number;
}

export interface PathDiscoveryResponse {
  contact: Contact;
  forward_path: PathDiscoveryRoute;
  return_path: PathDiscoveryRoute;
}

export interface UnreadCounts {
  counts: Record<string, number>;
  mentions: Record<string, boolean>;
  last_message_times: Record<string, number>;
  last_read_ats: Record<string, number | null>;
}

interface BusyChannel {
  channel_key: string;
  channel_name: string;
  message_count: number;
}

interface ContactActivityCounts {
  last_hour: number;
  last_24_hours: number;
  last_week: number;
}

export interface NoiseFloorSample {
  timestamp: number;
  noise_floor_dbm: number;
}

export interface NoiseFloorHistoryStats {
  sample_interval_seconds: number;
  coverage_seconds: number;
  latest_noise_floor_dbm: number | null;
  latest_timestamp: number | null;
  samples: NoiseFloorSample[];
}

interface PacketsPerHourBucket {
  timestamp: number;
  count: number;
}

export interface StatisticsResponse {
  busiest_channels_24h: BusyChannel[];
  contact_count: number;
  repeater_count: number;
  channel_count: number;
  advert_neighbor_count: number;
  total_packets: number;
  decrypted_packets: number;
  undecrypted_packets: number;
  total_dms: number;
  total_channel_messages: number;
  total_outgoing: number;
  contacts_heard: ContactActivityCounts;
  repeaters_heard: ContactActivityCounts;
  known_channels_active: ContactActivityCounts;
  path_hash_width_24h: {
    total_packets: number;
    single_byte: number;
    double_byte: number;
    triple_byte: number;
    single_byte_pct: number;
    double_byte_pct: number;
    triple_byte_pct: number;
  };
  primary_regions_24h: RegionUsageStats;
  packets_per_hour_72h: PacketsPerHourBucket[];
  noise_floor_24h: NoiseFloorHistoryStats;
}
