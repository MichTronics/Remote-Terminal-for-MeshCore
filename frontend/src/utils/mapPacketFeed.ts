import {
  ChannelCrypto,
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
  '?':'UNKNOWN',
};

export interface MapPacketFeedEntry {
  key: string;
  timestamp: number;
  typeLabel: string;
  typeColor: string;
  hopsPrefix: string;
  senderLabel: string | null;
  channelTargetLabel: string | null;
  messageBody: string | null;
  inlineSuffix: string;
}

export interface MapPacketFeedIndexes {
  prefixIndex: Map<string, Contact[]>;
  nameIndex: Map<string, Contact>;
}

export interface MapPacketFeedContext {
  indexes: MapPacketFeedIndexes;
  channels: Channel[];
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
    channels: channels ?? [],
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
  return pubkey.slice(0, 4).toUpperCase();
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
  return `(${count}⇢) `;
}

export function formatMapPacketFeedMessageBody(message: string | null | undefined): string {
  const trimmed = message?.trim();
  if (!trimmed) return '';
  return trimmed;
}

/** @deprecated Use formatMapPacketFeedMessageBody for feed body lines. */
export function formatMapPacketDecodedMessage(message: string | null | undefined): string {
  const body = formatMapPacketFeedMessageBody(message);
  return body ? `: ${body}` : '';
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

function formatBackendSenderLabel(
  sender: string | null | undefined,
  indexes: MapPacketFeedIndexes
): string | null {
  if (!sender?.trim()) return null;
  const trimmed = sender.trim();
  const contact = indexes.nameIndex.get(trimmed);
  if (contact) {
    return getContactDisplayName(contact.name, contact.public_key, contact.last_advert);
  }
  if (/^[0-9a-f]+$/i.test(trimmed)) {
    return formatTokenOrContact(trimmed, indexes);
  }
  return trimmed;
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

function resolveChannelNameByKey(
  channelKey: string | null | undefined,
  channels: Channel[]
): string | null {
  if (!channelKey?.trim()) return null;
  const normalized = channelKey.trim().toLowerCase();
  return channels.find((channel) => channel.key.toLowerCase() === normalized)?.name ?? null;
}

function resolveGroupTextChannelTarget(
  packet: RawPacket,
  decoded: DecodedPacket,
  channels: Channel[]
): string | null {
  const backendName = packet.decrypted_info?.channel_name?.trim();
  if (backendName) return backendName;

  const backendKeyName = resolveChannelNameByKey(packet.decrypted_info?.channel_key, channels);
  if (backendKeyName) return backendKeyName;

  const payload = decoded.payload.decoded as {
    channelHash?: string;
    cipherMac?: string;
    ciphertext?: string;
    decrypted?: { message?: string };
  } | null;
  if (!payload?.channelHash) return null;

  const hashMatches = channels.filter(
    (channel) =>
      ChannelCrypto.calculateChannelHash(channel.key).toUpperCase() ===
      payload.channelHash?.toUpperCase()
  );
  if (hashMatches.length === 1) return hashMatches[0].name;
  if (
    hashMatches.length <= 1 ||
    !payload.cipherMac ||
    !payload.ciphertext ||
    !payload.decrypted?.message
  ) {
    return null;
  }

  const decryptMatches = hashMatches.filter(
    (channel) =>
      ChannelCrypto.decryptGroupTextMessage(payload.ciphertext!, payload.cipherMac!, channel.key)
        .success
  );
  return decryptMatches.length === 1 ? decryptMatches[0].name : null;
}

export function formatMapPacketGroupTextInlineSuffix(decoded: DecodedPacket): string {
  const payload = decoded.payload.decoded as { channelHash?: string } | null;
  const channelHash = payload?.channelHash?.trim();
  if (channelHash) {
    return ` *encrypted* ch:${channelHash.toUpperCase()}`;
  }
  return ' *encrypted*';
}

/** @deprecated Use formatMapPacketGroupTextInlineSuffix for encrypted channel headers. */
export function formatMapPacketGroupTextSuffix(
  packet: RawPacket,
  decoded: DecodedPacket
): string {
  const message = extractDecodedMessage(packet, decoded);
  if (message) {
    return formatMapPacketDecodedMessage(message);
  }
  return formatMapPacketGroupTextInlineSuffix(decoded);
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
          return getContactDisplayName(
            contact.name,
            contact.public_key,
            contact.last_advert
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
          return getContactDisplayName(
            contact.name,
            contact.public_key,
            contact.last_advert
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
    if (normalized === 'PATH') return ('ACK');
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
  const typeLabel = payloadTypeLabel(packet, decoded).padEnd(9, ' ');
  const typeColor = payloadTypeColor(packet, decoded);
  const hopsPrefix = formatMapPacketHops(decoded ? getDecodedPathTokens(decoded) : []);
  const senderLabel = decoded
    ? formatMapPacketSenderFromDecoded(packet, decoded, context.indexes)
    : formatBackendSenderLabel(packet.decrypted_info?.sender, context.indexes);
  let channelTargetLabel: string | null = null;
  let messageBody: string | null = null;
  let inlineSuffix = '';

  const decodedMessage = decoded
    ? extractDecodedMessage(packet, decoded)
    : packet.decrypted_info?.message?.trim() || null;

  if (decoded?.payloadType === PayloadType.GroupText) {
    if (decodedMessage) {
      channelTargetLabel = resolveGroupTextChannelTarget(packet, decoded, context.channels);
      messageBody = formatMapPacketFeedMessageBody(decodedMessage);
    } else {
      inlineSuffix = formatMapPacketGroupTextInlineSuffix(decoded);
    }
  } else if (
    decoded?.payloadType === PayloadType.TextMessage ||
    packet.payload_type?.toUpperCase() === 'PRIV'
  ) {
    if (decodedMessage) {
      messageBody = formatMapPacketFeedMessageBody(decodedMessage);
    }
  } else if (decodedMessage) {
    const normalizedType = packet.payload_type?.toUpperCase() ?? '';
    if (normalizedType.includes('GROUP') || normalizedType === 'CHAN') {
      channelTargetLabel =
        packet.decrypted_info?.channel_name?.trim() ??
        resolveChannelNameByKey(packet.decrypted_info?.channel_key, context.channels);
      messageBody = formatMapPacketFeedMessageBody(decodedMessage);
    } else if (normalizedType.includes('TEXT') || normalizedType === 'PRIV') {
      messageBody = formatMapPacketFeedMessageBody(decodedMessage);
    }
  }

  return {
    key: getRawPacketObservationKey(packet),
    timestamp: packet.timestamp,
    typeLabel,
    typeColor,
    hopsPrefix,
    senderLabel,
    channelTargetLabel,
    messageBody,
    inlineSuffix,
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
