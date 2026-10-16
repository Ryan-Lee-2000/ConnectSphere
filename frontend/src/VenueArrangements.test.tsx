import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { VenueArrangements } from './VenueArrangements';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
import { VenueBookingRequest } from './VenueBookingRequest';

// SPL-131 QA cases for the coordinator's view of several venue bookings (QA-SPL-131).
afterEach(cleanup);

const CASEY = { id: 'casey', name: 'Casey Lim' };
const STAFF = { id: 'valerie', name: 'Valerie Tan' };
const entry = (action: string, status: string, label: string, actor = CASEY, note: string | null = null) => ({
  action, status, status_label: label, actor, changed_at: '2026-10-01T10:00:00+08:00', note,
});
const booking = (id: number, venue: string, status: string, attendees: number, layout: string, facilities: string[]) => ({
  id, event_request_id: 12, venue: { id, name: venue }, date: '2026-10-14', event_slots: ['PM'], setup: null, turnaround: null,
  layout, expected_attendance: attendees, status, required_facilities: facilities, review_reasons: [], timing: null,
});
const HALL = {
  booking: booking(41, 'Harbour Hall', 'approved', 150, 'theatre', ['Projector']),
  current_status: { status: 'approved', label: 'Approved' },
  history: [entry('request', 'requested', 'Requested'), entry('approve', 'approved', 'Approved', STAFF)],
  review: { requires_review: false },
};
const ROOM = {
  booking: booking(42, 'Breakout Room', 'requested', 20, 'classroom', []),
  current_status: { status: 'requested', label: 'Requested' },
  history: [entry('request', 'requested', 'Requested')],
  review: { requires_review: false },
};

function statusApi(bookings: unknown[], cancelResponse: { ok: boolean; body: unknown } = { ok: true, body: {} }) {
  return vi.fn(async (path: string, _options?: RequestInit) => {
    if (path.endsWith('/cancel')) return { ok: cancelResponse.ok, status: cancelResponse.ok ? 200 : 409, json: async () => cancelResponse.body } as Response;
    return { ok: true, json: async () => bookings.length ? { venue_booking_request: {}, bookings } : { venue_booking_request: null } } as Response;
  });
}

// TC-SPL-131-44 (BB) AC8: every booking with its venue, attendee count, status and own history
it('[TC-SPL-131-44] lists every venue booking with its own details and history', async () => {
  render(<VenueArrangements api={statusApi([HALL, ROOM]) as unknown as ApiRequest} eventId={12} eventStatus="planning" />);

  const list = await screen.findByRole('list', { name: 'Venue bookings' });
  const items = within(list).getAllByRole('listitem').filter(item => item.parentElement === list);
  expect(items).toHaveLength(2);
  expect(items[0].textContent).toContain('Harbour Hall');
  expect(items[0].textContent).toContain('150 attendees · Facilities: Projector');
  expect(items[0].textContent).toContain('Status: Approved');
  expect(within(screen.getByRole('list', { name: 'History of Harbour Hall booking' })).getAllByRole('listitem')).toHaveLength(2);
  expect(items[1].textContent).toContain('Breakout Room');
  expect(items[1].textContent).toContain('20 attendees');
  expect(items[1].textContent).toContain('Status: Requested');
  expect(within(screen.getByRole('list', { name: 'History of Breakout Room booking' })).getAllByRole('listitem')).toHaveLength(1);
  expect(screen.getByText('Venue bookings · 2')).toBeTruthy();
});

// TC-SPL-131-44 (BB) AC7: cancelling needs a non-blank reason and is two-step
it('[TC-SPL-131-44] cancels one approved booking only after a reason is given', async () => {
  const api = statusApi([HALL, ROOM]);
  render(<VenueArrangements api={api as unknown as ApiRequest} eventId={12} eventStatus="planning" />);

  fireEvent.click(await screen.findByRole('button', { name: 'Cancel booking' }));
  const form = screen.getByRole('form', { name: 'Cancel Harbour Hall booking' });
  fireEvent.change(within(form).getByLabelText('Cancellation reason'), { target: { value: '   ' } });
  fireEvent.submit(form);
  expect((await screen.findByRole('alert')).textContent).toBe('Give a reason for cancelling this venue booking.');
  expect(api.mock.calls.some(([path]) => String(path).endsWith('/cancel'))).toBe(false);

  fireEvent.change(within(form).getByLabelText('Cancellation reason'), { target: { value: ' Plenary moved online. ' } });
  fireEvent.click(within(form).getByRole('button', { name: 'Confirm cancellation' }));

  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/event-requests/12/venue-bookings/41/cancel', {
    method: 'POST', body: JSON.stringify({ reason: 'Plenary moved online.' }),
  }));
  expect((await screen.findByRole('status')).textContent).toContain("the event's other venues are unchanged");
  // The list is read again from the server after the change.
  await waitFor(() => expect(api.mock.calls.filter(([path]) => String(path).endsWith('venue-booking-status'))).toHaveLength(2));
});

// TC-SPL-131-44 (BB) AC7: a refusal is shown and the form keeps the reason
it('[TC-SPL-131-44] shows the server refusal and keeps the reason', async () => {
  const api = statusApi([HALL], { ok: false, body: { error: 'Only an Approved venue booking can be cancelled.' } });
  render(<VenueArrangements api={api as unknown as ApiRequest} eventId={12} eventStatus="planning" />);

  fireEvent.click(await screen.findByRole('button', { name: 'Cancel booking' }));
  fireEvent.change(screen.getByLabelText('Cancellation reason'), { target: { value: 'Moved.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm cancellation' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Only an Approved venue booking can be cancelled.');
  expect((screen.getByLabelText('Cancellation reason') as HTMLTextAreaElement).value).toBe('Moved.');
  fireEvent.click(screen.getByRole('button', { name: 'Keep booking' }));
  expect(screen.queryByLabelText('Cancellation reason')).toBeNull();
});

// TC-SPL-131-51 (BB) AC9: an event with no booking says so explicitly
it('[TC-SPL-131-51] states that no venue booking has been requested yet', async () => {
  render(<VenueArrangements api={statusApi([]) as unknown as ApiRequest} eventId={12} eventStatus="planning" emptyMessage />);

  expect(await screen.findByText('No venue-booking request has been made for this event yet.')).toBeTruthy();
});

// TC-SPL-131-56 (BB) AC10: no cancel action outside Planning; withdrawal stays (SPL-78, Q60)
it('[TC-SPL-131-56] offers no cancellation once the event has left Planning', async () => {
  render(<VenueArrangements api={statusApi([HALL, ROOM]) as unknown as ApiRequest} eventId={12} eventStatus="confirmed" />);

  await screen.findByRole('list', { name: 'Venue bookings' });
  expect(screen.queryByRole('button', { name: 'Cancel booking' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Withdraw request' })).toBeTruthy();
});

const VENUE = { venue: { layouts: [{ layout: 'theatre', capacity: 200 }, { layout: 'classroom', capacity: 30 }], facilities: ['Projector', 'PA system'] } };

// TC-SPL-131-45 (BB) AC2/AC3: the booking's own attendee count and facilities
it('[TC-SPL-131-45] requests a breakout with its own attendee count and facilities', async () => {
  const api = vi.fn(async (_path: string, options?: RequestInit) => options?.method === 'POST'
    ? { ok: true, json: async () => ({ booking: booking(43, 'Breakout Room', 'requested', 20, 'classroom', []) }) }
    : { ok: true, json: async () => VENUE }) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
  render(<VenueBookingRequest api={api} eventId={12} venueId={3} venueName="Breakout Room" expectedAttendance={150} preferredRoomLayout="theatre" attendeeCount={20} requiredFacilities={['Projector']} onRequested={vi.fn()} />);

  const picker = await screen.findByLabelText('Booking layout') as HTMLSelectElement;
  expect((screen.getByLabelText('Attendees in this venue') as HTMLInputElement).value).toBe('20');
  expect(Array.from(picker.options).map(option => option.value)).toEqual(['theatre', 'classroom']);
  fireEvent.change(picker, { target: { value: 'classroom' } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Projector' }));
  fireEvent.click(screen.getByRole('button', { name: 'Request booking' }));

  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/event-requests/12/venue-bookings', {
    method: 'POST', body: JSON.stringify({ venue_id: 3, layout: 'classroom', attendee_count: 20, required_facilities: [] }),
  }));
});

// TC-SPL-131-45 (BB) AC2 boundary: never more than the event's attendance; layouts follow the count
it('[TC-SPL-131-45] keeps the attendee count within the event and offers fitting layouts', async () => {
  const api = vi.fn(async () => ({ ok: true, json: async () => VENUE })) as unknown as ApiRequest;
  render(<VenueBookingRequest api={api} eventId={12} venueId={3} venueName="Breakout Room" expectedAttendance={150} preferredRoomLayout={null} onRequested={vi.fn()} />);

  const picker = await screen.findByLabelText('Booking layout') as HTMLSelectElement;
  expect(Array.from(picker.options).map(option => option.value)).toEqual(['theatre']);
  fireEvent.change(screen.getByLabelText('Attendees in this venue'), { target: { value: '151' } });
  expect(screen.getByText('Enter between 1 and 150 attendees for this venue.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();
  fireEvent.change(screen.getByLabelText('Attendees in this venue'), { target: { value: '0' } });
  expect(screen.getByText('Enter between 1 and 150 attendees for this venue.')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Attendees in this venue'), { target: { value: '30' } });
  expect(Array.from((screen.getByLabelText('Booking layout') as HTMLSelectElement).options).map(option => option.value)).toEqual(['theatre', 'classroom']);
});

// TC-SPL-131-57 (BB) AC3: a search for part of the event can be requested despite the whole-event capacity check
it('[TC-SPL-131-57] treats a search for fewer attendees as one part of the event', async () => {
  const unsuitableForAll = { suitable: false, checks: [
    { key: 'timing', label: 'Timing and preparation', passed: true, detail: 'Available.' },
    { key: 'layout_capacity', label: 'Layout and capacity', passed: false, detail: 'No supported layout has capacity for 150 guests.' },
    { key: 'accessibility', label: 'Accessibility needs', passed: true, detail: 'Met.' },
  ] };
  const api = vi.fn(async (path: string) => ({ ok: true, json: async () => path.includes('available-venues')
    ? { venues: [{ id: 3, name: 'Breakout Room', location: 'Marina', maximum_layout_capacity: 30, matching_layouts: [{ layout: 'classroom', capacity: 30 }], suitability: unsuitableForAll }] }
    : path.startsWith('/api/venues/') ? VENUE : {} })) as unknown as ApiRequest;
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-14" initialSlots={['PM']} expectedAttendance={150} preferredRoomLayout={null} request={api} />);

  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  fireEvent.click(await screen.findByRole('button', { name: /Breakout Room/ }));
  await screen.findByRole('heading', { name: /Breakout Room/ });
  expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();

  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '20' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  fireEvent.click(await screen.findByRole('button', { name: /Breakout Room/ }));
  expect(await screen.findByRole('button', { name: 'Request booking' })).toBeTruthy();
  expect((screen.getByLabelText('Attendees in this venue') as HTMLInputElement).value).toBe('20');
});

// TC-SPL-131-62 (BB) AC2/AC3 (review, dannywthefatty): a full-attendance booking may use its own
// layout and facilities; the event's saved values are only the default.
it('[TC-SPL-131-62] requests a full-attendance booking with its own layout and no facilities', async () => {
  const savedEventChecks = { suitable: false, checks: [
    { key: 'timing', label: 'Timing and preparation', passed: true, detail: 'Available.' },
    { key: 'layout_capacity', label: 'Layout and capacity', passed: false, detail: 'The requested Theatre layout is not supported by this venue.' },
    { key: 'facilities', label: 'Required facilities', passed: false, detail: 'Missing required facilities: Projector.' },
    { key: 'accessibility', label: 'Accessibility needs', passed: true, detail: 'Met.' },
  ] };
  const api = vi.fn(async (path: string, options?: RequestInit) => ({ ok: true, json: async () => options?.method === 'POST'
    ? { booking: booking(44, 'Seminar Hall', 'requested', 150, 'classroom', []) }
    : path.includes('available-venues')
      ? { venues: [{ id: 5, name: 'Seminar Hall', location: 'Marina', maximum_layout_capacity: 150, matching_layouts: [{ layout: 'classroom', capacity: 150 }], suitability: savedEventChecks }] }
      : path.startsWith('/api/venues/') ? { venue: { layouts: [{ layout: 'classroom', capacity: 150 }], facilities: [] } }
        : path.includes('venue-filter-options') ? { filter_options: { facilities: ['Projector'], accessibility_needs: [], locations: [] } } : {} })) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-14" initialSlots={['PM']} expectedAttendance={150} preferredRoomLayout="Theatre" requiredFacilities={['Projector']} request={api} />);

  // With the event's own layout and facilities, the saved checks still decide: no request.
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  fireEvent.click(await screen.findByRole('button', { name: /Seminar Hall/ }));
  await screen.findByRole('heading', { name: /Seminar Hall/ });
  expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();

  // Propose this booking's own values: classroom, no projector, still all 150 attendees.
  fireEvent.change(screen.getByLabelText('Room layout'), { target: { value: 'Classroom' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Remove Projector' }));
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  fireEvent.click(await screen.findByRole('button', { name: /Seminar Hall/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Request booking' }));

  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/event-requests/12/venue-bookings', {
    method: 'POST', body: JSON.stringify({ venue_id: 5, layout: 'classroom', required_facilities: [] }),
  }));
});
