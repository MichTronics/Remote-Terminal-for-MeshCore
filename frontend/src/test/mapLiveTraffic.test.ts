import { describe, expect, it } from 'vitest';

import {
  MAP_LIVE_ANIMATION_WINDOW_SEC,
  shouldAnimateMapLivePacket,
} from '../utils/mapLiveTraffic';

describe('mapLiveTraffic', () => {
  it('animates only packets within the live window', () => {
    const nowMs = 1_700_000_000_000;
    const freshSec = nowMs / 1000 - 10;
    const staleSec = nowMs / 1000 - MAP_LIVE_ANIMATION_WINDOW_SEC - 1;

    expect(shouldAnimateMapLivePacket(freshSec, nowMs)).toBe(true);
    expect(shouldAnimateMapLivePacket(staleSec, nowMs)).toBe(false);
  });
});
