import type { RawPacket } from '../types';

export function isTrackerDecryptedPacket(packet: RawPacket): boolean {
  if (!packet.decrypted || !packet.decrypted_info) {
    return false;
  }
  if (packet.decrypted_info.is_tracker) {
    return true;
  }
  // Backward compatibility for stored LOCATION rows and older payloads.
  return packet.payload_type === 'LOCATION' && typeof packet.decrypted_info.speed === 'number';
}

export function trackerNodeIdFromPacket(packet: RawPacket): string | null {
  const info = packet.decrypted_info;
  if (!info) return null;
  if (info.node_id?.trim()) {
    return info.node_id.trim().toLowerCase();
  }
  if (info.contact_key?.trim()) {
    return info.contact_key.trim().toLowerCase().slice(0, 8);
  }
  return null;
}
