import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { OpenEvents, type OpenEvent } from './OpenEvents';
afterEach(cleanup);

// SPL-115 (CS-E19-S2) component cases. Which events are open, the public fields and the Registered
// mark are decided by the server and proved in backend/tests/test_open_registrations.py; these
// prove an attendee can read the list and register from it.

const GALA: OpenEvent = {
  id: 12, name: 'Harbour Lights Gala', description: 'An evening of music by the water.', date: '2026-11-20',
  start_time: '18:00', end_time: '22:00', venues: ['Bayfront Room', 'Harbour Hall'], places_remaining: 7, registered: false,
};
const TALK: OpenEvent = {
  id: 13, name: 'Founders Talk', description: null, date: '2026-11-25',
  start_time: '09:00', end_time: '11:00', venues: ['Atrium'], places_remaining: 3, registered: true,
};
const SOLD_OUT: OpenEvent = { ...GALA, id: 14, name: 'Sold out', places_remaining: 0 };

// A fake server: GET returns the list; POST (registering through SPL-116's form) returns a confirmation.
function api(events: OpenEvent[]) {
  return vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      return {
        ok: true, status: 201, json: async () => ({
          registration: {
            id: 7, status: 'registered', name: 'Avery Koh', email: 'avery@example.test', contact_number: '+65 9123 4567',
            special_requirements: null, registered_at: '2026-10-20T12:00:00+08:00',
          },
          event: { ...GALA, places_remaining: 6 },
        }),
      };
    }
    expect(path).toBe('/api/open-events');
    return { ok: true, status: 200, json: async () => ({ events }) };
  }) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
}

const card = (name: string) => screen.getByRole('heading', { name }).closest('li') as HTMLElement;

// TC-SPL-115-09
// SPL-115 AC-2 Test-09
it('[TC-SPL-115-09] shows each event with its details, places remaining and a Registered badge', async () => {
  render(<OpenEvents accessToken="token" request={api([GALA, TALK])} />);

  await screen.findByRole('heading', { name: 'Harbour Lights Gala' });
  const gala = within(card('Harbour Lights Gala'));
  expect(gala.getByText('20 Nov 2026 · 18:00–22:00')).toBeTruthy();
  expect(gala.getByText('Bayfront Room, Harbour Hall')).toBeTruthy();
  expect(gala.getByText('An evening of music by the water.')).toBeTruthy();
  expect(gala.getByText('7 places remaining')).toBeTruthy();
  expect(gala.queryByText('Registered')).toBeNull();

  // AC4: only the event this attendee holds a place at carries the badge.
  const talk = within(card('Founders Talk'));
  expect(talk.getByText('Registered')).toBeTruthy();
  expect(talk.queryByRole('button', { name: /Register for/ })).toBeNull();
});

// TC-SPL-115-09
// SPL-115 AC-1 Test-09
it('[TC-SPL-115-09] says so when no events are open for registration', async () => {
  render(<OpenEvents accessToken="token" request={api([])} />);

  expect(await screen.findByText('No events are open for registration right now.')).toBeTruthy();
  expect(screen.queryByRole('list', { name: 'Events open for registration' })).toBeNull();
});

// TC-SPL-115-09
// SPL-115 AC-2 Test-09
it('[TC-SPL-115-09] keeps a full event listed with no places and no way to register', async () => {
  render(<OpenEvents accessToken="token" request={api([SOLD_OUT])} />);

  await screen.findByRole('heading', { name: 'Sold out' });
  const soldOut = within(card('Sold out'));
  expect(soldOut.getByText('Full · no places remaining')).toBeTruthy();
  expect(soldOut.queryByRole('button', { name: /Register for/ })).toBeNull();
});

// TC-SPL-115-09
// SPL-115 AC-4 Test-09
it('[TC-SPL-115-09] registers from the list and then marks the event Registered with the new places', async () => {
  const request = api([GALA]);
  render(<OpenEvents accessToken="token" request={request} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Register for Harbour Lights Gala' }));
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Avery Koh' } });
  fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'avery@example.test' } });
  fireEvent.change(screen.getByLabelText('Contact number'), { target: { value: '+65 9123 4567' } });
  fireEvent.click(screen.getByRole('button', { name: 'Register' }));

  // SPL-116's confirmation shows, and the list entry updates from the server's own answer.
  expect(await screen.findByText('You are registered')).toBeTruthy();
  const gala = within(card('Harbour Lights Gala'));
  expect(gala.getByText('Registered')).toBeTruthy();
  expect(gala.getByText('6 places remaining')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/registrations', expect.objectContaining({ method: 'POST' }));
});

// TC-SPL-115-09
// SPL-115 AC-1 Test-09
it('[TC-SPL-115-09] shows an error instead of an empty list when the events cannot be loaded', async () => {
  const failing = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({ error: 'Server error' }) })) as unknown as ApiRequest;
  render(<OpenEvents accessToken="token" request={failing} />);

  expect((await screen.findByRole('alert')).textContent).toBe('Could not load the events open for registration. Try again.');
  expect(screen.queryByText('No events are open for registration right now.')).toBeNull();
});
