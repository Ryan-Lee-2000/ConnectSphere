import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { VenueOperationalBlocks } from './VenueOperationalBlocks';
import { VenueOccupancyCalendar } from './VenueOccupancyCalendar';
import type { Venue } from './VenueCatalogue';
afterEach(() => { cleanup(); vi.useRealTimers(); });
const venue: Venue = { id: 1, name: 'Hall', location: null, description: null, facilities: [], accessibility_features: [], operating_slots: ['AM'], setup_buffer_slots: 0, turnaround_buffer_slots: 0, layouts: [] };
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
const block = { id: 3, venue_id: 1, start_date: '2026-10-14', end_date: '2026-10-14', slots: [], reason: 'Repair', timing: { start: '2026-10-14T12:30:00+08:00', end: '2026-10-14T13:00:00+08:00' } };
async function fill() {
  await screen.findByLabelText('Start time (SGT)');
  fireEvent.change(screen.getByLabelText('Unavailable from'), { target: { value: '2026-10-14' } });
  fireEvent.change(screen.getByLabelText('Start time (SGT)'), { target: { value: '12:30' } });
  fireEvent.change(screen.getByLabelText('End time (SGT)'), { target: { value: '13:00' } });
  fireEvent.change(screen.getByLabelText('Reason for unavailability'), { target: { value: 'Repair' } });
}
it('[TC-SPL-138-01] creates exact payload and removes the selected closure', async () => {
  const api = vi.fn(async (_path: string, init?: RequestInit) => init?.method === 'POST' ? json({ operational_block: block, affected_booking_count: 2 }) : init?.method === 'DELETE' ? json({ operational_block: block }) : json({ operational_blocks: [], capabilities: { exact_venue_timing: true } }));
  render(<VenueOperationalBlocks venue={venue} api={api} />);
  await fill();
  expect(screen.queryByLabelText('Unavailable through')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Record unavailability' }));
  await screen.findByText(/2 active bookings require review/);
  expect(JSON.parse(api.mock.calls.find(([, init]) => init?.method === 'POST')![1]!.body as string)).toEqual({ date: '2026-10-14', start_time: '12:30', end_time: '13:00', reason: 'Repair' });
  fireEvent.click(screen.getByRole('button', { name: 'Remove Repair' }));
  await screen.findByText('Operational unavailability removed.');
  expect(screen.queryByRole('button', { name: 'Remove Repair' })).toBeNull();
});
it('[TC-SPL-138-12] failed creation retains input and permits retry', async () => {
  let fail = true;
  const api = vi.fn(async (_path: string, init?: RequestInit) => {
    if (init?.method === 'POST') { if (fail) throw new Error('Connection lost'); return json({ operational_block: block }); }
    return json({ operational_blocks: [], capabilities: { exact_venue_timing: true } });
  });
  render(<VenueOperationalBlocks venue={venue} api={api} />);
  await fill();
  fireEvent.click(screen.getByRole('button', { name: 'Record unavailability' }));
  await screen.findByRole('alert');
  expect((screen.getByLabelText('Reason for unavailability') as HTMLTextAreaElement).value).toBe('Repair');
  expect((screen.getByRole('button', { name: 'Record unavailability' }) as HTMLButtonElement).disabled).toBe(false);
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Record unavailability' }));
  await screen.findByRole('button', { name: 'Remove Repair' });
});
it('[TC-SPL-138-12] failed loading retries and failed removal retains closure', async () => {
  let loadFails = true;
  const api = vi.fn(async (_path: string, init?: RequestInit) => {
    if (loadFails || init?.method === 'DELETE') throw new Error('Connection lost');
    return json({ operational_blocks: [block], capabilities: { exact_venue_timing: true } });
  });
  render(<VenueOperationalBlocks venue={venue} api={api} />);
  await screen.findByRole('button', { name: 'Retry loading closures' });
  loadFails = false;
  fireEvent.click(screen.getByRole('button', { name: 'Retry loading closures' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Remove Repair' }));
  await screen.findByRole('alert');
  expect((screen.getByRole('button', { name: 'Remove Repair' }) as HTMLButtonElement).disabled).toBe(false);
});
it('[TC-SPL-138-04] renders exact minute boundaries, free time and every reason', async () => {
  const api = vi.fn(async () => json({ mode: 'exact', venue, days: [{ date: '2026-10-14', intervals: [
    { start: '2026-10-14T12:30:00+08:00', end: '2026-10-14T12:46:00+08:00', status: 'blocked', reasons: [{ key: 'block', label: 'Operational closure' }, { key: 'turnaround', label: 'Turnaround' }] },
    { start: '2026-10-14T13:00:00+08:00', end: '2026-10-15T00:00:00+08:00', status: 'available', reasons: [] },
  ] }] }));
  render(<VenueOccupancyCalendar accessToken="fixture" venues={[venue]} request={api} />);
  await screen.findByText(/12:30.*12:46.*Blocked/);
  expect(screen.getByText('Turnaround')).not.toBeNull();
  expect(screen.getByText(/13:00.*24:00.*Available/)).not.toBeNull();
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '' } });
  await waitFor(() => expect(screen.queryByText('Turnaround')).toBeNull());
});

it('[TC-SPL-138-12] ignores a late closure list from the previous venue', async () => {
  let finishOld: (value: Response) => void = () => {};
  const api = vi.fn((path: string) => path.includes('/venues/1/') ? new Promise<Response>(resolve => { finishOld = resolve; }) : Promise.resolve(json({ operational_blocks: [], capabilities: { exact_venue_timing: true } })));
  const view = render(<VenueOperationalBlocks venue={venue} api={api} />);
  view.rerender(<VenueOperationalBlocks venue={{ ...venue, id: 2, name: 'Other hall' }} api={api} />);
  await screen.findByLabelText('Start time (SGT)');
  await act(async () => { finishOld(json({ operational_blocks: [block], capabilities: { exact_venue_timing: false } })); });
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove Repair' })).toBeNull());
  expect(screen.getByLabelText('Start time (SGT)')).not.toBeNull();
});

it('[TC-SPL-138-04] defaults to the Singapore date before UTC midnight', async () => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-13T17:00:00Z'));
  const api = vi.fn(async (_path: string) => json({ mode: 'exact', venue, days: [] }));
  render(<VenueOccupancyCalendar accessToken="fixture" venues={[venue]} request={api} />);
  await waitFor(() => expect(api).toHaveBeenCalled());
  expect((screen.getByLabelText('From') as HTMLInputElement).value).toBe('2026-10-14');
  expect(api.mock.calls[0][0]).toContain('start_date=2026-10-14');
});
it('[TC-SPL-138-12] clearing the date prompts for a date instead of loading forever', async () => {
  const api = vi.fn(async (_path: string) => json({ mode: 'exact', venue, days: [] }));
  render(<VenueOccupancyCalendar accessToken="fixture" venues={[venue]} request={api} />);
  await screen.findByLabelText('Exact venue occupancy');
  const calls = api.mock.calls.length;
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '' } });
  await screen.findByText('Choose a start date to view occupancy.');
  expect(screen.queryByText(/Loading the calendar/)).toBeNull();
  expect(api.mock.calls.length).toBe(calls);
});
it('[TC-SPL-138-12] failed closure loading never claims the venue has no closures', async () => {
  const api = vi.fn(async () => { throw new Error('Connection lost'); });
  render(<VenueOperationalBlocks venue={venue} api={api} />);
  await screen.findByRole('alert');
  expect(screen.queryByText('No operational unavailability recorded.')).toBeNull();
});
