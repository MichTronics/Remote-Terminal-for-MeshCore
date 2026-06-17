import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { Contact } from '../types';
import { getContactDisplayName } from '../utils/pubkey';
import {
  filterContactsBySearchQuery,
  getContactTypeLabel,
} from '../utils/contactSearch';
import { ContactAvatar } from './ContactAvatar';
import { Input } from './ui/input';
import { cn } from '@/lib/utils';

const DEBOUNCE_MS = 200;
const MAX_RESULTS = 500;

export interface NodeSearchViewProps {
  contacts: Contact[];
  blockedKeys?: string[];
  blockedNames?: string[];
  visibilityVersion?: number;
  onSelectContact: (contact: Contact) => void;
}

function highlightMatch(text: string, query: string): React.ReactNode[] {
  if (!query) return [text];
  const parts: React.ReactNode[] = [];
  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  const segments = text.split(regex);
  for (let i = 0; i < segments.length; i++) {
    if (regex.test(segments[i])) {
      parts.push(
        <mark key={i} className="bg-primary/30 text-foreground rounded-sm px-0.5">
          {segments[i]}
        </mark>
      );
    } else {
      parts.push(segments[i]);
    }
    regex.lastIndex = 0;
  }
  return parts;
}

function isContactBlocked(
  contact: Contact,
  blockedKeys: string[],
  blockedNames: string[]
): boolean {
  const lowerKey = contact.public_key.toLowerCase();
  if (blockedKeys.some((key) => lowerKey.startsWith(key.toLowerCase()))) {
    return true;
  }
  const name = contact.name?.trim().toLowerCase();
  return !!name && blockedNames.some((blocked) => blocked.toLowerCase() === name);
}

export function NodeSearchView({
  contacts,
  blockedKeys = [],
  blockedNames = [],
  visibilityVersion = 0,
  onSelectContact,
}: NodeSearchViewProps) {
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const highlightQuery = debouncedQuery.toLowerCase();

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (visibilityVersion > 0) {
      inputRef.current?.focus();
    }
  }, [visibilityVersion]);

  const results = useMemo(() => {
    if (!debouncedQuery) return [];

    const visibleContacts = contacts.filter(
      (contact) => !isContactBlocked(contact, blockedKeys, blockedNames)
    );
    const matches = filterContactsBySearchQuery(visibleContacts, debouncedQuery);

    return matches
      .map((contact) => ({
        contact,
        displayName: getContactDisplayName(
          contact.name,
          contact.public_key,
          contact.last_advert
        ),
      }))
      .sort((a, b) => a.displayName.localeCompare(b.displayName, undefined, { sensitivity: 'base' }));
  }, [contacts, debouncedQuery, blockedKeys, blockedNames]);

  const displayedResults = results.slice(0, MAX_RESULTS);
  const truncated = results.length > MAX_RESULTS;

  const handleContactClick = useCallback(
    (contact: Contact) => {
      onSelectContact(contact);
    },
    [onSelectContact]
  );

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  return (
    <div className="flex flex-col h-full">
      <h2 className="flex justify-between items-center px-4 py-2.5 border-b border-border font-semibold text-base">
        Node Search
      </h2>

      <div className="px-4 py-3 border-b border-border">
        <Input
          ref={inputRef}
          type="text"
          placeholder="Search by name or public key..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="h-9 text-sm"
          aria-label="Search nodes"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {!debouncedQuery && (
          <div className="p-8 text-center text-muted-foreground text-sm">
            <p>Type to search contacts, repeaters, room servers, and sensors</p>
            <p className="mt-2 text-xs">
              Matches any part of a node name or public key ({contacts.length.toLocaleString()}{' '}
              nodes loaded)
            </p>
          </div>
        )}

        {debouncedQuery && results.length === 0 && (
          <div className="p-8 text-center text-muted-foreground text-sm">
            No nodes found for &ldquo;{debouncedQuery}&rdquo;
          </div>
        )}

        {debouncedQuery && results.length > 0 && (
          <div className="px-4 py-2 text-[0.6875rem] text-muted-foreground border-b border-border/50">
            {results.length.toLocaleString()} match{results.length === 1 ? '' : 'es'}
            {truncated ? ` (showing first ${MAX_RESULTS.toLocaleString()})` : ''}
          </div>
        )}

        {displayedResults.map(({ contact, displayName }) => {
          const typeLabel = getContactTypeLabel(contact.type);

          return (
            <div
              key={contact.public_key}
              className="px-4 py-3 border-b border-border/50 cursor-pointer hover:bg-accent/50 transition-colors"
              role="button"
              tabIndex={0}
              onClick={() => handleContactClick(contact)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleContactClick(contact);
                }
              }}
            >
              <div className="flex items-center gap-2">
                <ContactAvatar
                  name={contact.name}
                  publicKey={contact.public_key}
                  size={28}
                  contactType={contact.type}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[0.8125rem] font-medium text-foreground truncate">
                      {highlightMatch(displayName, highlightQuery)}
                    </span>
                    <span
                      className={cn(
                        'text-[0.625rem] font-medium px-1.5 py-0.5 rounded flex-shrink-0',
                        contact.type === 2
                          ? 'bg-primary/20 text-primary'
                          : contact.type === 3
                            ? 'bg-secondary text-secondary-foreground'
                            : 'bg-muted text-muted-foreground'
                      )}
                    >
                      {typeLabel}
                    </span>
                  </div>
                  <div className="text-[0.6875rem] text-muted-foreground font-mono truncate">
                    {highlightMatch(contact.public_key, highlightQuery)}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
