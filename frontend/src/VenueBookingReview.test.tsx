import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { VenueBookingReview } from './VenueBookingReview';
afterEach(cleanup);

const BOOKING = {
  id: 41, event_request_id: 12, venue: { id: 1, name: 'Harbour Hall' }, date: '2026-10-14', event_slots: ['PM'],
  setup: { date: '2026-10-14', slot: 'AM' }, turnaround: { date: '2026-10-14', slot: 'NIGHT' }, layout: 'theatre',
  expected_attendance: 150, status: 'requested', requested_by: { id: 'casey', name: 'Casey Lim' },
  requested_at: '2026-09-27T21:15:00+08:00', requires_review: false, review_trigger_block_id: null, review_marked_at: null,
  withdrawn_by: null, withdrawn_at: null, approved_by: null, approved_at: null, approval_note: null,
  rejected_by: null, rejected_at: null, rejection_reason: null, rejection_alternative_suggestion: null,
};
// SPL-80 (CS-E10-S2 AC3) widened this payload with the event information Venue Staff need in
// order to decide. SPL-81's own cases below are unaffected: id, name and status are unchanged.
const EVENT = {
  id: 12, name: 'Coastal Forum', status: 'planning',
  organisation: { id: 3, name: 'Northstar Community Partners' },
  purpose: 'Community planning', description: 'An open forum for the redevelopment plan.',
  proposed_date: '2026-10-14', start_time: '13:00', end_time: '18:00',
  expected_attendance: 150, preferred_room_layout: 'theatre',
  required_facilities: ['Projector'], accessibility_needs: ['Step-free access'],
  facilities_notes: 'Lectern needed', location_preference: 'Marina Centre',
  venue_notes: 'Ground floor preferred',
};
const UNMARKED = { requires_review: false, marked_at: null, trigger_block: null };

function reply(status: number, body: object) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function api(review: object, approval?: Response) {
  return vi.fn(async (path: string, init?: RequestInit) => (
    init?.method === 'POST' ? approval as Response : reply(200, review)
  )) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
}

it('[TC-SPL-81-23] reviews, confirms and approves with a note', async () => {
  const approved = { ...BOOKING, status: 'approved', approved_by: { id: 'valerie', name: 'Valerie Tan' }, approved_at: '2026-09-28T10:05:00+08:00', approval_note: 'Confirmed with the hall manager' };
  const request = api(
    { booking: BOOKING, event: EVENT, review: { requires_review: true, marked_at: '2026-09-27T09:00:00+08:00', trigger_block: { id: 7, start_date: '2026-10-14', end_date: '2026-10-14', slots: ['PM'], reason: 'Ceiling repair' } } },
    reply(200, { booking: approved }),
  );
  render(<VenueBookingReview accessToken="token" bookingId={41} request={request} />);

  const details = await screen.findByRole('list', { name: 'Request details' });
  for (const text of ['Coastal Forum', 'Harbour Hall', '14 Oct 2026', 'PM', 'AM · 14 Oct 2026', 'Night · 14 Oct 2026', 'Theatre', '150', 'Casey Lim', '27 Sept 2026, 9:15 pm', 'Requested']) {
    expect(details.textContent).toContain(text);
  }
  expect(screen.getByRole('note').textContent).toContain('Ceiling repair');

  fireEvent.change(screen.getByLabelText('Approval note (optional)'), { target: { value: 'Confirmed with the hall manager' } });
  fireEvent.click(screen.getByRole('button', { name: 'Approve booking' }));
  const confirm = screen.getByRole('group', { name: 'Confirm approval' });
  fireEvent.click(within(confirm).getByRole('button', { name: 'Keep reviewing' }));
  expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);

  fireEvent.click(screen.getByRole('button', { name: 'Approve booking' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm approval' }));

  expect((await screen.findByRole('status')).textContent).toContain('Approved by Valerie Tan on 28 Sept 2026, 10:05 am');
  const [path, init] = request.mock.calls.find(([, call]) => call?.method === 'POST')!;
  expect(path).toBe('/api/venue-bookings/41/approve');
  expect(JSON.parse(String(init.body))).toEqual({ note: 'Confirmed with the hall manager' });
  expect(screen.getByRole('list', { name: 'Request details' }).textContent).toContain('Approved');
  expect(screen.queryByRole('button', { name: 'Approve booking' })).toBeNull();
});

it('[TC-SPL-81-23] offers no Approve action for a request that is not Requested', async () => {
  const withdrawn = { ...BOOKING, status: 'withdrawn' };
  render(<VenueBookingReview accessToken="token" bookingId={41} request={api({ booking: withdrawn, event: EVENT, review: UNMARKED })} />);

  expect((await screen.findByRole('list', { name: 'Request details' })).textContent).toContain('Withdrawn');
  expect(screen.queryByRole('button', { name: 'Approve booking' })).toBeNull();
  expect(screen.queryByLabelText('Approval note (optional)')).toBeNull();
});

it('[TC-SPL-81-12] shows the conflict and keeps the request Requested', async () => {
  const conflict = reply(409, { error: 'Harbour Hall is unavailable on 14 Oct 2026 during Night.', conflict: { date: '2026-10-14', slot: 'NIGHT' } });
  render(<VenueBookingReview accessToken="token" bookingId={41} request={api({ booking: BOOKING, event: EVENT, review: UNMARKED }, conflict)} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Approve booking' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm approval' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Harbour Hall is unavailable on 14 Oct 2026 during Night.');
  expect(screen.getByRole('list', { name: 'Request details' }).textContent).toContain('Requested');
  expect(screen.queryByRole('status')).toBeNull();
  expect(screen.getByRole('button', { name: 'Approve booking' })).toBeTruthy();
});

it('[TC-SPL-81-21] explains when the request cannot be found', async () => {
  render(<VenueBookingReview accessToken="token" bookingId={999} request={vi.fn(async () => reply(404, { error: 'Venue-booking request not found.' })) as unknown as ApiRequest} />);

  expect((await screen.findByRole('alert')).textContent).toBe('Venue-booking request not found.');
});

// QA-SPL-80 TC-SPL-80-17: AC3 is only met if the widened payload actually reaches the screen,
// and AC4 only if nothing attendee-facing arrives with it.
it('[TC-SPL-80-17] shows the event details needed to decide, and no registration details', async () => {
  render(<VenueBookingReview accessToken="token" bookingId={41} request={api({ booking: BOOKING, event: EVENT, review: UNMARKED })} />);

  const eventDetails = await screen.findByRole('list', { name: 'Event details' });
  for (const text of ['Northstar Community Partners', 'Community planning', '13:00–18:00', '150', 'Theatre', 'Projector', 'Step-free access', 'Lectern needed', 'Marina Centre', 'Ground floor preferred']) {
    expect(eventDetails.textContent).toContain(text);
  }
  // AC4: the server sends an allowlist, so there is nothing attendee-facing to render anywhere.
  expect(document.body.textContent).not.toContain('registration');
  expect(document.body.textContent).not.toContain('Registration');
});

// QA-SPL-82 TC-SPL-82-18/-19: Reject sits beside Approve with a required reason and an optional
// suggestion, and the outcome replaces both actions once the request is decided.
it('[TC-SPL-82-18] rejects with a reason and an optional alternative suggestion', async () => {
  const rejected = {
    ...BOOKING, status: 'rejected',
    rejected_by: { id: 'valerie', name: 'Valerie Tan' }, rejected_at: '2026-09-28T10:05:00+08:00',
    rejection_reason: 'The PA system is under repair that week.',
    rejection_alternative_suggestion: 'The Riverside Room is free the same afternoon.',
  };
  const request = api(
    { booking: BOOKING, event: EVENT, review: UNMARKED },
    reply(200, { booking: rejected }),
  );
  render(<VenueBookingReview accessToken="token" bookingId={41} request={request} />);

  expect(await screen.findByRole('button', { name: 'Approve booking' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Reject booking' }));
  const form = screen.getByRole('group', { name: 'Reject request' });
  // The reason is required: confirming is disabled until something is typed.
  expect(within(form).getByRole('button', { name: 'Confirm rejection' })).toHaveProperty('disabled', true);

  fireEvent.change(within(form).getByLabelText('Rejection reason'), { target: { value: 'The PA system is under repair that week.' } });
  fireEvent.change(within(form).getByLabelText('Alternative suggestion (optional)'), { target: { value: 'The Riverside Room is free the same afternoon.' } });
  expect(within(form).getByRole('button', { name: 'Confirm rejection' })).toHaveProperty('disabled', false);
  fireEvent.click(within(form).getByRole('button', { name: 'Confirm rejection' }));

  expect((await screen.findByRole('status')).textContent).toContain('Rejected by Valerie Tan on 28 Sept 2026, 10:05 am');
  const [path, init] = request.mock.calls.find(([, call]) => call?.method === 'POST')!;
  expect(path).toBe('/api/venue-bookings/41/reject');
  expect(JSON.parse(String(init.body))).toEqual({
    reason: 'The PA system is under repair that week.',
    alternative_suggestion: 'The Riverside Room is free the same afternoon.',
  });
  expect(screen.getByRole('status').textContent).toContain('Reason: The PA system is under repair that week.');
  expect(screen.getByRole('status').textContent).toContain('Suggested alternative: The Riverside Room is free the same afternoon.');
  // A decided request offers neither action any more.
  expect(screen.queryByRole('button', { name: 'Approve booking' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Reject booking' })).toBeNull();
});

it('[TC-SPL-82-19] cancelling the reject form returns to both actions without submitting', async () => {
  const request = api({ booking: BOOKING, event: EVENT, review: UNMARKED });
  render(<VenueBookingReview accessToken="token" bookingId={41} request={request} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Reject booking' }));
  fireEvent.change(screen.getByLabelText('Rejection reason'), { target: { value: 'Not needed' } });
  fireEvent.click(screen.getByRole('button', { name: 'Keep reviewing' }));

  expect(screen.getByRole('button', { name: 'Approve booking' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Reject booking' })).toBeTruthy();
  expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
});
