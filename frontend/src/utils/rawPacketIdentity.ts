import { MeshCoreDecoder } from '@michaelhart/meshcore-decoder';
import type { RawPacket } from '../types';

/** After this many distinct paths, show the latest observation instead of longest. */
export const RAW_PACKET_LATEST_PATH_THRESHOLD = 3;

/**
 * Get path length from a packet by decoding it.
 * Returns 0 if decoding fails or no path exists.
 */
function getPathLength(packet: RawPacket): number {
  try {
    const decoded = MeshCoreDecoder.decode(packet.data);
    if (!decoded.isValid || !decoded.path) {
      return 0;
    }
    return decoded.path.length;
  } catch {
    return 0;
  }
}

function getPathSignature(packet: RawPacket): string {
  try {
    const decoded = MeshCoreDecoder.decode(packet.data);
    if (decoded.isValid && decoded.path?.length) {
      return decoded.path.join(',');
    }
  } catch {
    // Fall back to raw bytes when the decoder cannot extract a path.
  }
  return packet.data ? `raw:${packet.data}` : '';
}

function registerPathObservation(
  existingPaths: string[] | undefined,
  pathSignature: string
): string[] {
  if (!pathSignature) {
    return existingPaths ? [...existingPaths] : [];
  }
  const seen = existingPaths ? [...existingPaths] : [];
  if (!seen.includes(pathSignature)) {
    seen.push(pathSignature);
  }
  return seen;
}

function mergePacketDataPreferringLongestPath(
  existing: RawPacket,
  incoming: RawPacket
): RawPacket {
  const existingPathLen = getPathLength(existing);
  const newPathLen = getPathLength(incoming);

  let shouldUseIncomingData = false;
  if (existingPathLen === 0 && newPathLen === 0) {
    shouldUseIncomingData = incoming.data.length >= existing.data.length;
  } else {
    shouldUseIncomingData = newPathLen >= existingPathLen;
  }

  if (shouldUseIncomingData) {
    return incoming;
  }

  return {
    ...incoming,
    data: existing.data,
  };
}

function appendWithCap(packets: RawPacket[], maxPackets: number): RawPacket[] {
  if (packets.length > maxPackets) {
    return packets.slice(-maxPackets);
  }
  return packets;
}

/**
 * Get unique key for a raw packet.
 * For the raw packet feed, we use the DB row ID so the same packet (same payload)
 * updates the existing box as it propagates through different paths.
 * observation_id is used by stats tracking to count every RF observation.
 */
export function getRawPacketObservationKey(
  packet: Pick<RawPacket, 'id' | 'observation_id'>
): string {
  return `db-${packet.id}`;
}

export function appendRawPacketUnique(
  prev: RawPacket[],
  packet: RawPacket,
  maxPackets: number
): RawPacket[] {
  const pathSignature = getPathSignature(packet);

  const existingIndex = prev.findIndex((p) => p.id === packet.id);
  if (existingIndex === -1) {
    const nextPacket: RawPacket = {
      ...packet,
      feed_seen_paths: registerPathObservation(undefined, pathSignature),
    };
    return appendWithCap([...prev, nextPacket], maxPackets);
  }

  const existing = prev[existingIndex];
  const feedSeenPaths = registerPathObservation(existing.feed_seen_paths, pathSignature);
  const useLatestPath = feedSeenPaths.length >= RAW_PACKET_LATEST_PATH_THRESHOLD;

  const merged: RawPacket = {
    ...(useLatestPath
      ? packet
      : mergePacketDataPreferringLongestPath(existing, packet)),
    feed_seen_paths: feedSeenPaths,
  };

  const withoutExisting = prev.filter((_, index) => index !== existingIndex);
  return appendWithCap([...withoutExisting, merged], maxPackets);
}
