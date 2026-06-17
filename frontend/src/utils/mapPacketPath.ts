import { PayloadType } from '@michaelhart/meshcore-decoder';

import type { Contact, RawPacket } from '../types';
import { isValidLocation } from './pathUtils';
import { dedupeConsecutive, type ParsedPacket } from './visualizerUtils';

export interface MapPacketPathContext {
  prefixIndex: Map<string, Contact[]>;
  nameIndex: Map<string, Contact>;
  myLatLon: [number, number] | null;
  myPublicKey?: string | null;
}

function getMyPrefix(publicKey: string | null | undefined): string | null {
  const normalized = publicKey?.trim().toLowerCase() ?? '';
  return normalized.length > 0 ? normalized.slice(0, 12) : null;
}

function resolveHopToGps(hopToken: string, prefixIndex: Map<string, Contact[]>): Contact | null {
  const matches = prefixIndex.get(hopToken.toLowerCase());
  if (!matches || matches.length !== 1) return null;
  const contact = matches[0];
  return isValidLocation(contact.lat, contact.lon) ? contact : null;
}

function resolveNameToGps(name: string, nameIndex: Map<string, Contact>): Contact | null {
  const contact = nameIndex.get(name);
  if (!contact) return null;
  return isValidLocation(contact.lat, contact.lon) ? contact : null;
}

function resolvePubkeyToGps(pubkey: string, prefixIndex: Map<string, Contact[]>): Contact | null {
  const prefix = pubkey.slice(0, 12).toLowerCase();
  const matches = prefixIndex.get(prefix);
  if (!matches || matches.length !== 1) return null;
  const contact = matches[0];
  return isValidLocation(contact.lat, contact.lon) ? contact : null;
}

function pushContactWaypoint(
  waypoints: [number, number][],
  contact: Contact | null
): void {
  if (!contact) return;
  waypoints.push([contact.lat!, contact.lon!]);
}

function pushLatLonWaypoint(
  waypoints: [number, number][],
  latLon: [number, number] | null
): void {
  if (!latLon) return;
  waypoints.push(latLon);
}

/** Resolve geographic waypoints for map particle/route rendering. */
export function resolveMapPacketWaypoints(
  parsed: ParsedPacket,
  context: MapPacketPathContext,
  packet?: RawPacket | null
): [number, number][] | null {
  const { prefixIndex, nameIndex, myLatLon, myPublicKey } = context;
  const myPrefix = getMyPrefix(myPublicKey);
  const waypoints: [number, number][] = [];

  const isDm = parsed.payloadType === PayloadType.TextMessage;
  const isOutgoingDm =
    isDm && !!myPrefix && parsed.srcHash?.toLowerCase() === myPrefix;

  if (parsed.payloadType === PayloadType.Advert && parsed.advertPubkey) {
    pushContactWaypoint(waypoints, resolvePubkeyToGps(parsed.advertPubkey, prefixIndex));
  } else if (parsed.payloadType === PayloadType.AnonRequest && parsed.anonRequestPubkey) {
    pushContactWaypoint(waypoints, resolvePubkeyToGps(parsed.anonRequestPubkey, prefixIndex));
  } else if (isDm && parsed.srcHash) {
    if (isOutgoingDm) {
      pushLatLonWaypoint(waypoints, myLatLon);
    } else {
      pushContactWaypoint(waypoints, resolveHopToGps(parsed.srcHash, prefixIndex));
    }
  } else if (parsed.payloadType === PayloadType.GroupText) {
    const senderName = parsed.groupTextSender || packet?.decrypted_info?.sender;
    if (senderName) {
      pushContactWaypoint(waypoints, resolveNameToGps(senderName, nameIndex));
    }
  } else if (
    (parsed.payloadType === PayloadType.Request ||
      parsed.payloadType === PayloadType.Response) &&
    parsed.srcHash
  ) {
    pushContactWaypoint(waypoints, resolveHopToGps(parsed.srcHash, prefixIndex));
  }

  for (const hop of parsed.pathBytes) {
    pushContactWaypoint(waypoints, resolveHopToGps(hop, prefixIndex));
  }

  if (isDm && parsed.dstHash) {
    if (myPrefix && parsed.dstHash.toLowerCase() === myPrefix) {
      pushLatLonWaypoint(waypoints, myLatLon);
    } else if (isOutgoingDm) {
      pushContactWaypoint(waypoints, resolveHopToGps(parsed.dstHash, prefixIndex));
    } else {
      const destination = resolveHopToGps(parsed.dstHash, prefixIndex);
      if (destination) {
        pushContactWaypoint(waypoints, destination);
      } else if (waypoints.length > 0) {
        pushLatLonWaypoint(waypoints, myLatLon);
      }
    }
  } else if (waypoints.length > 0) {
    pushLatLonWaypoint(waypoints, myLatLon);
  }

  const deduped = dedupeConsecutive(waypoints.map((waypoint) => `${waypoint[0]},${waypoint[1]}`));
  if (deduped.length < 2) return null;

  return deduped.map((value) => {
    const [lat, lon] = value.split(',').map(Number);
    return [lat, lon] as [number, number];
  });
}

/** Collect public keys of unambiguously resolved GPS-bearing contacts from a parsed packet. */
export function resolveMapPacketContactKeys(
  parsed: ParsedPacket,
  context: MapPacketPathContext,
  packet?: RawPacket | null
): Set<string> {
  const keys = new Set<string>();
  const { prefixIndex, nameIndex, myLatLon, myPublicKey } = context;
  const myPrefix = getMyPrefix(myPublicKey);

  const addContact = (contact: Contact | null) => {
    if (contact) keys.add(contact.public_key);
  };

  if (parsed.advertPubkey) {
    addContact(resolvePubkeyToGps(parsed.advertPubkey, prefixIndex));
  }

  if (parsed.anonRequestPubkey) {
    addContact(resolvePubkeyToGps(parsed.anonRequestPubkey, prefixIndex));
  }

  if (parsed.srcHash) {
    if (
      parsed.payloadType === PayloadType.TextMessage &&
      myPrefix &&
      parsed.srcHash.toLowerCase() === myPrefix
    ) {
      if (myPublicKey) keys.add(myPublicKey.toLowerCase());
    } else {
      addContact(resolveHopToGps(parsed.srcHash, prefixIndex));
    }
  }

  const senderName = parsed.groupTextSender || packet?.decrypted_info?.sender;
  if (senderName) {
    addContact(resolveNameToGps(senderName, nameIndex));
  }

  for (const hop of parsed.pathBytes) {
    addContact(resolveHopToGps(hop, prefixIndex));
  }

  if (myLatLon && myPublicKey) {
    keys.add(myPublicKey.toLowerCase());
  }

  if (parsed.dstHash) {
    addContact(resolveHopToGps(parsed.dstHash, prefixIndex));
  }

  return keys;
}
