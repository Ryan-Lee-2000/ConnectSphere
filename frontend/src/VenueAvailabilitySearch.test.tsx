import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
afterEach(cleanup);

it('[TC-SPL-71-01] sends the selected Singapore date and slots, then shows result facts', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [{ id: 1, name: 'Atlas Hall', location: 'City Campus', maximum_layout_capacity: 180, matching_layouts: [{ layout: 'theatre', capacity: 180 }] }] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM', 'PM']} expectedAttendance={120} preferredRoomLayout="theatre" request={request} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('Atlas Hall')).toBeTruthy();
  expect(screen.getByText('City Campus')).toBeTruthy(); expect(screen.getByText('Fits 120 guests')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&slot=PM&expected_attendance=120&preferred_room_layout=Theatre&required_facility=&accessibility_need=&location_preference=');
  fireEvent.click(screen.getByRole('button', { name: /Atlas Hall/ }));
  expect(await screen.findByRole('heading', { name: 'Atlas Hall is available' })).toBeTruthy();
  expect(screen.getByText('Timing and capacity confirmed')).toBeTruthy();
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

it('allows a chosen room layout to be changed or cleared back to any supported layout', () => {
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM']} expectedAttendance={120} preferredRoomLayout="theatre" request={vi.fn()} />);

  fireEvent.change(screen.getByLabelText('Room layout'), { target: { value: 'Classroom' } });
  expect((screen.getByLabelText('Room layout') as HTMLSelectElement).value).toBe('Classroom');
  fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
  expect((screen.getByLabelText('Room layout') as HTMLSelectElement).value).toBe('');
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
