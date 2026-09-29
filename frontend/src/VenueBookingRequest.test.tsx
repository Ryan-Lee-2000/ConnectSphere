import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
afterEach(cleanup);

const passed = (label: string) => ({ key: label, label, passed: true, detail: `${label} met.` });
const HARBOUR_HALL = {
  id: 1, name: 'Harbour Hall', location: 'Level 3, Marina Centre', maximum_layout_capacity: 200,
  matching_layouts: [{ layout: 'theatre', capacity: 200 }, { layout: 'boardroom', capacity: 150 }],
  layouts: [{ layout: 'theatre', capacity: 200 }, { layout: 'classroom', capacity: 120 }, { layout: 'boardroom', capacity: 150 }],
  suitability: { suitable: true, checks: ['Timing and preparation', 'Layout and capacity', 'Required facilities'].map(passed) },
};
const RIVERSIDE_ROOM = {
  id: 2, name: 'Riverside Room', location: 'Level 1, Marina Centre', maximum_layout_capacity: 200,
  matching_layouts: [{ layout: 'theatre', capacity: 200 }], layouts: [{ layout: 'theatre', capacity: 200 }],
  suitability: { suitable: false, checks: [passed('Timing and preparation'), { key: 'facilities', label: 'Required facilities', passed: false, detail: 'Missing required facilities: Projector.' }] },
};
const REQUESTED = {
  id: 41, event_request_id: 12, venue: { id: 1, name: 'Harbour Hall' }, date: '2026-10-14', event_slots: ['PM'],
  setup: { date: '2026-10-14', slot: 'AM' }, turnaround: { date: '2026-10-14', slot: 'NIGHT' }, layout: 'boardroom',
  expected_attendance: 150, status: 'requested', requested_by: { id: 'casey', name: 'Casey Lim' },
  requested_at: '2026-09-27T21:15:00+08:00', requires_review: false, review_trigger_block_id: null, review_marked_at: null,
};

function api(booking: { status: number; body: unknown }, venues = [HARBOUR_HALL, RIVERSIDE_ROOM]) {
  return vi.fn(async (path: string) => {
    if (path.includes('venue-filter-options')) return { ok: true, json: async () => ({ filter_options: { facilities: [], accessibility_needs: [], locations: [] } }) };
    if (path.includes('venue-bookings')) return { ok: booking.status < 300, status: booking.status, json: async () => booking.body };
    if (path.startsWith('/api/venues/')) {
      const venue = venues.find(candidate => path === `/api/venues/${candidate.id}`);
      return { ok: Boolean(venue), json: async () => ({ venue }) };
    }
    return { ok: true, json: async () => ({ venues }) };
  }) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
}

async function openVenue(name: string, request: ApiRequest) {
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-14" initialSlots={['PM']} expectedAttendance={150} preferredRoomLayout={null} request={request} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(name) }));
  return screen.findByRole('heading', { name: new RegExp(`^${name}`) });
}

// SPL-77 AC-2,6 Test-23
it('[TC-SPL-77-23] offers Request booking only for suitable venues with fitting layouts', async () => {
  const request = api({ status: 201, body: { booking: REQUESTED } });

  await openVenue('Riverside Room', request);
  expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: /Harbour Hall/ }));
  await screen.findByRole('heading', { name: 'Harbour Hall is suitable' });
  const picker = await screen.findByLabelText('Booking layout') as HTMLSelectElement;
  expect(Array.from(picker.options).map(option => option.textContent)).toEqual(['Theatre — 200 guests', 'Boardroom — 150 guests']);

  fireEvent.change(picker, { target: { value: 'boardroom' } });
  fireEvent.click(screen.getByRole('button', { name: 'Request booking' }));

  await screen.findByText(/Booking requested/);
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/venue-bookings', {
    method: 'POST', body: JSON.stringify({ venue_id: 1, layout: 'boardroom' }),
  });
});

// SPL-77 AC-5,6 Test-24
it('[TC-SPL-77-24] announces the Requested booking with its derived preparation slots', async () => {
  const request = api({ status: 201, body: { booking: REQUESTED } });
  await openVenue('Harbour Hall', request);

  fireEvent.click(await screen.findByRole('button', { name: 'Request booking' }));

  const notice = await screen.findByText(/Booking requested/);
  const region = notice.closest('[role="status"]') as HTMLElement;
  expect(region).toBeTruthy();
  expect(region.textContent).toContain('Harbour Hall');
  expect(region.textContent).toContain('Requested');
  expect(region.textContent).toContain('14 Oct 2026');
  expect(within(region).getByText('Event').nextSibling?.textContent).toBe('PM · 14 Oct 2026');
  expect(within(region).getByText('Setup').nextSibling?.textContent).toBe('AM · 14 Oct 2026');
  expect(within(region).getByText('Turnaround').nextSibling?.textContent).toBe('Night · 14 Oct 2026');
  // The search is refreshed, so the venue's held slots are re-read from the server.
  expect(request.mock.calls.filter(([path]) => String(path).includes('available-venues'))).toHaveLength(2);
});

// SPL-77 AC-5,6 Test-24
it('[TC-SPL-77-24] shows the server refusal verbatim and never a confirmation', async () => {
  const request = api({ status: 409, body: { error: 'Venue is unavailable on 2026-10-14 during AM.', conflict: { date: '2026-10-14', slot: 'AM' } } });
  await openVenue('Harbour Hall', request);

  fireEvent.click(await screen.findByRole('button', { name: 'Request booking' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Venue is unavailable on 2026-10-14 during AM.');
  expect(screen.queryByText(/Booking requested/)).toBeNull();
  expect(request.mock.calls.filter(([path]) => String(path).includes('available-venues'))).toHaveLength(1);
});
