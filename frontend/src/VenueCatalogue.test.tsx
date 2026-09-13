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
  operating_slots: ['AM', 'PM'],
  setup_buffer_slots: 1,
  turnaround_buffer_slots: 2,
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
  expect(screen.getByText('Step-free access')).toBeTruthy();
  expect(screen.getByText('180')).toBeTruthy();
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

it('lets venue staff create a venue through the form', async () => {
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
  fireEvent.click(screen.getByLabelText('AM · 7am–12pm'));
  fireEvent.click(screen.getByRole('button', { name: 'Add layout' }));
  fireEvent.change(screen.getByLabelText('Stated capacity 1'), { target: { value: '60' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save venue' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues', expect.objectContaining({ method: 'POST' })));
  const createCall = request.mock.calls.find(([path, init]) => path === '/api/venues' && init?.method === 'POST');
  expect(JSON.parse(createCall?.[1]?.body as string).layouts).toEqual([{ layout: 'classroom', capacity: 60 }]);
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
