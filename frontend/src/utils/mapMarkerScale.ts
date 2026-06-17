/** Map zoom at which role/tracker markers render at their designed full size. */
export const MAP_MARKER_FULL_SCALE_ZOOM = 13;

/** Country/regional overview zoom — markers render at half of full size. */
export const MAP_MARKER_HALF_SCALE_ZOOM = 8;

/** Smallest scale factor when fully zoomed out. */
export const MAP_MARKER_MIN_SCALE = 0.3;

/**
 * Marker pixel scale for a Leaflet zoom level.
 * Full size at high zoom; ~50% at country view (zoom 8); smaller when zoomed out further.
 */
export function getMarkerZoomScale(zoom: number, minZoom = 2): number {
  const fullAt = MAP_MARKER_FULL_SCALE_ZOOM;
  const halfAt = MAP_MARKER_HALF_SCALE_ZOOM;
  const minScale = MAP_MARKER_MIN_SCALE;

  if (zoom >= fullAt) return 1;

  if (zoom <= halfAt) {
    if (zoom <= minZoom) return minScale;
    const t = (zoom - minZoom) / (halfAt - minZoom);
    return minScale + t * (0.5 - minScale);
  }

  const t = (zoom - halfAt) / (fullAt - halfAt);
  return 0.5 + t * 0.5;
}
