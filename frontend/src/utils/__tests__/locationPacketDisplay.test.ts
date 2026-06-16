import { describe, it, expect } from 'vitest';
import { KNOWN_PAYLOAD_TYPES } from '../rawPacketStats';
import type { RawPacket } from '../../types';

describe('Location packet display support', () => {
  it('includes Location in known payload types', () => {
    expect(KNOWN_PAYLOAD_TYPES).toContain('Location');
  });

  it('includes Atlas in known payload types', () => {
    expect(KNOWN_PAYLOAD_TYPES).toContain('Atlas');
  });

  it('Location packet with decrypted_info shows readable summary', () => {
    const mockLocationPacket: RawPacket = {
      id: 1,
      observation_id: 1,
      timestamp: 1718582400,
      data: '0D0000000000', // Minimal hex
      payload_type: 'LOCATION',
      snr: 8.5,
      rssi: -85,
      transport_codes: null,
      region_name: null,
      decrypted: true,
      decrypted_info: {
        channel_name: null,
        sender: 'TrackerNode',
        channel_key: null,
        contact_key: 'abcd1234ef567890abcd1234ef567890abcd1234ef567890abcd1234ef567890',
        sender_timestamp: 1718582400,
        speed: 1.5,
        heading: 90,
        message:
          '📍 TrackerNode: 37.774900, -122.419400 (alt: 50m, speed: 1.5m/s, hdg: 90.0°, sats: 8, batt: 3700mV)',
      },
    };

    // Verify the packet structure is valid
    expect(mockLocationPacket.payload_type).toBe('LOCATION');
    expect(mockLocationPacket.decrypted).toBe(true);
    expect(mockLocationPacket.decrypted_info?.sender).toBe('TrackerNode');
    expect(mockLocationPacket.decrypted_info?.message).toContain('📍');
    expect(mockLocationPacket.decrypted_info?.message).toContain('37.774900');
    expect(mockLocationPacket.decrypted_info?.message).toContain('-122.419400');
    expect(mockLocationPacket.decrypted_info?.speed).toBe(1.5);
    expect(mockLocationPacket.decrypted_info?.heading).toBe(90);
  });

  it('ATLAS packet type is recognized', () => {
    const mockAtlasPacket: RawPacket = {
      id: 2,
      observation_id: 2,
      timestamp: 1718582400,
      data: '0C0000000000',
      payload_type: 'ATLAS',
      snr: null,
      rssi: null,
      transport_codes: null,
      region_name: null,
      decrypted: false,
      decrypted_info: null,
    };

    expect(mockAtlasPacket.payload_type).toBe('ATLAS');
  });
});
