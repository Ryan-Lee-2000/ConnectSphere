import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { VenueAvailabilityOverview, type Overview } from './VenueAvailabilityOverview';

afterEach(() => { cleanup(); vi.useRealTimers(); });
const start = (time: string) => `2026-10-14T${time}:00+08:00`;
const payload: Overview = { date: '2026-10-14', timezone: 'Asia/Singapore', venues: [
  { id: 1, name: 'Harbour Hall', intervals: [
    { start: start('09:30'), end: start('10:00'), status: 'preparation', requires_review: true, reasons: [{ key: 'setup', label: 'Setup', detail: 'Setup' }] },
    { start: start('10:00'), end: start('12:00'), status: 'booked', requires_review: true, reasons: [{ key: 'booking', label: 'Approved booking', detail: 'Approved booking', event_name: 'Forum', links: [{ label: 'Open booking', href: '/workspace/venue-bookings/7', role: 'venue_staff' }] }] },
    { start: start('12:00'), end: start('12:46'), status: 'preparation', requires_review: true, reasons: [{ key: 'turnaround', label: 'Turnaround', detail: 'Turnaround' }] },
    { start: start('12:46'), end: start('18:00'), status: 'available', requires_review: false, reasons: [] },
  ] },
  { id: 2, name: 'Quiet Room', intervals: [{ start: start('00:00'), end: '2026-10-15T00:00:00+08:00', status: 'review_required', requires_review: true, reasons: [] }] },
] };
const response = (body = payload) => new Response(JSON.stringify(body), { status: 200 });

it('[TC-SPL-107-01, TC-SPL-107-05, TC-SPL-107-09] compares venues and opens exact permitted detail with keyboard controls', async () => {
  render(<VenueAvailabilityOverview accessToken="fixture" activeRole="venue_staff" request={vi.fn(async () => response())} />);
  fireEvent.change(screen.getByLabelText('Date (Singapore time)'), { target: { value: '2026-10-14' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Harbour Hall' }));
  expect(screen.getByRole('button', { name: 'Inspect Quiet Room' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect 10:00–12:00 Approved' }));
  const details = screen.getByRole('region', { name: 'Selected period' });
  expect(within(details).getByText('Review required')).toBeTruthy();
  expect(within(details).getByText('Forum')).toBeTruthy();
  expect(within(details).getByRole('link', { name: 'Open booking' }).getAttribute('href')).toBe('/workspace/venue-bookings/7');
  expect(screen.getByRole('button', { name: 'Inspect 12:00–12:46 Turnaround' })).toBeTruthy();
});

it('[TC-SPL-107-10] recovers from a failed request and distinguishes an empty catalogue', async () => {
  let failed = true;
  const api = vi.fn(async () => {
    if (failed) throw new Error('offline');
    return response({ ...payload, venues: [] });
  });
  render(<VenueAvailabilityOverview accessToken="fixture" activeRole="venue_staff" request={api} />);
  fireEvent.change(screen.getByLabelText('Date (Singapore time)'), { target: { value: '2026-10-14' } });
  expect(await screen.findByRole('alert')).toBeTruthy();
  failed = false;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh availability' }));
  expect(await screen.findByText('No venues have been added yet.')).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});

it('[TC-SPL-107-10] clears selected detail on an empty date and ignores an older response', async () => {
  let resolveOld!: (value: Response) => void;
  const api = vi.fn(async (path: string) => path.includes('2026-10-15') ? new Promise<Response>(resolve => { resolveOld = resolve; }) : response());
  render(<VenueAvailabilityOverview accessToken="fixture" activeRole="venue_staff" request={api} />);
  const input = screen.getByLabelText('Date (Singapore time)');
  fireEvent.change(input, { target: { value: '2026-10-14' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Harbour Hall' }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect 10:00–12:00 Approved' }));
  fireEvent.change(input, { target: { value: '2026-10-15' } });
  expect(screen.queryByRole('region', { name: 'Selected period' })).toBeNull();
  fireEvent.change(input, { target: { value: '' } });
  await act(async () => resolveOld(response({ ...payload, date: '2026-10-15' })));
  expect(screen.getByText('Choose a date to view availability.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Inspect Harbour Hall' })).toBeNull();
  expect(screen.queryByText('Loading venue availability…')).toBeNull();
});

it('[TC-SPL-107-02] requests the Singapore date when UTC is still the previous day', async () => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-13T16:30:00Z'));
  const api = vi.fn(async () => response());
  render(<VenueAvailabilityOverview accessToken="fixture" activeRole="event_operations_manager" request={api} />);
  await screen.findByRole('button', { name: 'Inspect Harbour Hall' });
  expect(api).toHaveBeenCalledWith('/api/venues/occupancy-overview?date=2026-10-14');
  vi.useRealTimers();
});

it('[TC-SPL-107-06, TC-SPL-107-08] removes old details on a role switch and filters unusable role links', async () => {
  const api = vi.fn(async () => response());
  const view = render(<VenueAvailabilityOverview accessToken="fixture" activeRole="venue_staff" request={api} />);
  fireEvent.change(screen.getByLabelText('Date (Singapore time)'), { target: { value: '2026-10-14' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Harbour Hall' }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect 10:00–12:00 Approved' }));
  expect(screen.getByRole('link', { name: 'Open booking' })).toBeTruthy();
  view.rerender(<VenueAvailabilityOverview accessToken="fixture" activeRole="event_operations_manager" request={api} />);
  expect(screen.queryByRole('region', { name: 'Selected period' })).toBeNull();
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Harbour Hall' }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect 10:00–12:00 Approved' }));
  expect(screen.queryByRole('link', { name: 'Open booking' })).toBeNull();
});

it('[TC-SPL-107-05] shows all overlapping causes and original timing in the selected period', async () => {
  const body = structuredClone(payload);
  const booking = body.venues[0].intervals[1];
  booking.status = 'blocked';
  booking.reasons.push({ key: 'block', label: 'Operational closure', detail: 'Maintenance' });
  render(<VenueAvailabilityOverview accessToken="fixture" activeRole="venue_staff" request={vi.fn(async () => response(body))} />);
  fireEvent.change(screen.getByLabelText('Date (Singapore time)'), { target: { value: '2026-10-14' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect Harbour Hall' }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect 10:00–12:00 Closure' }));
  const details = screen.getByRole('region', { name: 'Selected period' });
  expect(within(details).getByText('Approved booking')).toBeTruthy();
  expect(within(details).getByText('Operational closure')).toBeTruthy();
  expect(within(details).getByText('Maintenance')).toBeTruthy();
});

it('[TC-SPL-107-11] shows the feature-disabled response without presenting a free calendar', async () => {
  render(<VenueAvailabilityOverview accessToken="fixture" activeRole="venue_staff" request={vi.fn(async () => new Response(JSON.stringify({ error: 'The all-venues timeline is not enabled yet. Use the one-venue calendar.' }), { status: 409 }))} />);
  expect((await screen.findByRole('alert')).textContent).toContain('one-venue calendar');
  expect(screen.queryByRole('button', { name: 'Inspect Harbour Hall' })).toBeNull();
});
