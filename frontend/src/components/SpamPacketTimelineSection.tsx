import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { api } from '../api';
import type { SpamPacketTimelineResponse } from '../types';

const TIMELINE_POLL_MS = 5 * 60 * 1000;

const CATEGORY_COLORS: Record<string, string> = {
  pm_transport: '#ef4444',
  dm: '#f97316',
  group_transport: '#ec4899',
  group_text: '#8b5cf6',
  response: '#10b981',
  request: '#0ea5e9',
  path: '#14b8a6',
  ack: '#6366f1',
  advert: '#22c55e',
  anon_request: '#eab308',
  trace: '#84cc16',
  control: '#64748b',
  other: '#94a3b8',
};

const TOOLTIP_STYLE = {
  contentStyle: {
    backgroundColor: 'hsl(var(--popover))',
    border: '1px solid hsl(var(--border))',
    borderRadius: '6px',
    fontSize: '11px',
    color: 'hsl(var(--popover-foreground))',
  },
  itemStyle: { color: 'hsl(var(--popover-foreground))' },
  labelStyle: { color: 'hsl(var(--muted-foreground))' },
} as const;

function formatBucketLabel(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function formatGeneratedAt(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

interface TimelineChartRow {
  idx: number;
  label: string;
  total: number;
  [category: string]: string | number;
}

interface SpamPacketTimelineSectionProps {
  refreshNonce?: number;
}

export function SpamPacketTimelineSection({ refreshNonce = 0 }: SpamPacketTimelineSectionProps) {
  const [data, setData] = useState<SpamPacketTimelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = (showLoading: boolean) => {
      if (showLoading) {
        setLoading(true);
        setError(null);
      }
      api
        .getSpamPacketTimeline({ windowHours: 24, bucketMinutes: 30 })
        .then((result) => {
          if (!cancelled) {
            setData(result);
            setError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : 'Failed to load packet timeline');
          }
        })
        .finally(() => {
          if (!cancelled && showLoading) setLoading(false);
        });
    };

    load(true);
    const intervalId = window.setInterval(() => load(false), TIMELINE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [refreshNonce]);

  const chartData = useMemo(() => {
    if (!data) return [];
    return data.buckets.map((bucket, index): TimelineChartRow => {
      const entry: TimelineChartRow = {
        idx: index,
        label: formatBucketLabel(bucket.timestamp),
        total: bucket.total,
      };
      for (const category of data.categories) {
        entry[category] = bucket.counts[category] ?? 0;
      }
      return entry;
    });
  }, [data]);

  const tickIndices = useMemo(() => {
    if (chartData.length <= 1) return chartData.length === 1 ? [0] : [];
    const tickCount = Math.min(6, chartData.length);
    const indices: number[] = [];
    for (let i = 0; i < tickCount; i += 1) {
      indices.push(Math.round((i / (tickCount - 1)) * (chartData.length - 1)));
    }
    return indices;
  }, [chartData]);

  return (
    <section className="space-y-2 rounded-md border border-border bg-muted/10 px-3 py-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">24-Hour Packet Activity</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Database-backed packet mix by type. Refreshes every 5 minutes while this page is open.
          </p>
        </div>
        {data && (
          <div className="text-xs text-muted-foreground">
            {data.total_packets.toLocaleString()} packets · updated {formatGeneratedAt(data.generated_at)}
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {data && data.categories.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[0.6875rem] text-muted-foreground">
          {data.categories.map((category) => (
            <span key={category} className="inline-flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: CATEGORY_COLORS[category] ?? CATEGORY_COLORS.other }}
              />
              <span>
                {data.category_labels[category] ?? category}
                {' '}
                <span className="tabular-nums">({data.totals_by_category[category]?.toLocaleString() ?? 0})</span>
              </span>
            </span>
          ))}
        </div>
      )}

      <div className="h-[180px] w-full">
        {loading && chartData.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Loading packet timeline...
          </div>
        ) : chartData.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            No packets recorded in the last 24 hours.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis
                dataKey="idx"
                type="number"
                domain={[0, Math.max(0, chartData.length - 1)]}
                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                tickLine={false}
                axisLine={false}
                ticks={tickIndices}
                tickFormatter={(idx) => chartData[Number(idx)]?.label ?? ''}
              />
              <YAxis
                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <RechartsTooltip
                {...TOOLTIP_STYLE}
                cursor={{ fill: 'hsl(var(--muted))', opacity: 0.45 }}
                labelFormatter={(idx) => chartData[Number(idx)]?.label ?? ''}
                formatter={(value, name) => {
                  const label =
                    data?.category_labels[String(name)] ?? String(name);
                  return [`${Number(value).toLocaleString()}`, label];
                }}
              />
              {(data?.categories ?? []).map((category, index, categories) => (
                <Bar
                  key={category}
                  dataKey={category}
                  stackId="packets"
                  fill={CATEGORY_COLORS[category] ?? CATEGORY_COLORS.other}
                  radius={
                    index === categories.length - 1 ? [2, 2, 0, 0] : undefined
                  }
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
