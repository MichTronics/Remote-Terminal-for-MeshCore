/** Format tracker altitude for map labels (meters above sea level). */
export function formatTrackerAltitudeM(altitude: number | null | undefined): string | null {
  if (altitude == null || !Number.isFinite(altitude)) {
    return null;
  }
  return `${Math.round(altitude)}m`;
}

/** Convert stored tracker speed (m/s) to km/h. */
export function trackerSpeedToKmh(speedMs: number | null | undefined): number | null {
  if (speedMs == null || !Number.isFinite(speedMs)) {
    return null;
  }
  return speedMs * 3.6;
}

/** Format tracker speed for map labels (km/h). */
export function formatTrackerSpeedKmh(speedMs: number | null | undefined): string | null {
  const kmh = trackerSpeedToKmh(speedMs);
  if (kmh == null) {
    return null;
  }
  return `${kmh.toFixed(1)} km/h`;
}
