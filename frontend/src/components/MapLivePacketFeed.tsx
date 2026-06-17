import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GripHorizontal } from 'lucide-react';

import type { Channel, Contact, RawPacket } from '../types';
import { cn } from '@/lib/utils';
import {
  buildMapPacketFeedContext,
  buildMapPacketFeedEntries,
  type MapPacketFeedEntry,
} from '../utils/mapPacketFeed';

const POSITION_STORAGE_KEY = 'remoteterm-map-packet-feed-position';
const DEFAULT_POSITION = { x: 12, y: 12 };

interface StoredPosition {
  x: number;
  y: number;
}

function loadStoredPosition(): StoredPosition | null {
  try {
    const raw = localStorage.getItem(POSITION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredPosition;
    if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
      return parsed;
    }
  } catch {
    // Ignore malformed storage.
  }
  return null;
}

function saveStoredPosition(position: StoredPosition): void {
  try {
    localStorage.setItem(POSITION_STORAGE_KEY, JSON.stringify(position));
  } catch {
    // localStorage may be unavailable.
  }
}

interface MapLivePacketFeedProps {
  packets: RawPacket[];
  contacts: Contact[];
  channels?: Channel[];
  visible: boolean;
}

function FeedLine({ entry }: { entry: MapPacketFeedEntry }) {
  return (
    <div className="text-[0.8125rem] leading-snug text-foreground/90 font-mono whitespace-normal break-words">
      <span className="font-semibold" style={{ color: entry.typeColor }}>
        {entry.typeLabel}
      </span>{' '}
      {entry.hopsPrefix && <span className="text-muted-foreground">{entry.hopsPrefix}</span>}
      {entry.senderLabel && (
        <span className="text-foreground/80">
          From {entry.senderLabel}
          {entry.messageSuffix && (
            <span className="text-muted-foreground">{entry.messageSuffix}</span>
          )}
        </span>
      )}
    </div>
  );
}

export function MapLivePacketFeed({ packets, contacts, channels, visible }: MapLivePacketFeedProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const [position, setPosition] = useState<StoredPosition>(
    () => loadStoredPosition() ?? DEFAULT_POSITION
  );
  const [dragging, setDragging] = useState(false);

  const feedContext = useMemo(
    () => buildMapPacketFeedContext(contacts, channels),
    [contacts, channels]
  );
  const entries = useMemo(
    () => (visible ? buildMapPacketFeedEntries(packets, feedContext) : []),
    [packets, feedContext, visible]
  );

  const clampPosition = useCallback((next: StoredPosition): StoredPosition => {
    const parent = containerRef.current?.offsetParent as HTMLElement | null;
    const box = containerRef.current;
    if (!parent || !box) return next;

    const maxX = Math.max(0, parent.clientWidth - box.offsetWidth);
    const maxY = Math.max(0, parent.clientHeight - box.offsetHeight);
    return {
      x: Math.min(Math.max(0, next.x), maxX),
      y: Math.min(Math.max(0, next.y), maxY),
    };
  }, []);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      const box = containerRef.current;
      if (!box) return;

      event.preventDefault();
      dragOffsetRef.current = {
        x: event.clientX - box.offsetLeft,
        y: event.clientY - box.offsetTop,
      };
      setDragging(true);
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    []
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging) return;
      const parent = containerRef.current?.offsetParent as HTMLElement | null;
      const box = containerRef.current;
      if (!parent || !box) return;

      const parentRect = parent.getBoundingClientRect();
      const next = clampPosition({
        x: event.clientX - parentRect.left - dragOffsetRef.current.x,
        y: event.clientY - parentRect.top - dragOffsetRef.current.y,
      });
      setPosition(next);
    },
    [clampPosition, dragging]
  );

  const handlePointerUp = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging) return;
      setDragging(false);
      event.currentTarget.releasePointerCapture(event.pointerId);
      setPosition((current) => {
        const clamped = clampPosition(current);
        saveStoredPosition(clamped);
        return clamped;
      });
    },
    [clampPosition, dragging]
  );

  useEffect(() => {
    if (!visible) return;
    const clamped = clampPosition(position);
    if (clamped.x !== position.x || clamped.y !== position.y) {
      setPosition(clamped);
    }
  }, [visible, position, clampPosition, entries.length]);

  if (!visible) return null;

  return (
    <div
      ref={containerRef}
      className={cn(
        'absolute z-[500] w-[28rem] max-w-[calc(100%-1.5rem)] rounded-md border border-border/70 bg-background/90 shadow-lg backdrop-blur-sm pointer-events-auto',
        dragging && 'select-none'
      )}
      style={{ left: position.x, top: position.y }}
      aria-label="Live packet feed"
    >
      <div
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1.5 border-b border-border/60 text-[0.625rem] uppercase tracking-wider text-muted-foreground font-medium cursor-grab active:cursor-grabbing',
          dragging && 'cursor-grabbing'
        )}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
      >
        <GripHorizontal className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>Live traffic</span>
        <span className="ml-auto tabular-nums">{entries.length}/12</span>
      </div>

      <div className="px-3 py-2.5 flex flex-col gap-1.5 h-[14.5rem] overflow-y-auto overflow-x-hidden">
        {entries.length === 0 ? (
          <div className="text-[0.8125rem] text-muted-foreground py-2 text-center">
            Waiting for packets...
          </div>
        ) : (
          entries.map((entry) => <FeedLine key={entry.key} entry={entry} />)
        )}
      </div>
    </div>
  );
}
