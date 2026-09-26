import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { VenueCatalogue } from './VenueCatalogue';

afterEach(() => { vi.restoreAllMocks(); });

const venue = {
  id: 1,
  name: 'Harbour Hall',
  location: 'Marina Centre',
  description: 'A flexible event space.',
  facilities: ['Projector'],
  accessibility_features: ['Step-free access'],
  operating_slots: ['AM', 'PM', 'NIGHT'],
  setup_buffer_slots: 1,
  turnaround_buffer_slots: 1,
  layouts: [{ id: 4, layout: 'theatre', capacity: 180 }],
};

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

it('asks unauthenticated visitors to sign in', () => {
  render(<VenueCatalogue accessToken={null} />);
  expect(screen.getByRole('heading', { name: 'Sign in to view venues' })).toBeTruthy();
});

it('shows a coordinator the catalogue as read-only', async () => {
  const request = vi.fn(async (path: string) => {
    if (path === '/api/venues') return response({ venues: [{ id: 1, name: 'Harbour Hall', location: 'Marina Centre' }], capabilities: { can_manage: false } });
    return response({ venue, capabilities: { can_manage: false } });
  });
  render(<VenueCatalogue accessToken="token" request={request} />);
  await screen.findByRole('button', { name: /Harbour Hall/ });
  fireEvent.click(screen.getByRole('button', { name: /Harbour Hall/ }));
  expect(await screen.findByRole('heading', { name: 'Harbour Hall' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Harbour Hall' }).closest('.venue-marketplace')).toBeTruthy();
  expect(screen.getByText('A flexible event space.')).toBeTruthy();
  expect(screen.getByText('Projector')).toBeTruthy();
  expect(screen.getByText('Step-free access')).toBeTruthy();
  expect(screen.getByText('180')).toBeTruthy();
  expect(screen.getAllByText('Required')).toHaveLength(2);
  expect(screen.getByText('Night · 7pm–12am')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Edit venue' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Add venue' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: /Harbour Hall/ }));
  await waitFor(() => expect(screen.queryByRole('heading', { name: 'Harbour Hall' })).toBeNull());
});

it('shows the appropriate empty state when no venues exist', async () => {
  const request = vi.fn(async () => response({ venues: [], capabilities: { can_manage: false } }));
  render(<VenueCatalogue accessToken="token" request={request} />);
  expect(await screen.findByRole('heading', { name: 'No venues to browse yet' })).toBeTruthy();
  expect(screen.getByText('Venue profiles will appear here when Venue Staff add them.')).toBeTruthy();
});

it('lets venue staff create a complete venue profile with all slots and preparation requirements', async () => {
  const created = { ...venue, id: 2, name: 'Orchid Room', layouts: [{ id: 8, layout: 'classroom', capacity: 60 }] };
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues' && !init?.method) return response({ venues: [], capabilities: { can_manage: true } });
    if (path === '/api/venues' && init?.method === 'POST') return response({ venue: created }, 201);
    if (path === '/api/venues') return response({ venues: [{ id: 2, name: 'Orchid Room', location: 'Marina Centre' }], capabilities: { can_manage: true } });
    return response({ venue: created, capabilities: { can_manage: true } });
  });
  render(<VenueCatalogue accessToken="token" request={request} />);
  await screen.findByRole('button', { name: 'Add venue' });
  fireEvent.click(screen.getByRole('button', { name: 'Add venue' }));
  fireEvent.change(screen.getByLabelText('Venue name'), { target: { value: 'Orchid Room' } });
  fireEvent.change(screen.getByLabelText('Location'), { target: { value: 'Marina Centre' } });
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'A flexible venue.' } });
  fireEvent.change(screen.getByLabelText(/^Facilities/), { target: { value: 'Projector, PA system' } });
  fireEvent.change(screen.getByLabelText(/^Accessibility features/), { target: { value: 'Step-free access' } });
  fireEvent.click(screen.getByLabelText('AM · 7am–12pm'));
  fireEvent.click(screen.getByLabelText('PM · 1pm–6pm'));
  fireEvent.click(screen.getByLabelText('Night · 7pm–12am'));
  fireEvent.click(screen.getByLabelText(/Setup required/));
  fireEvent.click(screen.getByLabelText(/Turnaround required/));
  fireEvent.click(screen.getByRole('button', { name: 'Add layout' }));
  expect(screen.getByText('Stated capacity (guests)')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Stated capacity 1'), { target: { value: '60' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save venue' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues', expect.objectContaining({ method: 'POST' })));
  const createCall = request.mock.calls.find(([path, init]) => path === '/api/venues' && init?.method === 'POST');
  expect(JSON.parse(createCall?.[1]?.body as string)).toMatchObject({
    name: 'Orchid Room',
    location: 'Marina Centre',
    description: 'A flexible venue.',
    facilities: ['Projector', 'PA system'],
    accessibility_features: ['Step-free access'],
    operating_slots: ['AM', 'PM', 'NIGHT'],
    setup_buffer_slots: 1,
    turnaround_buffer_slots: 1,
    layouts: [{ layout: 'classroom', capacity: 60 }],
  });
  expect(await screen.findByText('Venue and its room layouts created.')).toBeTruthy();
});

it('requires a venue name and at least one operating slot before saving', async () => {
  const request = vi.fn(async () => response({ venues: [], capabilities: { can_manage: true } }));
  render(<VenueCatalogue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Add venue' }));
  const save = screen.getByRole('button', { name: 'Save venue' });
  expect(save).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('Venue name'), { target: { value: 'Orchid Room' } });
  expect(save).toHaveProperty('disabled', true);
  fireEvent.click(screen.getByLabelText('AM · 7am–12pm'));
  expect(save).toHaveProperty('disabled', false);
});

it('TC-SPL-89-06 lets venue staff record operational unavailability for a selected venue', async () => {
  const createdBlock = {
    id: 9,
    venue_id: 1,
    start_date: '2026-10-05',
    end_date: '2026-10-07',
    slots: ['AM', 'PM'],
    reason: 'Annual fire-safety inspection',
    created_by_account_id: 'venue-staff-id',
    created_at: '2026-09-26T10:00:00+08:00',
    removed_by_account_id: null,
    removed_at: null,
  };
  let blocks: typeof createdBlock[] = [];
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues' && !init?.method) return response({ venues: [{ id: 1, name: 'Harbour Hall', location: 'Marina Centre' }], capabilities: { can_manage: true } });
    if (path === '/api/venues/1' && !init?.method) return response({ venue, capabilities: { can_manage: true } });
    if (path === '/api/venues/1/operational-blocks' && init?.method === 'POST') {
      blocks = [createdBlock];
      return response({ operational_block: createdBlock, affected_booking_count: 2 }, 201);
    }
    if (path === '/api/venues/1/operational-blocks/9' && init?.method === 'DELETE') {
      blocks = [];
      return response({ operational_block: { ...createdBlock, removed_by_account_id: 'venue-staff-id', removed_at: '2026-09-26T10:05:00+08:00' } });
    }
    if (path === '/api/venues/1/operational-blocks') return response({ operational_blocks: blocks });
    throw new Error(`Unexpected request: ${path}`);
  });

  render(<VenueCatalogue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: /Harbour Hall/ }));
  expect(await screen.findByRole('heading', { name: 'Operational unavailability' })).toBeTruthy();

  fireEvent.change(screen.getByLabelText('Unavailable from'), { target: { value: '2026-10-05' } });
  fireEvent.change(screen.getByLabelText('Unavailable through'), { target: { value: '2026-10-07' } });
  fireEvent.click(screen.getByLabelText('AM · 7am–12pm unavailable'));
  fireEvent.click(screen.getByLabelText('PM · 1pm–6pm unavailable'));
  fireEvent.change(screen.getByLabelText('Reason for unavailability'), { target: { value: 'Annual fire-safety inspection' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record unavailability' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues/1/operational-blocks', expect.objectContaining({ method: 'POST' })));
  const createCall = request.mock.calls.find(([path, init]) => path === '/api/venues/1/operational-blocks' && init?.method === 'POST');
  expect(JSON.parse(createCall?.[1]?.body as string)).toEqual({
    start_date: '2026-10-05',
    end_date: '2026-10-07',
    slots: ['AM', 'PM'],
    reason: 'Annual fire-safety inspection',
  });
  expect(await screen.findByText('Annual fire-safety inspection')).toBeTruthy();
  expect(screen.getByText('Operational unavailability recorded. 2 active bookings require review.')).toBeTruthy();
  expect(screen.getByText('5 Oct 2026 – 7 Oct 2026')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Remove Annual fire-safety inspection' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues/1/operational-blocks/9', { method: 'DELETE' }));
  expect(screen.queryByText('Annual fire-safety inspection')).toBeNull();
  expect(await screen.findByText('Operational unavailability removed.')).toBeTruthy();
});

it('sends not-required preparation values when neither requirement is selected', async () => {
  const created = { ...venue, id: 2, name: 'Orchid Room', setup_buffer_slots: 0, turnaround_buffer_slots: 0 };
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues' && !init?.method) return response({ venues: [], capabilities: { can_manage: true } });
    if (path === '/api/venues' && init?.method === 'POST') return response({ venue: created }, 201);
    return response({ venues: [{ id: 2, name: 'Orchid Room', location: 'Marina Centre' }], capabilities: { can_manage: true } });
  });
  render(<VenueCatalogue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Add venue' }));
  fireEvent.change(screen.getByLabelText('Venue name'), { target: { value: 'Orchid Room' } });
  fireEvent.click(screen.getByLabelText('AM · 7am–12pm'));
  expect(screen.queryByLabelText('Setup slots before event')).toBeNull();
  expect(screen.getByLabelText(/Setup required/)).toHaveProperty('checked', false);
  expect(screen.getByLabelText(/Turnaround required/)).toHaveProperty('checked', false);
  fireEvent.click(screen.getByRole('button', { name: 'Save venue' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues', expect.objectContaining({ method: 'POST' })));
  const createCall = request.mock.calls.find(([path, init]) => path === '/api/venues' && init?.method === 'POST');
  expect(JSON.parse(createCall?.[1]?.body as string)).toMatchObject({ setup_buffer_slots: 0, turnaround_buffer_slots: 0 });
});

it('sends a staff-defined name when Other room layout is selected', async () => {
  const created = { ...venue, id: 2, name: 'Orchid Room', layouts: [{ id: 8, layout: 'cabaret', capacity: 60 }] };
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues' && !init?.method) return response({ venues: [], capabilities: { can_manage: true } });
    if (path === '/api/venues' && init?.method === 'POST') return response({ venue: created }, 201);
    return response({ venues: [{ id: 2, name: 'Orchid Room', location: 'Marina Centre' }], capabilities: { can_manage: true } });
  });
  render(<VenueCatalogue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Add venue' }));
  fireEvent.change(screen.getByLabelText('Venue name'), { target: { value: 'Orchid Room' } });
  fireEvent.click(screen.getByLabelText('AM · 7am–12pm'));
  fireEvent.click(screen.getByRole('button', { name: 'Add layout' }));
  fireEvent.change(screen.getByLabelText('Room layout 1'), { target: { value: 'other' } });
  fireEvent.change(screen.getByLabelText('Custom room layout 1'), { target: { value: 'Cabaret' } });
  fireEvent.change(screen.getByLabelText('Stated capacity 1'), { target: { value: '60' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save venue' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues', expect.objectContaining({ method: 'POST' })));
  const createCall = request.mock.calls.find(([path, init]) => path === '/api/venues' && init?.method === 'POST');
  expect(JSON.parse(createCall?.[1]?.body as string).layouts).toEqual([{ layout: 'Cabaret', capacity: 60 }]);
});

it('stages layout edits until Save venue is pressed', async () => {
  const updated = { ...venue, layouts: [{ id: 4, layout: 'classroom', capacity: 240 }] };
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues' && !init?.method) return response({ venues: [{ id: 1, name: 'Harbour Hall', location: 'Marina Centre' }], capabilities: { can_manage: true } });
    if (path === '/api/venues/1' && !init?.method) return response({ venue, capabilities: { can_manage: true } });
    if (path === '/api/venues/1' && init?.method === 'PATCH') return response({ venue: updated });
    return response({ venues: [{ id: 1, name: 'Harbour Hall', location: 'Marina Centre' }], capabilities: { can_manage: true } });
  });
  render(<VenueCatalogue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: /Harbour Hall/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Edit venue' }));
  fireEvent.change(screen.getByLabelText('Room layout 1'), { target: { value: 'classroom' } });
  fireEvent.change(screen.getByLabelText('Stated capacity 1'), { target: { value: '240' } });
  expect(request.mock.calls.some(([path]) => path.includes('/layouts'))).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Save venue' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues/1', expect.objectContaining({ method: 'PATCH' })));
  const updateCall = request.mock.calls.find(([path, init]) => path === '/api/venues/1' && init?.method === 'PATCH');
  expect(JSON.parse(updateCall?.[1]?.body as string).layouts).toEqual([{ layout: 'classroom', capacity: 240 }]);
});

it('sends every editable venue attribute when Venue Staff save an update', async () => {
  const updated = {
    ...venue,
    name: 'Harbour Grand Hall',
    location: 'Level 4, Marina Centre',
    description: 'An updated flexible event space.',
    facilities: ['Projector', 'Hearing loop'],
    accessibility_features: ['Step-free access'],
    operating_slots: ['NIGHT'],
    setup_buffer_slots: 0,
    turnaround_buffer_slots: 1,
  };
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues' && !init?.method) return response({ venues: [{ id: 1, name: 'Harbour Hall', location: 'Marina Centre' }], capabilities: { can_manage: true } });
    if (path === '/api/venues/1' && !init?.method) return response({ venue, capabilities: { can_manage: true } });
    if (path === '/api/venues/1' && init?.method === 'PATCH') return response({ venue: updated });
    return response({ venues: [{ id: 1, name: 'Harbour Grand Hall', location: 'Level 4, Marina Centre' }], capabilities: { can_manage: true } });
  });
  render(<VenueCatalogue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: /Harbour Hall/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Edit venue' }));
  fireEvent.change(screen.getByLabelText('Venue name'), { target: { value: updated.name } });
  fireEvent.change(screen.getByLabelText('Location'), { target: { value: updated.location } });
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: updated.description } });
  fireEvent.change(screen.getByLabelText(/^Facilities/), { target: { value: 'Projector, Hearing loop' } });
  fireEvent.change(screen.getByLabelText(/^Accessibility features/), { target: { value: 'Step-free access' } });
  fireEvent.click(screen.getByLabelText('AM · 7am–12pm'));
  fireEvent.click(screen.getByLabelText('PM · 1pm–6pm'));
  fireEvent.click(screen.getByLabelText('Night · 7pm–12am'));
  fireEvent.click(screen.getByLabelText('Night · 7pm–12am'));
  fireEvent.click(screen.getByLabelText(/Setup required/));
  fireEvent.click(screen.getByRole('button', { name: 'Save venue' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues/1', expect.objectContaining({ method: 'PATCH' })));
  const updateCall = request.mock.calls.find(([path, init]) => path === '/api/venues/1' && init?.method === 'PATCH');
  expect(JSON.parse(updateCall?.[1]?.body as string)).toMatchObject({
    name: updated.name,
    location: updated.location,
    description: updated.description,
    facilities: updated.facilities,
    accessibility_features: updated.accessibility_features,
    operating_slots: ['NIGHT'],
    setup_buffer_slots: 0,
    turnaround_buffer_slots: 1,
  });
});
