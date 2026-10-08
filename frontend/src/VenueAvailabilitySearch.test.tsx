import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
afterEach(cleanup);

it('[TC-SPL-71-01] sends the selected Singapore date and slots, then shows result facts', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [{ id: 1, name: 'Atlas Hall', location: 'City Campus', maximum_layout_capacity: 180, matching_layouts: [{ layout: 'theatre', capacity: 180 }], suitability: { suitable: true, checks: [{ key: 'timing', label: 'Timing and preparation', passed: true, detail: 'Available for the event date and selected slots.' }, { key: 'layout_capacity', label: 'Layout and capacity', passed: true, detail: 'Theatre supports 120 guests.' }, { key: 'facilities', label: 'Required facilities', passed: true, detail: 'All required facilities are recorded.' }] } }] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM', 'PM']} expectedAttendance={120} preferredRoomLayout="theatre" request={request} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('Atlas Hall')).toBeTruthy();
  expect(screen.getByText('City Campus')).toBeTruthy(); expect(screen.getByText('Fits 120 guests')).toBeTruthy();
  expect(screen.getByText('Suitable for this event')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&slot=PM&expected_attendance=120&preferred_room_layout=Theatre&required_facility=&accessibility_need=&location_preference=');
  fireEvent.click(screen.getByRole('button', { name: /Atlas Hall/ }));
  expect(await screen.findByRole('heading', { name: 'Atlas Hall is suitable' })).toBeTruthy();
  expect(screen.getByText('Timing and preparation')).toBeTruthy();
  expect(screen.getByText('Search filters are exploratory. This assessment uses the saved, current event requirements and creates neither a booking nor a hold.')).toBeTruthy();
  expect(screen.getByText('Theatre (180)')).toBeTruthy();
});

it('[TC-SPL-71-03] retains applied controls and shows a clear empty result', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM']} expectedAttendance={120} preferredRoomLayout={null} request={request} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('No venues are available for this search.')).toBeTruthy();
  expect((screen.getByLabelText('Singapore date') as HTMLInputElement).value).toBe('2026-10-12');
  expect((screen.getByLabelText('AM · 7am–12pm') as HTMLInputElement).checked).toBe(true);
});

it('[TC-SPL-71-04] prevents an incomplete search before calling the API', () => {
  const request = vi.fn();
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate={null} initialSlots={[]} expectedAttendance={120} preferredRoomLayout={null} request={request} />);

  expect((screen.getByRole('button', { name: 'Search venues' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText('Choose a date, at least one slot and a positive expected attendance to search.')).toBeTruthy();
  expect(request).not.toHaveBeenCalledWith(expect.stringContaining('available-venues'));
});

it('[TC-SPL-72-07] lets a coordinator adjust the prefixed capacity and layout filters without editing the event', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [{ id: 2, name: 'Forum Room', location: 'Civic District', maximum_layout_capacity: 90, matching_layouts: [{ layout: 'classroom', capacity: 90 }] }] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM']} expectedAttendance={120} preferredRoomLayout="theatre" request={request} />);

  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '80' } });
  fireEvent.change(screen.getByLabelText('Room layout'), { target: { value: 'Classroom' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));

  expect(await screen.findByText('Forum Room')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&expected_attendance=80&preferred_room_layout=Classroom&required_facility=&accessibility_need=&location_preference=');
  expect(screen.getByText('Fits 80 guests')).toBeTruthy();
});

it('[TC-SPL-74-06] keeps a cleared layout empty across a parent render', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [] }) });
  const props = {
    accessToken: 'token', eventId: 12, initialDate: '2026-10-12', initialSlots: ['AM'],
    expectedAttendance: 120, preferredRoomLayout: 'theatre', requiredFacilities: ['Projector'],
    accessibilityNeeds: ['Step-free access'], locationPreference: 'Marina Centre', request,
  };
  const page = render(<VenueAvailabilitySearch {...props} />);

  fireEvent.change(screen.getByLabelText('Room layout'), { target: { value: 'Classroom' } });
  expect((screen.getByLabelText('Room layout') as HTMLSelectElement).value).toBe('Classroom');
  fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
  expect((screen.getByLabelText('Room layout') as HTMLSelectElement).value).toBe('');

  // Parent renders can supply fresh array references without changing the event snapshot.
  page.rerender(<VenueAvailabilitySearch {...props} initialSlots={[...props.initialSlots]}
    requiredFacilities={[...props.requiredFacilities]} accessibilityNeeds={[...props.accessibilityNeeds]} />);
  expect((screen.getByLabelText('Room layout') as HTMLSelectElement).value).toBe('');

  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('No venues are available for this search.')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&expected_attendance=120&preferred_room_layout=&required_facility=Projector&accessibility_need=Step-free+access&location_preference=Marina+Centre');
});

it('[TC-SPL-75-04] identifies unmet saved-event requirements in an expanded venue assessment', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [{ id: 3, name: 'Riverside Studio', location: 'Riverside', maximum_layout_capacity: 90, matching_layouts: [{ layout: 'classroom', capacity: 90 }], suitability: { suitable: false, checks: [{ key: 'timing', label: 'Timing and preparation', passed: true, detail: 'Available for the event date and selected slots.' }, { key: 'layout_capacity', label: 'Layout and capacity', passed: false, detail: 'The requested Theatre layout is not supported by this venue.' }, { key: 'facilities', label: 'Required facilities', passed: false, detail: 'Missing required facilities: Projector.' }, { key: 'accessibility', label: 'Accessibility needs', passed: true, detail: 'All required accessibility features are recorded on this venue.' }, { key: 'location', label: 'Preferred location', passed: true, detail: 'Riverside matches the event location preference.' }] } }] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM']} expectedAttendance={80} preferredRoomLayout={null} request={request} />);

  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('Does not meet current event requirements')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: /Riverside Studio/ }));
  expect(await screen.findByRole('heading', { name: 'Riverside Studio does not meet every event requirement' })).toBeTruthy();
  expect(screen.getByText('Missing required facilities: Projector.')).toBeTruthy();
});

it('[TC-SPL-73-05] applies editable facility, accessibility and location filters without changing the event', async () => {
  const request = vi.fn(async (path: string) => ({ ok: true, json: async () => path.includes('venue-filter-options') ? {
    filter_options: { facilities: ['Projector', 'PA system'], accessibility_needs: ['Step-free access', 'Hearing loop'], locations: ['Level 3, Marina Centre', 'Rooftop, Marina Centre'] },
  } : { venues: [] } })) as unknown as ApiRequest;
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM']} expectedAttendance={120} preferredRoomLayout={null} requiredFacilities={['Projector']} accessibilityNeeds={['Step-free access']} locationPreference="Marina" request={request} />);

  fireEvent.change(await screen.findByLabelText('Add Required facilities'), { target: { value: 'PA system' } });
  fireEvent.click(screen.getByRole('button', { name: 'Remove Step-free access' }));
  fireEvent.change(screen.getByLabelText('Preferred venue location'), { target: { value: 'Rooftop, Marina Centre' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));

  expect(await screen.findByText('No venues are available for this search.')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&expected_attendance=120&preferred_room_layout=&required_facility=Projector&required_facility=PA+system&accessibility_need=&location_preference=Rooftop%2C+Marina+Centre');
});


it('[TC-SPL-129-02] searches quarter-hour Singapore times and displays both intervals', async () => {
  const request = vi.fn(async (path: string) => ({ ok: true, json: async () => path.includes('venue-filter-options') ? { filter_options: {}, capabilities: { exact_venue_timing: true } } : path.includes('available-venues') ? { venues: [{ id: 2, name: 'Exact Hall', location: 'Singapore', matching_layouts: [{ layout: 'theatre', capacity: 100 }], timing: { event: { start: '2026-10-12T10:00:00+08:00', end: '2026-10-12T12:00:00+08:00' }, occupied: { start: '2026-10-12T09:30:00+08:00', end: '2026-10-12T12:45:00+08:00' }, setup_minutes: 30, turnaround_minutes: 45 } }] } : { bookings: [] } } as Response));
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialStartTime="10:00" initialEndTime="12:00" expectedAttendance={80} preferredRoomLayout={null} request={request} />);
  expect((await screen.findByLabelText('Event start (SGT)') as HTMLInputElement).value).toBe('10:00');
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('Exact Hall')).toBeTruthy();
  expect(request).toHaveBeenCalledWith(expect.stringContaining('start_time=10%3A00&end_time=12%3A00'));
  expect(screen.getByText(/Occupied:.*09:30.*12:45/)).toBeTruthy();
  expect(screen.getByText('2026-10-12 · 10:00–12:00 SGT')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();
});
