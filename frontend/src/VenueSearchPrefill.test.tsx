import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';

afterEach(cleanup);

const event = {
  id: 12, name: 'Planning Forum', status: 'planning', status_label: 'In planning',
  proposed_date: '2026-10-12', mapped_slots: ['AM', 'PM'], expected_attendance: 120,
  preferred_room_layout: 'theatre', required_facilities: ['Projector'],
  accessibility_needs: ['Step-free access'], location_preference: 'Marina Centre',
};

function fixture(record = event) {
  // Each opening reads the current server record; search endpoints never change it.
  const request = vi.fn(async (path: string) => Response.json(
    path === '/api/event-requests/assigned/12' ? { event: record } :
      path.includes('venue-filter-options') ? { filter_options: {
        facilities: ['Projector', 'PA system'], accessibility_needs: ['Step-free access', 'Hearing loop'],
        locations: ['Marina Centre', 'City Campus'],
      } } : { venues: [], bookings: [] },
  ));
  const props = { accessToken: 'token', eventId: 12, request, onNavigate: vi.fn() };
  return { request, props };
}

it('[TC-SPL-74-01] pre-fills every recorded criterion from the assigned event', async () => {
  const { props } = fixture();
  render(<AssignedEvents {...props} view="venue-search" />);
  expect(await screen.findByLabelText('Singapore date')).toHaveProperty('value', '2026-10-12');
  expect(screen.getByLabelText('Expected attendance')).toHaveProperty('value', '120');
  expect(screen.getByLabelText('AM · 7am–12pm')).toHaveProperty('checked', true);
  expect(screen.getByLabelText('PM · 1pm–6pm')).toHaveProperty('checked', true);
  expect(screen.getByLabelText('Night · 7pm–12am')).toHaveProperty('checked', false);
  expect(screen.getByLabelText('Room layout')).toHaveProperty('value', 'Theatre');
  expect(screen.getByRole('button', { name: 'Remove Projector' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Remove Step-free access' })).toBeTruthy();
  expect(screen.getByLabelText('Preferred venue location')).toHaveProperty('value', 'Marina Centre');
});

it('[TC-SPL-74-02] edits all search criteria through GET queries without mutating the recorded event', async () => {
  const record = structuredClone(event);
  const { props, request } = fixture(record);
  render(<AssignedEvents {...props} view="venue-search" />);
  fireEvent.change(await screen.findByLabelText('Singapore date'), { target: { value: '2026-10-13' } });
  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '80' } });
  fireEvent.click(screen.getByLabelText('AM · 7am–12pm'));
  fireEvent.change(screen.getByLabelText('Room layout'), { target: { value: 'Classroom' } });
  fireEvent.click(screen.getByRole('button', { name: 'Remove Projector' }));
  fireEvent.click(screen.getByRole('button', { name: 'Remove Step-free access' }));
  fireEvent.change(await screen.findByLabelText('Add Required facilities'), { target: { value: 'PA system' } });
  fireEvent.change(screen.getByLabelText('Add Accessibility needs'), { target: { value: 'Hearing loop' } });
  fireEvent.change(screen.getByLabelText('Preferred venue location'), { target: { value: 'City Campus' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('No venues are available for this search.')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-13&slot=PM&expected_attendance=80&preferred_room_layout=Classroom&required_facility=PA+system&accessibility_need=Hearing+loop&location_preference=City+Campus');
  expect(record).toEqual(event);
  // Any write would supply request options; every request here uses GET's default.
  expect(request.mock.calls.every(call => call.length === 1)).toBe(true);
});

it('[TC-SPL-74-03] searches with all optional requirements missing', async () => {
  const record = { ...event, preferred_room_layout: null, required_facilities: undefined,
    accessibility_needs: undefined, location_preference: null };
  const { props, request } = fixture(record as unknown as typeof event);
  render(<AssignedEvents {...props} view="venue-search" />);
  expect(await screen.findByLabelText('Room layout')).toHaveProperty('value', '');
  expect(screen.getByLabelText('Preferred venue location')).toHaveProperty('value', '');
  expect(screen.getByRole('button', { name: 'Search venues' })).toHaveProperty('disabled', false);
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('No venues are available for this search.')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&slot=PM&expected_attendance=120&preferred_room_layout=&required_facility=&accessibility_need=&location_preference=');
});

it('[TC-SPL-74-04] reopening search reloads current event data and discards exploratory edits', async () => {
  const record = structuredClone(event);
  const { props, request } = fixture(record);
  const page = render(<AssignedEvents {...props} view="venue-search" />);
  fireEvent.change(await screen.findByLabelText('Expected attendance'), { target: { value: '80' } });
  page.rerender(<AssignedEvents {...props} view="detail" />);
  await screen.findByRole('heading', { name: 'Planning Forum' });
  Object.assign(record, { proposed_date: '2026-10-14', mapped_slots: ['PM'], expected_attendance: 200,
    preferred_room_layout: 'Banquet', required_facilities: ['PA system'],
    accessibility_needs: ['Hearing loop'], location_preference: 'City Campus' });
  page.rerender(<AssignedEvents {...props} view="venue-search" />);
  await waitFor(() => expect(screen.getByLabelText('Expected attendance')).toHaveProperty('value', '200'));
  expect(screen.getByLabelText('Singapore date')).toHaveProperty('value', '2026-10-14');
  expect(screen.getByLabelText('AM · 7am–12pm')).toHaveProperty('checked', false);
  expect(screen.getByLabelText('PM · 1pm–6pm')).toHaveProperty('checked', true);
  expect(screen.getByLabelText('Room layout')).toHaveProperty('value', 'Banquet');
  expect(screen.getByRole('button', { name: 'Remove PA system' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Remove Hearing loop' })).toBeTruthy();
  expect(screen.getByLabelText('Preferred venue location')).toHaveProperty('value', 'City Campus');
  expect(request.mock.calls.filter(([path]) => path === '/api/event-requests/assigned/12')).toHaveLength(3);
});

// AC1: recorded free-text preferences must survive even when catalogue suggestions differ.
it('[TC-SPL-74-05] preserves custom preferences and a Night-only event', async () => {
  const { props } = fixture({ ...event, mapped_slots: ['NIGHT'], preferred_room_layout: 'Round tables',
    required_facilities: ['Recording booth'], accessibility_needs: ['Quiet space'], location_preference: 'West annex' });
  render(<AssignedEvents {...props} view="venue-search" />);
  expect(await screen.findByLabelText('Room layout')).toHaveProperty('value', 'Round tables');
  expect(screen.getByLabelText('Night · 7pm–12am')).toHaveProperty('checked', true);
  expect(screen.getByLabelText('AM · 7am–12pm')).toHaveProperty('checked', false);
  expect(screen.getByLabelText('PM · 1pm–6pm')).toHaveProperty('checked', false);
  expect(screen.getByRole('button', { name: 'Remove Recording booth' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Remove Quiet space' })).toBeTruthy();
  expect(screen.getByLabelText('Preferred venue location')).toHaveProperty('value', 'West annex');
});

// AC2: clearing a saved preference must send an explicit blank, not fall back to that preference.
it('[TC-SPL-74-06] clears optional filters for a search without clearing the event requirements', async () => {
  const record = structuredClone(event);
  const { props, request } = fixture(record);
  render(<AssignedEvents {...props} view="venue-search" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Clear' }));
  fireEvent.click(screen.getByRole('button', { name: 'Remove Projector' }));
  fireEvent.click(screen.getByRole('button', { name: 'Remove Step-free access' }));
  fireEvent.change(screen.getByLabelText('Preferred venue location'), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('No venues are available for this search.')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&slot=PM&expected_attendance=120&preferred_room_layout=&required_facility=&accessibility_need=&location_preference=');
  expect(record).toEqual(event);
  expect(request.mock.calls.every(call => call.length === 1)).toBe(true);
  expect(screen.getByText('Marina Centre', { selector: 'dd' })).toBeTruthy();
});

// AC3: partially recorded requirements must still be applied when other optionals are empty.
it('[TC-SPL-74-07] searches with only some optional requirements recorded', async () => {
  const { props, request } = fixture({ ...event, preferred_room_layout: '', accessibility_needs: [], location_preference: '' });
  render(<AssignedEvents {...props} view="venue-search" />);
  expect(await screen.findByRole('button', { name: 'Remove Projector' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Search venues' })).toHaveProperty('disabled', false);
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  expect(await screen.findByText('No venues are available for this search.')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/available-venues?date=2026-10-12&slot=AM&slot=PM&expected_attendance=120&preferred_room_layout=&required_facility=Projector&accessibility_need=&location_preference=');
});

// AC4: a fresh opening must also remove preferences that have since been cleared on the event.
it('[TC-SPL-74-08] a fresh search opening drops requirements removed from the current event', async () => {
  const record = structuredClone(event);
  const { props, request } = fixture(record);
  const page = render(<AssignedEvents {...props} view="venue-search" />);
  expect(await screen.findByRole('button', { name: 'Remove Projector' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Search venues' }));
  await screen.findByText('No venues are available for this search.');
  page.unmount();
  Object.assign(record, { preferred_room_layout: '', required_facilities: [], accessibility_needs: [], location_preference: '' });
  render(<AssignedEvents {...props} view="venue-search" />);
  expect(await screen.findByLabelText('Room layout')).toHaveProperty('value', '');
  expect(screen.getByLabelText('Preferred venue location')).toHaveProperty('value', '');
  expect(screen.queryByRole('button', { name: 'Remove Projector' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Remove Step-free access' })).toBeNull();
  expect(screen.queryByText('No venues are available for this search.')).toBeNull();
  expect(request.mock.calls.filter(([path]) => path === '/api/event-requests/assigned/12')).toHaveLength(2);
});
