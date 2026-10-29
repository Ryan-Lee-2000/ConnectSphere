import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { AssignedEvents } from './AssignedEvents';
import { VenueArrangements } from './VenueArrangements';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
import { VenueBookingReview } from './VenueBookingReview';

// SPL-132 QA cases for the replacement-venue screens (QA-SPL-132). Backend cases are in
// backend/tests/test_qa_spl132.py.
afterEach(cleanup);

const EVENT = {
  id: 12, name: 'Coastal Forum', status: 'planning', status_label: 'In planning',
  proposed_date: '2030-06-15', mapped_slots: ['AM'], start_time: '09:00', end_time: '12:00', expected_attendance: 300,
  preferred_room_layout: 'banquet', required_facilities: ['PA system'],
  accessibility_needs: ['Step-free access'], location_preference: 'Marina Centre',
};
const LINK = (id: number, name: string, status: string) => ({ id, venue: { id, name }, status });
const DISRUPTED = {
  id: 41, event_request_id: 12, venue: { id: 1, name: 'QA hall' }, date: '2030-06-15', event_slots: [],
  timing: {
    event: { start: '2030-06-15T10:00:00+08:00', end: '2030-06-15T11:00:00+08:00' },
    occupied: { start: '2030-06-15T10:00:00+08:00', end: '2030-06-15T11:00:00+08:00' },
    setup_minutes: 0, turnaround_minutes: 0,
  },
  setup: null, turnaround: null, layout: 'theatre', expected_attendance: 150, status: 'approved',
  required_facilities: ['Projector'], review_reasons: [], requires_review: true,
  replaces: null, replacements: [], replaceable: true,
};

function reply(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function searchPage(booking: unknown, bookingStatus = 200) {
  const request = vi.fn(async (path: string) => {
    if (path === '/api/event-requests/assigned/12') return reply(200, { event: EVENT });
    if (path === '/api/event-requests/12/venue-bookings/41') return reply(bookingStatus, booking);
    if (path.includes('venue-filter-options')) {
      return reply(200, { filter_options: { facilities: ['Projector', 'PA system'], accessibility_needs: ['Step-free access'], locations: ['Marina Centre'] }, capabilities: { exact_venue_timing: true } });
    }
    return reply(200, { venues: [], bookings: [] });
  });
  render(<AssignedEvents accessToken="token" eventId={12} request={request as unknown as ApiRequest} onNavigate={vi.fn()} view="venue-search" replacingBookingId={41} />);
  return request;
}

function arrangement(booking: object) {
  return { booking: { ...DISRUPTED, ...booking }, current_status: { status: 'approved', label: 'Approved' }, history: [], review: { requires_review: true } };
}

function arrangementsApi(items: unknown[]) {
  return vi.fn(async () => reply(200, { venue_booking_request: {}, bookings: items })) as unknown as ApiRequest;
}

// QA-SPL-132-120 | AC4 | BB
it('[QA-SPL-132-120] seeds the replacement search from the affected booking, not the event', async () => {
  searchPage({ booking: DISRUPTED });

  expect(await screen.findByRole('note')).toHaveProperty('textContent', expect.stringContaining('Finding a replacement for the QA hall booking of Coastal Forum'));
  expect(screen.getByLabelText('Singapore date')).toHaveProperty('value', '2030-06-15');
  expect(screen.getByLabelText('Expected attendance')).toHaveProperty('value', '150');
  expect(screen.getByLabelText('Room layout')).toHaveProperty('value', 'Theatre');
  expect(screen.getByRole('button', { name: 'Remove Projector' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Remove PA system' })).toBeNull();
  await waitFor(() => expect(screen.getByLabelText('Event start (SGT)')).toHaveProperty('value', '10:00'));
  expect(screen.getByLabelText('Event end (SGT)')).toHaveProperty('value', '11:00');
});

// QA-SPL-132-121 | AC4 | BB negative
it('[QA-SPL-132-121] refuses to search for a booking that no longer needs a replacement', async () => {
  const request = searchPage({ booking: { ...DISRUPTED, replaceable: false } });

  expect((await screen.findByRole('alert')).textContent).toBe('The QA hall booking does not need a replacement now: its venue is available again, it is no longer active, or a replacement is already waiting for Venue Staff.');
  expect(screen.queryByLabelText('Singapore date')).toBeNull();
  expect(request.mock.calls.some(([path]) => String(path).includes('available-venues'))).toBe(false);
});

// QA-SPL-132-122 | AC4 | BB negative
it('[QA-SPL-132-122] says so when the booking to replace cannot be read', async () => {
  searchPage({ error: 'Venue-booking request not found.' }, 404);

  expect((await screen.findByRole('alert')).textContent).toBe('The booking to replace could not be loaded.');
  expect(screen.queryByLabelText('Singapore date')).toBeNull();
});

// QA-SPL-132-123 | AC4 | BB boundary
it('[QA-SPL-132-123] seeds a booking that ends at midnight as 24:00', async () => {
  searchPage({ booking: { ...DISRUPTED, timing: { event: { start: '2030-06-15T22:00:00+08:00', end: '2030-06-16T00:00:00+08:00' } } } });

  await waitFor(() => expect(screen.getByLabelText('Event start (SGT)')).toHaveProperty('value', '22:00'));
  expect(screen.getByLabelText('End at midnight (24:00)')).toHaveProperty('checked', true);
});

// QA-SPL-132-124 | AC4 | BB
it('[QA-SPL-132-124] an ordinary venue search still starts from the event', async () => {
  const request = vi.fn(async (path: string) => path === '/api/event-requests/assigned/12'
    ? reply(200, { event: EVENT })
    : reply(200, { filter_options: { facilities: [], accessibility_needs: [], locations: [] }, venues: [] }));
  render(<AssignedEvents accessToken="token" eventId={12} request={request as unknown as ApiRequest} onNavigate={vi.fn()} view="venue-search" />);

  expect(await screen.findByLabelText('Expected attendance')).toHaveProperty('value', '300');
  expect(screen.queryByRole('note')).toBeNull();
  expect(request.mock.calls.some(([path]) => String(path).endsWith('/venue-bookings/41'))).toBe(false);
});

// QA-SPL-132-125 | AC4 | BB
it('[QA-SPL-132-125] offers a replacement search only for a replaceable booking in Planning', async () => {
  const onFindReplacement = vi.fn();
  const items = [arrangement({}), arrangement({ id: 42, venue: { id: 2, name: 'QA sibling' }, replaceable: false })];
  render(<VenueArrangements api={arrangementsApi(items)} eventId={12} eventStatus="planning" onFindReplacement={onFindReplacement} />);

  const buttons = await screen.findAllByRole('button', { name: 'Find a replacement venue' });
  expect(buttons).toHaveLength(1);
  fireEvent.click(buttons[0]);
  expect(onFindReplacement).toHaveBeenCalledWith(41);
});

// QA-SPL-132-126 | AC10 | BB negative
it('[QA-SPL-132-126] offers no replacement search outside Planning', async () => {
  render(<VenueArrangements api={arrangementsApi([arrangement({})])} eventId={12} eventStatus="confirmed" onFindReplacement={vi.fn()} />);

  await screen.findByRole('list', { name: 'Venue bookings' });
  expect(screen.queryByRole('button', { name: 'Find a replacement venue' })).toBeNull();
});

// QA-SPL-132-127 | AC5 AC6 AC7 | BB
it('[QA-SPL-132-127] names the booking replaced and every replacement with its status', async () => {
  const original = arrangement({ replaceable: true, replacements: [LINK(43, 'QA loft', 'requested'), LINK(42, 'QA annex', 'rejected')] });
  const replacement = arrangement({ id: 43, venue: { id: 3, name: 'QA loft' }, replaceable: false, replaces: LINK(41, 'QA hall', 'approved') });
  render(<VenueArrangements api={arrangementsApi([original, replacement])} eventId={12} eventStatus="planning" />);

  const [first, second] = within(await screen.findByRole('list', { name: 'Venue bookings' })).getAllByRole('listitem')
    .filter(item => item.parentElement?.getAttribute('aria-label') === 'Venue bookings');
  expect(first.textContent).toContain('Replacement requested: QA loft (Requested).');
  expect(first.textContent).toContain('Replacement requested: QA annex (Rejected).');
  expect(second.textContent).toContain('Replacement for the QA hall booking.');
});

// QA-SPL-132-128 | AC5 | BB
it('[QA-SPL-132-128] a replacement request names the booking it replaces', async () => {
  const venue = {
    id: 5, name: 'QA annex', location: 'Marina Centre', maximum_layout_capacity: 200,
    matching_layouts: [{ layout: 'theatre', capacity: 200 }], layouts: [{ layout: 'theatre', capacity: 200 }],
    suitability: { suitable: true, checks: [{ key: 'timing', label: 'Timing and preparation', passed: true, detail: 'Met.' }] },
  };
  const request = vi.fn(async (path: string) => {
    if (path.includes('venue-filter-options')) return reply(200, { filter_options: { facilities: [], accessibility_needs: [], locations: [] } });
    if (path.includes('venue-bookings')) return reply(201, { booking: { ...DISRUPTED, id: 44, venue: { id: 5, name: 'QA annex' }, status: 'requested', replaces: LINK(41, 'QA hall', 'approved'), event_slots: ['PM'], timing: null } });
    if (path.startsWith('/api/venues/')) return reply(200, { venue });
    return reply(200, { venues: [venue] });
  });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2030-06-15" initialSlots={['PM']} expectedAttendance={150} preferredRoomLayout={null} replacesBookingId={41} request={request as unknown as ApiRequest} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  fireEvent.click(await screen.findByRole('button', { name: /QA annex/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Request replacement' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/12/venue-bookings', expect.objectContaining({ method: 'POST' })));
  const [, init] = request.mock.calls.find(([path]) => path === '/api/event-requests/12/venue-bookings') as unknown as [string, RequestInit];
  expect(JSON.parse(String(init.body))).toMatchObject({ venue_id: 5, replaces_booking_id: 41 });
  expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();
});

// QA-SPL-132-129 | AC7 | BB
it('[QA-SPL-132-129] tells Venue Staff that approving releases the replaced booking', async () => {
  const booking = {
    ...DISRUPTED, id: 44, venue: { id: 5, name: 'QA annex' }, status: 'requested', event_slots: ['PM'], timing: null,
    requested_by: { id: 'casey', name: 'Casey Lim' }, requested_at: '2030-06-01T09:00:00+08:00', replaces: LINK(41, 'QA hall', 'approved'),
  };
  const request = vi.fn(async () => reply(200, { booking, event: EVENT, review: { requires_review: false, marked_at: null, trigger_block: null } }));
  render(<VenueBookingReview accessToken="token" bookingId={44} request={request as unknown as ApiRequest} />);

  const details = await screen.findByRole('list', { name: 'Request details' });
  expect(details.textContent).toContain('Replaces');
  expect(details.textContent).toContain('QA hall booking #41 (Approved); approving releases it');
});
