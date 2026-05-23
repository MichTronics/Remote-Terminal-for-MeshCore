/**
 * Client-side region identification for MeshCore transport codes.
 * Matches packets against known regions using HMAC calculation.
 */

import type { Region } from '../types';

/**
 * Calculate MeshCore transport code for a given region and packet.
 * Matches Python backend: HMAC-SHA256(region_key, payload_type_byte + payload)[:2]
 */
async function calculateTransportCode(
  regionKeyHex: string,
  payloadType: number,
  payload: Uint8Array
): Promise<number> {
  // Convert hex key to bytes
  const keyBytes = new Uint8Array(
    regionKeyHex.match(/.{2}/g)!.map((byte) => parseInt(byte, 16))
  );

  // Build message: payload_type byte + payload
  const message = new Uint8Array(1 + payload.length);
  message[0] = payloadType;
  message.set(payload, 1);

  // Import key for HMAC
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    keyBytes,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );

  // Calculate HMAC
  const signature = await crypto.subtle.sign('HMAC', cryptoKey, message);
  const mac = new Uint8Array(signature);

  // Extract first 2 bytes as little-endian uint16
  let code = mac[0] | (mac[1] << 8);

  // Remap 0x0000 → 0x0001 and 0xFFFF → 0xFFFE (matches backend)
  if (code === 0x0000) code = 0x0001;
  if (code === 0xffff) code = 0xfffe;

  return code;
}

/**
 * Extract transport codes from packet hex data.
 * Returns [primary, secondary] as uint16 values, or null if not a transport packet.
 */
function extractTransportCodes(dataHex: string): [number, number] | null {
  if (dataHex.length < 10) return null; // Need at least header (1) + transport codes (4)

  const header = parseInt(dataHex.slice(0, 2), 16);
  const routeType = (header >> 6) & 0x03;

  // Transport codes only present for TRANSPORT_FLOOD (0x00) or TRANSPORT_DIRECT (0x03)
  if (routeType !== 0x00 && routeType !== 0x03) {
    return null;
  }

  // Extract 4 bytes of transport codes (bytes 1-4)
  const transportBytes = dataHex.slice(2, 10); // 4 bytes = 8 hex chars
  if (transportBytes.length !== 8) return null;

  // Parse as little-endian uint16s
  const primaryLow = parseInt(transportBytes.slice(0, 2), 16);
  const primaryHigh = parseInt(transportBytes.slice(2, 4), 16);
  const secondaryLow = parseInt(transportBytes.slice(4, 6), 16);
  const secondaryHigh = parseInt(transportBytes.slice(6, 8), 16);

  const primary = primaryLow | (primaryHigh << 8);
  const secondary = secondaryLow | (secondaryHigh << 8);

  return [primary, secondary];
}

/**
 * Extract payload type and payload from packet hex data.
 * Returns { payloadType, payload } or null if packet is too short.
 */
function extractPayload(dataHex: string): { payloadType: number; payload: Uint8Array } | null {
  if (dataHex.length < 10) return null;

  const header = parseInt(dataHex.slice(0, 2), 16);
  const routeType = (header >> 6) & 0x03;
  const payloadType = (header >> 2) & 0x0f;

  // For transport packets, payload starts after header (1 byte) + transport codes (4 bytes)
  // For non-transport, payload starts after header (1 byte)
  const payloadStartByte = routeType === 0x00 || routeType === 0x03 ? 5 : 1;
  const payloadHex = dataHex.slice(payloadStartByte * 2);

  // Convert payload hex to bytes
  const payload = new Uint8Array(
    payloadHex.match(/.{2}/g)?.map((byte) => parseInt(byte, 16)) || []
  );

  return { payloadType, payload };
}

/**
 * Identify which region a packet belongs to by testing transport codes against known regions.
 * Returns the region name if matched, otherwise null.
 */
export async function identifyPacketRegion(
  dataHex: string,
  regions: Region[]
): Promise<string | null> {
  // Extract transport codes from packet
  const codes = extractTransportCodes(dataHex);
  if (!codes) return null; // Not a transport packet

  const [primaryCode, secondaryCode] = codes;

  // Extract payload for HMAC calculation
  const packetData = extractPayload(dataHex);
  if (!packetData) return null;

  const { payloadType, payload } = packetData;

  // Test each region
  for (const region of regions) {
    try {
      const expectedPrimary = await calculateTransportCode(region.key, payloadType, payload);

      // Primary code must match
      if (expectedPrimary !== primaryCode) {
        continue;
      }

      // If secondary is 0x0000, primary match is sufficient
      if (secondaryCode === 0x0000) {
        return region.name;
      }

      // Otherwise, calculate secondary code and verify match
      // Secondary uses same calculation with secondary region key (if we had it)
      // For now, we only check primary since we don't have secondary keys in Region model
      // This matches the backend behavior where we identify by primary region only
      return region.name;
    } catch (err) {
      // HMAC calculation failed for this region, continue to next
      console.debug(`Failed to calculate transport code for region ${region.name}:`, err);
      continue;
    }
  }

  return null; // No matching region found
}
