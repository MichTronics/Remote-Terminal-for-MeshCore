import { PayloadType } from '@michaelhart/meshcore-decoder';
import type { Contact, RawPacket } from '../types';
import { getContactDisplayName } from './pubkey';
import {
  getPacketLabel,
  parsePacket,
  PARTICLE_COLOR_MAP,
  type ParsedPacket,
} from './visualizerUtils';
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
  senderLabel: string;
  messageSuffix: string;
}

export interface MapPacketFeedIndexes {
  prefixIndex: Map<string, Contact[]>;
  nameIndex: Map<string, Contact>;
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

export function formatMapPacketSender(
  parsed: ParsedPacket | null,
  packet: RawPacket,
  indexes: MapPacketFeedIndexes
): string {
  const { prefixIndex, nameIndex } = indexes;

  let contact: Contact | null = null;
  let fallbackHex: string | null = null;

  if (parsed?.advertPubkey) {
    fallbackHex = parsed.advertPubkey;
    contact = resolveContactByPrefix(parsed.advertPubkey.slice(0, 12), prefixIndex);
  } else if (parsed?.groupTextSender) {
    contact = nameIndex.get(parsed.groupTextSender) ?? null;
    if (!contact) {
      return parsed.groupTextSender;
    }
  } else if (parsed?.srcHash) {
    fallbackHex = parsed.srcHash;
    contact = resolveContactByPrefix(parsed.srcHash, prefixIndex);
  } else if (parsed?.anonRequestPubkey) {
    fallbackHex = parsed.anonRequestPubkey;
    contact = resolveContactByPrefix(parsed.anonRequestPubkey.slice(0, 12), prefixIndex);
  } else if (packet.decrypted_info?.contact_key) {
    fallbackHex = packet.decrypted_info.contact_key;
    contact = resolveContactByPrefix(packet.decrypted_info.contact_key.slice(0, 12), prefixIndex);
  } else if (packet.decrypted_info?.sender) {
    contact = nameIndex.get(packet.decrypted_info.sender) ?? null;
    if (!contact) {
      return packet.decrypted_info.sender;
    }
  }

  if (contact) {
    const displayName = getContactDisplayName(
      contact.name,
      contact.public_key,
      contact.last_advert
    );
    const pubkeySource = contact.public_key || fallbackHex;
    if (pubkeySource) {
      return `${displayName} (${formatPubkeySnippet(pubkeySource)})`;
    }
    return displayName;
  }

  if (fallbackHex) {
    return formatPubkeySnippet(fallbackHex);
  }

  if (packet.decrypted_info?.sender) {
    return packet.decrypted_info.sender;
  }

  return 'unknown';
}

export function formatMapPacketHops(pathBytes: string[]): string {
  const count = pathBytes.length;
  if (count === 0) return '';
  return `(${count}->) `;
}

export function formatMapPacketDecodedMessage(message: string | null | undefined): string {
  const trimmed = message?.trim();
  if (!trimmed) return '';
  if (trimmed.length <= 30) return `: ${trimmed}`;
  return `: ${trimmed.slice(0, 28)}...`;
}

function payloadTypeLabel(packet: RawPacket, parsed: ParsedPacket | null): string {
  if (parsed) {
    return PACKET_TYPE_LABELS[getPacketLabel(parsed.payloadType)] ?? 'UNKNOWN';
  }
  const backendType = packet.payload_type?.trim();
  if (backendType) {
    return backendType.toUpperCase();
  }
  return 'UNKNOWN';
}

function payloadTypeColor(packet: RawPacket, parsed: ParsedPacket | null): string {
  if (parsed) {
    return PARTICLE_COLOR_MAP[getPacketLabel(parsed.payloadType)];
  }
  const normalized = packet.payload_type?.toUpperCase() ?? '';
  if (normalized.includes('ADVERT')) return PARTICLE_COLOR_MAP.AD;
  if (normalized.includes('GROUP') || normalized === 'CHAN') return PARTICLE_COLOR_MAP.GT;
  if (normalized.includes('TEXT') || normalized === 'PRIV') return PARTICLE_COLOR_MAP.DM;
  if (normalized.includes('ACK')) return PARTICLE_COLOR_MAP.ACK;
  if (normalized.includes('TRACE')) return PARTICLE_COLOR_MAP.TR;
  if (normalized.includes('REQUEST')) return PARTICLE_COLOR_MAP.RQ;
  if (normalized.includes('RESPONSE')) return PARTICLE_COLOR_MAP.RS;
  return PARTICLE_COLOR_MAP['?'];
}

export function buildMapPacketFeedEntry(
  packet: RawPacket,
  indexes: MapPacketFeedIndexes
): MapPacketFeedEntry {
  const parsed = parsePacket(packet.data);
  const typeLabel = payloadTypeLabel(packet, parsed);
  const typeColor = payloadTypeColor(packet, parsed);
  const hopsPrefix = formatMapPacketHops(parsed?.pathBytes ?? []);
  const senderLabel = formatMapPacketSender(parsed, packet, indexes);
  const messageSuffix = formatMapPacketDecodedMessage(packet.decrypted_info?.message);

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
  indexes: MapPacketFeedIndexes,
  limit = MAP_PACKET_FEED_LIMIT
): MapPacketFeedEntry[] {
  const seen = new Set<string>();
  const entries: MapPacketFeedEntry[] = [];

  for (let i = packets.length - 1; i >= 0; i--) {
    const packet = packets[i];
    const key = getRawPacketObservationKey(packet);
    if (seen.has(key)) continue;
    seen.add(key);
    entries.push(buildMapPacketFeedEntry(packet, indexes));
    if (entries.length >= limit) break;
  }

  return entries;
}

export function isAdvertPacket(packet: RawPacket): boolean {
  const parsed = parsePacket(packet.data);
  if (parsed) return parsed.payloadType === PayloadType.Advert;
  return packet.payload_type?.toUpperCase().includes('ADVERT') ?? false;
}
