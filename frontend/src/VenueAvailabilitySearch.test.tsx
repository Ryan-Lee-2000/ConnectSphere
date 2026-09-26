import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
afterEach(cleanup);

it('[TC-SPL-71-01] sends the selected Singapore date and slots, then shows result facts', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [{ id: 1, name: 'Atlas Hall', location: 'City Campus', maximum_layout_capacity: 180, matching_layouts: [{ layout: 'theatre', capacity: 180 }] }] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM', 'PM']} expectedAttendance={120} preferredRoomLayout="theatre" request={request} />);
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('Atlas Hall')).toBeTruthy();
  expect(screen.getByText('City Campus')).toBeTruthy(); expect(screen.getByText('Fits 120 guests')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&slot=PM&expected_attendance=120&preferred_room_layout=Theatre');
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
  expect(request).not.toHaveBeenCalled();
});

it('[TC-SPL-72-07] lets a coordinator adjust the prefixed capacity and layout filters without editing the event', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [{ id: 2, name: 'Forum Room', location: 'Civic District', maximum_layout_capacity: 90, matching_layouts: [{ layout: 'classroom', capacity: 90 }] }] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM']} expectedAttendance={120} preferredRoomLayout="theatre" request={request} />);

  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '80' } });
  fireEvent.change(screen.getByLabelText('Room layout'), { target: { value: 'Classroom' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));

  expect(await screen.findByText('Forum Room')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&expected_attendance=80&preferred_room_layout=Classroom');
  expect(screen.getByText('Fits 80 guests')).toBeTruthy();
});

it('allows a chosen room layout to be changed or cleared back to any supported layout', () => {
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM']} expectedAttendance={120} preferredRoomLayout="theatre" request={vi.fn()} />);

  fireEvent.change(screen.getByLabelText('Room layout'), { target: { value: 'Classroom' } });
  expect((screen.getByLabelText('Room layout') as HTMLSelectElement).value).toBe('Classroom');
  fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
  expect((screen.getByLabelText('Room layout') as HTMLSelectElement).value).toBe('');
});
