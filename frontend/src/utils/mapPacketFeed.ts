import {
  MeshCoreDecoder,
  PayloadType,
  type DecodedPacket,
  type DecryptionOptions,
} from '@michaelhart/meshcore-decoder';

import type { Channel, Contact, RawPacket } from '../types';
import { createDecoderOptions } from './rawPacketInspector';
import { getContactDisplayName } from './pubkey';
import { getPacketLabel, PARTICLE_COLOR_MAP } from './visualizerUtils';
import { getRawPacketObservationKey } from './rawPacketIdentity';

export const MAP_PACKET_FEED_LIMIT = 12;

const PACKET_TYPE_LABELS: Record<string, string> = {
  AD: 'ADVERT',
  GT: 'CHANNEL',
  DM: 'DIRECT',
  ACK: 'ACK',
  TR: 'TRACE',
  RQ: 'REQUEST',
  RS: 'RESPONSE',
  '?': 'UNKNOWN',
};

export interface MapPacketFeedEntry {
  key: string;
  timestamp: number;
  typeLabel: string;
  typeColor: string;
  hopsPrefix: string;
  senderLabel: string | null;
  messageSuffix: string;
}

export interface MapPacketFeedIndexes {
  prefixIndex: Map<string, Contact[]>;
  nameIndex: Map<string, Contact>;
}

export interface MapPacketFeedContext {
  indexes: MapPacketFeedIndexes;
  decoderOptions?: DecryptionOptions;
}

export function buildMapPacketFeedIndexes(contacts: Contact[]): MapPacketFeedIndexes {
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
  return { prefixIndex, nameIndex };
}

export function buildMapPacketFeedContext(
  contacts: Contact[],
  channels?: Channel[] | null
): MapPacketFeedContext {
  return {
    indexes: buildMapPacketFeedIndexes(contacts),
    decoderOptions: createDecoderOptions(channels),
  };
}

function resolveContactByPrefix(
  token: string,
  prefixIndex: Map<string, Contact[]>
): Contact | null {
  const matches = prefixIndex.get(token.toLowerCase());
  return matches?.length === 1 ? matches[0] : null;
}

function formatPubkeySnippet(pubkey: string): string {
  return pubkey.slice(0, 6).toLowerCase();
}

function getDecodedPathTokens(decoded: DecodedPacket): string[] {
  const tracePayload =
    decoded.payloadType === PayloadType.Trace && decoded.payload.decoded
      ? (decoded.payload.decoded as { pathHashes?: string[] })
      : null;
  return tracePayload?.pathHashes || decoded.path || [];
}

export function formatMapPacketHops(pathBytes: string[]): string {
  const count = pathBytes.length;
  if (count === 0) return '';
  return `(${count}->) `;
}

export function formatMapPacketDecodedMessage(message: string | null | undefined): string {
  const trimmed = message?.trim();
  if (!trimmed) return '';
  return `\n   ${trimmed}`;
}

function formatKnownOrToken(
  label: string,
  pubkey: string | null | undefined,
  indexes: MapPacketFeedIndexes
): string {
  if (pubkey) {
    const contact = resolveContactByPrefix(pubkey, indexes.prefixIndex);
    if (contact) {
      const displayName = getContactDisplayName(
        contact.name,
        contact.public_key,
        contact.last_advert
      );
      return `${displayName} (${formatPubkeySnippet(contact.public_key)})`;
    }
    return `${label} (${formatPubkeySnippet(pubkey)})`;
  }
  return label;
}

function formatTokenForDisplay(token: string): string {
  const normalized = token.trim().toLowerCase();
  if (/^[0-9a-f]+$/i.test(normalized) && normalized.length > 6) {
    return normalized.slice(0, 6);
  }
  return normalized;
}

function formatTokenOrContact(
  token: string | null | undefined,
  indexes: MapPacketFeedIndexes
): string | null {
  if (!token?.trim()) return null;
  const normalized = token.trim();
  const contact = resolveContactByPrefix(normalized, indexes.prefixIndex);
  if (contact) {
    const displayName = getContactDisplayName(
      contact.name,
      contact.public_key,
      contact.last_advert
    );
    return `${displayName} (${formatPubkeySnippet(contact.public_key)})`;
  }
  return formatTokenForDisplay(normalized);
}

function extractDecodedMessage(packet: RawPacket, decoded: DecodedPacket): string | null {
  const backendMessage = packet.decrypted_info?.message?.trim();
  if (backendMessage) return backendMessage;

  if (decoded.payloadType === PayloadType.GroupText && decoded.payload.decoded) {
    const payload = decoded.payload.decoded as {
      decrypted?: { message?: string };
    };
    const message = payload.decrypted?.message?.trim();
    if (message) return message;
  }

  if (decoded.payloadType === PayloadType.TextMessage && decoded.payload.decoded) {
    const payload = decoded.payload.decoded as {
      decrypted?: { message?: string };
    };
    const message = payload.decrypted?.message?.trim();
    if (message) return message;
  }

  return null;
}

export function formatMapPacketGroupTextSuffix(
  packet: RawPacket,
  decoded: DecodedPacket
): string {
  const message = extractDecodedMessage(packet, decoded);
  if (message) {
    return formatMapPacketDecodedMessage(message);
  }

  const payload = decoded.payload.decoded as { channelHash?: string } | null;
  const channelHash = payload?.channelHash?.trim();
  if (channelHash) {
    return ` *encrypted* ch:${channelHash.toUpperCase()}`;
  }
  return ' *encrypted*';
}

export function formatMapPacketSenderFromDecoded(
  packet: RawPacket,
  decoded: DecodedPacket,
  indexes: MapPacketFeedIndexes
): string | null {
  switch (decoded.payloadType) {
    case PayloadType.Advert: {
      const payload = decoded.payload.decoded as {
        publicKey?: string;
        appData?: { name?: string };
      } | null;
      if (payload?.appData?.name) {
        return formatKnownOrToken(payload.appData.name, payload.publicKey, indexes);
      }
      if (payload?.publicKey) {
        return formatTokenOrContact(payload.publicKey, indexes);
      }
      break;
    }
    case PayloadType.TextMessage: {
      const payload = decoded.payload.decoded as { sourceHash?: string } | null;
      return formatTokenOrContact(payload?.sourceHash, indexes);
    }
    case PayloadType.GroupText: {
      if (packet.decrypted_info?.sender) {
        const contact = indexes.nameIndex.get(packet.decrypted_info.sender);
        if (contact) {
          return formatKnownOrToken(
            getContactDisplayName(contact.name, contact.public_key, contact.last_advert),
            contact.public_key,
            indexes
          );
        }
        return packet.decrypted_info.sender;
      }
      const payload = decoded.payload.decoded as {
        decrypted?: { sender?: string };
        channelHash?: string;
      } | null;
      const sender = payload?.decrypted?.sender;
      if (sender) {
        const contact = indexes.nameIndex.get(sender);
        if (contact) {
          return formatKnownOrToken(
            getContactDisplayName(contact.name, contact.public_key, contact.last_advert),
            contact.public_key,
            indexes
          );
        }
        return sender;
      }
      const pathTokens = getDecodedPathTokens(decoded);
      if (pathTokens.length > 0) {
        return formatTokenForDisplay(pathTokens[0]);
      }
      break;
    }
    case PayloadType.Request:
    case PayloadType.Response: {
      const payload = decoded.payload.decoded as { sourceHash?: string } | null;
      return formatTokenOrContact(payload?.sourceHash, indexes);
    }
    case PayloadType.AnonRequest: {
      const payload = decoded.payload.decoded as { senderPublicKey?: string } | null;
      return formatTokenOrContact(payload?.senderPublicKey, indexes);
    }
    case PayloadType.Control: {
      const payload = decoded.payload.decoded as { publicKey?: string } | null;
      return formatTokenOrContact(payload?.publicKey, indexes);
    }
    default: {
      if (packet.decrypted_info?.sender) {
        return formatTokenOrContact(packet.decrypted_info.sender, indexes);
      }
      if (packet.decrypted_info?.contact_key) {
        return formatTokenOrContact(packet.decrypted_info.contact_key, indexes);
      }
      break;
    }
  }

  return null;
}

function payloadTypeLabel(packet: RawPacket, decoded: DecodedPacket | null): string {
  if (decoded?.isValid) {
    return PACKET_TYPE_LABELS[getPacketLabel(decoded.payloadType)] ?? 'UNKNOWN';
  }
  const backendType = packet.payload_type?.trim();
  if (backendType) {
    const normalized = backendType.toUpperCase();
    if (normalized === 'PATH') return 'ACK';
    return normalized;
  }
  return 'UNKNOWN';
}

function payloadTypeColor(packet: RawPacket, decoded: DecodedPacket | null): string {
  if (decoded?.isValid) {
    return PARTICLE_COLOR_MAP[getPacketLabel(decoded.payloadType)];
  }
  const normalized = packet.payload_type?.toUpperCase() ?? '';
  if (normalized.includes('ADVERT')) return PARTICLE_COLOR_MAP.AD;
  if (normalized.includes('GROUP') || normalized === 'CHAN') return PARTICLE_COLOR_MAP.GT;
  if (normalized.includes('TEXT') || normalized === 'PRIV') return PARTICLE_COLOR_MAP.DM;
  if (normalized.includes('ACK') || normalized === 'PATH') return PARTICLE_COLOR_MAP.ACK;
  if (normalized.includes('TRACE')) return PARTICLE_COLOR_MAP.TR;
  if (normalized.includes('REQUEST')) return PARTICLE_COLOR_MAP.RQ;
  if (normalized.includes('RESPONSE')) return PARTICLE_COLOR_MAP.RS;
  return PARTICLE_COLOR_MAP['?'];
}

function decodePacket(packet: RawPacket, decoderOptions?: DecryptionOptions): DecodedPacket | null {
  try {
    const decoded = MeshCoreDecoder.decode(packet.data, decoderOptions);
    return decoded.isValid ? decoded : null;
  } catch {
    return null;
  }
}

export function buildMapPacketFeedEntry(
  packet: RawPacket,
  context: MapPacketFeedContext
): MapPacketFeedEntry {
  const decoded = decodePacket(packet, context.decoderOptions);
  const typeLabel = payloadTypeLabel(packet, decoded);
  const typeColor = payloadTypeColor(packet, decoded);
  const hopsPrefix = formatMapPacketHops(decoded ? getDecodedPathTokens(decoded) : []);
  const senderLabel = decoded
    ? formatMapPacketSenderFromDecoded(packet, decoded, context.indexes)
    : packet.decrypted_info?.sender
      ? formatTokenOrContact(packet.decrypted_info.sender, context.indexes)
      : null;
  const messageSuffix =
    decoded?.payloadType === PayloadType.GroupText
      ? formatMapPacketGroupTextSuffix(packet, decoded)
      : formatMapPacketDecodedMessage(
          decoded ? extractDecodedMessage(packet, decoded) : packet.decrypted_info?.message
        );

  return {
    key: getRawPacketObservationKey(packet),
    timestamp: packet.timestamp,
    typeLabel,
    typeColor,
    hopsPrefix,
    senderLabel,
    messageSuffix,
  };
}

export function buildMapPacketFeedEntries(
  packets: RawPacket[],
  context: MapPacketFeedContext,
  limit = MAP_PACKET_FEED_LIMIT
): MapPacketFeedEntry[] {
  const seen = new Set<string>();
  const entries: MapPacketFeedEntry[] = [];

  for (let i = packets.length - 1; i >= 0; i--) {
    const packet = packets[i];
    const key = getRawPacketObservationKey(packet);
    if (seen.has(key)) continue;
    seen.add(key);
    entries.push(buildMapPacketFeedEntry(packet, context));
    if (entries.length >= limit) break;
  }

  return entries;
}

export function isAdvertPacket(
  packet: RawPacket,
  decoderOptions?: DecryptionOptions
): boolean {
  const decoded = decodePacket(packet, decoderOptions);
  if (decoded) return decoded.payloadType === PayloadType.Advert;
  return packet.payload_type?.toUpperCase().includes('ADVERT') ?? false;
}

// Backwards-compatible helper for tests that only need sender formatting hooks.
export function formatMapPacketSender(
  _parsed: null,
  packet: RawPacket,
  indexes: MapPacketFeedIndexes,
  decoderOptions?: DecryptionOptions
): string | null {
  const decoded = decodePacket(packet, decoderOptions);
  if (!decoded) {
    return packet.decrypted_info?.sender
      ? formatTokenOrContact(packet.decrypted_info.sender, indexes)
      : null;
  }
  return formatMapPacketSenderFromDecoded(packet, decoded, indexes);
}
