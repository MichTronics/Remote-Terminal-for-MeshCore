import type { Contact } from '../types';
import { getContactDisplayName } from './pubkey';

export const CONTACT_TYPE_LABELS: Record<number, string> = {
  0: 'Unknown',
  1: 'Client',
  2: 'Repeater',
  3: 'Room',
  4: 'Sensor',
};

export function getContactTypeLabel(type: number): string {
  return CONTACT_TYPE_LABELS[type] ?? 'Unknown';
}

export function contactMatchesSearchQuery(contact: Contact, query: string): boolean {
  const normalized = query.toLowerCase().trim();
  if (!normalized) return false;

  const displayName = getContactDisplayName(
    contact.name,
    contact.public_key,
    contact.last_advert
  ).toLowerCase();
  const name = contact.name?.toLowerCase() ?? '';
  const publicKey = contact.public_key.toLowerCase();

  return (
    displayName.includes(normalized) ||
    name.includes(normalized) ||
    publicKey.includes(normalized)
  );
}

export function filterContactsBySearchQuery(contacts: Contact[], query: string): Contact[] {
  const normalized = query.trim();
  if (!normalized) return [];

  return contacts.filter((contact) => contactMatchesSearchQuery(contact, normalized));
}
