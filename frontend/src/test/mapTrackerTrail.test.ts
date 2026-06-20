import { describe, expect, it } from 'vitest';

import type { Contact, LocationHistory } from '../types';
import {
  appendTrackerTrailPoint,
  mergeTrackerTrailUpdates,
} from '../utils/mapTrackerTrail';

function makeTracker(overrides: Partial<Contact> = {}): Contact {
  return {
    public_key: 'aa'.repeat(32),
    name: 'Tracker',
    type: 1,
    flags: 0,
    direct_path: null,
    direct_path_len: -1,
    direct_path_hash_mode: 0,
    last_advert: null,
    lat: 52.0,
    lon: 5.0,
    last_seen: 1_700_000_000,
    on_radio: false,
    favorite: false,
    last_contacted: null,
    last_read_at: null,
    first_seen: null,
    is_tracker: true,
    tracker_name: 'Van',
    tracker_heading: 90,
    ...overrides,
  };
}

describe('mapTrackerTrail', () => {
  it('appends a new point when tracker coordinates change', () => {
    const tracker = makeTracker();
    const trails = new Map<string, LocationHistory[]>();

    const first = appendTrackerTrailPoint(trails, tracker, 1_700_000_000);
    expect(first?.get(tracker.public_key)).toHaveLength(1);

    const moved = appendTrackerTrailPoint(
      first!,
      { ...tracker, lat: 52.01, lon: 5.01, last_seen: 1_700_000_030 },
      1_700_000_030
    );
    expect(moved?.get(tracker.public_key)).toHaveLength(2);
    expect(moved?.get(tracker.public_key)?.[1].lat).toBe(52.01);
  });

  it('copies tracker altitude and speed into trail points', () => {
    const tracker = makeTracker({ tracker_altitude: 120, tracker_speed: 1.5 });
    const trails = new Map<string, LocationHistory[]>();

    const first = appendTrackerTrailPoint(trails, tracker, 1_700_000_000);
    const point = first?.get(tracker.public_key)?.[0];
    expect(point?.altitude).toBe(120);
    expect(point?.speed).toBe(1.5);
  });

  it('ignores duplicate coordinates', () => {
    const tracker = makeTracker();
    const trails = new Map<string, LocationHistory[]>([
      [tracker.public_key, [{ id: 1, contact_public_key: tracker.public_key, lat: 52, lon: 5, altitude: null, speed: null, heading: null, satellites: null, battery: null, timestamp: 1, received_at: 1 }]],
    ]);

    expect(appendTrackerTrailPoint(trails, tracker)).toBeNull();
  });

  it('merges updates for multiple trackers', () => {
    const trackerA = makeTracker({ public_key: 'aa'.repeat(32), lat: 52, lon: 5 });
    const trackerB = makeTracker({ public_key: 'bb'.repeat(32), lat: 40, lon: -105 });

    const merged = mergeTrackerTrailUpdates(new Map(), [trackerA, trackerB], 1_700_000_000);
    expect(merged.get(trackerA.public_key)).toHaveLength(1);
    expect(merged.get(trackerB.public_key)).toHaveLength(1);
  });
});
