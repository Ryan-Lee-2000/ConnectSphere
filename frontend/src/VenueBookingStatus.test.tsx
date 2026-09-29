import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { VenueBookingPanel } from './VenueBookingWithdrawal';
afterEach(cleanup);

const BOOKING = {
  id: 41, event_request_id: 12, venue: { id: 1, name: 'Harbour Hall' }, date: '2026-10-14', event_slots: ['PM'],
  setup: { date: '2026-10-14', slot: 'AM' }, turnaround: { date: '2026-10-14', slot: 'NIGHT' }, layout: 'theatre',
  expected_attendance: 150, status: 'withdrawn', requested_by: { id: 'casey', name: 'Casey Lim' },
  requested_at: '2026-09-27T21:15:00+08:00', requires_review: false, review_trigger_block_id: null, review_marked_at: null,
  withdrawn_by: { id: 'casey', name: 'Casey Lim' }, withdrawn_at: '2026-09-28T10:15:00+08:00',
};
const casey = { id: 'casey', name: 'Casey Lim' };
const valerie = { id: 'valerie', name: 'Valerie Tan' };
const STATUS = {
  venue_booking_request: BOOKING,
  current_status: { status: 'withdrawn', label: 'Withdrawn' },
  history: [
    { action: 'request', status: 'requested', status_label: 'Requested', actor: casey, changed_at: '2026-09-27T21:15:00+08:00', note: null },
    { action: 'withdraw', status: 'withdrawn', status_label: 'Withdrawn', actor: casey, changed_at: '2026-09-28T10:15:00+08:00', note: null },
  ],
  review: { requires_review: false, marked_at: null, trigger_block: null },
  earlier_requests: [],
};

function api(latest: object | null, status: object) {
  return vi.fn(async (path: string) => ({
    ok: true, status: 200,
    json: async () => (path.endsWith('/venue-booking-status') ? status : { booking: latest }),
  })) as unknown as ApiRequest;
}

// SPL-79 AC-3 Test-08
it('[TC-SPL-79-08] shows the current status apart from the history', async () => {
  render(<VenueBookingPanel api={api(BOOKING, STATUS)} eventId={12} />);

  const history = await screen.findByRole('list', { name: 'History' });
  const current = screen.getByText('Status:').closest('span') as HTMLElement;
  expect(current.textContent).toBe('Status: Withdrawn');
  expect(history.contains(current)).toBe(false);
  expect(within(history).getAllByRole('listitem').map(item => item.querySelector('strong')?.textContent)).toEqual(['Requested', 'Withdrawn']);
});

// SPL-79 AC-6 Test-15
it('[TC-SPL-79-15] tells the coordinator when no request exists', async () => {
  const empty = { venue_booking_request: null, current_status: null, history: [], review: null, earlier_requests: [], message: 'No venue-booking request has been made for this event yet.' };
  render(<VenueBookingPanel api={api(null, empty)} eventId={12} emptyMessage />);

  expect(await screen.findByText('No venue-booking request has been made for this event yet.')).toBeTruthy();
  expect(screen.queryByText('Status:')).toBeNull();
  expect(screen.queryByRole('list', { name: 'History' })).toBeNull();
});

// SPL-79 AC-2 Test-19
it('[TC-SPL-79-19] lists each change with who, when and any note', async () => {
  const rejected = {
    ...STATUS,
    venue_booking_request: { ...BOOKING, status: 'rejected', withdrawn_by: null, withdrawn_at: null },
    current_status: { status: 'rejected', label: 'Rejected' },
    history: [
      STATUS.history[0],
      { action: 'reject', status: 'rejected', status_label: 'Rejected', actor: valerie, changed_at: '2026-09-28T09:05:00+08:00', note: 'Stage under repair' },
    ],
  };
  render(<VenueBookingPanel api={api(rejected.venue_booking_request, rejected)} eventId={12} />);

  const items = within(await screen.findByRole('list', { name: 'History' })).getAllByRole('listitem');
  expect(items).toHaveLength(2);
  expect(items[0].textContent).toContain('Requested');
  expect(items[0].textContent).toContain('Casey Lim');
  expect(items[0].textContent).toContain('27 Sept 2026, 9:15 pm');
  expect(items[0].textContent).not.toContain('Stage under repair');
  expect(items[1].textContent).toContain('Rejected');
  expect(items[1].textContent).toContain('Valerie Tan');
  expect(items[1].textContent).toContain('28 Sept 2026, 9:05 am');
  expect(items[1].textContent).toContain('Stage under repair');
});

// SPL-79 AC-7 Test-20
it('[TC-SPL-79-20] shows the review warning and earlier requests', async () => {
  const marked = {
    ...STATUS,
    venue_booking_request: { ...BOOKING, status: 'requested', withdrawn_by: null, withdrawn_at: null },
    current_status: { status: 'requested', label: 'Requested' },
    history: [STATUS.history[0]],
    review: {
      requires_review: true, marked_at: '2026-09-27T09:00:00+08:00',
      trigger_block: { id: 7, start_date: '2026-10-14', end_date: '2026-10-14', slots: ['PM'], reason: 'Ceiling repair' },
    },
    earlier_requests: [{ id: 40, venue: { id: 2, name: 'Riverside Room' }, date: '2026-10-14', status: 'withdrawn', status_label: 'Withdrawn' }],
  };
  render(<VenueBookingPanel api={api(marked.venue_booking_request, marked)} eventId={12} />);

  const warning = await screen.findByRole('note');
  expect(warning.textContent).toContain('Marked for review');
  expect(warning.textContent).toContain('Ceiling repair');
  expect(warning.textContent).toContain('14 Oct 2026');
  expect(warning.textContent).toContain('PM');
  expect(warning.textContent).toContain('27 Sept 2026, 9:00 am');
  const earlier = screen.getByRole('list', { name: 'Earlier requests' });
  expect(earlier.textContent).toContain('Riverside Room');
  expect(earlier.textContent).toContain('Withdrawn');
});
