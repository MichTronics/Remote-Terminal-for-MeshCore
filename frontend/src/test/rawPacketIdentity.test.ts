import { describe, expect, it } from 'vitest';
import type { RawPacket } from '../types';
import { appendRawPacketUnique, getRawPacketObservationKey } from '../utils/rawPacketIdentity';

function createPacket(overrides: Partial<RawPacket> = {}): RawPacket {
  return {
    id: 1,
    timestamp: 1700000000,
    data: '010203',
    payload_type: 'ACK',
    snr: null,
    rssi: null,
    transport_codes: null,
    region_name: null,
    decrypted: false,
    decrypted_info: null,
    ...overrides,
  };
}

describe('getRawPacketObservationKey', () => {
  it('always uses db id for packet feed deduplication', () => {
    const packet = createPacket({ id: 99, observation_id: 7 });
    expect(getRawPacketObservationKey(packet)).toBe('db-99');
  });

  it('uses db id when observation_id is missing', () => {
    const packet = createPacket({ id: 42 });
    expect(getRawPacketObservationKey(packet)).toBe('db-42');
  });
});

describe('appendRawPacketUnique', () => {
  it('updates existing packet when same db id arrives with new observation', () => {
    const first = createPacket({ id: 5, observation_id: 100, data: 'aa' });
    const second = createPacket({ id: 5, observation_id: 101, data: 'bb' });

    const afterFirst = appendRawPacketUnique([], first, 500);
    const afterSecond = appendRawPacketUnique(afterFirst, second, 500);

    // Should have 1 packet (updated), not 2
    expect(afterSecond).toHaveLength(1);
    expect(afterSecond[0].observation_id).toBe(101);
    expect(afterSecond[0].data).toBe('bb');
  });

  it('preserves longest path when packets arrive out of order', () => {
    // Create packets with actual path data (simplified for test)
    // In reality, these would be full MeshCore packet hex
    const sevenHops = createPacket({ 
      id: 10, 
      observation_id: 200, 
      data: '00010203040506' // Shorter path
    });
    const nineHops = createPacket({ 
      id: 10, 
      observation_id: 201, 
      data: '000102030405060708' // Longer path
    });
    const eightHops = createPacket({ 
      id: 10, 
      observation_id: 202, 
      data: '0001020304050607' // Medium path
    });

    // Arrive in order: 7, 9, 8
    let state: RawPacket[] = [];
    state = appendRawPacketUnique(state, sevenHops, 500);
    state = appendRawPacketUnique(state, nineHops, 500);
    state = appendRawPacketUnique(state, eightHops, 500);

    // Should preserve the 9-hop path data even though 8-hop arrived last
    expect(state).toHaveLength(1);
    expect(state[0].observation_id).toBe(202); // Latest observation
    expect(state[0].data).toBe('000102030405060708'); // But longest path data
  });

  it('updates to longer path when it arrives later', () => {
    const shortPath = createPacket({ id: 15, observation_id: 300, data: 'aabb' });
    const longPath = createPacket({ id: 15, observation_id: 301, data: 'aabbccdd' });

    const afterFirst = appendRawPacketUnique([], shortPath, 500);
    const afterSecond = appendRawPacketUnique(afterFirst, longPath, 500);

    expect(afterSecond).toHaveLength(1);
    expect(afterSecond[0].data).toBe('aabbccdd'); // Longer path wins
  });

  it('drops exact duplicate observations', () => {
    const packet = createPacket({ id: 5, observation_id: 100 });

    const afterFirst = appendRawPacketUnique([], packet, 500);
    const afterSecond = appendRawPacketUnique(afterFirst, packet, 500);

    expect(afterSecond).toHaveLength(1);
  });

  it('dedupes by db id when observation_id is absent', () => {
    const first = createPacket({ id: 11, observation_id: undefined });
    const second = createPacket({ id: 11, observation_id: undefined, timestamp: 1700000001 });

    const afterFirst = appendRawPacketUnique([], first, 500);
    const afterSecond = appendRawPacketUnique(afterFirst, second, 500);

    expect(afterSecond).toHaveLength(1);
    expect(afterSecond[0].timestamp).toBe(1700000001);
  });

  it('enforces max packet cap', () => {
    const packets = [
      createPacket({ id: 1, observation_id: 1 }),
      createPacket({ id: 2, observation_id: 2 }),
      createPacket({ id: 3, observation_id: 3 }),
    ];

    let state: RawPacket[] = [];
    state = appendRawPacketUnique(state, packets[0], 2);
    state = appendRawPacketUnique(state, packets[1], 2);
    state = appendRawPacketUnique(state, packets[2], 2);

    expect(state).toHaveLength(2);
    expect(state[0].id).toBe(2);
    expect(state[1].id).toBe(3);
  });
});
