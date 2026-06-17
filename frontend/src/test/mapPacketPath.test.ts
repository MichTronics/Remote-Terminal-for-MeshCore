import { describe, expect, it } from 'vitest';
import { PayloadType } from '@michaelhart/meshcore-decoder';

import type { Contact } from '../types';
import {
  resolveMapPacketContactKeys,
  resolveMapPacketWaypoints,
  type MapPacketPathContext,
} from '../utils/mapPacketPath';
import type { ParsedPacket } from '../utils/visualizerUtils';

function makeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    public_key: 'bbbbbbbbbbbb0000000000000000000000000000000000000000000000000000',
    name: 'Bob',
    type: 1,
    flags: 0,
    direct_path: null,
    direct_path_len: -1,
    direct_path_hash_mode: 0,
    last_advert: 1700000000,
    lat: 40.1,
    lon: -105.1,
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

function makeParsed(overrides: Partial<ParsedPacket> = {}): ParsedPacket {
  return {
    payloadType: PayloadType.TextMessage,
    messageHash: 'abc',
    pathBytes: [],
    srcHash: null,
    dstHash: null,
    advertPubkey: null,
    groupTextSender: null,
    anonRequestPubkey: null,
    ...overrides,
  };
}

function buildContext(
  contacts: Contact[],
  myPublicKey?: string,
  myLatLon: [number, number] | null = [39.7, -104.9]
): MapPacketPathContext {
  const prefixIndex = new Map<string, Contact[]>();
  const nameIndex = new Map<string, Contact>();
  for (const contact of contacts) {
    const pubkey = contact.public_key.toLowerCase();
    for (let len = 1; len <= 12 && len <= pubkey.length; len++) {
      const prefix = pubkey.slice(0, len);
      const existing = prefixIndex.get(prefix);
      if (existing) existing.push(contact);
      else prefixIndex.set(prefix, [contact]);
    }
    if (contact.name && !nameIndex.has(contact.name)) {
      nameIndex.set(contact.name, contact);
    }
  }
  return {
    prefixIndex,
    nameIndex,
    myLatLon,
    myPublicKey,
  };
}

describe('mapPacketPath', () => {
  it('draws incoming direct messages from sender through hops to self', () => {
    const selfKey = 'ffffffffffff0000000000000000000000000000000000000000000000000000';
    const alice = makeContact({
      public_key: 'aaaaaaaaaaaa0000000000000000000000000000000000000000000000000000',
      name: 'Alice',
      lat: 40,
      lon: -105,
    });
    const relay = makeContact({
      public_key: '3232323232320000000000000000000000000000000000000000000000000000',
      name: 'Relay',
      type: 2,
      lat: 40.05,
      lon: -105.05,
    });
    const context = buildContext([alice, relay], selfKey);
    const parsed = makeParsed({
      srcHash: 'aaaaaaaaaaaa',
      dstHash: 'ffffffffffff',
      pathBytes: ['323232323232'],
    });

    expect(resolveMapPacketWaypoints(parsed, context)).toEqual([
      [40, -105],
      [40.05, -105.05],
      [39.7, -104.9],
    ]);
  });

  it('draws outgoing direct messages from self through hops to recipient', () => {
    const selfKey = 'ffffffffffff0000000000000000000000000000000000000000000000000000';
    const bob = makeContact();
    const relay = makeContact({
      public_key: '3232323232320000000000000000000000000000000000000000000000000000',
      name: 'Relay',
      type: 2,
      lat: 40.05,
      lon: -105.05,
    });
    const context = buildContext([bob, relay], selfKey);
    const parsed = makeParsed({
      srcHash: 'ffffffffffff',
      dstHash: 'bbbbbbbbbbbb',
      pathBytes: ['323232323232'],
    });

    expect(resolveMapPacketWaypoints(parsed, context)).toEqual([
      [39.7, -104.9],
      [40.05, -105.05],
      [40.1, -105.1],
    ]);
  });

  it('resolves one-byte repeater hops when the prefix is unambiguous', () => {
    const selfKey = 'ffffffffffff0000000000000000000000000000000000000000000000000000';
    const alice = makeContact({
      public_key: 'aaaaaaaaaaaa0000000000000000000000000000000000000000000000000000',
      name: 'Alice',
      lat: 40,
      lon: -105,
    });
    const relay = makeContact({
      public_key: '3232323232320000000000000000000000000000000000000000000000000000',
      name: 'Relay',
      type: 2,
      lat: 40.05,
      lon: -105.05,
    });
    const context = buildContext([alice, relay], selfKey);
    const parsed = makeParsed({
      srcHash: 'aaaaaaaaaaaa',
      dstHash: 'ffffffffffff',
      pathBytes: ['32'],
    });

    expect(resolveMapPacketWaypoints(parsed, context)).toEqual([
      [40, -105],
      [40.05, -105.05],
      [39.7, -104.9],
    ]);
  });

  it('collects discovered contacts from resolved packet endpoints and hops', () => {
    const selfKey = 'ffffffffffff0000000000000000000000000000000000000000000000000000';
    const alice = makeContact({
      public_key: 'aaaaaaaaaaaa0000000000000000000000000000000000000000000000000000',
      name: 'Alice',
    });
    const context = buildContext([alice], selfKey);
    const parsed = makeParsed({
      srcHash: 'aaaaaaaaaaaa',
      dstHash: 'ffffffffffff',
    });

    const keys = resolveMapPacketContactKeys(parsed, context);
    expect(keys.has(alice.public_key)).toBe(true);
    expect(keys.has(selfKey)).toBe(true);
  });
});
