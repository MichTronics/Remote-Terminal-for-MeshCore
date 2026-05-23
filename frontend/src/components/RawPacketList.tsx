import { useEffect, useRef, useMemo, useState } from 'react';
import type { Channel, RawPacket, Region } from '../types';
import { getRawPacketObservationKey } from '../utils/rawPacketIdentity';
import { createDecoderOptions, decodePacketSummary } from '../utils/rawPacketInspector';
import { identifyPacketRegion } from '../utils/regionIdentifier';
import { cn } from '@/lib/utils';

interface RawPacketListProps {
  packets: RawPacket[];
  channels?: Channel[];
  regions?: Region[];
  onPacketClick?: (packet: RawPacket) => void;
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatTransportCodes(transportCodes: string): string {
  // Transport codes are 4 bytes: primary (0-1) and secondary (2-3)
  const upper = transportCodes.toUpperCase();
  if (upper.length !== 8) return upper; // Malformed, show as-is
  
  const primary = upper.slice(0, 4);
  const secondary = upper.slice(4, 8);
  
  // Only show secondary if not 0000
  if (secondary === '0000') {
    return primary;
  }
  return `${primary} ${secondary}`;
}

function formatSignalInfo(packet: RawPacket, identifiedRegion?: string | null): string {
  const parts: string[] = [];
  if (packet.snr !== null && packet.snr !== undefined) {
    parts.push(`SNR: ${packet.snr.toFixed(1)} dB`);
  }
  if (packet.rssi !== null && packet.rssi !== undefined) {
    parts.push(`RSSI: ${packet.rssi} dBm`);
  }
  // Prefer client-side identified region, then stored region_name, then hex codes
  if (identifiedRegion) {
    console.log(`[formatSignalInfo] Using client-identified region: ${identifiedRegion}`);
    parts.push(`Region: ${identifiedRegion}`);
  } else if (packet.region_name) {
    console.log(`[formatSignalInfo] Using stored region_name: ${packet.region_name}`);
    parts.push(`Region: ${packet.region_name}`);
  } else if (packet.transport_codes) {
    console.log(`[formatSignalInfo] Using hex codes: ${packet.transport_codes} (no region match)`);
    parts.push(`Region: ${formatTransportCodes(packet.transport_codes)}`);
  }
  return parts.join(' | ');
}

// Get route type badge color
function getRouteTypeColor(routeType: string): string {
  switch (routeType) {
    case 'Flood':
      return 'bg-info/20 text-info';
    case 'Direct':
      return 'bg-success/20 text-success';
    case 'TransportFlood':
      return 'bg-purple-500/20 text-purple-400';
    case 'TransportDirect':
      return 'bg-orange-500/20 text-orange-400';
    default:
      return 'bg-muted text-muted-foreground';
  }
}

// Get short route type label
function getRouteTypeLabel(routeType: string): string {
  switch (routeType) {
    case 'Flood':
      return 'F';
    case 'Direct':
      return 'D';
    case 'TransportFlood':
      return 'TF';
    case 'TransportDirect':
      return 'TD';
    default:
      return '?';
  }
}

export function RawPacketList({ packets, channels, regions, onPacketClick }: RawPacketListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const decoderOptions = useMemo(() => createDecoderOptions(channels), [channels]);

  // Track client-side identified region names per packet observation_id
  const [identifiedRegions, setIdentifiedRegions] = useState<Map<number, string | null>>(new Map());
  const attemptedIdentificationRef = useRef<Set<number>>(new Set());

  // Identify regions for packets with transport codes
  useEffect(() => {
    console.log('[RawPacketList] Regions loaded:', regions?.length ?? 0);
    if (!regions || regions.length === 0) return;

    const identifyRegions = async () => {
      const newIdentifications = new Map<number, string | null>();

      for (const packet of packets) {
        const packetKey = packet.observation_id ?? packet.id;
        
        // Skip if no transport codes
        if (!packet.transport_codes) {
          continue;
        }

        // Skip if already attempted
        if (attemptedIdentificationRef.current.has(packetKey)) {
          continue;
        }

        attemptedIdentificationRef.current.add(packetKey);
        const regionName = await identifyPacketRegion(packet.data, regions);
        if (regionName) {
          console.log(`[RawPacketList] Identified packet ${packetKey} as region: ${regionName}`);
        }
        newIdentifications.set(packetKey, regionName);
      }

      if (newIdentifications.size > 0) {
        setIdentifiedRegions((prev) => new Map([...prev, ...newIdentifications]));
      }
    };

    identifyRegions();
  }, [packets, regions]);

  // Decode all packets (memoized to avoid re-decoding on every render)
  const decodedPackets = useMemo(() => {
    return packets.map((packet) => ({
      packet,
      decoded: decodePacketSummary(packet, decoderOptions),
    }));
  }, [decoderOptions, packets]);

  // Sort packets by timestamp ascending (oldest first)
  const sortedPackets = useMemo(
    () => [...decodedPackets].sort((a, b) => a.packet.timestamp - b.packet.timestamp),
    [decodedPackets]
  );

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [packets]);

  if (packets.length === 0) {
    return (
      <div className="h-full overflow-y-auto p-5 text-center text-muted-foreground [contain:layout_paint]">
        No packets received yet. Packets will appear here in real-time.
      </div>
    );
  }

  return (
    <div
      className="h-full overflow-y-auto p-4 flex flex-col gap-2 [contain:layout_paint]"
      ref={listRef}
    >
      {sortedPackets.map(({ packet, decoded }) => {
        const identifiedRegion = identifiedRegions.get(packet.observation_id ?? packet.id);
        const cardContent = (
          <>
            <div className="flex items-center gap-2">
              {/* Route type badge */}
              <span
                className={`text-[0.625rem] font-mono px-1.5 py-0.5 rounded ${getRouteTypeColor(decoded.routeType)}`}
                title={decoded.routeType}
              >
                {getRouteTypeLabel(decoded.routeType)}
              </span>

              {/* Encryption status */}
              {!packet.decrypted && (
                <>
                  <span aria-hidden="true">🔒</span>
                  <span className="sr-only">Encrypted</span>
                </>
              )}

              {/* Summary */}
              <span
                className={cn(
                  'text-[0.8125rem]',
                  packet.decrypted ? 'text-primary' : 'text-foreground'
                )}
              >
                {decoded.summary}
              </span>

              {/* Time */}
              <span className="text-muted-foreground ml-auto text-xs tabular-nums">
                {formatTime(packet.timestamp)}
              </span>
            </div>

            {/* Signal info */}
            {(packet.snr !== null || packet.rssi !== null || packet.transport_codes) && (
              <div className="text-[0.6875rem] text-muted-foreground mt-0.5 tabular-nums">
                {formatSignalInfo(packet, identifiedRegion)}
              </div>
            )}

            {/* Decoded message text (when available) */}
            {packet.decrypted_info?.message && (
              <div className="text-[0.75rem] text-foreground mt-1.5 p-2 bg-success/10 border border-success/20 rounded">
                <div className="break-words">{packet.decrypted_info.message}</div>
              </div>
            )}

            {/* Raw hex data (always visible) */}
            <div className="font-mono text-[0.625rem] break-all text-muted-foreground mt-1.5 p-1.5 bg-background/60 rounded">
              {packet.data.toUpperCase()}
            </div>
          </>
        );

        const className = cn(
          'rounded-md border border-border/50 bg-card px-3 py-2 text-left',
          onPacketClick &&
            'cursor-pointer transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
        );

        if (onPacketClick) {
          return (
            <button
              key={getRawPacketObservationKey(packet)}
              type="button"
              onClick={() => onPacketClick(packet)}
              className={className}
            >
              {cardContent}
            </button>
          );
        }

        return (
          <div key={getRawPacketObservationKey(packet)} className={className}>
            {cardContent}
          </div>
        );
      })}
    </div>
  );
}
