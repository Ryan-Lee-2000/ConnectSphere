import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { VenueBookingPanel } from './VenueBookingWithdrawal';
afterEach(cleanup);

const BOOKING = {
  id: 41, event_request_id: 12, venue: { id: 1, name: 'Harbour Hall' }, date: '2026-10-14', event_slots: ['PM'],
  setup: { date: '2026-10-14', slot: 'AM' }, turnaround: { date: '2026-10-14', slot: 'NIGHT' }, layout: 'theatre',
  expected_attendance: 150, status: 'requested', requested_by: { id: 'casey', name: 'Casey Lim' },
  requested_at: '2026-09-27T21:15:00+08:00', requires_review: false, review_trigger_block_id: null, review_marked_at: null,
  withdrawn_by: null, withdrawn_at: null,
};
const WITHDRAWN = { ...BOOKING, status: 'withdrawn', withdrawn_by: { id: 'casey', name: 'Casey Lim' }, withdrawn_at: '2026-09-28T10:15:00+08:00' };

function api(latest: object | null, withdrawal?: { status: number; body: unknown }) {
  return vi.fn(async (path: string) => {
    if (path.endsWith('/withdraw')) {
      return { ok: (withdrawal?.status ?? 200) < 300, status: withdrawal?.status ?? 200, json: async () => withdrawal?.body };
    }
    return { ok: true, status: 200, json: async () => ({ booking: latest }) };
  }) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
}
const withdrawCalls = (request: ReturnType<typeof vi.fn>) => request.mock.calls.filter(([path]) => String(path).endsWith('/withdraw'));

// SPL-78 AC-1,6 Test-22
it('[TC-SPL-78-22] offers Withdraw only for a Requested booking and confirms first', async () => {
  for (const status of ['approved', 'withdrawn']) {
    const request = api({ ...BOOKING, status });
    render(<VenueBookingPanel api={request} eventId={12} />);
    expect(await screen.findByText('Harbour Hall')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Withdraw request' })).toBeNull();
    cleanup();
  }

  const request = api(BOOKING, { status: 200, body: { booking: WITHDRAWN } });
  render(<VenueBookingPanel api={request} eventId={12} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Withdraw request' }));
  expect(screen.getByRole('group', { name: 'Confirm withdrawal' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Keep request' }));
  expect(withdrawCalls(request)).toHaveLength(0);

  fireEvent.click(screen.getByRole('button', { name: 'Withdraw request' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm withdrawal' }));
  await screen.findByText(/Request withdrawn/);
  expect(withdrawCalls(request)).toEqual([['/api/event-requests/12/venue-bookings/41/withdraw', { method: 'POST' }]]);
});

// SPL-78 AC-2,4,6 Test-23
it('[TC-SPL-78-23] shows the withdrawal record after success, and keeps the request details', async () => {
  const onWithdrawn = vi.fn();
  const request = api(BOOKING, { status: 200, body: { booking: WITHDRAWN } });
  render(<VenueBookingPanel api={request} eventId={12} onWithdrawn={onWithdrawn} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Withdraw request' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm withdrawal' }));

  expect((await screen.findByRole('status')).textContent).toContain('Request withdrawn');
  expect(screen.getByText('Withdrawn')).toBeTruthy();
  expect(screen.getByText(/Withdrawn by Casey Lim/).textContent).toContain('28 Sept 2026');
  expect(screen.getByText('Harbour Hall')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Withdraw request' })).toBeNull();
  expect(onWithdrawn).toHaveBeenCalledTimes(1);
});

// SPL-78 AC-2,4,6 Test-23
it('[TC-SPL-78-23] shows the server refusal verbatim and never marks the request withdrawn', async () => {
  const onWithdrawn = vi.fn();
  const request = api(BOOKING, { status: 409, body: { error: 'Only a Requested venue-booking request can be withdrawn.' } });
  render(<VenueBookingPanel api={request} eventId={12} onWithdrawn={onWithdrawn} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Withdraw request' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm withdrawal' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Only a Requested venue-booking request can be withdrawn.');
  expect(screen.getByText('Requested')).toBeTruthy();
  expect(screen.queryByText(/Request withdrawn/)).toBeNull();
  expect(onWithdrawn).not.toHaveBeenCalled();
});

// SPL-78 AC-1,6 Test-22
it('[TC-SPL-78-22] shows nothing when the event has no venue-booking request yet', async () => {
  const request = api(null);
  const { container } = render(<VenueBookingPanel api={request} eventId={12} />);
  await vi.waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/12/venue-bookings/latest'));
  expect(container.textContent).toBe('');
});
