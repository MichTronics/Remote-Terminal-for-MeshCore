import { describe, expect, it } from 'vitest';
import { PayloadType } from '@michaelhart/meshcore-decoder';

import type { Contact, RadioConfig } from '../types';
import { CONTACT_TYPE_REPEATER } from '../types';
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

function makeConfig(publicKey: string): RadioConfig {
  return {
    public_key: publicKey,
    name: 'MyRadio',
    lat: 39.7,
    lon: -104.9,
    tx_power: 20,
    max_tx_power: 22,
    radio: {
      frequency: 915,
      bandwidth: 250,
      spreading_factor: 10,
      coding_rate: 5,
    },
    path_hash_mode: 1,
    path_hash_mode_supported: true,
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
  config: RadioConfig
): MapPacketPathContext {
  return {
    contacts,
    config,
    myLatLon: [config.lat, config.lon],
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
      type: CONTACT_TYPE_REPEATER,
      lat: 40.05,
      lon: -105.05,
    });
    const context = buildContext([alice, relay], makeConfig(selfKey));
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

  it('draws adverts from source through repeater hops to self', () => {
    const selfKey = 'ffffffffffff0000000000000000000000000000000000000000000000000000';
    const advertiser = makeContact({
      public_key: 'cccccccccccc0000000000000000000000000000000000000000000000000000',
      name: 'Advertiser',
      lat: 41,
      lon: -106,
    });
    const relay = makeContact({
      public_key: '3232323232320000000000000000000000000000000000000000000000000000',
      name: 'Relay',
      type: CONTACT_TYPE_REPEATER,
      lat: 40.05,
      lon: -105.05,
    });
    const context = buildContext([advertiser, relay], makeConfig(selfKey));
    const parsed = makeParsed({
      payloadType: PayloadType.Advert,
      advertPubkey: advertiser.public_key,
      pathBytes: ['323232323232'],
    });

    expect(resolveMapPacketWaypoints(parsed, context)).toEqual([
      [41, -106],
      [40.05, -105.05],
      [39.7, -104.9],
    ]);
  });

  it('draws ack packets through repeater hops even without an explicit sender', () => {
    const selfKey = 'ffffffffffff0000000000000000000000000000000000000000000000000000';
    const relayA = makeContact({
      public_key: '3232323232320000000000000000000000000000000000000000000000000000',
      name: 'Relay A',
      type: CONTACT_TYPE_REPEATER,
      lat: 40.05,
      lon: -105.05,
    });
    const relayB = makeContact({
      public_key: '5656565656560000000000000000000000000000000000000000000000000000',
      name: 'Relay B',
      type: CONTACT_TYPE_REPEATER,
      lat: 40.02,
      lon: -105.02,
    });
    const context = buildContext([relayA, relayB], makeConfig(selfKey));
    const parsed = makeParsed({
      payloadType: PayloadType.Ack,
      pathBytes: ['323232323232', '565656565656'],
    });

    expect(resolveMapPacketWaypoints(parsed, context)).toEqual([
      [40.05, -105.05],
      [40.02, -105.02],
      [39.7, -104.9],
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
      type: CONTACT_TYPE_REPEATER,
      lat: 40.05,
      lon: -105.05,
    });
    const context = buildContext([alice, relay], makeConfig(selfKey));
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
    const context = buildContext([alice], makeConfig(selfKey));
    const parsed = makeParsed({
      srcHash: 'aaaaaaaaaaaa',
      dstHash: 'ffffffffffff',
    });

    const keys = resolveMapPacketContactKeys(parsed, context);
    expect(keys.has(alice.public_key)).toBe(true);
    expect(keys.has(selfKey)).toBe(true);
  });
});
