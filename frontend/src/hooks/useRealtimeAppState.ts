import {
  useCallback,
  useMemo,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from 'react';
import { api } from '../api';
import type { UseWebSocketOptions } from '../useWebSocket';
import { toast } from '../components/ui/sonner';
import { getStateKey } from '../utils/conversationState';
import { mergeContactIntoList } from '../utils/contactMerge';
import { getContactDisplayName } from '../utils/pubkey';
import { appendRawPacketUnique } from '../utils/rawPacketIdentity';
import { emitStatusDotPulse } from '../utils/statusDotPulse';
import type {
  Channel,
  Contact,
  Conversation,
  HealthStatus,
  Message,
  MessagePath,
  RawPacket,
  SpamLiveStatus,
} from '../types';
import type { LocationPayload } from '../wsEvents';

interface UseRealtimeAppStateArgs {
  prevHealthRef: MutableRefObject<HealthStatus | null>;
  setHealth: Dispatch<SetStateAction<HealthStatus | null>>;
  fetchConfig: () => void | Promise<void>;
  setRawPackets: Dispatch<SetStateAction<RawPacket[]>>;
  reconcileOnReconnect: () => void;
  refreshUnreads: () => Promise<void>;
  setChannels: Dispatch<SetStateAction<Channel[]>>;
  fetchAllContacts: () => Promise<Contact[]>;
  setContacts: Dispatch<SetStateAction<Contact[]>>;
  blockedKeysRef: MutableRefObject<string[]>;
  blockedNamesRef: MutableRefObject<string[]>;
  channelsRef: MutableRefObject<Channel[]>;
  activeConversationRef: MutableRefObject<Conversation | null>;
  observeMessage: (msg: Message) => { added: boolean; activeConversation: boolean };
  recordMessageEvent: (args: {
    msg: Message;
    activeConversation: boolean;
    isNewMessage: boolean;
    hasMention?: boolean;
  }) => void;
  renameConversationState: (oldStateKey: string, newStateKey: string) => void;
  removeConversationState: (stateKey: string) => void;
  checkMention: (text: string) => boolean;
  pendingDeleteFallbackRef: MutableRefObject<boolean>;
  setActiveConversation: (conv: Conversation | null) => void;
  renameConversationMessages: (oldId: string, newId: string) => void;
  removeConversationMessages: (conversationId: string) => void;
  receiveMessageAck: (
    messageId: number,
    ackCount: number,
    paths?: MessagePath[],
    packetId?: number | null
  ) => void;
  notifyIncomingMessage?: (msg: Message) => void;
  recordRawPacketObservation?: (packet: RawPacket) => void;
  maxRawPackets?: number;
  setSpamLiveStatus?: Dispatch<SetStateAction<SpamLiveStatus | null>>;
}

function isMessageBlocked(msg: Message, blockedKeys: string[], blockedNames: string[]): boolean {
  if (msg.outgoing) {
    return false;
  }

  if (blockedKeys.length > 0) {
    if (msg.type === 'PRIV' && blockedKeys.includes(msg.conversation_key.toLowerCase())) {
      return true;
    }
    if (
      msg.type === 'CHAN' &&
      msg.sender_key &&
      blockedKeys.includes(msg.sender_key.toLowerCase())
    ) {
      return true;
    }
  }

  return blockedNames.length > 0 && !!msg.sender_name && blockedNames.includes(msg.sender_name);
}

export function useRealtimeAppState({
  prevHealthRef,
  setHealth,
  fetchConfig,
  setRawPackets,
  reconcileOnReconnect,
  refreshUnreads,
  setChannels,
  fetchAllContacts,
  setContacts,
  blockedKeysRef,
  blockedNamesRef,
  channelsRef,
  activeConversationRef,
  observeMessage,
  recordMessageEvent,
  renameConversationState,
  removeConversationState,
  checkMention,
  pendingDeleteFallbackRef,
  setActiveConversation,
  renameConversationMessages,
  removeConversationMessages,
  receiveMessageAck,
  notifyIncomingMessage,
  recordRawPacketObservation,
  maxRawPackets = 500,
  setSpamLiveStatus,
}: UseRealtimeAppStateArgs): UseWebSocketOptions {
  const mergeChannelIntoList = useCallback(
    (updated: Channel) => {
      setChannels((prev) => {
        const existingIndex = prev.findIndex((channel) => channel.key === updated.key);
        if (existingIndex === -1) {
          return [...prev, updated].sort((a, b) => a.name.localeCompare(b.name));
        }
        const next = [...prev];
        next[existingIndex] = updated;
        return next;
      });
    },
    [setChannels]
  );

  return useMemo(
    () => ({
      onHealth: (data: HealthStatus) => {
        const prev = prevHealthRef.current;
        prevHealthRef.current = data;
        setHealth(data);
        const nextRadioState =
          data.radio_state ??
          (data.radio_initializing
            ? 'initializing'
            : data.radio_connected
              ? 'connected'
              : 'disconnected');
        const initializationCompleted =
          prev !== null &&
          prev.radio_connected &&
          prev.radio_initializing &&
          data.radio_connected &&
          !data.radio_initializing;

        if (prev !== null && prev.radio_connected !== data.radio_connected) {
          if (data.radio_connected) {
            toast.success('Radio connected', {
              description: data.connection_info
                ? `Connected via ${data.connection_info}`
                : undefined,
            });
            fetchConfig();
          } else {
            if (nextRadioState === 'paused') {
              toast.success('Radio connection paused');
            } else {
              toast.error('Radio disconnected', {
                description: 'Check radio connection and power',
              });
            }
          }
        }

        if (initializationCompleted) {
          fetchConfig();
        }
      },
      onError: (error: { message: string; details?: string }) => {
        toast.error(error.message, {
          description: error.details,
        });
      },
      onSuccess: (success: { message: string; details?: string }) => {
        toast.success(success.message, {
          description: success.details,
        });
      },
      onReconnect: () => {
        setRawPackets([]);
        reconcileOnReconnect();
        refreshUnreads();
        api.getChannels().then(setChannels).catch(console.error);
        fetchAllContacts()
          .then((data) => setContacts(data))
          .catch(console.error);
      },
      onMessage: (msg: Message) => {
        if (isMessageBlocked(msg, blockedKeysRef.current, blockedNamesRef.current)) {
          return;
        }

        const isMutedChannel =
          msg.type === 'CHAN' &&
          !!msg.conversation_key &&
          channelsRef.current.some((c) => c.key === msg.conversation_key && c.muted);

        const { added: isNewMessage, activeConversation: isForActiveConversation } =
          observeMessage(msg);

        if (!isMutedChannel) {
          recordMessageEvent({
            msg,
            activeConversation: isForActiveConversation,
            isNewMessage,
            hasMention: checkMention(msg.text),
          });
        }

        if (!msg.outgoing && isNewMessage && !isMutedChannel) {
          notifyIncomingMessage?.(msg);
        }
      },
      onContact: (contact: Contact) => {
        setContacts((prev) => mergeContactIntoList(prev, contact));
      },
      onLocation: (location: LocationPayload) => {
        setContacts((prev) => {
          let idx = -1;
          if (location.public_key) {
            idx = prev.findIndex((c) => c.public_key === location.public_key);
          }
          if (idx < 0 && location.node_id) {
            const nodeId = location.node_id.toLowerCase();
            idx = prev.findIndex((c) => c.public_key.toLowerCase().startsWith(nodeId));
          }
          if (idx < 0) return prev;
          const existing = prev[idx];
          const merged: Contact = {
            ...existing,
            lat: location.lat,
            lon: location.lon,
            is_tracker: true,
          };
          if (Number.isFinite(location.heading)) {
            merged.tracker_heading = location.heading;
          }
          if (location.name && !existing.tracker_name) {
            merged.tracker_name = location.name;
          }
          const unchanged =
            existing.lat === merged.lat &&
            existing.lon === merged.lon &&
            existing.is_tracker === merged.is_tracker &&
            existing.tracker_heading === merged.tracker_heading &&
            existing.tracker_name === merged.tracker_name;
          if (unchanged) return prev;
          const updated = [...prev];
          updated[idx] = merged;
          return updated;
        });
      },
      onContactResolved: (previousPublicKey: string, contact: Contact) => {
        setContacts((prev) =>
          mergeContactIntoList(
            prev.filter((candidate) => candidate.public_key !== previousPublicKey),
            contact
          )
        );
        renameConversationMessages(previousPublicKey, contact.public_key);
        renameConversationState(
          getStateKey('contact', previousPublicKey),
          getStateKey('contact', contact.public_key)
        );

        const active = activeConversationRef.current;
        if (active?.type === 'contact' && active.id === previousPublicKey) {
          setActiveConversation({
            type: 'contact',
            id: contact.public_key,
            name: getContactDisplayName(contact.name, contact.public_key, contact.last_advert),
          });
        }
      },
      onChannel: (channel: Channel) => {
        mergeChannelIntoList(channel);
      },
      onContactDeleted: (publicKey: string) => {
        setContacts((prev) => prev.filter((c) => c.public_key !== publicKey));
        removeConversationMessages(publicKey);
        removeConversationState(getStateKey('contact', publicKey));
        const active = activeConversationRef.current;
        if (active?.type === 'contact' && active.id === publicKey) {
          pendingDeleteFallbackRef.current = true;
          setActiveConversation(null);
        }
      },
      onChannelDeleted: (key: string) => {
        setChannels((prev) => prev.filter((c) => c.key !== key));
        removeConversationMessages(key);
        removeConversationState(getStateKey('channel', key));
        const active = activeConversationRef.current;
        if (active?.type === 'channel' && active.id === key) {
          pendingDeleteFallbackRef.current = true;
          setActiveConversation(null);
        }
      },
      onRawPacket: (packet: RawPacket) => {
        recordRawPacketObservation?.(packet);
        emitStatusDotPulse(packet.payload_type);
        setRawPackets((prev) => appendRawPacketUnique(prev, packet, maxRawPackets));
      },
      onMessageAcked: (
        messageId: number,
        ackCount: number,
        paths?: MessagePath[],
        packetId?: number | null
      ) => {
        receiveMessageAck(messageId, ackCount, paths, packetId);
      },
      onSpamFloodAlert: (status: SpamLiveStatus) => {
        setSpamLiveStatus?.(status);
      },
    }),
    [
      activeConversationRef,
      blockedKeysRef,
      blockedNamesRef,
      checkMention,
      fetchAllContacts,
      fetchConfig,
      removeConversationState,
      renameConversationState,
      renameConversationMessages,
      maxRawPackets,
      mergeChannelIntoList,
      pendingDeleteFallbackRef,
      prevHealthRef,
      recordMessageEvent,
      recordRawPacketObservation,
      receiveMessageAck,
      observeMessage,
      refreshUnreads,
      reconcileOnReconnect,
      removeConversationMessages,
      setSpamLiveStatus,
      setActiveConversation,
      setChannels,
      setContacts,
      setHealth,
      setRawPackets,
      notifyIncomingMessage,
    ]
  );
}
