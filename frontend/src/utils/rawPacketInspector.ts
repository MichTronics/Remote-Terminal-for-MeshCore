import {
  MeshCoreDecoder,
  PayloadType,
  Utils,
  type DecodedPacket,
  type DecryptionOptions,
  type HeaderBreakdown,
  type PacketStructure,
} from '@michaelhart/meshcore-decoder';

import type { Channel, RawPacket } from '../types';

export interface RawPacketSummary {
  summary: string;
  routeType: string;
  details?: string;
}

export interface PacketByteField {
  id: string;
  scope: 'packet' | 'payload';
  name: string;
  description: string;
  value: string;
  decryptedMessage?: string;
  startByte: number;
  endByte: number;
  absoluteStartByte: number;
  absoluteEndByte: number;
  headerBreakdown?: HeaderBreakdown;
}

export interface RawPacketInspection {
  decoded: DecodedPacket | null;
  structure: PacketStructure | null;
  routeTypeName: string;
  payloadTypeName: string;
  payloadVersionName: string;
  pathTokens: string[];
  summary: RawPacketSummary;
  validationErrors: string[];
  packetFields: PacketByteField[];
  payloadFields: PacketByteField[];
}

export function formatHexByHop(hex: string, hashSize: number | null | undefined): string {
  const normalized = hex.trim().toUpperCase();
  if (!normalized || !hashSize || hashSize < 1) {
    return normalized;
  }

  const charsPerHop = hashSize * 2;
  if (normalized.length <= charsPerHop || normalized.length % charsPerHop !== 0) {
    return normalized;
  }

  const hops = normalized.match(new RegExp(`.{1,${charsPerHop}}`, 'g'));
  return hops && hops.length > 1 ? hops.join(' → ') : normalized;
}

export function describeCiphertextStructure(
  payloadType: PayloadType,
  byteLength: number,
  fallbackDescription: string
): string {
  switch (payloadType) {
    case PayloadType.GroupText:
      return `Encrypted message content (${byteLength} bytes). Contains encrypted plaintext with this structure:
• Timestamp (4 bytes) - send time as unix timestamp
• Flags (1 byte) - channel-message flags byte
• Message (remaining bytes) - UTF-8 channel message text`;
    case PayloadType.TextMessage:
      return `Encrypted message data (${byteLength} bytes). Contains encrypted plaintext with this structure:
• Timestamp (4 bytes) - send time as unix timestamp
• Message (remaining bytes) - UTF-8 direct message text`;
    case PayloadType.Response:
      return `Encrypted response data (${byteLength} bytes). Contains encrypted plaintext with this structure:
• Tag (4 bytes) - request/response correlation tag
• Content (remaining bytes) - response body`;
    default:
      return fallbackDescription;
  }
}

function getPathTokens(decoded: DecodedPacket): string[] {
  const tracePayload =
    decoded.payloadType === PayloadType.Trace && decoded.payload.decoded
      ? (decoded.payload.decoded as { pathHashes?: string[] })
      : null;
  return tracePayload?.pathHashes || decoded.path || [];
}

function formatUnixTimestamp(timestamp: number): string {
  return `${timestamp} (${new Date(timestamp * 1000).toLocaleString()})`;
}

function createPacketField(
  scope: 'packet' | 'payload',
  id: string,
  field: {
    name: string;
    description: string;
    value: string;
    decryptedMessage?: string;
    startByte: number;
    endByte: number;
    headerBreakdown?: HeaderBreakdown;
  },
  absoluteOffset: number
): PacketByteField {
  return {
    id,
    scope,
    name: field.name,
    description: field.description,
    value: field.value,
    decryptedMessage: field.decryptedMessage,
    startByte: field.startByte,
    endByte: field.endByte,
    absoluteStartByte: absoluteOffset + field.startByte,
    absoluteEndByte: absoluteOffset + field.endByte,
    headerBreakdown: field.headerBreakdown,
  };
}

export function createDecoderOptions(
  channels: Channel[] | null | undefined
): DecryptionOptions | undefined {
  const channelSecrets =
    channels
      ?.map((channel) => channel.key?.trim())
      .filter((key): key is string => Boolean(key && key.length > 0)) ?? [];

  if (channelSecrets.length === 0) {
    return undefined;
  }

  return {
    keyStore: MeshCoreDecoder.createKeyStore({ channelSecrets }),
    attemptDecryption: true,
  };
}

function safeValidate(hexData: string): string[] {
  try {
    const validation = MeshCoreDecoder.validate(hexData);
    return validation.errors ?? [];
  } catch (error) {
    return [error instanceof Error ? error.message : 'Packet validation failed'];
  }
}

function generateLocationPayloadFields(
  payloadHex: string,
  payloadStartByte: number
): PacketByteField[] {
  // LOCATION packet structure (all multi-byte values are big-endian):
  // 0-3: Magic ("MCL1")
  // 4: Version
  // 5: Flags
  // 6-9: Node ID (4 bytes)
  // 10-13: Latitude (int32 BE, microdegrees)
  // 14-17: Longitude (int32 BE, microdegrees)
  // 18-19: Altitude (int16 BE, metres)
  // 20-21: Speed (uint16 BE, cm/s)
  // 22-23: Heading (uint16 BE, centidegrees)
  // 24: Satellites
  // 25-26: Battery (uint16 BE, millivolts)
  // 27-30: Timestamp (uint32 BE, Unix time)
  // 31: Name length
  // 32+: Name (UTF-8, up to 24 bytes)

  const bytes = payloadHex.match(/.{2}/g) ?? [];
  if (bytes.length < 32) {
    return [];
  }

  const fields: PacketByteField[] = [];

  // Helper to parse big-endian integers
  const parseBE = (start: number, len: number, signed: boolean): number => {
    const hexValue = bytes.slice(start, start + len).join('');
    let value = parseInt(hexValue, 16);
    if (signed && len > 0) {
      const max = Math.pow(2, len * 8);
      if (value >= max / 2) {
        value -= max;
      }
    }
    return value;
  };

  const magic = bytes.slice(0, 4).map((b) => String.fromCharCode(parseInt(b, 16))).join('');
  const version = parseInt(bytes[4], 16);
  const flags = parseInt(bytes[5], 16);
  const nodeId = bytes.slice(6, 10).join('');
  const latMicro = parseBE(10, 4, true);
  const lonMicro = parseBE(14, 4, true);
  const lat = latMicro / 1_000_000;
  const lon = lonMicro / 1_000_000;
  const altitude = parseBE(18, 2, true);
  const speedCm = parseBE(20, 2, false);
  const speed = speedCm / 100;
  const headingCenti = parseBE(22, 2, false);
  const heading = headingCenti / 100;
  const satellites = parseInt(bytes[24], 16);
  const battery = parseBE(25, 2, false);
  const timestamp = parseBE(27, 4, false);
  const nameLen = parseInt(bytes[31], 16);

  const createField = (
    name: string,
    start: number,
    end: number,
    value: string,
    description: string
  ): PacketByteField => ({
    id: `location-${name.toLowerCase().replace(/\s+/g, '-')}`,
    scope: 'payload',
    name,
    description,
    value,
    startByte: start,
    endByte: end,
    absoluteStartByte: payloadStartByte + start,
    absoluteEndByte: payloadStartByte + end,
  });

  fields.push(createField('Magic', 0, 3, bytes.slice(0, 4).join(' '), `Magic bytes: "${magic}"`));
  fields.push(createField('Version', 4, 4, bytes[4], `Protocol version: ${version}`));
  fields.push(createField('Flags', 5, 5, bytes[5], `Reserved flags: 0x${bytes[5]}`));
  fields.push(
    createField('Node ID', 6, 9, bytes.slice(6, 10).join(' '), `First 4 bytes of public key: ${nodeId}`)
  );
  fields.push(
    createField(
      'Latitude',
      10,
      13,
      bytes.slice(10, 14).join(' '),
      `Latitude: ${lat.toFixed(6)}° (${latMicro} microdegrees, big-endian)`
    )
  );
  fields.push(
    createField(
      'Longitude',
      14,
      17,
      bytes.slice(14, 18).join(' '),
      `Longitude: ${lon.toFixed(6)}° (${lonMicro} microdegrees, big-endian)`
    )
  );
  fields.push(
    createField('Altitude', 18, 19, bytes.slice(18, 20).join(' '), `Altitude: ${altitude}m (big-endian)`)
  );
  fields.push(
    createField(
      'Speed',
      20,
      21,
      bytes.slice(20, 22).join(' '),
      `Speed: ${speed.toFixed(1)}m/s (${speedCm}cm/s, big-endian)`
    )
  );
  fields.push(
    createField(
      'Heading',
      22,
      23,
      bytes.slice(22, 24).join(' '),
      `Heading: ${heading.toFixed(1)}° (${headingCenti} centidegrees, big-endian)`
    )
  );
  fields.push(createField('Satellites', 24, 24, bytes[24], `GPS satellites: ${satellites}`));
  fields.push(
    createField('Battery', 25, 26, bytes.slice(25, 27).join(' '), `Battery: ${battery}mV (big-endian)`)
  );
  fields.push(
    createField(
      'Timestamp',
      27,
      30,
      bytes.slice(27, 31).join(' '),
      `Sent: ${formatUnixTimestamp(timestamp)} (big-endian)`
    )
  );
  fields.push(createField('Name Length', 31, 31, bytes[31], `Name field length: ${nameLen} bytes`));

  if (nameLen > 0 && bytes.length >= 32 + nameLen) {
    const nameBytes = bytes.slice(32, 32 + nameLen);
    const name = nameBytes.map((b) => String.fromCharCode(parseInt(b, 16))).join('');
    fields.push(
      createField('Name', 32, 31 + nameLen, nameBytes.join(' '), `Tracker name: ${name}`)
    );
  }

  return fields;
}

export function decodePacketSummary(
  packet: RawPacket,
  decoderOptions?: DecryptionOptions
): RawPacketSummary {
  try {
    const decoded = MeshCoreDecoder.decode(packet.data, decoderOptions);

    if (!decoded.isValid) {
      return { summary: 'Invalid packet', routeType: 'Unknown' };
    }

    const routeType = Utils.getRouteTypeName(decoded.routeType);
    const payloadTypeName = Utils.getPayloadTypeName(decoded.payloadType);
    const pathTokens = getPathTokens(decoded);
    const pathStr = pathTokens.length > 0 ? ` via ${pathTokens.join(', ')}` : '';

    let summary = payloadTypeName;
    let details: string | undefined;

    switch (decoded.payloadType) {
      case PayloadType.TextMessage: {
        const payload = decoded.payload.decoded as {
          destinationHash?: string;
          sourceHash?: string;
        } | null;
        if (payload?.sourceHash && payload?.destinationHash) {
          summary = `DM from ${payload.sourceHash} to ${payload.destinationHash}${pathStr}`;
        } else {
          summary = `DM${pathStr}`;
        }
        break;
      }
      case PayloadType.GroupText: {
        const payload = decoded.payload.decoded as {
          channelHash?: string;
          decrypted?: { sender?: string; message?: string };
        } | null;
        if (packet.decrypted_info?.channel_name) {
          if (packet.decrypted_info.sender) {
            summary = `GT from ${packet.decrypted_info.sender} in ${packet.decrypted_info.channel_name}${pathStr}`;
          } else {
            summary = `GT in ${packet.decrypted_info.channel_name}${pathStr}`;
          }
        } else if (payload?.decrypted?.sender) {
          summary = `GT from ${payload.decrypted.sender}${pathStr}`;
        } else if (payload?.decrypted?.message) {
          summary = `GT decrypted${pathStr}`;
        } else if (payload?.channelHash) {
          summary = `GT ch:${payload.channelHash}${pathStr}`;
        } else {
          summary = `GroupText${pathStr}`;
        }
        break;
      }
      case PayloadType.Advert: {
        const payload = decoded.payload.decoded as {
          publicKey?: string;
          appData?: { name?: string; deviceRole?: number };
        } | null;
        if (payload?.appData?.name) {
          const role =
            payload.appData.deviceRole !== undefined
              ? Utils.getDeviceRoleName(payload.appData.deviceRole)
              : '';
          summary = `Advert: ${payload.appData.name}${role ? ` (${role})` : ''}${pathStr}`;
        } else if (payload?.publicKey) {
          summary = `Advert: ${payload.publicKey.slice(0, 8)}...${pathStr}`;
        } else {
          summary = `Advert${pathStr}`;
        }
        break;
      }
      case PayloadType.Ack:
        summary = `ACK${pathStr}`;
        break;
      case PayloadType.Request: {
        const reqPayload = decoded.payload.decoded as {
          sourceHash?: string;
          destinationHash?: string;
        } | null;
        if (reqPayload?.sourceHash) {
          summary = `Request from ${reqPayload.sourceHash}${pathStr}`;
        } else {
          summary = `Request${pathStr}`;
        }
        break;
      }
      case PayloadType.Response: {
        const respPayload = decoded.payload.decoded as {
          sourceHash?: string;
          destinationHash?: string;
        } | null;
        if (respPayload?.sourceHash) {
          summary = `Response from ${respPayload.sourceHash}${pathStr}`;
        } else {
          summary = `Response${pathStr}`;
        }
        break;
      }
      case PayloadType.AnonRequest: {
        const anonPayload = decoded.payload.decoded as {
          senderPublicKey?: string;
          destinationHash?: string;
        } | null;
        if (anonPayload?.senderPublicKey) {
          summary = `AnonRequest from ${anonPayload.senderPublicKey.slice(0, 8)}...${pathStr}`;
        } else {
          summary = `AnonRequest${pathStr}`;
        }
        break;
      }
      case PayloadType.Trace:
        summary = `Trace${pathStr}`;
        break;
      case PayloadType.Path:
        summary = `Path${pathStr}`;
        break;
      case PayloadType.Control: {
        const ctrlPayload = decoded.payload.decoded as {
          subType?: number;
          publicKey?: string;
        } | null;
        if (ctrlPayload?.publicKey) {
          const subTypeName = Utils.getControlSubTypeName
            ? Utils.getControlSubTypeName(ctrlPayload.subType ?? 0)
            : 'Control';
          summary = `${subTypeName} from ${ctrlPayload.publicKey.slice(0, 8)}...${pathStr}`;
        } else {
          summary = `Control${pathStr}`;
        }
        break;
      }
      default:
        // Handle unknown types that may be defined server-side (e.g., LOCATION = 0x0D)
        // Use backend payload_type name if available, or fall back to library name
        const backendPayloadType = packet.payload_type;
        if (backendPayloadType === 'LOCATION' && packet.decrypted_info?.sender) {
          summary = `Location from ${packet.decrypted_info.sender}${pathStr}`;
        } else if (backendPayloadType === 'ATLAS') {
          summary = `Atlas${pathStr}`;
        } else {
          summary = `${payloadTypeName}${pathStr}`;
        }
        break;
    }

    return { summary, routeType, details };
  } catch {
    return { summary: 'Decode error', routeType: 'Unknown' };
  }
}

export function inspectRawPacket(packet: RawPacket): RawPacketInspection {
  return inspectRawPacketWithOptions(packet);
}

export function inspectRawPacketWithOptions(
  packet: RawPacket,
  decoderOptions?: DecryptionOptions
): RawPacketInspection {
  const summary = decodePacketSummary(packet, decoderOptions);
  const validationErrors = safeValidate(packet.data);

  let decoded: DecodedPacket | null = null;
  let structure: PacketStructure | null = null;

  try {
    decoded = MeshCoreDecoder.decode(packet.data, decoderOptions);
  } catch {
    decoded = null;
  }

  try {
    structure = MeshCoreDecoder.analyzeStructure(packet.data, decoderOptions);
  } catch {
    structure = null;
  }

  const routeTypeName = decoded?.isValid
    ? Utils.getRouteTypeName(decoded.routeType)
    : summary.routeType;
  const payloadTypeName = decoded?.isValid
    ? Utils.getPayloadTypeName(decoded.payloadType)
    : packet.payload_type;
  const payloadVersionName = decoded?.isValid
    ? Utils.getPayloadVersionName(decoded.payloadVersion)
    : 'Unknown';
  const pathTokens = decoded?.isValid ? getPathTokens(decoded) : [];

  const packetFields =
    structure?.segments
      .map((segment, index) => createPacketField('packet', `packet-${index}`, segment, 0))
      .map((field) => {
        if (field.name !== 'Path Data') {
          return field;
        }
        const hashSize =
          decoded?.pathHashSize ??
          (decoded?.pathLength && decoded.pathLength > 0
            ? Math.max(1, field.value.length / 2 / decoded.pathLength)
            : null);
        return {
          ...field,
          value: formatHexByHop(field.value, hashSize),
        };
      }) ?? [];

  const payloadFields =
    structure == null
      ? []
      : packet.payload_type === 'LOCATION' && structure.payload.hex.length >= 64
        ? // Generate custom fields for LOCATION tracker packets
          generateLocationPayloadFields(structure.payload.hex, structure.payload.startByte)
        : (structure.payload.segments.length > 0
              ? structure.payload.segments
              : structure.payload.hex.length > 0
                ? [
                    {
                      name: 'Payload Bytes',
                      description:
                        'Field-level payload breakdown is not available for this packet type.',
                      startByte: 0,
                      endByte: Math.max(0, structure.payload.hex.length / 2 - 1),
                      value: structure.payload.hex,
                    },
                  ]
                : []
          ).map((segment, index) =>
            createPacketField('payload', `payload-${index}`, segment, structure.payload.startByte)
          );

  const enrichedPayloadFields = payloadFields.map((field) => {
    if (!decoded?.isValid || field.name !== 'Ciphertext') {
      return field;
    }

    const withStructure = {
      ...field,
      description: describeCiphertextStructure(
        decoded.payloadType,
        field.endByte - field.startByte + 1,
        field.description
      ),
    };

    // GroupText: client-side decoder has the decrypted content
    if (decoded.payloadType === PayloadType.GroupText && decoded.payload.decoded) {
      const payload = decoded.payload.decoded as {
        decrypted?: { timestamp?: number; flags?: number; sender?: string; message?: string };
      };
      if (!payload.decrypted?.message) {
        return withStructure;
      }
      const detailLines = [
        payload.decrypted.timestamp != null
          ? `Sent (packet): ${formatUnixTimestamp(payload.decrypted.timestamp)}`
          : null,
        payload.decrypted.flags != null
          ? `Flags: 0x${payload.decrypted.flags.toString(16).padStart(2, '0')}`
          : null,
        payload.decrypted.sender ? `Sender: ${payload.decrypted.sender}` : null,
        `Message: ${payload.decrypted.message}`,
      ].filter((line): line is string => line !== null);
      return { ...withStructure, decryptedMessage: detailLines.join('\n') };
    }

    // TextMessage (DM): server-side decryption via decrypted_info
    if (decoded.payloadType === PayloadType.TextMessage && packet.decrypted_info?.message) {
      const info = packet.decrypted_info;
      const detailLines = [
        info.sender_timestamp != null
          ? `Sent (packet): ${formatUnixTimestamp(info.sender_timestamp)}`
          : null,
        info.sender ? `Sender: ${info.sender}` : null,
        `Message: ${info.message}`,
      ].filter((line): line is string => line !== null);
      return { ...withStructure, decryptedMessage: detailLines.join('\n') };
    }

    // LOCATION tracker packets (0x0D): server-side parsing via decrypted_info
    // Backend decodes LOCATION payload and provides formatted message
    if (packet.payload_type === 'LOCATION' && packet.decrypted_info?.message) {
      const info = packet.decrypted_info;
      const detailLines = [
        info.sender_timestamp != null
          ? `Sent (packet): ${formatUnixTimestamp(info.sender_timestamp)}`
          : null,
        info.sender ? `Tracker: ${info.sender}` : null,
        `Location: ${info.message}`,
      ].filter((line): line is string => line !== null);
      return { ...withStructure, decryptedMessage: detailLines.join('\n') };
    }

    return withStructure;
  });

  return {
    decoded,
    structure,
    routeTypeName,
    payloadTypeName,
    payloadVersionName,
    pathTokens,
    summary,
    validationErrors:
      validationErrors.length > 0
        ? validationErrors
        : (decoded?.errors ?? (decoded || structure ? [] : ['Unable to decode packet'])),
    packetFields,
    payloadFields: enrichedPayloadFields,
  };
}
