import { describe, expect, it } from 'vitest';

import type { Contact, RawPacket } from '../types';
import {
  buildMapPacketFeedEntries,
  buildMapPacketFeedEntry,
  buildMapPacketFeedIndexes,
  formatMapPacketDecodedMessage,
  formatMapPacketHops,
  formatMapPacketSender,
} from '../utils/mapPacketFeed';

function makeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    public_key: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
    name: 'MountainTop',
    type: 2,
    flags: 0,
    direct_path: null,
    direct_path_len: -1,
    direct_path_hash_mode: 0,
    last_advert: 1700000000,
    lat: 40,
    lon: -105,
    last_seen: 1700000000,
    on_radio: false,
    favorite: false,
    last_contacted: null,
    last_read_at: null,
    first_seen: 1699000000,
    is_tracker: false,
    tracker_name: null,
    ...overrides,
  };
}

function makePacket(overrides: Partial<RawPacket> = {}): RawPacket {
  return {
    id: 1,
    observation_id: 1,
    timestamp: 1700000000,
    data: '00',
    payload_type: 'Unknown',
    snr: null,
    rssi: null,
    transport_codes: null,
    region_name: null,
    decrypted: false,
    decrypted_info: null,
    ...overrides,
  };
}

describe('mapPacketFeed', () => {
  it('formats hop count instead of listing hop tokens', () => {
    expect(formatMapPacketHops(['aa11', 'bb22'])).toBe('(2->) ');
    expect(formatMapPacketHops([])).toBe('');
  });

  it('formats decoded messages with a 30-character cap', () => {
    expect(formatMapPacketDecodedMessage('hello')).toBe(': hello');
    expect(formatMapPacketDecodedMessage('a'.repeat(30))).toBe(`: ${'a'.repeat(30)}`);
    expect(formatMapPacketDecodedMessage('a'.repeat(31))).toBe(`: ${'a'.repeat(28)}...`);
    expect(formatMapPacketDecodedMessage('   ')).toBe('');
  });

  it('formats known sender as name plus pubkey snippet', () => {
    const contact = makeContact();
    const indexes = buildMapPacketFeedIndexes([contact]);
    const packet = makePacket({
      decrypted_info: {
        channel_name: null,
        sender: 'MountainTop',
        channel_key: null,
        contact_key: contact.public_key,
        sender_timestamp: null,
        message: null,
      },
    });

    expect(formatMapPacketSender(null, packet, indexes)).toBe('MountainTop (abcdef)');
  });

  it('builds feed entries newest-first with a limit of 12', () => {
    const indexes = buildMapPacketFeedIndexes([]);
    const packets = Array.from({ length: 15 }, (_, index) =>
      makePacket({
        id: index + 1,
        observation_id: index + 1,
        timestamp: 1700000000 + index,
        payload_type: index % 2 === 0 ? 'ADVERT' : 'ACK',
      })
    );

    const entries = buildMapPacketFeedEntries(packets, indexes, 12);
    expect(entries).toHaveLength(12);
    expect(entries[0].timestamp).toBe(1700000014);
    expect(entries[11].timestamp).toBe(1700000003);
  });

  it('uses live-traffic advert color for advert packets', () => {
    const indexes = buildMapPacketFeedIndexes([]);
    const entry = buildMapPacketFeedEntry(
      makePacket({ payload_type: 'ADVERT', decrypted_info: { sender: 'solo' } as RawPacket['decrypted_info'] }),
      indexes
    );

    expect(entry.typeLabel).toBe('ADVERT');
    expect(entry.typeColor).toBe('#f59e0b');
    expect(entry.senderLabel).toBe('solo');
    expect(entry.messageSuffix).toBe('');
  });

  it('includes truncated decoded message suffix on feed entries', () => {
    const indexes = buildMapPacketFeedIndexes([]);
    const entry = buildMapPacketFeedEntry(
      makePacket({
        payload_type: 'GroupText',
        decrypted_info: {
          sender: 'Alice',
          message: 'x'.repeat(35),
        } as RawPacket['decrypted_info'],
      }),
      indexes
    );

    expect(entry.messageSuffix).toBe(`: ${'x'.repeat(28)}...`);
  });
});
