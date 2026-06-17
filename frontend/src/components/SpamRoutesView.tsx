import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, Crosshair, ExternalLink, MapPin, RadioTower, RefreshCw, Route } from 'lucide-react';

import { api } from '../api';
import type {
  SpamFloodCluster,
  SpamLiveStatus,
  SpamRepeaterStat,
  SpamRouteStat,
  SpamRouteStatsResponse,
} from '../types';
import { Button } from './ui/button';

type WindowOption = 1 | 6 | 24 | 72 | 168;

const WINDOW_OPTIONS: WindowOption[] = [1, 6, 24, 72, 168];
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

function sourceRatio(item: SpamRepeaterStat): number {
  if (item.observation_count <= 0) return 0;
  return item.source_side_count / item.observation_count;
}

function getRoutePreview(routes: SpamRouteStat[], hop: string): string {
  const route = routes.find((item) => item.hop_tokens[0] === hop);
  return route?.route ?? '-';
}

function buildMapUrl(lat: number, lon: number): string {
  return `https://www.google.com/maps?q=${lat},${lon}`;
}

interface SpamRoutesViewProps {
  liveStatus?: SpamLiveStatus | null;
  onLiveStatusChange?: (status: SpamLiveStatus) => void;
}

export function SpamRoutesView({ liveStatus, onLiveStatusChange }: SpamRoutesViewProps) {
  const [windowHours, setWindowHours] = useState<WindowOption>(24);
  const [data, setData] = useState<SpamRouteStatsResponse | null>(null);
  const [localLiveStatus, setLocalLiveStatus] = useState<SpamLiveStatus | null>(liveStatus ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      .getSpamRouteStats({ windowHours, limit: 50, repeaterLimit: 50 })
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
  }, [windowHours, refreshNonce]);

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
    };

    refreshLive();
    const intervalId = window.setInterval(refreshLive, LIVE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [onLiveStatusChange]);

  const sourceSideMax = useMemo(
    () => Math.max(1, ...(data?.repeaters.map((item) => item.source_side_count) ?? [0])),
    [data]
  );
  const topSourceCandidates = useMemo(() => {
    const routes = data?.routes ?? [];
    return [...(data?.repeaters ?? [])]
      .filter((item) => item.source_side_count > 0)
      .sort((a, b) => {
        const sourceDelta = b.source_side_count - a.source_side_count;
        if (sourceDelta !== 0) return sourceDelta;
        const ratioDelta = sourceRatio(b) - sourceRatio(a);
        if (ratioDelta !== 0) return ratioDelta;
        return (b.last_seen ?? 0) - (a.last_seen ?? 0);
      })
      .slice(0, 5)
      .map((item) => ({
        ...item,
        sourceRatio: sourceRatio(item),
        routePreview: getRoutePreview(routes, item.hop),
      }));
  }, [data]);
  const topRoute = data?.routes[0];
  const live = localLiveStatus;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-background">
      <div className="border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-base">Spam Path Analysis</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Live flood detection plus historical direct-message path observations.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={windowHours}
              onChange={(event) => setWindowHours(Number(event.target.value) as WindowOption)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              aria-label="Analysis window"
            >
              {WINDOW_OPTIONS.map((hours) => (
                <option key={hours} value={hours}>
                  {hours < 24 ? `${hours}h` : `${hours / 24}d`}
                </option>
              ))}
            </select>
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

        <LiveFloodSection live={live} />

        <div className="grid gap-3 sm:grid-cols-3">
          <Metric
            icon={<Crosshair className="h-4 w-4" aria-hidden="true" />}
            label="Source Candidates"
            value={topSourceCandidates.length}
          />
          <Metric
            icon={<RadioTower className="h-4 w-4" aria-hidden="true" />}
            label="Path Observations"
            value={data?.total_observations ?? 0}
          />
          <Metric
            icon={<Route className="h-4 w-4" aria-hidden="true" />}
            label="Unique Hops"
            value={data?.repeaters.length ?? 0}
          />
        </div>

        <section className="space-y-2">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <h3 className="text-sm font-semibold">Likely Closest To Source</h3>
            {topRoute && (
              <div className="max-w-full truncate text-xs text-muted-foreground">
                Top route: <span className="font-mono text-foreground">{topRoute.route}</span>
              </div>
            )}
          </div>
          <div className="grid gap-2 lg:grid-cols-5">
            {topSourceCandidates.map((item, index) => (
              <div key={item.hop} className="rounded-md border border-border bg-muted/15 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-mono text-lg font-semibold">{item.hop}</div>
                  <div className="rounded bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                    #{index + 1}
                  </div>
                </div>
                <div className="mt-3 space-y-2 text-xs">
                  <StatBar
                    label="Source ratio"
                    value={formatPercent(item.sourceRatio)}
                    width={item.sourceRatio}
                  />
                  <div className="flex justify-between gap-2">
                    <span className="text-muted-foreground">Source hits</span>
                    <span className="font-medium tabular-nums">{item.source_side_count}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-muted-foreground">Total uses</span>
                    <span className="font-medium tabular-nums">{item.observation_count}</span>
                  </div>
                  <div className="truncate font-mono text-muted-foreground" title={item.routePreview}>
                    {item.routePreview}
                  </div>
                </div>
              </div>
            ))}
            {!loading && topSourceCandidates.length === 0 && (
              <div className="rounded-md border border-border px-3 py-6 text-center text-sm text-muted-foreground lg:col-span-5">
                No source-side hops found in this window.
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
          <h3 className="text-sm font-semibold">Hop Position Breakdown</h3>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="bg-muted/60 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">Hop</th>
                  <th className="px-3 py-2 text-right">Source Ratio</th>
                  <th className="px-3 py-2 text-right">Uses</th>
                  <th className="px-3 py-2 text-right">Source Side</th>
                  <th className="px-3 py-2 text-right">Middle</th>
                  <th className="px-3 py-2 text-right">Radio Side</th>
                  <th className="px-3 py-2 text-right">Routes</th>
                  <th className="px-3 py-2 text-right">Last Seen</th>
                  <th className="px-3 py-2 text-right">Avg RSSI</th>
                  <th className="px-3 py-2 text-right">Avg SNR</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data?.repeaters.map((item) => (
                  <tr key={item.hop} className="hover:bg-muted/30">
                    <td className="px-3 py-2 font-mono font-semibold">{item.hop}</td>
                    <td className="px-3 py-2 text-right">
                      <span className="font-medium tabular-nums">{formatPercent(sourceRatio(item))}</span>
                    </td>
                    <td className="px-3 py-2 text-right">{item.observation_count}</td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full bg-primary"
                            style={{
                              width: `${Math.max(4, (item.source_side_count / sourceSideMax) * 100)}%`,
                            }}
                          />
                        </div>
                        <span>{item.source_side_count}</span>
                      </div>
                    </td>
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
                    <td className="px-3 py-6 text-center text-muted-foreground" colSpan={10}>
                      No direct-message paths found in this window.
                    </td>
                  </tr>
                )}
                {loading && (
                  <tr>
                    <td className="px-3 py-6 text-center text-muted-foreground" colSpan={10}>
                      Loading...
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold">Most Used Full Routes</h3>
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
              </tbody>
            </table>
          </div>
        </section>
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

  if (!live.active) {
    return (
      <section className="rounded-md border border-border bg-muted/10 px-3 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold">Live Flood Monitor</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Watching the last {live.window_secs}s for {live.packet_threshold}+ DM path observations.
            </p>
          </div>
          <div className="rounded bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
            {live.total_packets} / {live.packet_threshold} packets
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden="true" />
          <div>
            <h3 className="text-sm font-semibold text-destructive">Coordinated DM Flood Detected</h3>
            <p className="mt-1 text-xs text-destructive/90">
              {live.total_packets} packets in {live.window_secs}s
              {live.detected_at != null ? ` · since ${formatSeen(live.detected_at)}` : ''}
              {live.total_packets < live.packet_threshold ? ' · hold active' : ''}
            </p>
          </div>
        </div>
        <div className="rounded bg-destructive/15 px-2 py-1 text-[0.625rem] font-semibold uppercase tracking-wider text-destructive">
          Live alarm
        </div>
      </div>

      {live.clusters.length === 0 ? (
        <p className="text-xs text-destructive/90">
          Flood volume exceeded threshold, but no ingress cluster met the minimum share yet.
        </p>
      ) : (
        <div className="grid gap-2 lg:grid-cols-2">
          {live.clusters.map((cluster, index) => (
            <LiveHotspotCard key={`${cluster.entry_hop}-${index}`} cluster={cluster} index={index} />
          ))}
        </div>
      )}
    </section>
  );
}

function LiveHotspotCard({ cluster, index }: { cluster: SpamFloodCluster; index: number }) {
  const hasCoords = cluster.lat != null && cluster.lon != null;

  return (
    <div className="rounded-md border border-destructive/30 bg-background/80 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold">Attack Hotspot #{index + 1}</div>
        <div className="rounded bg-destructive/10 px-2 py-0.5 text-xs font-semibold text-destructive">
          {cluster.packet_count} pkts
        </div>
      </div>
      <div className="mt-3 space-y-2 text-xs">
        <div>
          <div className="text-muted-foreground">RF ingress path</div>
          <div className="mt-0.5 font-mono text-sm">{cluster.dominant_route}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Primary entry hop</div>
          <div className="mt-0.5 font-medium">
            {cluster.entry_name ?? `[${cluster.entry_hop}]`}
            <span className="ml-2 font-mono text-muted-foreground">{cluster.entry_hop}</span>
          </div>
        </div>
        {hasCoords && (
          <div className="flex flex-wrap items-center gap-2">
            <MapPin className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <span className="font-mono tabular-nums">
              {cluster.lat!.toFixed(5)}, {cluster.lon!.toFixed(5)}
            </span>
            <a
              href={buildMapUrl(cluster.lat!, cluster.lon!)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              Open map
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
          </div>
        )}
        <div className="text-muted-foreground">Last seen {formatSeen(cluster.last_seen)}</div>
      </div>
    </div>
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
