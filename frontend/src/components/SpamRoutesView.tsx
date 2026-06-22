import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, Crosshair, ExternalLink, MapPin, RadioTower, RefreshCw, Route, Trash2 } from 'lucide-react';

import { api } from '../api';
import type {
  SpamCategoryFloodStatus,
  SpamFloodCluster,
  SpamFloodEpisode,
  SpamLiveStatus,
  SpamRepeaterStat,
  SpamRouteStatsResponse,
} from '../types';
import { Button } from './ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './ui/dialog';
import { SpamPacketTimelineSection } from './SpamPacketTimelineSection';
import { cn } from '@/lib/utils';
import { formatSpamCategoryBreakdown } from '../utils/spamPacketCategories';
import {
  formatEpisodeLocationSummary as formatEpisodeLocSummary,
  resolveEpisodeLocationCoords,
} from '../utils/spamEpisodeLocation';

type WindowOption = 24;

const HISTORICAL_WINDOW_HOURS: WindowOption = 24;
const LIVE_POLL_MS = 5000;

function formatSeen(timestamp: number | null): string {
  if (timestamp == null) return '-';
  return new Date(timestamp * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatSignal(value: number | null, unit: string): string {
  if (value == null) return '-';
  return `${value.toFixed(unit === 'dBm' ? 0 : 1)} ${unit}`;
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function clusterModeBadge(cluster: SpamFloodCluster): ReactNode {
  if (cluster.cluster_mode === 'entry_fallback') {
    return (
      <div
        className="rounded bg-amber-500/15 px-2 py-0.5 text-[0.625rem] font-medium text-amber-700 dark:text-amber-300"
        title="No ingress hop reached the 15% shared-prefix threshold on its own. Grouped by first hop only — typical when several sources split the flood."
      >
        Split ingress
      </div>
    );
  }
  if (cluster.cluster_mode === 'partitioned') {
    return (
      <div
        className="rounded bg-amber-500/15 px-2 py-0.5 text-[0.625rem] font-medium text-amber-700 dark:text-amber-300"
        title="Multiple ingress sources detected. Each candidate was narrowed within its own entry hop."
      >
        Multi-source
      </div>
    );
  }
  if (cluster.cluster_mode === 'geo_merged') {
    return (
      <div
        className="rounded bg-primary/10 px-2 py-0.5 text-[0.625rem] font-medium text-primary"
        title="Several nearby ingress repeaters were merged into one geographic focus area."
      >
        Geo focus
      </div>
    );
  }
  if (cluster.cluster_mode === 'sticky') {
    return (
      <div className="rounded bg-muted px-2 py-0.5 text-[0.625rem] font-medium text-muted-foreground">
        Last known
      </div>
    );
  }
  return null;
}

function suspectScore(item: SpamRepeaterStat): number {
  return item.suspect_score ?? 0;
}

function formatHopLabel(item: SpamRepeaterStat): string {
  if (item.contact_name) return item.contact_name;
  return item.hop;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || seconds <= 0) return '-';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
}

function formatClusterHotspotLabel(cluster: SpamFloodCluster): string {
  const name =
    cluster.origin_name ??
    cluster.entry_name ??
    cluster.hop_names_by_token?.[cluster.entry_hop] ??
    null;
  const hop = cluster.origin_hop ?? cluster.entry_hop;
  if (name && hop) return `${name} (${hop})`;
  if (hop) return hop;
  return '-';
}

const MAX_CLUSTER_ROUTE_HOPS = 10;

function clusterLongestRouteTokens(cluster: SpamFloodCluster): string[] {
  const tokens =
    cluster.longest_route_tokens && cluster.longest_route_tokens.length > 0
      ? cluster.longest_route_tokens
      : cluster.hop_tokens;
  return (tokens ?? []).slice(0, MAX_CLUSTER_ROUTE_HOPS);
}

function formatHopTokenLabel(hop: string, cluster: SpamFloodCluster): string {
  const name = cluster.hop_names_by_token?.[hop];
  return name ? `${name} (${hop})` : hop;
}

function formatClusterLongestRoute(cluster: SpamFloodCluster): string | null {
  const tokens = clusterLongestRouteTokens(cluster);
  if (tokens.length === 0) return null;
  return tokens.map((hop) => formatHopTokenLabel(hop, cluster)).join(' ⇢ ');
}

function formatClusterIngressHeading(cluster: SpamFloodCluster): string | null {
  const entryName =
    cluster.entry_name ??
    cluster.hop_names_by_token?.[cluster.entry_hop] ??
    cluster.origin_name ??
    null;
  if (!entryName) return null;
  return `${entryName} · ingress ${cluster.entry_hop}`;
}

function ClusterRouteDetails({ cluster }: { cluster: SpamFloodCluster }) {
  const ingressHeading = formatClusterIngressHeading(cluster);
  const longestRoute = formatClusterLongestRoute(cluster);
  const lat = cluster.origin_lat ?? cluster.lat;
  const lon = cluster.origin_lon ?? cluster.lon;
  const hasCoords = lat != null && lon != null;

  if (!ingressHeading && !longestRoute && !hasCoords) return null;

  return (
    <div className="mt-1.5 space-y-1">
      {ingressHeading && (
        <div className="text-[0.8125rem] font-medium text-foreground">{ingressHeading}</div>
      )}
      {longestRoute && (
        <div className="font-mono text-[0.6875rem] leading-relaxed text-muted-foreground">
          {longestRoute}
        </div>
      )}
      {hasCoords && (
        <a
          href={buildMapUrl(lat!, lon!)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 font-mono text-[0.6875rem] text-primary hover:underline"
        >
          {lat!.toFixed(5)}, {lon!.toFixed(5)}
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      )}
      {cluster.origin_geo_hint && (
        <div className="text-[0.8125rem] text-muted-foreground">{cluster.origin_geo_hint}</div>
      )}
    </div>
  );
}

const MAX_EPISODE_REPORT_CLUSTERS = 5;

function episodeReportClusters(episode: SpamFloodEpisode): SpamFloodCluster[] {
  if (episode.clusters.length > 0) {
    return episode.clusters.slice(0, MAX_EPISODE_REPORT_CLUSTERS);
  }
  const hop = episode.primary_origin_hop ?? episode.primary_entry_hop;
  if (!hop) return [];
  return [
    {
      entry_hop: episode.primary_entry_hop ?? hop,
      entry_name: episode.primary_entry_name,
      entry_public_key: null,
      lat: episode.primary_origin_lat,
      lon: episode.primary_origin_lon,
      packet_count: episode.total_packets,
      dominant_route: episode.primary_refined_route ?? hop,
      hop_tokens: [],
      longest_route_tokens: [],
      hop_names_by_token: {},
      refined_route: episode.primary_refined_route ?? '',
      refined_hop_tokens: [],
      traffic_share: 0,
      concentration: 1,
      narrowing_depth: 1,
      confidence: episode.primary_confidence ?? 0,
      origin_hop: episode.primary_origin_hop,
      origin_name: episode.primary_origin_name,
      origin_public_key: null,
      origin_lat: episode.primary_origin_lat,
      origin_lon: episode.primary_origin_lon,
      origin_geo_hint: null,
      last_seen: episode.ended_at ?? episode.started_at,
      cluster_mode: null,
    },
  ];
}

function buildMapUrl(lat: number, lon: number): string {
  return `https://www.google.com/maps?q=${lat},${lon}`;
}

function primaryEpisodeCluster(episode: SpamFloodEpisode): SpamFloodCluster | null {
  const clusters = episodeReportClusters(episode);
  return clusters[0] ?? null;
}

function formatEpisodeFloodType(episode: SpamFloodEpisode): string {
  return formatSpamCategoryBreakdown(
    episode.category_counts,
    episode.category_labels,
    episode.total_packets,
  );
}

function formatLikelySourceSummary(
  source: Pick<
    SpamLiveStatus,
    | 'likely_source_key'
    | 'likely_source_label'
    | 'likely_source_name'
    | 'likely_source_geo_hint'
    | 'likely_source_traffic_share'
    | 'likely_source_packet_count'
    | 'likely_source_kind'
  >,
): string | null {
  if (!source.likely_source_key) return null;
  if (source.likely_source_geo_hint) return source.likely_source_geo_hint;
  if (source.likely_source_name && source.likely_source_label) {
    return `${source.likely_source_name} (${source.likely_source_label})`;
  }
  return source.likely_source_label ?? source.likely_source_key;
}

function LikelySourceBanner({
  source,
}: {
  source: Pick<
    SpamLiveStatus,
    | 'likely_source_key'
    | 'likely_source_label'
    | 'likely_source_name'
    | 'likely_source_geo_hint'
    | 'likely_source_traffic_share'
    | 'likely_source_packet_count'
    | 'likely_source_kind'
    | 'likely_source_lat'
    | 'likely_source_lon'
  >;
}) {
  const summary = formatLikelySourceSummary(source);
  if (!summary) return null;

  const share =
    source.likely_source_traffic_share != null
      ? formatPercent(source.likely_source_traffic_share)
      : null;
  const coords =
    source.likely_source_lat != null && source.likely_source_lon != null
      ? `${source.likely_source_lat.toFixed(5)}, ${source.likely_source_lon.toFixed(5)}`
      : null;

  return (
    <div className="rounded-md border border-destructive/40 bg-background/90 px-3 py-2">
      <div className="text-[0.625rem] font-semibold uppercase tracking-wider text-destructive">
        Likely spam source
      </div>
      <div className="mt-1 text-sm font-medium text-foreground">{summary}</div>
      <div className="mt-1 text-xs text-muted-foreground">
        {source.likely_source_kind === 'packet'
          ? 'Same packet sender identity on most flood packets'
          : 'Same shared RF path prefix on most flood packets'}
        {share ? ` · ${share} of identified traffic` : ''}
        {source.likely_source_packet_count != null
          ? ` · ${source.likely_source_packet_count} pkts`
          : ''}
      </div>
      {coords && (
        <a
          href={buildMapUrl(source.likely_source_lat!, source.likely_source_lon!)}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-flex items-center gap-1 font-mono text-[0.6875rem] text-primary hover:underline"
        >
          {coords}
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      )}
      <div className="mt-1 text-[0.8125rem] text-muted-foreground">
        Ingress hotspot analysis below still shows where traffic enters the mesh.
      </div>
    </div>
  );
}

function formatEpisodePrimaryNode(episode: SpamFloodEpisode): string {
  const cluster = primaryEpisodeCluster(episode);
  if (cluster) {
    return formatClusterHotspotLabel(cluster);
  }
  const hop = episode.primary_origin_hop ?? episode.primary_entry_hop;
  const name = episode.primary_origin_name ?? episode.primary_entry_name;
  if (name && hop) return `${name} (${hop})`;
  if (hop) return hop;
  return '-';
}

function formatEpisodeLocationSummary(episode: SpamFloodEpisode): string {
  return formatEpisodeLocSummary(episode, episodeReportClusters(episode));
}

function EpisodeSummarySegment({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="inline-flex shrink-0 items-baseline gap-1">
      <span className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span>{children}</span>
    </span>
  );
}

interface SpamRoutesViewProps {
  liveStatus?: SpamLiveStatus | null;
  onLiveStatusChange?: (status: SpamLiveStatus) => void;
}

export function SpamRoutesView({ liveStatus, onLiveStatusChange }: SpamRoutesViewProps) {
  const [data, setData] = useState<SpamRouteStatsResponse | null>(null);
  const [localLiveStatus, setLocalLiveStatus] = useState<SpamLiveStatus | null>(liveStatus ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [episodes, setEpisodes] = useState<SpamFloodEpisode[]>([]);
  const [episodesLoading, setEpisodesLoading] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    if (liveStatus != null) {
      setLocalLiveStatus(liveStatus);
    }
  }, [liveStatus]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getSpamRouteStats({
        windowHours: HISTORICAL_WINDOW_HOURS,
        limit: 25,
        repeaterLimit: 25,
      })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load spam paths');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshNonce]);

  useEffect(() => {
    let cancelled = false;
    setEpisodesLoading(true);
    api
      .getSpamFloodEpisodes({ limit: 50 })
      .then((result) => {
        if (!cancelled) setEpisodes(result.episodes);
      })
      .catch((err) => {
        if (!cancelled) console.error(err);
      })
      .finally(() => {
        if (!cancelled) setEpisodesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshNonce]);

  useEffect(() => {
    let cancelled = false;

    const refreshLive = () => {
      api
        .getSpamLiveStatus()
        .then((status) => {
          if (cancelled) return;
          setLocalLiveStatus(status);
          onLiveStatusChange?.(status);
        })
        .catch((err) => {
          if (!cancelled) console.error(err);
        });

      api
        .getSpamFloodEpisodes({ limit: 50 })
        .then((result) => {
          if (!cancelled) setEpisodes(result.episodes);
        })
        .catch((err) => {
          if (!cancelled) console.error(err);
        });
    };

    refreshLive();
    const intervalId = window.setInterval(refreshLive, LIVE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [onLiveStatusChange]);

  const topForensicHops = useMemo(() => {
    return [...(data?.repeaters ?? [])]
      .filter((item) => suspectScore(item) > 0)
      .sort((a, b) => {
        const suspectDelta = suspectScore(b) - suspectScore(a);
        if (suspectDelta !== 0) return suspectDelta;
        return (b.last_seen ?? 0) - (a.last_seen ?? 0);
      })
      .slice(0, 5);
  }, [data]);
  const live = localLiveStatus;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-background">
      <div className="border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-base">Spam Path Analysis</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Live flood hotspots and episode history above; optional 24h DM-path forensics below.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => setRefreshNonce((value) => value + 1)}
              disabled={loading}
              title="Refresh"
              aria-label="Refresh spam path analysis"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>

      <div className="space-y-6 px-4 py-4">
        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <SpamPacketTimelineSection refreshNonce={refreshNonce} />

        <LiveFloodSection live={live} />

        <FloodEpisodeLogSection
          episodes={episodes}
          loading={episodesLoading}
          onEpisodeDeleted={(episodeId) =>
            setEpisodes((current) => current.filter((episode) => episode.id !== episodeId))
          }
        />

        <details className="group rounded-md border border-border">
          <summary className="cursor-pointer list-none px-3 py-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold">Historical forensics (last 24 hours)</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Retrospective look at all direct-message path observations — not flood-filtered and
                  without gateway stripping or geo merge. Use for post-incident RF debugging; prefer Live
                  Flood Monitor and episode reports for attack hotspots.
                </p>
              </div>
              <span className="text-xs text-muted-foreground group-open:hidden">Show</span>
              <span className="hidden text-xs text-muted-foreground group-open:inline">Hide</span>
            </div>
          </summary>
          <div className="space-y-6 border-t border-border px-3 py-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Metric
                icon={<Crosshair className="h-4 w-4" aria-hidden="true" />}
                label="Top suspect hops"
                value={topForensicHops.length}
              />
              <Metric
                icon={<RadioTower className="h-4 w-4" aria-hidden="true" />}
                label="Path observations"
                value={data?.total_observations ?? 0}
              />
              <Metric
                icon={<Route className="h-4 w-4" aria-hidden="true" />}
                label="Unique hops"
                value={data?.repeaters.length ?? 0}
              />
            </div>

            <section className="space-y-2">
              <div>
                <h4 className="text-sm font-semibold">Top suspect hops (24h)</h4>
                <p className="mt-1 text-xs text-muted-foreground">
                  Ranked by path position and prefix concentration across all DM paths in the last day —
                  similar math to live clustering, but not episode-scoped.
                </p>
              </div>
              <div className="grid gap-2 lg:grid-cols-5">
                {topForensicHops.map((item, index) => {
                  const hasCoords = item.lat != null && item.lon != null;
                  return (
                    <div key={item.hop} className="rounded-md border border-border bg-muted/15 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <div className="font-medium">{formatHopLabel(item)}</div>
                          <div className="font-mono text-xs text-muted-foreground">{item.hop}</div>
                        </div>
                        <div className="rounded bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                          #{index + 1}
                        </div>
                      </div>
                      <div className="mt-3 space-y-2 text-xs">
                        <StatBar
                          label="Suspect score"
                          value={formatPercent(suspectScore(item))}
                          width={suspectScore(item)}
                        />
                        <div>
                          <div className="text-muted-foreground">Narrowed prefix</div>
                          <div
                            className="mt-0.5 truncate font-mono text-foreground"
                            title={item.narrowed_prefix || item.hop}
                          >
                            {item.narrowed_prefix || item.hop}
                          </div>
                        </div>
                        <div className="flex justify-between gap-2">
                          <span className="text-muted-foreground">Path uses</span>
                          <span className="font-medium tabular-nums">{item.observation_count}</span>
                        </div>
                        {hasCoords && (
                          <a
                            href={buildMapUrl(item.lat!, item.lon!)}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-primary hover:underline"
                          >
                            <MapPin className="h-3 w-3" aria-hidden="true" />
                            Open map
                            <ExternalLink className="h-3 w-3" aria-hidden="true" />
                          </a>
                        )}
                      </div>
                    </div>
                  );
                })}
                {!loading && topForensicHops.length === 0 && (
                  <div className="rounded-md border border-border px-3 py-6 text-center text-sm text-muted-foreground lg:col-span-5">
                    No DM paths with hop data in the last 24 hours.
                  </div>
                )}
                {loading && (
                  <div className="rounded-md border border-border px-3 py-6 text-center text-sm text-muted-foreground lg:col-span-5">
                    Loading...
                  </div>
                )}
              </div>
            </section>

            <section className="space-y-2">
              <div>
                <h4 className="text-sm font-semibold">Hop forensics</h4>
                <p className="mt-1 text-xs text-muted-foreground">
                  Per-hop counts for source-side vs relay vs radio-side position on each path.
                </p>
              </div>
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full min-w-[900px] text-sm">
                  <thead className="bg-muted/60 text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left">Hop</th>
                      <th className="px-3 py-2 text-right">Suspect</th>
                      <th className="px-3 py-2 text-left">Narrowed Prefix</th>
                      <th className="px-3 py-2 text-right">Uses</th>
                      <th className="px-3 py-2 text-right">Source</th>
                      <th className="px-3 py-2 text-right">Middle</th>
                      <th className="px-3 py-2 text-right">Radio</th>
                      <th className="px-3 py-2 text-right">Routes</th>
                      <th className="px-3 py-2 text-right">Last Seen</th>
                      <th className="px-3 py-2 text-right">Avg RSSI</th>
                      <th className="px-3 py-2 text-right">Avg SNR</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {data?.repeaters.map((item) => (
                      <tr key={item.hop} className="hover:bg-muted/30">
                        <td className="px-3 py-2">
                          <div className="font-medium">{formatHopLabel(item)}</div>
                          <div className="font-mono text-xs text-muted-foreground">{item.hop}</div>
                        </td>
                        <td className="px-3 py-2 text-right">
                          <span className="font-medium tabular-nums">
                            {formatPercent(suspectScore(item))}
                          </span>
                        </td>
                        <td className="px-3 py-2 font-mono text-xs">{item.narrowed_prefix || '-'}</td>
                        <td className="px-3 py-2 text-right">{item.observation_count}</td>
                        <td className="px-3 py-2 text-right">{item.source_side_count}</td>
                        <td className="px-3 py-2 text-right">{item.middle_count}</td>
                        <td className="px-3 py-2 text-right">{item.radio_side_count}</td>
                        <td className="px-3 py-2 text-right">{item.route_count}</td>
                        <td className="px-3 py-2 text-right">{formatSeen(item.last_seen)}</td>
                        <td className="px-3 py-2 text-right">{formatSignal(item.avg_rssi, 'dBm')}</td>
                        <td className="px-3 py-2 text-right">{formatSignal(item.avg_snr, 'dB')}</td>
                      </tr>
                    ))}
                    {!loading && data?.repeaters.length === 0 && (
                      <tr>
                        <td className="px-3 py-6 text-center text-muted-foreground" colSpan={11}>
                          No direct-message paths found in the last 24 hours.
                        </td>
                      </tr>
                    )}
                    {loading && (
                      <tr>
                        <td className="px-3 py-6 text-center text-muted-foreground" colSpan={11}>
                          Loading...
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="space-y-2">
              <div>
                <h4 className="text-sm font-semibold">Most used full routes (24h)</h4>
                <p className="mt-1 text-xs text-muted-foreground">
                  Exact path strings ranked by how often they appeared on stored DMs and raw DM packets.
                </p>
              </div>
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="bg-muted/60 text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left">Route</th>
                      <th className="px-3 py-2 text-right">Uses</th>
                      <th className="px-3 py-2 text-right">DMs</th>
                      <th className="px-3 py-2 text-right">Conversations</th>
                      <th className="px-3 py-2 text-right">Hops</th>
                      <th className="px-3 py-2 text-right">Last Seen</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {data?.routes.map((item) => (
                      <tr key={`${item.path}-${item.path_len}`} className="hover:bg-muted/30">
                        <td className="px-3 py-2 font-mono">{item.route}</td>
                        <td className="px-3 py-2 text-right">{item.observation_count}</td>
                        <td className="px-3 py-2 text-right">{item.message_count}</td>
                        <td className="px-3 py-2 text-right">{item.conversation_count}</td>
                        <td className="px-3 py-2 text-right">{item.hop_count}</td>
                        <td className="px-3 py-2 text-right">{formatSeen(item.last_seen)}</td>
                      </tr>
                    ))}
                    {!loading && data?.routes.length === 0 && (
                      <tr>
                        <td className="px-3 py-6 text-center text-muted-foreground" colSpan={6}>
                          No routes in the last 24 hours.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </details>
      </div>
    </div>
  );
}

function LiveFloodSection({ live }: { live: SpamLiveStatus | null }) {
  if (!live) {
    return (
      <section className="rounded-md border border-border bg-muted/10 px-3 py-4 text-sm text-muted-foreground">
        Loading live flood monitor...
      </section>
    );
  }

  const categoryFloods = live.category_floods ?? [];
  const activeFloods = categoryFloods.filter((item) => item.active);

  if (!live.active) {
    return (
      <section className="rounded-md border border-border bg-muted/10 px-3 py-3 space-y-2">
        <div>
          <h3 className="text-sm font-semibold">Live Flood Monitor</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Each packet type is tracked separately in the last {live.window_secs}s window (
            {live.packet_threshold}+ packets to trigger).
          </p>
        </div>
        {categoryFloods.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {categoryFloods.map((item) => (
              <div
                key={item.category}
                className="rounded bg-muted px-2 py-1 text-xs font-medium text-muted-foreground"
              >
                {item.category_label}: {item.total_packets} / {item.packet_threshold}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
            0 / {live.packet_threshold} packets
          </div>
        )}
      </section>
    );
  }

  return (
    <div className="space-y-3">
      {activeFloods.map((flood) => (
        <LiveCategoryFloodCard key={flood.category} flood={flood} />
      ))}
    </div>
  );
}

function LiveCategoryFloodCard({ flood }: { flood: SpamCategoryFloodStatus }) {
  return (
    <section className="space-y-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden="true" />
          <div>
            <h3 className="text-sm font-semibold text-destructive">
              {flood.category_label} Flood Detected
            </h3>
            <p className="mt-1 text-xs text-destructive/90">
              {flood.episode_packets > 0
                ? `${flood.episode_packets} packets in episode`
                : `${flood.total_packets} packets`}
              {' · '}
              {flood.total_packets} {flood.category_label.toLowerCase()} pkts in last {flood.window_secs}s
              {flood.baseline_packets_per_window != null
                ? ` · baseline ${flood.baseline_packets_per_window.toFixed(1)}/${flood.window_secs}s`
                : ''}
              {flood.anomaly_ratio != null ? ` · ${flood.anomaly_ratio.toFixed(1)}x normal` : ''}
              {flood.detected_at != null ? ` · since ${formatSeen(flood.detected_at)}` : ''}
              {flood.total_packets < flood.packet_threshold ? ' · hold active' : ''}
            </p>
          </div>
        </div>
        <div className="rounded bg-destructive/15 px-2 py-1 text-[0.625rem] font-semibold uppercase tracking-wider text-destructive">
          Live alarm
        </div>
      </div>

      <LikelySourceBanner source={flood} />

      {flood.source_filter_active && flood.source_filter_labels && flood.source_filter_labels.length > 0 && (
        <p className="text-xs text-destructive/90">
          Path clustering scoped to sender{' '}
          {flood.source_filter_mode === 'multi' ? 'identities' : 'identity'}{' '}
          {flood.source_filter_labels.join(' + ')}
          {flood.source_filter_excluded_packets != null && flood.source_filter_excluded_packets > 0
            ? ` (${flood.source_filter_excluded_packets} side-traffic paths excluded)`
            : ''}
          .
        </p>
      )}
      {flood.source_filter_mode === 'rotating' && (
        <p className="text-xs text-destructive/90">
          Sender hash is cycling across many identities — path clustering uses all RF paths instead
          of filtering to one from byte.
        </p>
      )}

      {flood.clusters.length === 0 ? (
        <p className="text-xs text-destructive/90">
          Flood volume is high, but no ingress hop reached the minimum share yet (
          {formatPercent(flood.cluster_min_share ?? 0.15)} of episode paths must share a prefix).
        </p>
      ) : (
        <div className="space-y-2">
          {flood.clusters_stale && (
            <p className="text-xs text-destructive/90">
              Showing peak hotspot snapshot while current paths are too dispersed for a fresh match.
            </p>
          )}
          <div className="grid gap-2 lg:grid-cols-2 xl:grid-cols-3 max-h-[32rem] overflow-y-auto pr-1">
            {flood.clusters.map((cluster, index) => (
              <LiveHotspotCard key={`${flood.category}-${cluster.entry_hop}-${index}`} cluster={cluster} index={index} />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function LiveHotspotCard({ cluster, index }: { cluster: SpamFloodCluster; index: number }) {
  const showRefinedRoute =
    cluster.refined_route &&
    cluster.refined_route !== cluster.dominant_route &&
    cluster.narrowing_depth > 1;

  return (
    <div className="rounded-md border border-destructive/30 bg-background/80 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold">
          Attack Hotspot #{index + 1}
          {cluster.flood_source_label ? (
            <span className="ml-2 text-xs font-medium text-muted-foreground">
              from {cluster.flood_source_label}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {clusterModeBadge(cluster)}
          {cluster.confidence > 0 && (
            <div
              className="rounded bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
              title={
                cluster.cluster_mode === 'entry_fallback'
                  ? 'Low confidence is expected for split-ingress grouping; traffic share is the stronger signal.'
                  : undefined
              }
            >
              {cluster.confidence}% conf
            </div>
          )}
          {cluster.traffic_share > 0 && (
            <div className="rounded bg-destructive/10 px-2 py-0.5 text-xs font-semibold text-destructive">
              {formatPercent(cluster.traffic_share)} of flood
            </div>
          )}
          <div className="rounded bg-destructive/10 px-2 py-0.5 text-xs font-semibold text-destructive">
            {cluster.packet_count} pkts
          </div>
        </div>
      </div>
      <div className="mt-3 space-y-2 text-xs">
        {showRefinedRoute && (
          <div>
            <div className="text-muted-foreground">
              Narrowed hotspot ({cluster.narrowing_depth} hops · {formatPercent(cluster.traffic_share)} share)
            </div>
            <div className="mt-0.5 font-mono text-sm text-destructive">{cluster.refined_route}</div>
          </div>
        )}
        <ClusterRouteDetails cluster={cluster} />
        {cluster.origin_hop && cluster.origin_hop !== cluster.entry_hop && (
          <div>
            <div className="text-muted-foreground">Estimated source-side hop</div>
            <div className="mt-0.5 font-medium">
              {cluster.origin_name ?? `[${cluster.origin_hop}]`}
              <span className="ml-2 font-mono text-muted-foreground">{cluster.origin_hop}</span>
            </div>
          </div>
        )}
        <div className="text-muted-foreground">Last seen {formatSeen(cluster.last_seen)}</div>
      </div>
    </div>
  );
}

function EpisodeHotspotCandidates({ clusters }: { clusters: SpamFloodCluster[] }) {
  return (
    <div className="space-y-2">
      {clusters.map((cluster, index) => {
        return (
          <div
            key={`${cluster.entry_hop}-${index}`}
            className="rounded border border-border/70 bg-muted/20 px-2 py-1.5"
          >
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-semibold">#{index + 1}</span>
              <span className="font-medium">{formatClusterHotspotLabel(cluster)}</span>
              {clusterModeBadge(cluster)}
              <span className="text-muted-foreground">
                {cluster.packet_count} pkts
                {cluster.traffic_share > 0 ? ` · ${formatPercent(cluster.traffic_share)} of flood` : ''}
                {cluster.confidence > 0 ? ` · ${cluster.confidence}% conf` : ''}
              </span>
            </div>
            <ClusterRouteDetails cluster={cluster} />
          </div>
        );
      })}
    </div>
  );
}

function FloodEpisodeDetailDialog({
  episode,
  open,
  onOpenChange,
  onDelete,
  deleting,
}: {
  episode: SpamFloodEpisode | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDelete: (episodeId: number) => void;
  deleting: boolean;
}) {
  if (!episode) return null;

  const reportClusters = episodeReportClusters(episode);
  const inProgress = episode.ended_at == null;
  const coords = resolveEpisodeLocationCoords(episode, reportClusters);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Flood report #{episode.id}</DialogTitle>
          <DialogDescription>
            {inProgress
              ? 'Attack still in progress when this snapshot was saved.'
              : 'Full hotspot analysis retained from the ended episode.'}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
            <div className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">Started</div>
            <div className="mt-1 text-sm">{formatSeen(episode.started_at)}</div>
          </div>
          <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
            <div className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">Ended</div>
            <div className="mt-1 text-sm">{inProgress ? 'In progress' : formatSeen(episode.ended_at)}</div>
          </div>
          <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
            <div className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">Flood type</div>
            <div className="mt-1 text-sm">{formatEpisodeFloodType(episode)}</div>
          </div>
          {episode.likely_source_key && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 sm:col-span-2">
              <div className="text-[0.625rem] uppercase tracking-wider text-destructive">
                Likely spam source
              </div>
              <div className="mt-1 text-sm font-medium">
                {formatLikelySourceSummary(episode) ?? episode.likely_source_label}
              </div>
            </div>
          )}
          <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
            <div className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">Duration</div>
            <div className="mt-1 text-sm tabular-nums">
              {inProgress ? '…' : formatDuration(episode.duration_secs)}
            </div>
          </div>
          <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
            <div className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">Packets</div>
            <div className="mt-1 text-sm tabular-nums">{episode.total_packets}</div>
          </div>
          <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
            <div className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">Peak / window</div>
            <div className="mt-1 text-sm tabular-nums">{episode.peak_packets_per_window}</div>
          </div>
          <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
            <div className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">Vs baseline</div>
            <div className="mt-1 text-sm tabular-nums">
              {episode.anomaly_ratio != null ? `${episode.anomaly_ratio.toFixed(1)}×` : '-'}
            </div>
          </div>
        </div>

        <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
          <div className="text-[0.625rem] uppercase tracking-wider text-muted-foreground">Primary hotspot</div>
          <div className="mt-1 text-sm font-medium">{formatEpisodePrimaryNode(episode)}</div>
          {coords ? (
            <a
              href={buildMapUrl(coords.lat, coords.lon)}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex items-center gap-1 font-mono text-[0.8125rem] text-primary hover:underline"
            >
              {coords.lat.toFixed(5)}, {coords.lon.toFixed(5)}
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
          ) : (
            <div className="mt-1 text-[0.8125rem] text-muted-foreground">
              {formatEpisodeLocationSummary(episode)}
            </div>
          )}
        </div>

        <div>
          <h4 className="text-sm font-semibold">Hotspot candidates</h4>
          <div className="mt-2">
            {reportClusters.length > 0 ? (
              <EpisodeHotspotCandidates clusters={reportClusters} />
            ) : (
              <span className="text-sm text-muted-foreground">No narrowed hotspots</span>
            )}
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            type="button"
            variant="outline"
            className="border-destructive/40 text-destructive hover:bg-destructive/10"
            onClick={() => onDelete(episode.id)}
            disabled={deleting}
          >
            <Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />
            Delete report
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function FloodEpisodeLogSection({
  episodes,
  loading,
  onEpisodeDeleted,
}: {
  episodes: SpamFloodEpisode[];
  loading: boolean;
  onEpisodeDeleted: (episodeId: number) => void;
}) {
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [selectedEpisode, setSelectedEpisode] = useState<SpamFloodEpisode | null>(null);

  const handleDelete = async (episodeId: number) => {
    setDeletingId(episodeId);
    setDeleteError(null);
    try {
      await api.deleteSpamFloodEpisode(episodeId);
      onEpisodeDeleted(episodeId);
      if (selectedEpisode?.id === episodeId) {
        setSelectedEpisode(null);
      }
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete flood report');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <section className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold">Flood Alert History</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Compact summary of persisted attacks. Click a row for the full hotspot log (up to five
          candidates). Stuck in-progress rows usually mean the server restarted mid-attack.
        </p>
      </div>
      {deleteError && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {deleteError}
        </div>
      )}
      <div className="space-y-2">
        {episodes.map((episode) => {
          const inProgress = episode.ended_at == null;
          return (
            <div
              key={episode.id}
              className="flex items-stretch gap-2 rounded-md border border-border bg-muted/10"
            >
              <button
                type="button"
                className={cn(
                  'min-w-0 flex-1 rounded-md px-3 py-2 text-left text-xs transition-colors',
                  'hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                )}
                onClick={() => setSelectedEpisode(episode)}
                aria-label={`Open flood report ${episode.id}`}
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <EpisodeSummarySegment label="Start">{formatSeen(episode.started_at)}</EpisodeSummarySegment>
                  <span className="text-muted-foreground/50">·</span>
                  <EpisodeSummarySegment label="End">
                    {inProgress ? '…' : formatSeen(episode.ended_at)}
                  </EpisodeSummarySegment>
                  <span className="text-muted-foreground/50">·</span>
                  <EpisodeSummarySegment label="Duration">
                    {inProgress ? '…' : formatDuration(episode.duration_secs)}
                  </EpisodeSummarySegment>
                  <span className="text-muted-foreground/50">·</span>
                  <EpisodeSummarySegment label="Pkts">{episode.total_packets}</EpisodeSummarySegment>
                  <span className="text-muted-foreground/50">·</span>
                  <EpisodeSummarySegment label="Peak">{episode.peak_packets_per_window}</EpisodeSummarySegment>
                  <span className="text-muted-foreground/50">·</span>
                  <EpisodeSummarySegment label="Type">{formatEpisodeFloodType(episode)}</EpisodeSummarySegment>
                  {episode.likely_source_key && (
                    <>
                      <span className="text-muted-foreground/50">·</span>
                      <EpisodeSummarySegment label="From">
                        {formatLikelySourceSummary(episode) ?? episode.likely_source_label}
                      </EpisodeSummarySegment>
                    </>
                  )}
                  <span className="text-muted-foreground/50">·</span>
                  <EpisodeSummarySegment label="#1">{formatEpisodePrimaryNode(episode)}</EpisodeSummarySegment>
                  <span className="text-muted-foreground/50">·</span>
                  <EpisodeSummarySegment label="Loc">
                    <span className="font-mono text-[0.6875rem]">{formatEpisodeLocationSummary(episode)}</span>
                  </EpisodeSummarySegment>
                  {inProgress && (
                    <>
                      <span className="text-muted-foreground/50">·</span>
                      <span className="text-[0.625rem] font-semibold uppercase tracking-wider text-destructive">
                        In progress
                      </span>
                    </>
                  )}
                </div>
              </button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="my-1 mr-1 shrink-0 self-center border-destructive/40 text-destructive hover:bg-destructive/10"
                onClick={() => void handleDelete(episode.id)}
                disabled={deletingId === episode.id}
                title="Delete flood report"
                aria-label={`Delete flood report ${episode.id}`}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          );
        })}
        {!loading && episodes.length === 0 && (
          <div className="rounded-md border border-border px-3 py-6 text-center text-sm text-muted-foreground">
            No flood episodes recorded yet.
          </div>
        )}
        {loading && (
          <div className="rounded-md border border-border px-3 py-6 text-center text-sm text-muted-foreground">
            Loading flood history...
          </div>
        )}
      </div>

      <FloodEpisodeDetailDialog
        episode={selectedEpisode}
        open={selectedEpisode != null}
        onOpenChange={(open) => {
          if (!open) setSelectedEpisode(null);
        }}
        onDelete={(episodeId) => void handleDelete(episodeId)}
        deleting={selectedEpisode != null && deletingId === selectedEpisode.id}
      />
    </section>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
      <div className="flex items-center gap-2 text-xs uppercase text-muted-foreground">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value.toLocaleString()}</div>
    </div>
  );
}

function StatBar({ label, value, width }: { label: string; value: string; width: number }) {
  return (
    <div>
      <div className="mb-1 flex justify-between gap-2">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">{value}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-primary" style={{ width: `${Math.max(4, width * 100)}%` }} />
      </div>
    </div>
  );
}
