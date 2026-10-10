import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { MyRegistrations, type MyRegistration } from './MyRegistrations';
afterEach(cleanup);

// SPL-117 (CS-E19-S4) component cases. Which registrations are listed, their order and the public
// fields are decided by the server and proved in backend/tests/test_my_registrations.py; these
// prove an attendee can read their list, open one, and withdraw from it (SPL-118).

const EVENT = {
  id: 12, name: 'Harbour Lights Gala', description: 'An evening of music by the water.', date: '2026-11-20',
  start_time: '18:00', end_time: '22:00', venues: ['Harbour Hall'], places_remaining: 9,
  status: 'confirmed', status_label: 'Confirmed',
};
const REGISTRATION = {
  id: 7, status: 'registered', name: 'Avery Koh', email: 'avery@example.test', contact_number: '+65 9123 4567',
  special_requirements: 'Vegetarian meal', registered_at: '2026-10-20T12:00:00+08:00', withdrawn_at: null,
};
const REGISTERED: MyRegistration = { registration: REGISTRATION, event: EVENT };
const WITHDRAWN: MyRegistration = {
  registration: { ...REGISTRATION, id: 8, status: 'withdrawn', withdrawn_at: '2026-10-21T09:00:00+08:00' },
  event: { ...EVENT, id: 13, name: 'Founders Talk' },
};
const CANCELLED: MyRegistration = {
  registration: { ...REGISTRATION, id: 9 },
  event: { ...EVENT, id: 14, name: 'Riverside Market', status: 'cancelled', status_label: 'Cancelled' },
};
// Before the event (20 Nov 18:00 Singapore time), so withdrawing is offered.
const BEFORE = () => new Date('2026-10-20T04:00:00Z');

// A fake server for the three calls this page makes.
function api(entries: MyRegistration[]) {
  return vi.fn(async (path: string, init?: RequestInit) => {
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
    if (init?.method === 'POST') {
      return reply({ registration: { id: 7, status: 'withdrawn', withdrawn_at: '2026-10-20T12:00:00+08:00' },
        event: { ...EVENT, places_remaining: 10 } });
    }
    if (path === '/api/my-registrations') return reply({ registrations: entries });
    const id = Number(path.split('/').pop());
    return reply(entries.find(entry => entry.registration.id === id));
  }) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
}

const card = (name: string) => within(screen.getByRole('heading', { name }).closest('li') as HTMLElement);

// TC-SPL-117-08
// SPL-117 AC-1 Test-08
it('[TC-SPL-117-08] shows a status for Registered, Withdrawn and a cancelled event', async () => {
  render(<MyRegistrations accessToken="token" request={api([REGISTERED, WITHDRAWN, CANCELLED])} now={BEFORE} />);

  await screen.findByRole('heading', { name: 'Harbour Lights Gala' });
  const gala = card('Harbour Lights Gala');
  expect(gala.getByText('20 Nov 2026 · 18:00–22:00 · Harbour Hall')).toBeTruthy();
  expect(gala.getByText('Registered')).toBeTruthy();
  expect(gala.queryByText(/^Event /)).toBeNull();   // a Confirmed event needs no warning

  expect(card('Founders Talk').getByText('Withdrawn')).toBeTruthy();
  // AC3: the event's current status, alongside the registration's own.
  const market = card('Riverside Market');
  expect(market.getByText('Registered')).toBeTruthy();
  expect(market.getByText('Event cancelled')).toBeTruthy();
});

// TC-SPL-117-08
// SPL-117 AC-1 Test-08
it('[TC-SPL-117-08] says so when the attendee has no registrations', async () => {
  render(<MyRegistrations accessToken="token" request={api([])} now={BEFORE} />);

  expect(await screen.findByText('You have not registered for any events yet.')).toBeTruthy();
  expect(screen.queryByRole('list', { name: 'My registrations' })).toBeNull();
});

// TC-SPL-117-08
// SPL-117 AC-4 Test-08
it('[TC-SPL-117-08] opening a registration shows the event and what was submitted', async () => {
  const request = api([REGISTERED]);
  render(<MyRegistrations accessToken="token" request={request} now={BEFORE} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Details for Harbour Lights Gala' }));

  const details = await screen.findByRole('region', { name: 'Registration details for Harbour Lights Gala' });
  expect(within(details).getByText('An evening of music by the water.')).toBeTruthy();
  expect(within(details).getByText('9 places remaining')).toBeTruthy();
  expect(within(details).getByText('Avery Koh · avery@example.test · +65 9123 4567')).toBeTruthy();
  expect(within(details).getByText('Special requirements: Vegetarian meal')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/my-registrations/7');
});

// TC-SPL-117-08 (with SPL-118's withdraw control)
// SPL-117 AC-1 Test-08
it('[TC-SPL-117-08] withdrawing from the list shows the registration as Withdrawn', async () => {
  render(<MyRegistrations accessToken="token" request={api([REGISTERED])} now={BEFORE} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Withdraw from Harbour Lights Gala' }));
  fireEvent.click(screen.getByRole('button', { name: 'Yes, withdraw' }));

  expect(await screen.findByText('You have withdrawn from Harbour Lights Gala.')).toBeTruthy();
  expect(card('Harbour Lights Gala').getByText('Withdrawn')).toBeTruthy();
});

// TC-SPL-117-08
// SPL-117 AC-1 Test-08
it('[TC-SPL-117-08] shows an error instead of an empty list when registrations cannot be loaded', async () => {
  const failing = vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })) as unknown as ApiRequest;
  render(<MyRegistrations accessToken="token" request={failing} now={BEFORE} />);

  expect((await screen.findByRole('alert')).textContent).toBe('Could not load your registrations. Try again.');
  expect(screen.queryByText('You have not registered for any events yet.')).toBeNull();
});
