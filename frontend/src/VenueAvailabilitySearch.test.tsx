import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
afterEach(cleanup);

it('[TC-SPL-71-01] sends the selected Singapore date and slots, then shows result facts', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [{ id: 1, name: 'Atlas Hall', location: 'City Campus', maximum_layout_capacity: 180 }] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM', 'PM']} request={request} />);
  fireEvent.click(screen.getByRole('button', { name: 'Find venues' }));
  expect(await screen.findByText('Atlas Hall')).toBeTruthy();
  expect(screen.getByText('City Campus')).toBeTruthy(); expect(screen.getByText('Up to 180 guests')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&slot=PM');
  fireEvent.click(screen.getByRole('button', { name: /Atlas Hall/ }));
  expect(await screen.findByRole('heading', { name: 'Atlas Hall is available' })).toBeTruthy();
  expect(screen.getByText('Timing confirmed')).toBeTruthy();
});

it('[TC-SPL-71-03] retains applied controls and shows a clear empty result', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venues: [] }) });
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate="2026-10-12" initialSlots={['AM']} request={request} />);
  fireEvent.click(screen.getByRole('button', { name: 'Find venues' }));
  expect(await screen.findByText('No venues are available for this search.')).toBeTruthy();
  expect((screen.getByLabelText('Singapore date') as HTMLInputElement).value).toBe('2026-10-12');
  expect((screen.getByLabelText('AM · 7am–12pm') as HTMLInputElement).checked).toBe(true);
});

it('[TC-SPL-71-04] prevents an incomplete search before calling the API', () => {
  const request = vi.fn();
  render(<VenueAvailabilitySearch accessToken="token" eventId={12} initialDate={null} initialSlots={[]} request={request} />);

  expect((screen.getByRole('button', { name: 'Find venues' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText('Choose a Singapore date and at least one slot to search.')).toBeTruthy();
  expect(request).not.toHaveBeenCalled();
});
