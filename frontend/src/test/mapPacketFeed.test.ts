import { describe, expect, it } from 'vitest';
import { PayloadType } from '@michaelhart/meshcore-decoder';

import type { Channel, Contact, RawPacket } from '../types';
import {
  buildMapPacketFeedContext,
  buildMapPacketFeedEntries,
  buildMapPacketFeedEntry,
  formatMapPacketFeedMessageBody,
  formatMapPacketGroupTextInlineSuffix,
  formatMapPacketHops,
  formatMapPacketSenderFromDecoded,
} from '../utils/mapPacketFeed';
import { getPacketLabel, PARTICLE_COLOR_MAP } from '../utils/visualizerUtils';

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

function makeChannel(name: string, key: string): Channel {
  return {
    key,
    name,
    is_hashtag: name.startsWith('#'),
    on_radio: true,
    favorite: false,
    last_read_at: null,
    muted: false,
  };
}

describe('mapPacketFeed', () => {
  it('formats hop count instead of listing hop tokens', () => {
    expect(formatMapPacketHops(['aa11', 'bb22'])).toBe('(2⇢) ');
    expect(formatMapPacketHops([])).toBe('');
  });

  it('formats decoded message bodies without altering text', () => {
    expect(formatMapPacketFeedMessageBody('hello')).toBe('hello');
    expect(formatMapPacketFeedMessageBody('a'.repeat(30))).toBe('a'.repeat(30));
    expect(formatMapPacketFeedMessageBody('a'.repeat(31))).toBe('a'.repeat(31));
    expect(formatMapPacketFeedMessageBody('   ')).toBe('');
  });

  it('shows source hash tokens like the packet feed when no contact matches', () => {
    const context = buildMapPacketFeedContext([]);
    const packet = makePacket();
    const decoded = makeDecodedStub(PayloadType.TextMessage, { sourceHash: '34' });

    expect(formatMapPacketSenderFromDecoded(packet, decoded, context)).toBe('34');
  });

  it('truncates long hex identities to six characters', () => {
    const context = buildMapPacketFeedContext([]);
    const packet = makePacket();
    const longKey = 'ba2840bcec68fdcb87ff69742b7d0812e93b18d8473f0c82e24b631232ac06e9';
    const decoded = makeDecodedStub(PayloadType.AnonRequest, { senderPublicKey: longKey });

    expect(formatMapPacketSenderFromDecoded(packet, decoded, context)).toBe('ba2840');
  });

  it('shows encrypted channel suffix and first-hop sender when group text is not decrypted', () => {
    const context = buildMapPacketFeedContext([]);
    const packet = makePacket({ decrypted: false });
    const decoded = makeDecodedStub(
      PayloadType.GroupText,
      { channelHash: '0e', ciphertext: 'aa' },
      ['02', 'aa', 'bb', 'cc', 'dd', 'ee', 'ff']
    );

    expect(formatMapPacketSenderFromDecoded(packet, decoded, context)).toBe('02');
    expect(formatMapPacketGroupTextInlineSuffix(decoded)).toBe(' *encrypted* ch:0E');
    expect(formatMapPacketHops(decoded.path ?? [])).toBe('(7⇢) ');
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

    expect(formatMapPacketSenderFromDecoded(packet, decoded, context)).toBe('MountainTop');
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
    expect(entry.messageBody).toBeNull();
    expect(entry.inlineSuffix).toBe('');
  });

  it('puts decoded channel messages on a second indented line with channel target', () => {
    const channels = [makeChannel('#mesh', '0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e')];
    const context = buildMapPacketFeedContext([], channels);
    const entry = buildMapPacketFeedEntry(
      makePacket({
        payload_type: 'GroupText',
        decrypted: true,
        decrypted_info: {
          sender: 'T1000-E 🍄',
          channel_name: '#mesh',
          message: '@[Purple(Mobile)] komt binnen in Nieuw Vennep',
        } as RawPacket['decrypted_info'],
      }),
      context
    );

    expect(entry.senderLabel).toBe('T1000-E 🍄');
    expect(entry.channelTargetLabel).toBe('#mesh');
    expect(entry.messageBody).toBe('@[Purple(Mobile)] komt binnen in Nieuw Vennep');
    expect(entry.inlineSuffix).toBe('');
  });

  it('puts decoded direct messages on a second indented line with recipient target', () => {
    const selfKey = 'ffffffffffff0000000000000000000000000000000000000000000000000000';
    const bob = makeContact({
      public_key: 'bbbbbbbbbbbb0000000000000000000000000000000000000000000000000000',
      name: 'Bob',
    });
    const context = buildMapPacketFeedContext([bob], null, selfKey, 'MyRadio');
    const entry = buildMapPacketFeedEntry(
      makePacket({
        payload_type: 'TextMessage',
        decrypted: true,
        decrypted_info: {
          sender: 'MyRadio',
          contact_key: bob.public_key,
          message: 'hello there',
        } as RawPacket['decrypted_info'],
      }),
      context
    );

    expect(entry.senderLabel).toBe('MyRadio');
    expect(entry.channelTargetLabel).toBe('Bob (BBBB)');
    expect(entry.messageBody).toBe('hello there');
    expect(entry.inlineSuffix).toBe('');
  });

  it('keeps long decoded message bodies on feed entries', () => {
    const context = buildMapPacketFeedContext([]);
    const entry = buildMapPacketFeedEntry(
      makePacket({
        payload_type: 'GroupText',
        decrypted: true,
        decrypted_info: {
          sender: 'Alice',
          message: 'x'.repeat(35),
        } as RawPacket['decrypted_info'],
      }),
      context
    );

    expect(entry.messageBody).toBe('x'.repeat(35));
    expect(entry.inlineSuffix).toBe('');
  });

  it('treats Path packets like ACK for label and live-traffic color', () => {
    expect(getPacketLabel(PayloadType.Path)).toBe('ACK');
    expect(PARTICLE_COLOR_MAP[getPacketLabel(PayloadType.Path)]).toBe(PARTICLE_COLOR_MAP.ACK);
  });
});
