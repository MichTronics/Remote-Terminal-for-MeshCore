import { describe, expect, it } from 'vitest';
import { PayloadType } from '@michaelhart/meshcore-decoder';

import type { Contact, RawPacket } from '../types';
import {
  buildMapPacketFeedContext,
  buildMapPacketFeedEntries,
  buildMapPacketFeedEntry,
  formatMapPacketDecodedMessage,
  formatMapPacketHops,
  formatMapPacketSenderFromDecoded,
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

function makeDecodedStub(
  payloadType: PayloadType,
  decoded: Record<string, unknown> | null,
  path: string[] = []
) {
  return {
    isValid: true,
    payloadType,
    path,
    payload: { decoded },
  } as Parameters<typeof formatMapPacketSenderFromDecoded>[1];
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

  it('shows source hash tokens like the packet feed when no contact matches', () => {
    const indexes = buildMapPacketFeedContext([]).indexes;
    const packet = makePacket();
    const decoded = makeDecodedStub(PayloadType.TextMessage, { sourceHash: '34' });

    expect(formatMapPacketSenderFromDecoded(packet, decoded, indexes)).toBe('34');
  });

  it('formats known sender as name plus pubkey snippet', () => {
    const contact = makeContact();
    const context = buildMapPacketFeedContext([contact]);
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
    const decoded = makeDecodedStub(PayloadType.GroupText, {
      decrypted: { sender: 'MountainTop' },
    });

    expect(formatMapPacketSenderFromDecoded(packet, decoded, context.indexes)).toBe(
      'MountainTop (abcdef)'
    );
  });

  it('builds feed entries newest-first with a limit of 12', () => {
    const context = buildMapPacketFeedContext([]);
    const packets = Array.from({ length: 15 }, (_, index) =>
      makePacket({
        id: index + 1,
        observation_id: index + 1,
        timestamp: 1700000000 + index,
        payload_type: index % 2 === 0 ? 'ADVERT' : 'ACK',
      })
    );

    const entries = buildMapPacketFeedEntries(packets, context, 12);
    expect(entries).toHaveLength(12);
    expect(entries[0].timestamp).toBe(1700000014);
    expect(entries[11].timestamp).toBe(1700000003);
  });

  it('uses live-traffic advert color for advert packets', () => {
    const context = buildMapPacketFeedContext([]);
    const entry = buildMapPacketFeedEntry(
      makePacket({ payload_type: 'ADVERT', decrypted_info: { sender: 'solo' } as RawPacket['decrypted_info'] }),
      context
    );

    expect(entry.typeLabel).toBe('ADVERT');
    expect(entry.typeColor).toBe('#f59e0b');
    expect(entry.senderLabel).toBe('solo');
    expect(entry.messageSuffix).toBe('');
  });

  it('includes truncated decoded message suffix on feed entries', () => {
    const context = buildMapPacketFeedContext([]);
    const entry = buildMapPacketFeedEntry(
      makePacket({
        payload_type: 'GroupText',
        decrypted_info: {
          sender: 'Alice',
          message: 'x'.repeat(35),
        } as RawPacket['decrypted_info'],
      }),
      context
    );

    expect(entry.messageSuffix).toBe(`: ${'x'.repeat(28)}...`);
  });
});
