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
    decrypted: false,
    decrypted_info: null,
    ...overrides,
  };
}

describe('getRawPacketObservationKey', () => {
  it('uses observation_id when present', () => {
    const packet = createPacket({ id: 99, observation_id: 7 });
    expect(getRawPacketObservationKey(packet)).toBe('obs-7');
  });

  it('falls back to db id when observation_id is missing', () => {
    const packet = createPacket({ id: 42 });
    expect(getRawPacketObservationKey(packet)).toBe('db-42');
  });
});

describe('appendRawPacketUnique', () => {
  it('keeps path-diverse observations with same db id', () => {
    const first = createPacket({ id: 5, observation_id: 100, data: 'aa' });
    const second = createPacket({ id: 5, observation_id: 101, data: 'bb' });

    const afterFirst = appendRawPacketUnique([], first, 500);
    const afterSecond = appendRawPacketUnique(afterFirst, second, 500);

    expect(afterSecond).toHaveLength(2);
    expect(afterSecond[0].observation_id).toBe(100);
    expect(afterSecond[1].observation_id).toBe(101);
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
    expect(state[0].observation_id).toBe(2);
    expect(state[1].observation_id).toBe(3);
  });
});
