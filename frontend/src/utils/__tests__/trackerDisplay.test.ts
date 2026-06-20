import { describe, expect, it } from 'vitest';

import {
  formatTrackerAltitudeM,
  formatTrackerSpeedKmh,
  trackerSpeedToKmh,
} from '../trackerDisplay';

describe('trackerDisplay', () => {
  it('formats altitude in metres', () => {
    expect(formatTrackerAltitudeM(123.7)).toBe('124m');
    expect(formatTrackerAltitudeM(-12.2)).toBe('-12m');
    expect(formatTrackerAltitudeM(null)).toBeNull();
  });

  it('formats speed in km/h from m/s', () => {
    expect(trackerSpeedToKmh(1.5)).toBeCloseTo(5.4);
    expect(formatTrackerSpeedKmh(1.5)).toBe('5.4 km/h');
    expect(formatTrackerSpeedKmh(null)).toBeNull();
  });
});
