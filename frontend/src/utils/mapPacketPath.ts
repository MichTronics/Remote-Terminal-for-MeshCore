import { PayloadType } from '@michaelhart/meshcore-decoder';

import type { Contact, RadioConfig, RawPacket } from '../types';
import { getContactDisplayName } from './pubkey';
import {
  buildWaypointsFromResolvedPath,
  findContactsByPrefix,
  isValidLocation,
  pickBestLocatedContact,
  resolvePath,
  type SenderInfo,
} from './pathUtils';
import type { ParsedPacket } from './visualizerUtils';

export interface MapPacketPathContext {
  contacts: Contact[];
  config: RadioConfig | null;
  myLatLon: [number, number] | null;
}

function pickUnambiguousOrFirst(matches: Contact[]): Contact | null {
  if (matches.length === 0) {
    return null;
  }
  if (matches.length === 1) {
    return matches[0];
  }
  const withGps = matches.filter((contact) => isValidLocation(contact.lat, contact.lon));
  return withGps[0] ?? matches[0];
}

function pathBytesToRoute(pathBytes: string[]): { path: string; hopCount: number } | null {
  if (pathBytes.length === 0) {
    return null;
  }
  return {
    path: pathBytes.map((token) => token.replace(/\s/g, '').toUpperCase()).join(''),
    hopCount: pathBytes.length,
  };
}

function effectiveRadioConfig(
  config: RadioConfig | null,
  myLatLon: [number, number] | null
): RadioConfig | null {
  if (!config) {
    return null;
  }
  if (myLatLon && !isValidLocation(config.lat, config.lon)) {
    return { ...config, lat: myLatLon[0], lon: myLatLon[1] };
  }
  return config;
}

function buildSenderInfo(
  parsed: ParsedPacket,
  packet: RawPacket | null | undefined,
  contacts: Contact[],
  config: RadioConfig | null
): SenderInfo {
  const configHashMode = config?.path_hash_mode ?? null;

  if (parsed.payloadType === PayloadType.Advert && parsed.advertPubkey) {
    const prefix = parsed.advertPubkey.slice(0, 12);
    const contact = pickUnambiguousOrFirst(findContactsByPrefix(prefix, contacts, false));
    return {
      name: contact
        ? getContactDisplayName(contact.name, contact.public_key, contact.last_advert)
        : prefix.toUpperCase(),
      publicKeyOrPrefix: parsed.advertPubkey,
      lat: contact?.lat ?? null,
      lon: contact?.lon ?? null,
      pathHashMode: contact?.direct_path_hash_mode ?? configHashMode,
    };
  }

  if (parsed.payloadType === PayloadType.AnonRequest && parsed.anonRequestPubkey) {
    const prefix = parsed.anonRequestPubkey.slice(0, 12);
    const contact = pickUnambiguousOrFirst(findContactsByPrefix(prefix, contacts, false));
    return {
      name: contact
        ? getContactDisplayName(contact.name, contact.public_key, contact.last_advert)
        : prefix.toUpperCase(),
      publicKeyOrPrefix: parsed.anonRequestPubkey,
      lat: contact?.lat ?? null,
      lon: contact?.lon ?? null,
      pathHashMode: contact?.direct_path_hash_mode ?? configHashMode,
    };
  }

  if (parsed.payloadType === PayloadType.GroupText) {
    const senderName = parsed.groupTextSender || packet?.decrypted_info?.sender;
    if (senderName) {
      const contact = contacts.find((entry) => entry.name === senderName) ?? null;
      return {
        name: senderName,
        publicKeyOrPrefix: contact?.public_key ?? senderName,
        lat: contact?.lat ?? null,
        lon: contact?.lon ?? null,
        pathHashMode: contact?.direct_path_hash_mode ?? configHashMode,
      };
    }
  }

  if (parsed.srcHash) {
    const myPrefix = config?.public_key?.slice(0, 12).toLowerCase();
    if (
      parsed.payloadType === PayloadType.TextMessage &&
      myPrefix &&
      parsed.srcHash.toLowerCase() === myPrefix
    ) {
      return {
        name: config?.name || 'Me',
        publicKeyOrPrefix: config!.public_key,
        lat: config?.lat ?? null,
        lon: config?.lon ?? null,
        pathHashMode: configHashMode,
      };
    }

    const repeatersOnly =
      parsed.payloadType === PayloadType.Request ||
      parsed.payloadType === PayloadType.Response;
    const contact = pickUnambiguousOrFirst(
      findContactsByPrefix(parsed.srcHash, contacts, repeatersOnly)
    );
    return {
      name: contact
        ? getContactDisplayName(contact.name, contact.public_key, contact.last_advert)
        : parsed.srcHash.toUpperCase(),
      publicKeyOrPrefix: parsed.srcHash,
      lat: contact?.lat ?? null,
      lon: contact?.lon ?? null,
      pathHashMode: contact?.direct_path_hash_mode ?? configHashMode,
    };
  }

  return {
    name: 'Unknown',
    publicKeyOrPrefix: '??',
    lat: null,
    lon: null,
    pathHashMode: configHashMode,
  };
}

function buildResolvedPathFromParsed(
  parsed: ParsedPacket,
  context: MapPacketPathContext,
  packet?: RawPacket | null
) {
  const route = pathBytesToRoute(parsed.pathBytes);
  const sender = buildSenderInfo(parsed, packet, context.contacts, context.config);
  return resolvePath(
    route?.path ?? '',
    sender,
    context.contacts,
    effectiveRadioConfig(context.config, context.myLatLon),
    route?.hopCount ?? 0
  );
}

/** Resolve geographic waypoints for map particle/route rendering. */
export function resolveMapPacketWaypoints(
  parsed: ParsedPacket,
  context: MapPacketPathContext,
  packet?: RawPacket | null
): [number, number][] | null {
  const waypoints = buildWaypointsFromResolvedPath(
    buildResolvedPathFromParsed(parsed, context, packet)
  );
  return waypoints.length >= 2 ? waypoints : null;
}

/** Collect public keys of unambiguously resolved GPS-bearing contacts from a parsed packet. */
export function resolveMapPacketContactKeys(
  parsed: ParsedPacket,
  context: MapPacketPathContext,
  packet?: RawPacket | null
): Set<string> {
  const keys = new Set<string>();
  const resolved = buildResolvedPathFromParsed(parsed, context, packet);

  const addContact = (contact: Contact | null | undefined) => {
    if (contact && isValidLocation(contact.lat, contact.lon)) {
      keys.add(contact.public_key);
    }
  };

  if (isValidLocation(resolved.sender.lat, resolved.sender.lon)) {
    const senderMatches = findContactsByPrefix(
      resolved.sender.prefix,
      context.contacts,
      false
    );
    if (senderMatches.length === 1) {
      addContact(senderMatches[0]);
    }
  }

  let prevLat = resolved.sender.lat;
  let prevLon = resolved.sender.lon;
  for (const hop of resolved.hops) {
    const best = pickBestLocatedContact(hop.matches, prevLat, prevLon);
    addContact(best);
    if (best && isValidLocation(best.lat, best.lon)) {
      prevLat = best.lat;
      prevLon = best.lon;
    }
  }

  if (resolved.receiver.publicKey && isValidLocation(resolved.receiver.lat, resolved.receiver.lon)) {
    keys.add(resolved.receiver.publicKey.toLowerCase());
  }

  return keys;
}
