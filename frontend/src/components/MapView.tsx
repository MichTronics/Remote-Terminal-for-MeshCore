import { useEffect, useState, useMemo, useRef, useCallback } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMap,
  useMapEvents,
  Polyline,
  LayersControl,
} from 'react-leaflet';
import type { LatLngBoundsExpression } from 'leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { Channel, Contact, LocationHistory, RadioConfig, RawPacket } from '../types';
import { api } from '../api';
import { formatTime } from '../utils/messageParser';
import { isValidLocation } from '../utils/pathUtils';
import { CONTACT_TYPE_REPEATER, CONTACT_TYPE_ROOM } from '../types';
import { getMarkerZoomScale } from '../utils/mapMarkerScale';
import {
  parsePacket,
  getPacketLabel,
  PARTICLE_COLOR_MAP,
} from '../utils/visualizerUtils';
import { getRawPacketObservationKey } from '../utils/rawPacketIdentity';
import {
  resolveMapPacketContactKeys,
  resolveMapPacketWaypoints,
} from '../utils/mapPacketPath';
import { MapLivePacketFeed } from './MapLivePacketFeed';

interface MapViewProps {
  contacts: Contact[];
  channels?: Channel[];
  /** Public key of contact to focus on and open popup */
  focusedKey?: string | null;
  rawPackets?: RawPacket[];
  config?: RadioConfig | null;
  blockedKeys?: string[];
  blockedNames?: string[];
  /** When provided, the contact name in each popup becomes a clickable link
   *  that opens the conversation for that contact (DM, repeater, or room). */
  onSelectContact?: (contact: Contact) => void;
}

// --- Tile layer presets ---
// Every provider here is free and works without an API key. Attribution strings
// follow each provider's requirements; do not remove them. If you add a new
// provider, verify its terms of service (especially for Esri / Google-style
// satellite tiles) before committing.
interface TileLayerPreset {
  id: string;
  label: string;
  url: string;
  attribution: string;
  background: string;
  /** Highest zoom the provider publishes tiles at. When the layer is active,
   *  the map's zoom ceiling is tightened to this value via
   *  `MaxZoomByActiveLayer` so the user cannot zoom into a grey void. */
  maxZoom?: number;
}

// Global zoom bounds for the MapContainer itself. These are pinned to the
// container so Leaflet's internal tile-range math never has to guess when
// layers swap in/out via LayersControl. Without this, an initial-mount race
// between MapContainer layout and LayersControl.BaseLayer addition has been
// observed to throw "Attempted to load an infinite number of tiles".
const MAP_MIN_ZOOM = 2;
const MAP_MAX_ZOOM = 19;

const TILE_LAYERS: readonly TileLayerPreset[] = [
  {
    id: 'light',
    label: 'Light (OpenStreetMap)',
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    background: '#1a1a2e',
    maxZoom: 19,
  },
  {
    id: 'dark',
    label: 'Dark (CARTO)',
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
    background: '#0d0d0d',
    maxZoom: 19,
  },
  {
    id: 'topographic',
    label: 'Topographic (OpenTopoMap)',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution:
      'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
    background: '#a3b3bc',
    maxZoom: 17,
  },
  {
    id: 'satellite',
    label: 'Satellite (Esri)',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution:
      'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    background: '#1a1f2e',
    // Esri's tile service advertises LODs up to 23 and returns HTTP 200 for
    // every tile request, but the underlying imagery is only high-resolution
    // up to ~18 in most developed areas and shallower in rural regions. We
    // cap at 18 rather than 19 so users don't zoom into visibly-empty or
    // severely-upscaled tiles. Remote regions may still be sparse at 18.
    maxZoom: 18,
  },
] as const;

const MAP_LAYER_STORAGE_KEY = 'remoteterm-map-layer';
const LEGACY_DARK_MAP_STORAGE_KEY = 'remoteterm-dark-map';

function getSavedLayerId(): string {
  try {
    const stored = localStorage.getItem(MAP_LAYER_STORAGE_KEY);
    if (stored && TILE_LAYERS.some((l) => l.id === stored)) return stored;
    // Default to dark tiles (CoreScope-style live map).
    return 'dark';
  } catch {
    return 'dark';
  }
}

/**
 * Leaflet-internal companion component: listens for base-layer changes driven
 * by Leaflet's own LayersControl UI and pipes the selection back to React.
 * Kept separate so the persistence/state logic stays out of the render tree.
 */
function LayerChangeWatcher({ onChange }: { onChange: (name: string) => void }) {
  useMapEvents({
    baselayerchange: (event) => {
      if (event.name) onChange(event.name);
    },
  });
  return null;
}

/**
 * Enforces the active layer's zoom ceiling on the underlying Leaflet map.
 *
 * Leaflet's `map.getMaxZoom()` prefers `options.maxZoom` (set on MapContainer)
 * over per-layer `maxZoom`, so a per-TileLayer cap is silently ignored unless
 * we push it down to the map itself. We do that here whenever the active
 * layer changes, and clamp the current zoom if the user happened to be zoomed
 * past the new cap at the moment of the switch.
 *
 * The MapContainer's fixed `minZoom`/`maxZoom` remain the absolute hull that
 * prevents the "Attempted to load an infinite number of tiles" race during
 * initial mount (see `MAP_MIN_ZOOM`/`MAP_MAX_ZOOM` below).
 */
function MaxZoomByActiveLayer({ maxZoom }: { maxZoom: number }) {
  const map = useMap();
  useEffect(() => {
    map.setMaxZoom(maxZoom);
    if (map.getZoom() > maxZoom) {
      map.setZoom(maxZoom);
    }
  }, [map, maxZoom]);
  return null;
}

type MapRoleKey = 'repeater' | 'companion' | 'room' | 'sensor' | 'unknown';

/** CoreScope Wong palette — role color is primary, not recency. */
const MAP_ROLE_COLORS: Record<MapRoleKey, string> = {
  repeater: '#D55E00',
  companion: '#56B4E9',
  room: '#009E73',
  sensor: '#F0E442',
  unknown: '#6b7280',
};

const MAP_ROLE_RADIUS: Record<MapRoleKey, number> = {
  repeater: 7, // was 9
  companion: 6, // was 8
  room: 7, // was 8
  sensor: 6, // was 7
  unknown: 6, // was 7
};

const MAP_ROLE_LABELS: Record<MapRoleKey, string> = {
  repeater: 'Repeater',
  companion: 'Companion',
  room: 'Room',
  sensor: 'Sensor',
  unknown: 'Unknown',
};

// --- Packet visualization constants ---
const THREE_DAYS_SEC = 3 * 24 * 60 * 60;
const PARTICLE_LIFETIME_MS = 3500;
const PARTICLE_TAIL_LENGTH = 0.3;
const PARTICLE_RADIUS = 7;
const PARTICLE_TAIL_WIDTH = 4.5;
const PARTICLE_GLOW_RADIUS = 3;
const PARTICLE_SHADOW_BLUR = 9;
const MAX_MAP_PARTICLES = 200;
const ROUTE_LINE_OPACITY = 0.32;
const ROUTE_LINE_WEIGHT = 2;

// --- Helpers ---

function getContactRoleKey(contact: Contact): MapRoleKey {
  if (contact.type === CONTACT_TYPE_REPEATER) return 'repeater';
  if (contact.type === CONTACT_TYPE_ROOM) return 'room';
  if (contact.type === 4) return 'sensor';
  if (contact.type === 1) return 'companion';
  return 'unknown';
}

function getMarkerStaleOpacity(lastSeen: number | null | undefined): number {
  if (lastSeen == null) return 0.35;
  const age = Date.now() / 1000 - lastSeen;
  if (age < 3600) return 1; // age < 1h
  if (age < 86400) return 0.85; // age < 24h
  if (age < 3 * 86400) return 0.6; // age < 3 days
  return 0.25; // age >= 3 days
}

function makeRoleMarkerIcon(role: MapRoleKey, opacity: number, scale = 1): L.DivIcon {
  const color = MAP_ROLE_COLORS[role];
  const radius = MAP_ROLE_RADIUS[role] * scale;
  const size = radius * 2 + Math.max(2, 4 * scale);
  const c = size / 2;
  const stroke = '#1a1a1a';
  const strokeWidth = Math.max(1, 2 * scale);
  let inner = '';

  switch (role) {
    case 'repeater':
      inner = `<circle cx="${c}" cy="${c}" r="${radius}" fill="${color}" fill-opacity="${opacity}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
      break;
    case 'companion':
      inner = `<rect x="${c - radius}" y="${c - radius}" width="${radius * 2}" height="${radius * 2}" fill="${color}" fill-opacity="${opacity}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
      break;
    case 'room': {
      const d = radius;
      inner = `<polygon points="${c},${c - d} ${c + d},${c} ${c},${c + d} ${c - d},${c}" fill="${color}" fill-opacity="${opacity}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
      break;
    }
    case 'sensor':
      inner = `<polygon points="${c},${c - radius} ${c + radius},${c + radius} ${c - radius},${c + radius}" fill="${color}" fill-opacity="${opacity}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
      break;
    default:
      inner = `<circle cx="${c}" cy="${c}" r="${Math.max(1, radius - 1)}" fill="${color}" fill-opacity="${opacity}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-dasharray="3 2"/>`;
  }

  return L.divIcon({
    html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">${inner}</svg>`,
    className: 'mesh-role-marker',
    iconSize: [size, size],
    iconAnchor: [c, c],
    popupAnchor: [0, -radius],
  });
}

function makeTrackerMarkerIcon(scale = 1, heading: number | null = null): L.DivIcon {
  const size = Math.max(8, Math.round(28 * scale));
  const c = size / 2;
  const dotR = Math.max(2, 3.5 * scale);
  const arrowLen = Math.max(4, 8 * scale);
  const arrowHalfW = Math.max(2, 3 * scale);
  const color = '#0072B2';
  const stroke = '#1a1a1a';
  const strokeW = Math.max(1, 1.5 * scale);

  const dot = `<circle cx="${c}" cy="${c}" r="${dotR}" fill="${color}" stroke="${stroke}" stroke-width="${strokeW}"/>`;

  let arrow = '';
  if (heading != null && Number.isFinite(heading)) {
    const tipY = c - dotR - arrowLen;
    const baseY = c - dotR + Math.max(0.5, scale);
    arrow = `<g transform="rotate(${heading} ${c} ${c})"><polygon points="${c},${tipY} ${c + arrowHalfW},${baseY} ${c - arrowHalfW},${baseY}" fill="${color}" stroke="${stroke}" stroke-width="${Math.max(0.5, strokeW * 0.75)}"/></g>`;
  }

  return L.divIcon({
    html: `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">${arrow}${dot}</svg>`,
    className: 'tracker-marker',
    iconSize: [size, size],
    iconAnchor: [c, c],
    popupAnchor: [0, -Math.max(dotR, arrowLen * 0.5 + dotR)],
  });
}

/** Resolve geographic waypoints and discovered contact keys for map live traffic. */
function buildMapPacketPathContext(
  prefixIndex: Map<string, Contact[]>,
  nameIndex: Map<string, Contact>,
  myLatLon: [number, number] | null,
  config?: RadioConfig | null
) {
  return {
    prefixIndex,
    nameIndex,
    myLatLon,
    myPublicKey: config?.public_key ?? null,
  };
}

interface MapParticle {
  id: number;
  path: [number, number][]; // lat/lon waypoints
  color: string;
  startedAt: number;
}

// --- Map bounds handler ---

function MapBoundsHandler({
  contacts,
  focusedContact,
}: {
  contacts: Contact[];
  focusedContact: Contact | null;
}) {
  const map = useMap();
  const [hasInitialized, setHasInitialized] = useState(false);

  useEffect(() => {
    if (focusedContact && focusedContact.lat != null && focusedContact.lon != null) {
      map.setView([focusedContact.lat, focusedContact.lon], 12);
      setHasInitialized(true);
      return;
    }

    if (hasInitialized) return;

    const fitToContacts = () => {
      if (contacts.length === 0) {
        map.setView([20, 0], 2);
        setHasInitialized(true);
        return;
      }

      if (contacts.length === 1) {
        map.setView([contacts[0].lat!, contacts[0].lon!], 10);
        setHasInitialized(true);
        return;
      }

      const bounds: LatLngBoundsExpression = contacts.map(
        (c) => [c.lat!, c.lon!] as [number, number]
      );
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
      setHasInitialized(true);
    };

    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          map.setView([position.coords.latitude, position.coords.longitude], 8);
          setHasInitialized(true);
        },
        () => {
          fitToContacts();
        },
        { timeout: 5000, maximumAge: 300000 }
      );
    } else {
      fitToContacts();
    }
  }, [map, contacts, hasInitialized, focusedContact]);

  return null;
}

/** Keep marker scale in sync with Leaflet zoom (including fitBounds and wheel zoom). */
function useMapMarkerScale(): number {
  const map = useMap();
  const [markerScale, setMarkerScale] = useState(() => getMarkerZoomScale(map.getZoom()));

  useEffect(() => {
    const syncScale = () => {
      setMarkerScale(getMarkerZoomScale(map.getZoom()));
    };
    syncScale();
    map.on('zoom', syncScale);
    map.on('zoomend', syncScale);
    map.on('zoomlevelschange', syncScale);
    map.on('moveend', syncScale);
    return () => {
      map.off('zoom', syncScale);
      map.off('zoomend', syncScale);
      map.off('zoomlevelschange', syncScale);
      map.off('moveend', syncScale);
    };
  }, [map]);

  return markerScale;
}

function ContactMapMarker({
  contact,
  markerScale,
  onSelectContact,
  resolveTrackerHeading,
  onMarkerRef,
}: {
  contact: Contact;
  markerScale: number;
  onSelectContact?: (contact: Contact) => void;
  resolveTrackerHeading: (contact: Contact) => number | null;
  onMarkerRef: (key: string, ref: L.Marker | null) => void;
}) {
  const markerRef = useRef<L.Marker | null>(null);
  const isRepeater = contact.type === CONTACT_TYPE_REPEATER;
  const isTracker = contact.is_tracker;
  const roleKey = getContactRoleKey(contact);
  const markerOpacity = getMarkerStaleOpacity(contact.last_seen);
  const displayName = contact.name || contact.public_key.slice(0, 12);
  const lastHeardLabel =
    contact.last_seen != null ? formatTime(contact.last_seen) : 'Never heard by this server';
  const trackerHeading = isTracker ? resolveTrackerHeading(contact) : null;

  const icon = useMemo(
    () =>
      isTracker
        ? makeTrackerMarkerIcon(markerScale, trackerHeading)
        : makeRoleMarkerIcon(roleKey, markerOpacity, markerScale),
    [isTracker, markerScale, trackerHeading, roleKey, markerOpacity]
  );

  useEffect(() => {
    const marker = markerRef.current;
    if (marker && typeof marker.setIcon === 'function') {
      marker.setIcon(icon);
    }
  }, [icon]);

  const setRef = useCallback(
    (ref: L.Marker | null) => {
      markerRef.current = ref;
      onMarkerRef(contact.public_key, ref);
    },
    [contact.public_key, onMarkerRef]
  );

  return (
    <Marker
      ref={setRef}
      position={[contact.lat!, contact.lon!]}
      icon={icon}
    >
      <Popup>
        <div className="text-sm">
          <div className="font-medium flex items-center gap-1">
            {isRepeater && (
              <span title="Repeater" aria-hidden="true">
                🛜
              </span>
            )}
            {isTracker && (
              <span className="text-[0.625rem] uppercase tracking-wider px-1 py-0.5 rounded bg-primary/10">
                Tracker
              </span>
            )}
            {onSelectContact ? (
              <button
                type="button"
                className="p-0 bg-transparent border-0 font-inherit text-primary underline hover:text-primary/80 cursor-pointer"
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectContact(contact);
                }}
                title={`Open conversation with ${displayName}`}
              >
                {displayName}
              </button>
            ) : (
              displayName
            )}
          </div>
          <div className="text-xs text-gray-500 mt-1">Last heard: {lastHeardLabel}</div>
          {isTracker && trackerHeading != null && (
            <div className="text-xs text-gray-500 mt-1">Heading: {trackerHeading.toFixed(0)}°</div>
          )}
          <div className="text-xs text-gray-400 mt-1 font-mono">
            {contact.lat!.toFixed(5)}, {contact.lon!.toFixed(5)}
          </div>
        </div>
      </Popup>
    </Marker>
  );
}

function ContactMarkersLayer({
  contacts,
  focusedContact,
  onSelectContact,
  resolveTrackerHeading,
}: {
  contacts: Contact[];
  focusedContact: Contact | null;
  onSelectContact?: (contact: Contact) => void;
  resolveTrackerHeading: (contact: Contact) => number | null;
}) {
  const markerScale = useMapMarkerScale();
  const markerRefs = useRef<Record<string, L.Marker | null>>({});

  const setMarkerRef = useCallback((key: string, ref: L.Marker | null) => {
    if (ref === null) {
      delete markerRefs.current[key];
      return;
    }
    markerRefs.current[key] = ref;
  }, []);

  useEffect(() => {
    const currentKeys = new Set(contacts.map((contact) => contact.public_key));
    for (const key of Object.keys(markerRefs.current)) {
      if (!currentKeys.has(key)) {
        delete markerRefs.current[key];
      }
    }
  }, [contacts]);

  useEffect(() => {
    if (focusedContact && markerRefs.current[focusedContact.public_key]) {
      const timer = setTimeout(() => {
        markerRefs.current[focusedContact.public_key]?.openPopup();
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [focusedContact]);

  return (
    <>
      {contacts.map((contact) => (
        <ContactMapMarker
          key={contact.public_key}
          contact={contact}
          markerScale={markerScale}
          onSelectContact={onSelectContact}
          resolveTrackerHeading={resolveTrackerHeading}
          onMarkerRef={setMarkerRef}
        />
      ))}
    </>
  );
}

// --- Canvas particle overlay ---

function ParticleOverlay({ particles }: { particles: MapParticle[] }) {
  const map = useMap();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animRef = useRef<number>(0);

  useEffect(() => {
    const container = map.getContainer();
    const canvas = document.createElement('canvas');
    canvas.style.position = 'absolute';
    canvas.style.top = '0';
    canvas.style.left = '0';
    canvas.style.pointerEvents = 'none';
    canvas.style.zIndex = '450'; // above tiles, below popups
    container.appendChild(canvas);
    canvasRef.current = canvas;

    const resize = () => {
      const size = map.getSize();
      canvas.width = size.x * window.devicePixelRatio;
      canvas.height = size.y * window.devicePixelRatio;
      canvas.style.width = `${size.x}px`;
      canvas.style.height = `${size.y}px`;
    };
    resize();
    map.on('resize', resize);
    map.on('zoom', resize);

    return () => {
      cancelAnimationFrame(animRef.current);
      map.off('resize', resize);
      map.off('zoom', resize);
      container.removeChild(canvas);
      canvasRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const draw = () => {
      const now = Date.now();
      const dpr = window.devicePixelRatio;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.save();
      ctx.scale(dpr, dpr);

      for (const particle of particles) {
        const elapsed = now - particle.startedAt;
        if (elapsed < 0 || elapsed > PARTICLE_LIFETIME_MS) continue;
        const progress = elapsed / PARTICLE_LIFETIME_MS;
        const path = particle.path;
        if (path.length < 2) continue;

        // Calculate total path length in pixels for even speed
        const pixelPath = path.map((ll) => map.latLngToContainerPoint(L.latLng(ll[0], ll[1])));
        const segLengths: number[] = [];
        let totalLen = 0;
        for (let i = 1; i < pixelPath.length; i++) {
          const dx = pixelPath[i].x - pixelPath[i - 1].x;
          const dy = pixelPath[i].y - pixelPath[i - 1].y;
          const len = Math.sqrt(dx * dx + dy * dy);
          segLengths.push(len);
          totalLen += len;
        }
        if (totalLen === 0) continue;

        // Interpolate head position
        const headDist = progress * totalLen;
        const tailDist = Math.max(0, headDist - PARTICLE_TAIL_LENGTH * totalLen);

        const pointAtDist = (d: number): { x: number; y: number } => {
          let accum = 0;
          for (let i = 0; i < segLengths.length; i++) {
            if (accum + segLengths[i] >= d) {
              const t = segLengths[i] > 0 ? (d - accum) / segLengths[i] : 0;
              return {
                x: pixelPath[i].x + (pixelPath[i + 1].x - pixelPath[i].x) * t,
                y: pixelPath[i].y + (pixelPath[i + 1].y - pixelPath[i].y) * t,
              };
            }
            accum += segLengths[i];
          }
          const last = pixelPath[pixelPath.length - 1];
          return { x: last.x, y: last.y };
        };

        const head = pointAtDist(headDist);
        const tail = pointAtDist(tailDist);

        // Tail follows route polyline with sharp corners (no round caps / curve sampling).
        const tailPoints: { x: number; y: number }[] = [tail];
        let vertexDist = 0;
        for (let i = 0; i < segLengths.length; i++) {
          vertexDist += segLengths[i];
          if (vertexDist > tailDist && vertexDist < headDist) {
            tailPoints.push({ x: pixelPath[i + 1].x, y: pixelPath[i + 1].y });
          }
        }
        const lastTailPoint = tailPoints[tailPoints.length - 1];
        if (lastTailPoint.x !== head.x || lastTailPoint.y !== head.y) {
          tailPoints.push(head);
        }

        if (tailPoints.length >= 2) {
          const grad = ctx.createLinearGradient(tail.x, tail.y, head.x, head.y);
          grad.addColorStop(0, particle.color + '00');
          grad.addColorStop(1, particle.color + 'cc');
          ctx.beginPath();
          ctx.moveTo(tailPoints[0].x, tailPoints[0].y);
          for (let i = 1; i < tailPoints.length; i++) {
            ctx.lineTo(tailPoints[i].x, tailPoints[i].y);
          }
          ctx.strokeStyle = grad;
          ctx.lineWidth = PARTICLE_TAIL_WIDTH;
          ctx.lineCap = 'butt';
          ctx.lineJoin = 'miter';
          ctx.stroke();
        }

        // Draw head blob with glow
        const fade = progress > 0.8 ? 1 - (progress - 0.8) / 0.2 : 1;
        const alpha = Math.round(fade * 230)
          .toString(16)
          .padStart(2, '0');
        // Outer glow
        ctx.beginPath();
        ctx.arc(head.x, head.y, PARTICLE_RADIUS + PARTICLE_GLOW_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle =
          particle.color +
          Math.round(fade * 40)
            .toString(16)
            .padStart(2, '0');
        ctx.fill();
        // Core blob
        ctx.beginPath();
        ctx.arc(head.x, head.y, PARTICLE_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = particle.color + alpha;
        ctx.shadowColor = particle.color;
        ctx.shadowBlur = PARTICLE_SHADOW_BLUR * fade;
        ctx.fill();
        ctx.shadowBlur = 0;
        // Bright center
        ctx.beginPath();
        ctx.arc(head.x, head.y, PARTICLE_RADIUS * 0.4, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff' + alpha;
        ctx.fill();
      }

      ctx.restore();
      animRef.current = requestAnimationFrame(draw);
    };

    animRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animRef.current);
  }, [map, particles]);

  // Redraw on map move/zoom
  useEffect(() => {
    const redraw = () => {}; // Animation loop already redraws every frame
    map.on('move', redraw);
    map.on('zoom', redraw);
    return () => {
      map.off('move', redraw);
      map.off('zoom', redraw);
    };
  }, [map]);

  return null;
}

// --- Main component ---

export function MapView({
  contacts,
  channels,
  focusedKey,
  rawPackets,
  config,
  blockedKeys,
  blockedNames,
  onSelectContact,
}: MapViewProps) {
  const [sevenDaysAgo] = useState(() => Date.now() / 1000 - 7 * 24 * 60 * 60);
  const [selectedLayerId, setSelectedLayerId] = useState<string>(getSavedLayerId);
  const activeLayer = TILE_LAYERS.find((l) => l.id === selectedLayerId) ?? TILE_LAYERS[0];

  // Sync layer selection across tabs and windows.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== MAP_LAYER_STORAGE_KEY) return;
      const next = e.newValue ?? '';
      if (TILE_LAYERS.some((l) => l.id === next)) {
        setSelectedLayerId(next);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const handleLayerChange = useCallback((layerName: string) => {
    const match = TILE_LAYERS.find((l) => l.label === layerName);
    if (!match) return;
    setSelectedLayerId(match.id);
    try {
      localStorage.setItem(MAP_LAYER_STORAGE_KEY, match.id);
      // Clear the legacy key so a future downgrade-rollback doesn't revert us.
      localStorage.removeItem(LEGACY_DARK_MAP_STORAGE_KEY);
    } catch {
      // localStorage may be disabled; selection stays in memory only.
    }
  }, []);

  const [showPackets, setShowPackets] = useState(true);
  const [discoveryMode, setDiscoveryMode] = useState(false);
  const [discoveredKeys, setDiscoveredKeys] = useState<Set<string>>(new Set());
  const [particles, setParticles] = useState<MapParticle[]>([]);
  const particleIdRef = useRef(0);
  const seenObservationsRef = useRef(new Set<string>());

  const [historyHeadings, setHistoryHeadings] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!contacts.some((c) => c.is_tracker && c.tracker_heading == null)) return;

    api
      .getAllTrackerLocationHistory()
      .then((data) => {
        const headings: Record<string, number> = {};
        for (const { contact, history } of data) {
          for (let i = history.length - 1; i >= 0; i--) {
            const heading = history[i].heading;
            if (heading != null && Number.isFinite(heading)) {
              headings[contact.public_key] = heading;
              break;
            }
          }
        }
        setHistoryHeadings(headings);
      })
      .catch((err) => {
        console.error('Failed to bootstrap tracker headings:', err);
      });
  }, [contacts]);

  const resolveTrackerHeading = useCallback(
    (contact: Contact): number | null => {
      if (contact.tracker_heading != null && Number.isFinite(contact.tracker_heading)) {
        return contact.tracker_heading;
      }
      const fromHistory = historyHeadings[contact.public_key];
      return fromHistory != null && Number.isFinite(fromHistory) ? fromHistory : null;
    },
    [historyHeadings]
  );

  // Tracker location history (movement trails)
  const [showTrails, setShowTrails] = useState(false);
  const [trackerTrails, setTrackerTrails] = useState<Map<string, LocationHistory[]>>(new Map());

  // Fetch tracker location history trails
  useEffect(() => {
    if (!showTrails) {
      setTrackerTrails(new Map());
      return;
    }

    api
      .getAllTrackerLocationHistory()
      .then((data) => {
        const trails = new Map<string, LocationHistory[]>();
        data.forEach(({ contact, history }) => {
          if (history.length > 1) {
            // Only include trails with 2+ points
            trails.set(contact.public_key, history);
          }
        });
        setTrackerTrails(trails);
      })
      .catch((err) => {
        console.error('Failed to fetch tracker location history:', err);
      });
  }, [showTrails]);

  // Build prefix index and name index for hop resolution
  const { prefixIndex, nameIndex } = useMemo(() => {
    const prefix = new Map<string, Contact[]>();
    const name = new Map<string, Contact>();
    for (const c of contacts) {
      const pubkey = c.public_key.toLowerCase();
      for (let len = 1; len <= 12 && len <= pubkey.length; len++) {
        const p = pubkey.slice(0, len);
        const arr = prefix.get(p);
        if (arr) arr.push(c);
        else prefix.set(p, [c]);
      }
      if (c.name && !name.has(c.name)) name.set(c.name, c);
    }
    return { prefixIndex: prefix, nameIndex: name };
  }, [contacts]);

  // Self GPS
  const myLatLon = useMemo<[number, number] | null>(() => {
    if (!config || !isValidLocation(config.lat, config.lon)) return null;
    return [config.lat, config.lon];
  }, [config]);

  // Determine time window for packet visualization
  const threeDaysAgoSec = useMemo(() => Date.now() / 1000 - THREE_DAYS_SEC, []);

  // Filter contacts for map display
  const mappableContacts = useMemo(() => {
    const isBlocked = (c: Contact) =>
      (blockedKeys?.length && blockedKeys.includes(c.public_key.toLowerCase())) ||
      (blockedNames?.length && c.name != null && blockedNames.includes(c.name));

    if (showPackets && discoveryMode) {
      // Discovery mode: only show nodes that have appeared in resolved packets
      return contacts.filter(
        (c) => isValidLocation(c.lat, c.lon) && discoveredKeys.has(c.public_key) && !isBlocked(c)
      );
    }
    if (showPackets) {
      // Packet mode: show only last 3 days
      return contacts.filter(
        (c) =>
          isValidLocation(c.lat, c.lon) &&
          !isBlocked(c) &&
          (c.public_key === focusedKey || (c.last_seen != null && c.last_seen > threeDaysAgoSec))
      );
    }
    return contacts.filter(
      (c) =>
        isValidLocation(c.lat, c.lon) &&
        !isBlocked(c) &&
        (c.public_key === focusedKey || (c.last_seen != null && c.last_seen > sevenDaysAgo))
    );
  }, [
    contacts,
    focusedKey,
    sevenDaysAgo,
    threeDaysAgoSec,
    showPackets,
    discoveryMode,
    discoveredKeys,
    blockedKeys,
    blockedNames,
  ]);

  // Resolve a parsed packet to geographic waypoints for particle/route rendering.
  const mapPacketPathContext = useMemo(
    () => buildMapPacketPathContext(prefixIndex, nameIndex, myLatLon, config),
    [prefixIndex, nameIndex, myLatLon, config]
  );

  const resolvePacketPath = useCallback(
    (parsed: ReturnType<typeof parsePacket>, packet?: RawPacket | null) =>
      parsed ? resolveMapPacketWaypoints(parsed, mapPacketPathContext, packet) : null,
    [mapPacketPathContext]
  );

  // Process new packets into particles and track discovered contacts
  useEffect(() => {
    if (!showPackets || !rawPackets?.length) return;

    const now = Date.now();
    const newParticles: MapParticle[] = [];
    const newDiscovered = new Set<string>();

    for (const pkt of rawPackets) {
      // Skip old packets
      if (pkt.timestamp < threeDaysAgoSec) continue;

      // Deduplicate by observation
      const obsKey = getRawPacketObservationKey(pkt);
      if (seenObservationsRef.current.has(obsKey)) continue;

      const parsed = parsePacket(pkt.data);
      if (!parsed) continue;

      // Discover contacts from this packet regardless of whether a full path resolves
      const resolvedContacts = resolveMapPacketContactKeys(
        parsed,
        mapPacketPathContext,
        pkt
      );
      const path = resolvePacketPath(parsed, pkt);

      // Only mark as seen if we got something useful; otherwise a later run
      // with updated contacts/config can retry this observation.
      if (resolvedContacts.size === 0 && !path) continue;
      seenObservationsRef.current.add(obsKey);

      for (const key of resolvedContacts) newDiscovered.add(key);

      if (path) {
        newParticles.push({
          id: particleIdRef.current++,
          path,
          color: PARTICLE_COLOR_MAP[getPacketLabel(parsed.payloadType)],
          startedAt: now,
        });
      }
    }

    if (newDiscovered.size > 0) {
      setDiscoveredKeys((prev) => {
        const next = new Set(prev);
        for (const k of newDiscovered) next.add(k);
        return next.size !== prev.size ? next : prev;
      });
    }

    if (newParticles.length === 0) return;

    setParticles((prev) => {
      const combined = [...prev, ...newParticles];
      // Prune expired and cap total
      const alive = combined.filter((p) => now - p.startedAt < PARTICLE_LIFETIME_MS);
      return alive.slice(-MAX_MAP_PARTICLES);
    });
  }, [
    rawPackets,
    showPackets,
    resolvePacketPath,
    mapPacketPathContext,
    threeDaysAgoSec,
  ]);

  // Prune expired particles periodically
  useEffect(() => {
    if (!showPackets) return;
    const interval = setInterval(() => {
      const now = Date.now();
      setParticles((prev) => prev.filter((p) => now - p.startedAt < PARTICLE_LIFETIME_MS));
    }, 1000);
    return () => clearInterval(interval);
  }, [showPackets]);

  // Reset discovered set when exiting discovery mode
  useEffect(() => {
    if (!discoveryMode) setDiscoveredKeys(new Set());
  }, [discoveryMode]);

  // Clear state when toggling off
  useEffect(() => {
    if (!showPackets) {
      setParticles([]);
      setDiscoveredKeys(new Set());
      setDiscoveryMode(false);
      seenObservationsRef.current.clear();
    }
  }, [showPackets]);

  // Find the focused contact by key
  const focusedContact = useMemo(() => {
    if (!focusedKey) return null;
    return mappableContacts.find((c) => c.public_key === focusedKey) || null;
  }, [focusedKey, mappableContacts]);

  const includesFocusedOutsideWindow =
    focusedContact != null &&
    (focusedContact.last_seen == null ||
      focusedContact.last_seen <= (showPackets ? threeDaysAgoSec : sevenDaysAgo));

  // Gather unique link paths for static route lines when packet viz is on
  const routeLines = useMemo(() => {
    if (!showPackets) return [];
    const seen = new Set<string>();
    const lines: { path: [number, number][]; color: string }[] = [];
    for (const p of particles) {
      const key = p.path.map((w) => `${w[0]},${w[1]}`).join('|');
      if (seen.has(key)) continue;
      seen.add(key);
      lines.push({ path: p.path, color: p.color });
    }
    return lines;
  }, [showPackets, particles]);

  const timeWindowLabel = showPackets ? '3 days' : '7 days';
  const infoLabel =
    showPackets && discoveryMode
      ? `${mappableContacts.length} node${mappableContacts.length !== 1 ? 's' : ''} discovered from live traffic`
      : `Showing ${mappableContacts.length} contact${mappableContacts.length !== 1 ? 's' : ''} heard in the last ${timeWindowLabel}${includesFocusedOutsideWindow ? ' plus the focused contact' : ''}`;

  return (
    <div className="flex flex-col h-full">
      {/* Info bar: stacks vertically on narrow viewports (info label, legend
          row, controls row) so nothing truncates; flattens to a single row
          with right-aligned cluster at md and up. */}
      <div className="px-4 py-2 bg-muted/50 text-xs text-muted-foreground flex flex-col gap-1 md:flex-row md:items-center md:justify-between md:gap-3">
        <span>{infoLabel}</span>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 md:justify-end">
          {(Object.keys(MAP_ROLE_COLORS) as MapRoleKey[]).map((role) => (
            <span key={role} className="flex items-center gap-1">
              <span
                className="inline-block h-3 w-3 shrink-0"
                style={{
                  backgroundColor: MAP_ROLE_COLORS[role],
                  borderRadius: role === 'repeater' || role === 'unknown' ? '9999px' : '1px',
                  clipPath:
                    role === 'room'
                      ? 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)'
                      : role === 'sensor'
                        ? 'polygon(50% 0%, 0% 100%, 100% 100%)'
                        : undefined,
                }}
                aria-hidden="true"
              />
              {MAP_ROLE_LABELS[role]}
            </span>
          ))}
          <span className="flex items-center gap-1">
            <span
              className="inline-flex h-3 w-3 shrink-0 items-center justify-center"
              aria-hidden="true"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                <polygon points="6,1 8,6 6,5 4,6" fill="#0072B2" stroke="#1a1a1a" strokeWidth="0.75" />
                <circle cx="6" cy="6" r="2" fill="#0072B2" stroke="#1a1a1a" strokeWidth="0.75" />
              </svg>
            </span>
            Tracker
          </span>
          {showPackets && (
            <>
              <span className="hidden sm:inline text-muted-foreground/60">|</span>
              <span className="flex items-center gap-1">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: PARTICLE_COLOR_MAP['AD'] }}
                  aria-hidden="true"
                />
                Ad
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: PARTICLE_COLOR_MAP['GT'] }}
                  aria-hidden="true"
                />
                Ch
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: PARTICLE_COLOR_MAP['DM'] }}
                  aria-hidden="true"
                />
                DM
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: PARTICLE_COLOR_MAP['ACK'] }}
                  aria-hidden="true"
                />
                ACK
              </span>
            </>
          )}
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={showPackets}
              onChange={(e) => setShowPackets(e.target.checked)}
              className="rounded border-border"
            />
            <span className="text-[0.6875rem]">Live traffic</span>
          </label>
          {showPackets && (
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={discoveryMode}
                onChange={(e) => setDiscoveryMode(e.target.checked)}
                className="rounded border-border"
              />
              <span className="text-[0.6875rem]">Discover nodes</span>
            </label>
          )}
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={showTrails}
              onChange={(e) => setShowTrails(e.target.checked)}
              className="rounded border-border"
            />
            <span className="text-[0.6875rem]">Tracker trails</span>
          </label>
        </div>
      </div>

      {/* Map */}
      <div
        className="flex-1 relative"
        style={{ zIndex: 0 }}
        role="img"
        aria-label="Map showing mesh node locations"
      >
        <MapContainer
          center={[20, 0]}
          zoom={2}
          minZoom={MAP_MIN_ZOOM}
          maxZoom={MAP_MAX_ZOOM}
          className="h-full w-full"
          style={{ background: activeLayer.background }}
        >
          <LayersControl position="topright" collapsed={false}>
            {TILE_LAYERS.map((layer) => (
              <LayersControl.BaseLayer
                key={layer.id}
                name={layer.label}
                checked={layer.id === selectedLayerId}
              >
                <TileLayer
                  url={layer.url}
                  attribution={layer.attribution}
                  maxZoom={layer.maxZoom}
                />
              </LayersControl.BaseLayer>
            ))}
          </LayersControl>
          <LayerChangeWatcher onChange={handleLayerChange} />
          <MaxZoomByActiveLayer maxZoom={activeLayer.maxZoom ?? MAP_MAX_ZOOM} />
          <MapBoundsHandler contacts={mappableContacts} focusedContact={focusedContact} />

          {/* Faint route lines for active packet paths */}
          {showPackets &&
            routeLines.map((line, i) => (
              <Polyline
                key={i}
                positions={line.path}
                pathOptions={{
                  color: line.color,
                  weight: ROUTE_LINE_WEIGHT,
                  opacity: ROUTE_LINE_OPACITY,
                  lineCap: 'round',
                  lineJoin: 'round',
                }}
              />
            ))}

          {/* Tracker movement trails (red polylines) */}
          {showTrails &&
            Array.from(trackerTrails.entries()).map(([publicKey, history]) => (
              <Polyline
                key={`trail-${publicKey}`}
                positions={history.map((h) => [h.lat, h.lon] as [number, number])}
                pathOptions={{
                  color: '#ef4444',
                  weight: 4,
                  opacity: 0.7,
                  lineCap: 'round',
                  lineJoin: 'round',
                }}
              />
            ))}

          <ContactMarkersLayer
            contacts={mappableContacts}
            focusedContact={focusedContact}
            onSelectContact={onSelectContact}
            resolveTrackerHeading={resolveTrackerHeading}
          />

          {showPackets && <ParticleOverlay particles={particles} />}
        </MapContainer>
        <MapLivePacketFeed
          packets={rawPackets ?? []}
          contacts={contacts}
          channels={channels}
          myPublicKey={config?.public_key ?? null}
          myName={config?.name ?? null}
          visible={showPackets}
        />
      </div>
    </div>
  );
}
