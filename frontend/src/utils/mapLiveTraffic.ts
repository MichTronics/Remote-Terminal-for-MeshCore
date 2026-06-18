/** Only animate map particles/lines for packets observed within this window. */
export const MAP_LIVE_ANIMATION_WINDOW_SEC = 60;

export function shouldAnimateMapLivePacket(
  packetTimestampSec: number,
  nowMs: number = Date.now(),
  windowSec: number = MAP_LIVE_ANIMATION_WINDOW_SEC
): boolean {
  return nowMs / 1000 - packetTimestampSec <= windowSec;
}
