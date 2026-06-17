import { fireEvent, render, screen, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest';

import { NodeSearchView } from '../components/NodeSearchView';
import type { Contact } from '../types';
import { CONTACT_TYPE_REPEATER, CONTACT_TYPE_ROOM } from '../types';

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

describe('NodeSearchView', () => {
  const onSelectContact = vi.fn();

  const defaultProps = {
    contacts: [
      makeContact({ name: 'Alice' }),
      makeContact({
        name: 'BobRepeater',
        type: CONTACT_TYPE_REPEATER,
        public_key: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      }),
      makeContact({
        name: 'RoomServer',
        type: CONTACT_TYPE_ROOM,
        public_key: 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
      }),
    ],
    onSelectContact,
  };

  beforeEach(() => {
    vi.useFakeTimers();
    onSelectContact.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders empty state before searching', () => {
    render(<NodeSearchView {...defaultProps} />);
    expect(screen.getByText(/Type to search contacts/i)).toBeInTheDocument();
  });

  it('filters nodes by partial name', async () => {
    render(<NodeSearchView {...defaultProps} />);
    fireEvent.change(screen.getByLabelText('Search nodes'), { target: { value: 'repeater' } });

    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    expect(screen.getByText((_, el) => el?.textContent === 'BobRepeater')).toBeInTheDocument();
    expect(screen.queryByText('Alice')).not.toBeInTheDocument();
  });

  it('filters nodes by partial public key', async () => {
    render(<NodeSearchView {...defaultProps} />);
    fireEvent.change(screen.getByLabelText('Search nodes'), { target: { value: 'cccccc' } });

    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    expect(screen.getByText('RoomServer')).toBeInTheDocument();
    expect(screen.getByText('Room')).toBeInTheDocument();
  });

  it('navigates on result click', async () => {
    render(<NodeSearchView {...defaultProps} />);
    fireEvent.change(screen.getByLabelText('Search nodes'), { target: { value: 'alice' } });

    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    fireEvent.click(screen.getByRole('button'));
    expect(onSelectContact).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Alice', public_key: defaultProps.contacts[0].public_key })
    );
  });

  it('excludes blocked contacts', async () => {
    render(
      <NodeSearchView
        {...defaultProps}
        blockedKeys={['bbbbbbbbbbbb']}
        blockedNames={['Alice']}
      />
    );
    fireEvent.change(screen.getByLabelText('Search nodes'), { target: { value: 'a' } });

    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    expect(screen.getByText(/No nodes found/i)).toBeInTheDocument();
  });
});
