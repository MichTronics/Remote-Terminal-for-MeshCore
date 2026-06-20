import { describe, it, expect } from 'vitest';
import { KNOWN_PAYLOAD_TYPES } from '../rawPacketStats';
import { decodePacketSummary } from '../rawPacketInspector';
import { isTrackerDecryptedPacket } from '../trackerPacket';
import type { RawPacket } from '../../types';

describe('Tracker packet display support', () => {
  it('includes GroupData in known payload types', () => {
    expect(KNOWN_PAYLOAD_TYPES).toContain('GroupData');
  });

  it('includes Atlas in known payload types', () => {
    expect(KNOWN_PAYLOAD_TYPES).toContain('Atlas');
  });

  it('GROUP_DATA tracker packet with decrypted_info shows readable summary', () => {
    const mockTrackerPacket: RawPacket = {
      id: 1,
      observation_id: 1,
      timestamp: 1718582400,
      data: '190000000000',
      payload_type: 'GROUP_DATA',
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
        node_id: 'abcd1234',
        is_tracker: true,
        speed: 1.5,
        heading: 90,
        message:
          '📍 TrackerNode: 37.774900, -122.419400 (alt: 50m, speed: 1.5m/s, hdg: 90.0°, sats: 8, batt: 3700mV)',
      },
    };

    expect(isTrackerDecryptedPacket(mockTrackerPacket)).toBe(true);
    expect(mockTrackerPacket.payload_type).toBe('GROUP_DATA');
    expect(mockTrackerPacket.decrypted).toBe(true);
    expect(mockTrackerPacket.decrypted_info?.sender).toBe('TrackerNode');
    expect(mockTrackerPacket.decrypted_info?.message).toContain('📍');
    expect(mockTrackerPacket.decrypted_info?.message).toContain('37.774900');
    expect(mockTrackerPacket.decrypted_info?.message).toContain('-122.419400');
    expect(mockTrackerPacket.decrypted_info?.speed).toBe(1.5);
    expect(mockTrackerPacket.decrypted_info?.heading).toBe(90);

    const summary = decodePacketSummary(mockTrackerPacket);
    expect(summary.summary).toContain('Tracker from TrackerNode');
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
