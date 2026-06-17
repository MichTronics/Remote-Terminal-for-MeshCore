import { describe, expect, it } from 'vitest';

import type { Contact } from '../types';
import {
  contactMatchesSearchQuery,
  filterContactsBySearchQuery,
  getContactTypeLabel,
} from '../utils/contactSearch';

function makeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    public_key: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
    name: 'Alice',
    type: 1,
    flags: 0,
    last_advert: 1700000000,
    last_contacted: null,
    last_seen: 1700000000,
    first_seen: 1699000000,
    lat: 0,
    lon: 0,
    on_radio: false,
    favorite: false,
    last_read_at: null,
    direct_path: null,
    direct_path_len: -1,
    direct_path_hash_mode: 0,
    is_tracker: false,
    tracker_name: null,
    ...overrides,
  };
}

describe('contactSearch', () => {
  it('matches partial names case-insensitively', () => {
    const contact = makeContact({ name: 'MountainRepeater' });
    expect(contactMatchesSearchQuery(contact, 'repeater')).toBe(true);
    expect(contactMatchesSearchQuery(contact, 'MOUNT')).toBe(true);
  });

  it('matches partial public keys anywhere in the key', () => {
    const contact = makeContact({
      public_key: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
    });
    expect(contactMatchesSearchQuery(contact, '3456789')).toBe(true);
    expect(contactMatchesSearchQuery(contact, 'CDEF01')).toBe(true);
  });

  it('returns no matches for empty query', () => {
    const contact = makeContact();
    expect(contactMatchesSearchQuery(contact, '')).toBe(false);
    expect(filterContactsBySearchQuery([contact], '')).toEqual([]);
  });

  it('filters a contact list', () => {
    const contacts = [
      makeContact({ name: 'Alpha', public_key: 'aa' + '0'.repeat(62) }),
      makeContact({ name: 'Beta', public_key: 'bb' + '0'.repeat(62) }),
    ];
    expect(filterContactsBySearchQuery(contacts, 'beta')).toHaveLength(1);
    expect(filterContactsBySearchQuery(contacts, 'bb00')).toHaveLength(1);
  });

  it('labels contact types', () => {
    expect(getContactTypeLabel(2)).toBe('Repeater');
    expect(getContactTypeLabel(99)).toBe('Unknown');
  });
});
