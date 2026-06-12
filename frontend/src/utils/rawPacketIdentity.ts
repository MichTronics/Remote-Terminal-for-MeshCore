import { MeshCoreDecoder } from '@michaelhart/meshcore-decoder';
import type { RawPacket } from '../types';

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
  // Use DB row ID for deduplication - same packet updates existing box
  const existingIndex = prev.findIndex((p) => p.id === packet.id);
  
  if (existingIndex !== -1) {
    // Update existing packet, but preserve the longest path seen
    const existing = prev[existingIndex];
    const existingPathLen = getPathLength(existing);
    const newPathLen = getPathLength(packet);
    
    let shouldUpdate = false;
    
    if (existingPathLen === 0 && newPathLen === 0) {
      // Decoder failed for both - fall back to comparing raw data length
      shouldUpdate = packet.data.length >= existing.data.length;
    } else {
      // Use decoded path length comparison
      shouldUpdate = newPathLen >= existingPathLen;
    }
    
    const updated = [...prev];
    if (shouldUpdate) {
      // New packet has longer or equal path - use it
      updated[existingIndex] = packet;
    } else {
      // Existing packet has longer path - keep its data but update other fields
      updated[existingIndex] = {
        ...packet,
        data: existing.data, // Preserve the longer path
      };
    }
    return updated;
  }

  // New packet - append to end
  const updated = [...prev, packet];
  if (updated.length > maxPackets) {
    return updated.slice(-maxPackets);
  }
  return updated;
}
