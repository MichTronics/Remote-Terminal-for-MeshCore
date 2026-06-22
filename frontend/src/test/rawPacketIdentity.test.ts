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

  it('preserves longest path when only two distinct paths have been seen', () => {
    const shortPath = createPacket({ id: 10, observation_id: 200, data: 'aa' });
    const longPath = createPacket({ id: 10, observation_id: 201, data: 'aabbcc' });
    const shortAgain = createPacket({ id: 10, observation_id: 202, data: 'aa' });

    let state: RawPacket[] = [];
    state = appendRawPacketUnique(state, shortPath, 500);
    state = appendRawPacketUnique(state, longPath, 500);
    state = appendRawPacketUnique(state, shortAgain, 500);

    expect(state).toHaveLength(1);
    expect(state[0].observation_id).toBe(202);
    expect(state[0].data).toBe('aabbcc');
    expect(state[0].feed_seen_paths).toHaveLength(2);
  });

  it('uses the latest path after three distinct paths have been seen', () => {
    const first = createPacket({ id: 20, observation_id: 400, data: 'aa11ccdd' });
    const second = createPacket({ id: 20, observation_id: 401, data: 'bb22ccdd' });
    const third = createPacket({ id: 20, observation_id: 402, data: 'cc33ccdd' });
    const fourth = createPacket({ id: 20, observation_id: 403, data: 'dd' });

    let state: RawPacket[] = [];
    state = appendRawPacketUnique(state, first, 500);
    state = appendRawPacketUnique(state, second, 500);
    state = appendRawPacketUnique(state, third, 500);
    state = appendRawPacketUnique(state, fourth, 500);

    expect(state).toHaveLength(1);
    expect(state[0].observation_id).toBe(403);
    expect(state[0].data).toBe('dd');
    expect(state[0].feed_seen_paths).toHaveLength(4);
  });

  it('moves updated packets to the end of the feed list', () => {
    const other = createPacket({ id: 2, observation_id: 2, data: 'ff' });
    const first = createPacket({ id: 1, observation_id: 1, data: 'aa' });
    const repeat = createPacket({ id: 1, observation_id: 3, data: 'aabb' });

    let state = appendRawPacketUnique([], first, 500);
    state = appendRawPacketUnique(state, other, 500);
    state = appendRawPacketUnique(state, repeat, 500);

    expect(state.map((packet) => packet.id)).toEqual([2, 1]);
    expect(state[1].data).toBe('aabb');
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
