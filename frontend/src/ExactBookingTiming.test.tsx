import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
import { VenueBookingRequest } from './VenueBookingRequest';
import type { ApiRequest } from './api';

afterEach(cleanup);
const timing = { event: { start: '2026-10-14T10:00:00+08:00', end: '2026-10-14T12:00:00+08:00' }, occupied: { start: '2026-10-14T09:30:00+08:00', end: '2026-10-14T12:45:00+08:00' }, setup_minutes: 30, turnaround_minutes: 45, venue_revision: 4 };
it('[TC-SPL-137-01] previews and submits reviewed exact times and revision, retains server refusal', async () => {
  const api = vi.fn(async (_path: string, options?: RequestInit) => options?.method === 'POST'
    ? { ok: false, json: async () => ({ error: 'Venue timing changed. Search again.' }) }
    : { ok: true, json: async () => ({ venue: { layouts: [{ layout: 'theatre', capacity: 200 }] } }) }) as unknown as ApiRequest;
  render(<VenueBookingRequest api={api} eventId={12} venueId={1} venueName="Hall" expectedAttendance={150} preferredRoomLayout={null} timing={timing} onRequested={vi.fn()} />);
  await screen.findByLabelText('Booking layout');
  expect(screen.getByText(/09:30/).textContent).toContain('12:45');
  fireEvent.click(screen.getByRole('button', { name: 'Request booking' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/api/event-requests/12/venue-bookings', {
    method: 'POST', body: JSON.stringify({ venue_id: 1, layout: 'theatre', date: '2026-10-14', start_time: '10:00', end_time: '12:00', venue_revision: 4 }),
  }));
  expect((await screen.findByRole('alert')).textContent).toContain('Search again');
  expect(screen.queryByText(/Booking requested/)).toBeNull();
});

it('[TC-SPL-137-05] exact requests offer only the saved required layout', async () => {
  const api = vi.fn(async () => ({ ok: true, json: async () => ({ venue: { layouts: [{ layout: 'theatre', capacity: 200 }, { layout: 'boardroom', capacity: 150 }] } }) })) as unknown as ApiRequest;
  render(<VenueBookingRequest api={api} eventId={12} venueId={1} venueName="Hall" expectedAttendance={150} preferredRoomLayout="boardroom" timing={timing} onRequested={vi.fn()} />);
  const picker = await screen.findByLabelText('Booking layout') as HTMLSelectElement;
  expect(Array.from(picker.options).map(option => option.value)).toEqual(['boardroom']);
});

for (const matching of [false, true]) {
  it(`[TC-SPL-137-02] booking action requires search to match saved event timing: ${matching}`, async () => {
    const api = vi.fn(async (path: string) => ({ ok: true, json: async () => path.includes('venue-filter-options')
      ? { capabilities: { exact_venue_timing: true } }
      : path.includes('available-venues') ? { venues: [{ id: 1, name: 'Hall', matching_layouts: [{ layout: 'theatre', capacity: 200 }], timing, suitability: { suitable: true, checks: [{ key: 'timing', passed: true, label: 'Timing', detail: 'Available' }], timing: matching ? timing : { ...timing, event: { ...timing.event, start: '2026-10-14T11:00:00+08:00' } } } }] }
      : { venue: { layouts: [{ layout: 'theatre', capacity: 200 }] } } })) as unknown as ApiRequest;
    render(<VenueAvailabilitySearch accessToken="test" eventId={12} initialDate="2026-10-14" initialStartTime="10:00" initialEndTime="12:00" expectedAttendance={150} preferredRoomLayout={null} request={api} />);
    await screen.findByLabelText('Event start (SGT)');
    fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
    fireEvent.click(await screen.findByRole('button', { name: /Hall/ }));
    if (matching) expect(await screen.findByRole('button', { name: 'Request booking' })).toBeTruthy();
    else {
      expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();
      expect(screen.getByText(/Booking requires the saved event/)).toBeTruthy();
    }
  });
}
