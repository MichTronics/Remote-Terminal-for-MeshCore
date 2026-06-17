import { describe, expect, it } from 'vitest';
import { getMarkerZoomScale } from '../utils/mapMarkerScale';

describe('getMarkerZoomScale', () => {
  it('returns full size at high zoom', () => {
    expect(getMarkerZoomScale(13)).toBe(1);
    expect(getMarkerZoomScale(16)).toBe(1);
  });

  it('returns half size at country-level zoom', () => {
    expect(getMarkerZoomScale(8)).toBeCloseTo(0.5);
  });

  it('ramps between half and full size', () => {
    expect(getMarkerZoomScale(10.5)).toBeCloseTo(0.75);
  });

  it('shrinks further when zoomed out below country level', () => {
    expect(getMarkerZoomScale(2)).toBeCloseTo(0.3);
    expect(getMarkerZoomScale(5)).toBeLessThan(0.5);
  });
});
