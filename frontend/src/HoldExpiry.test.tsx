import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { PendingBookingRequests } from './PendingBookingRequests';
import { VenueArrangements } from './VenueArrangements';
import { VenueBookingReview } from './VenueBookingReview';

// SPL-133 interface cases from QA-SPL-133. The server sets, moves and enforces hold deadlines;
// these tests prove the pages show the deadline, send changes faithfully and show Expired.

afterEach(cleanup);

const DEADLINE = '2026-11-08T10:00:00+08:00';
const BOOKING = {
  id: 41, event_request_id: 12, venue: { id: 1, name: 'Harbour Hall' }, date: '2026-11-20', event_slots: ['PM'],
  setup: null, turnaround: null, layout: 'theatre', expected_attendance: 150, status: 'requested',
  requested_by: { id: 'casey', name: 'Casey Lim' }, requested_at: '2026-11-01T10:00:00+08:00', expires_at: DEADLINE,
  requires_review: false, review_trigger_block_id: null, review_marked_at: null, withdrawn_by: null, withdrawn_at: null,
  approved_by: null, approved_at: null, approval_note: null, rejected_by: null, rejected_at: null, rejection_reason: null,
  rejection_alternative_suggestion: null, review_reasons: [], timing: null, required_facilities: [],
};
const EVENT = {
  id: 12, name: 'Coastal Forum', status: 'planning', organisation: null, purpose: null, description: null,
  proposed_date: '2026-11-20', start_time: '13:00', end_time: '18:00', expected_attendance: 150, preferred_room_layout: null,
  required_facilities: [], accessibility_needs: [], facilities_notes: null, location_preference: null, venue_notes: null,
};
const REVIEW = { requires_review: false, marked_at: null, trigger_block: null };

const reply = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;

function reviewApi(first: unknown, handlers: Record<string, Response> = {}, later?: unknown) {
  let loads = 0;
  return vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method && handlers[path]) return handlers[path];
    loads += 1;
    return reply(200, loads > 1 && later ? later : first);
  }) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
}

// QA-SPL-133-090 | AC2 | BB
it('[QA-SPL-133-090] Venue Staff see the hold deadline on the request', async () => {
  render(<VenueBookingReview accessToken="t" bookingId={41} request={reviewApi({ booking: BOOKING, event: EVENT, review: REVIEW })} />);

  const details = await screen.findByRole('list', { name: 'Request details' });
  expect(details.textContent).toContain('Hold expires');
  expect(details.textContent).toContain('8 Nov 2026, 10:00 am SGT');
  expect(within(screen.getByRole('region', { name: 'Hold deadline' })).getByText('8 Nov 2026, 10:00 am')).toBeTruthy();
});

// QA-SPL-133-091 | AC3 | BB
it('[QA-SPL-133-091] changes the deadline in Singapore time and shows the new one', async () => {
  const moved = { ...BOOKING, expires_at: '2026-11-05T12:00:00+08:00' };
  const request = reviewApi({ booking: BOOKING, event: EVENT, review: REVIEW }, {
    '/api/venue-bookings/41/hold-deadline': reply(200, { booking: moved }),
  });
  render(<VenueBookingReview accessToken="t" bookingId={41} request={request} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Change deadline' }));
  const form = screen.getByRole('form', { name: 'Change hold deadline' });
  const input = within(form).getByLabelText('New deadline (SGT)') as HTMLInputElement;
  expect(input.value).toBe('2026-11-08T10:00');
  fireEvent.change(input, { target: { value: '2026-11-05T12:00' } });
  fireEvent.click(within(form).getByRole('button', { name: 'Save deadline' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venue-bookings/41/hold-deadline', {
    method: 'PUT', body: JSON.stringify({ expires_at: '2026-11-05T12:00' }),
  }));
  expect(await screen.findByText('5 Nov 2026, 12:00 pm')).toBeTruthy();
  expect(screen.queryByRole('form', { name: 'Change hold deadline' })).toBeNull();
});

// QA-SPL-133-092 | AC3 | BB
it('[QA-SPL-133-092] a refused change shows the reason and Keep deadline sends nothing', async () => {
  const request = reviewApi({ booking: BOOKING, event: EVENT, review: REVIEW }, {
    '/api/venue-bookings/41/hold-deadline': reply(400, { error: 'A hold can be kept for at most 14 days from now.' }),
  });
  render(<VenueBookingReview accessToken="t" bookingId={41} request={request} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Change deadline' }));
  fireEvent.click(screen.getByRole('button', { name: 'Keep deadline' }));
  expect(request.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(0);

  fireEvent.click(screen.getByRole('button', { name: 'Change deadline' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save deadline' }));
  expect((await screen.findByRole('alert')).textContent).toBe('A hold can be kept for at most 14 days from now.');
});

// QA-SPL-133-093 | AC4/AC5 | BB
it('[QA-SPL-133-093] an approval refused because the hold expired reloads and shows Expired', async () => {
  const expired = { ...BOOKING, status: 'expired' };
  const request = reviewApi({ booking: BOOKING, event: EVENT, review: REVIEW }, {
    '/api/venue-bookings/41/approve': reply(409, { error: 'This hold expired at 8 Nov 2026, 10:00 SGT, so it can no longer be approved.' }),
  }, { booking: expired, event: EVENT, review: REVIEW });
  render(<VenueBookingReview accessToken="t" bookingId={41} request={request} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Approve booking' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm approval' }));

  expect((await screen.findByRole('alert')).textContent).toContain('This hold expired at 8 Nov 2026');
  expect(await screen.findByText(/This hold expired on 8 Nov 2026, 10:00 am SGT before it was approved/)).toBeTruthy();
  const details = screen.getByRole('list', { name: 'Request details' });
  expect(details.textContent).toContain('Expired');
  expect(details.textContent).toContain('Hold expired');
  expect(screen.queryByRole('button', { name: 'Approve booking' })).toBeNull();
  expect(screen.queryByRole('region', { name: 'Hold deadline' })).toBeNull();
});

// QA-SPL-133-094 | AC2/AC3/AC6 | BB
it('[QA-SPL-133-094] the coordinator sees the deadline, then Expired with a prompt to request again', async () => {
  const card = (status: string, label: string) => ({
    booking: { ...BOOKING, status }, current_status: { status, label },
    history: [{ action: 'request', status: 'requested', status_label: 'Requested', actor: { id: 'casey', name: 'Casey Lim' }, changed_at: '2026-11-01T10:00:00+08:00', note: null }],
    review: { requires_review: false },
  });
  const api = (body: unknown) => vi.fn(async () => reply(200, { venue_booking_request: {}, bookings: [body] })) as unknown as ApiRequest;

  const requested = card('requested', 'Requested');
  const moved = { ...requested, history: [...requested.history, {
    action: 'change_deadline', status: 'requested', status_label: 'Requested', actor: { id: 'val', name: 'Valerie Tan' },
    changed_at: '2026-11-02T09:00:00+08:00', note: 'Hold deadline moved from 5 Nov 2026, 10:00 SGT to 8 Nov 2026, 10:00 SGT.',
  }] };
  render(<VenueArrangements api={api(moved)} eventId={12} />);
  expect(await screen.findByText('Hold expires 8 Nov 2026, 10:00 am SGT unless Venue Staff approve it first.')).toBeTruthy();
  // AC3: the deadline change is named in the history, with who made it and the old and new times.
  const entries = within(screen.getByRole('list', { name: 'History of Harbour Hall booking' })).getAllByRole('listitem');
  expect(entries[0].querySelector('strong')?.textContent).toBe('Requested');
  expect(entries[1].querySelector('strong')?.textContent).toBe('Hold deadline changed');
  expect(entries[1].textContent).toContain('Valerie Tan');
  expect(entries[1].textContent).toContain('Hold deadline moved from 5 Nov 2026, 10:00 SGT to 8 Nov 2026, 10:00 SGT.');
  cleanup();

  render(<VenueArrangements api={api(card('expired', 'Expired'))} eventId={12} />);
  expect(await screen.findByText('The hold expired on 8 Nov 2026, 10:00 am SGT. Its time is released; request the venue again if it is still needed.')).toBeTruthy();
  expect(screen.getByText('Expired')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Withdraw request' })).toBeNull();
});

// QA-SPL-133-095 | AC2 | BB
it('[QA-SPL-133-095] the pending list shows when each hold expires', async () => {
  const item = {
    id: 41, event: { id: 12, name: 'Coastal Forum' }, venue: { id: 1, name: 'Harbour Hall' }, date: '2026-11-20',
    event_slots: ['PM'], timing: null, setup: null, turnaround: null, layout: 'theatre', expected_attendance: 150,
    required_facilities: [], requested_by: { id: 'casey', name: 'Casey Lim' }, requested_at: '2026-11-01T10:00:00+08:00',
    expires_at: DEADLINE, requires_review: false,
  };
  const request = vi.fn(async () => reply(200, { requests: [item], count: 1 })) as unknown as ApiRequest;
  render(<PendingBookingRequests accessToken="t" request={request} onOpen={vi.fn()} />);

  expect(await screen.findByText('Hold expires 8 Nov 2026, 10:00 am')).toBeTruthy();
});
