import type { Contact, LocationHistory } from '../types';
import { isValidLocation } from './pathUtils';

export function buildTrackerTrailPoint(
  contact: Contact,
  syntheticId: number,
  receivedAtSec = Math.floor(Date.now() / 1000)
): LocationHistory | null {
  if (!contact.is_tracker || !isValidLocation(contact.lat, contact.lon)) {
    return null;
  }

  return {
    id: syntheticId,
    contact_public_key: contact.public_key,
    lat: contact.lat!,
    lon: contact.lon!,
    altitude: contact.tracker_altitude ?? null,
    speed: contact.tracker_speed ?? null,
    heading: contact.tracker_heading ?? null,
    satellites: null,
    battery: null,
    timestamp: contact.last_seen ?? receivedAtSec,
    received_at: receivedAtSec,
  };
}

function sameTrailPosition(
  left: LocationHistory | undefined,
  lat: number,
  lon: number
): boolean {
  return left != null && left.lat === lat && left.lon === lon;
}

/** Append a new trail point when a tracker contact moves. Returns null if unchanged. */
export function appendTrackerTrailPoint(
  trails: Map<string, LocationHistory[]>,
  contact: Contact,
  receivedAtSec = Math.floor(Date.now() / 1000)
): Map<string, LocationHistory[]> | null {
  if (!contact.is_tracker || !isValidLocation(contact.lat, contact.lon)) {
    return null;
  }

  const existing = trails.get(contact.public_key) ?? [];
  const last = existing[existing.length - 1];
  if (sameTrailPosition(last, contact.lat!, contact.lon!)) {
    return null;
  }

  const point = buildTrackerTrailPoint(contact, -(existing.length + 1), receivedAtSec);
  if (!point) {
    return null;
  }

  const next = new Map(trails);
  next.set(contact.public_key, [...existing, point]);
  return next;
}

export function trackerTrailEntriesFromApi(
  rows: Array<{ contact: Contact; history: LocationHistory[] }>
): Map<string, LocationHistory[]> {
  const trails = new Map<string, LocationHistory[]>();
  for (const { contact, history } of rows) {
    if (history.length > 0) {
      trails.set(contact.public_key, history);
    }
  }
  return trails;
}

export function mergeTrackerTrailUpdates(
  trails: Map<string, LocationHistory[]>,
  contacts: Contact[],
  receivedAtSec = Math.floor(Date.now() / 1000)
): Map<string, LocationHistory[]> {
  let next: Map<string, LocationHistory[]> | null = null;
  for (const contact of contacts) {
    if (!contact.is_tracker) continue;
    const updated = appendTrackerTrailPoint(next ?? trails, contact, receivedAtSec);
    if (updated) {
      next = updated;
    }
  }
  return next ?? trails;
}
