import { forwardRef } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MapView } from '../components/MapView';
import type { Contact } from '../types';

const mockCanvas2dContext = {
  clearRect: vi.fn(),
  save: vi.fn(),
  restore: vi.fn(),
  scale: vi.fn(),
  beginPath: vi.fn(),
  moveTo: vi.fn(),
  lineTo: vi.fn(),
  stroke: vi.fn(),
  arc: vi.fn(),
  fill: vi.fn(),
  createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
};

HTMLCanvasElement.prototype.getContext = vi.fn((contextId: string) => {
  if (contextId === '2d') {
    return mockCanvas2dContext as unknown as CanvasRenderingContext2D;
  }
  return null;
}) as typeof HTMLCanvasElement.prototype.getContext;

vi.mock('react-leaflet', () => {
  const BaseLayer = ({
    children,
  }: {
    children: React.ReactNode;
    name: string;
    checked?: boolean;
  }) => <div>{children}</div>;
  const LayersControlMock = ({ children }: { children: React.ReactNode }) => <div>{children}</div>;
  (LayersControlMock as unknown as { BaseLayer: typeof BaseLayer }).BaseLayer = BaseLayer;
  return {
    MapContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    TileLayer: () => null,
    Marker: forwardRef<HTMLDivElement, { children: React.ReactNode; icon?: unknown }>(
      ({ children }, ref) => (
        <div ref={ref} data-testid="map-marker">
          {children}
        </div>
      )
    ),
    Popup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    Polyline: () => null,
    LayersControl: LayersControlMock,
    useMap: () => ({
      setView: vi.fn(),
      fitBounds: vi.fn(),
      setMaxZoom: vi.fn(),
      setZoom: vi.fn(),
      getZoom: vi.fn(() => 2),
      getContainer: () => document.createElement('div'),
      getSize: () => ({ x: 800, y: 600 }),
      latLngToContainerPoint: vi.fn(() => ({ x: 0, y: 0 })),
      on: vi.fn(),
      off: vi.fn(),
    }),
    useMapEvents: () => null,
  };
});

describe('MapView', () => {
  it('renders a never-heard fallback for a focused contact without last_seen', () => {
    const contact: Contact = {
      public_key: 'aa'.repeat(32),
      name: 'Mystery Node',
      type: 1,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 40,
      lon: -74,
      last_seen: null,
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
      is_tracker: false,
      tracker_name: null,
    };

    render(<MapView contacts={[contact]} focusedKey={contact.public_key} />);

    expect(
      screen.getByText(/showing 1 contact heard in the last 3 days plus the focused contact/i)
    ).toBeInTheDocument();
    expect(screen.getByText('Last heard: Never heard by this server')).toBeInTheDocument();
  });

  it('invokes onSelectContact when the popup name is clicked', () => {
    const contact: Contact = {
      public_key: 'cc'.repeat(32),
      name: 'Clickable',
      type: 1,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 42,
      lon: -72,
      last_seen: Math.floor(Date.now() / 1000),
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
      is_tracker: false,
      tracker_name: null,
    };
    const onSelectContact = vi.fn();

    render(<MapView contacts={[contact]} onSelectContact={onSelectContact} />);

    const link = screen.getByRole('button', { name: 'Clickable' });
    expect(link).toHaveAttribute('title', 'Open conversation with Clickable');
    fireEvent.click(link);

    expect(onSelectContact).toHaveBeenCalledWith(contact);
  });

  it('renders the popup name as plain text when no onSelectContact is provided', () => {
    const contact: Contact = {
      public_key: 'dd'.repeat(32),
      name: 'Static',
      type: 1,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 42,
      lon: -72,
      last_seen: Math.floor(Date.now() / 1000),
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
      is_tracker: false,
      tracker_name: null,
    };

    render(<MapView contacts={[contact]} />);

    expect(screen.queryByRole('button', { name: /open conversation with static/i })).toBeNull();
    expect(screen.getByText('Static')).toBeInTheDocument();
  });

  it('keeps the 3-day packet-window cutoff stable for the lifetime of the mounted map', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2026-03-15T12:00:00Z'));

      const contact: Contact = {
        public_key: 'bb'.repeat(32),
        name: 'Almost Stale',
        type: 1,
        flags: 0,
        direct_path: null,
        direct_path_len: -1,
        direct_path_hash_mode: -1,
        route_override_path: null,
        route_override_len: null,
        route_override_hash_mode: null,
        last_advert: null,
        lat: 41,
        lon: -73,
        last_seen: Math.floor(Date.now() / 1000) - 3 * 24 * 60 * 60 + 60,
        on_radio: false,
        favorite: false,
        last_contacted: null,
        last_read_at: null,
        first_seen: null,
        is_tracker: false,
        tracker_name: null,
      };

      const { rerender } = render(<MapView contacts={[contact]} focusedKey={null} />);

      expect(screen.getByText(/showing 1 contact heard in the last 3 days/i)).toBeInTheDocument();

      vi.advanceTimersByTime(2 * 60 * 1000);
      rerender(<MapView contacts={[contact]} focusedKey={null} />);

      expect(screen.getByText(/showing 1 contact heard in the last 3 days/i)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('excludes contacts whose public key is in blockedKeys', () => {
    const visible: Contact = {
      public_key: 'aa'.repeat(32),
      name: 'Visible',
      type: 1,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 40,
      lon: -74,
      last_seen: Math.floor(Date.now() / 1000),
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
is_tracker: false,
      tracker_name: null,
    };
    const blocked: Contact = {
      public_key: 'bb'.repeat(32),
      name: 'Blocked',
      type: 2,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 41,
      lon: -73,
      last_seen: Math.floor(Date.now() / 1000),
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
is_tracker: false,
      tracker_name: null,
    };

    render(<MapView contacts={[visible, blocked]} blockedKeys={['bb'.repeat(32)]} />);

    expect(screen.getByText('Visible')).toBeInTheDocument();
    expect(screen.queryByText('Blocked')).toBeNull();
  });

  it('excludes contacts whose name is in blockedNames', () => {
    const visible: Contact = {
      public_key: 'aa'.repeat(32),
      name: 'Visible',
      type: 1,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 40,
      lon: -74,
      last_seen: Math.floor(Date.now() / 1000),
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
is_tracker: false,
      tracker_name: null,
    };
    const blocked: Contact = {
      public_key: 'cc'.repeat(32),
      name: 'BadActor',
      type: 2,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 41,
      lon: -73,
      last_seen: Math.floor(Date.now() / 1000),
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
is_tracker: false,
      tracker_name: null,
    };

    render(<MapView contacts={[visible, blocked]} blockedNames={['BadActor']} />);

    expect(screen.getByText('Visible')).toBeInTheDocument();
    expect(screen.queryByText('BadActor')).toBeNull();
  });
  
  it('excludes contacts whose public key is in blockedKeys', () => {
    const visible: Contact = {
      public_key: 'aa'.repeat(32),
      name: 'Visible',
      type: 1,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 40,
      lon: -74,
      last_seen: Math.floor(Date.now() / 1000),
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
is_tracker: false,
      tracker_name: null,
    };
    const blocked: Contact = {
      public_key: 'bb'.repeat(32),
      name: 'Blocked',
      type: 2,
      flags: 0,
      direct_path: null,
      direct_path_len: -1,
      direct_path_hash_mode: -1,
      route_override_path: null,
      route_override_len: null,
      route_override_hash_mode: null,
      last_advert: null,
      lat: 41,
      lon: -73,
      last_seen: Math.floor(Date.now() / 1000),
      on_radio: false,
      favorite: false,
      last_contacted: null,
      last_read_at: null,
      first_seen: null,
is_tracker: false,
      tracker_name: null,
    };

    render(<MapView contacts={[visible, blocked]} blockedKeys={['bb'.repeat(32)]} />);

    expect(screen.getByText('Visible')).toBeInTheDocument();
    expect(screen.queryByText('Blocked')).toBeNull();
  });
});
