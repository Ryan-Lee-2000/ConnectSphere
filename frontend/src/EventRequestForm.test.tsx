import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EventRequestForm } from './EventRequestForm';

afterEach(() => { vi.restoreAllMocks(); });

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const created = {
  id: 1,
  name: 'Alumni Homecoming',
  mapped_slots: ['NIGHT'],
  equipment_requirements: [],
};

const harbourHall = {
  id: 7,
  name: 'Harbour Hall',
  location: 'Level 3',
  description: null,
  facilities: [],
  accessibility_features: [],
  operating_slots: ['AM'],
  setup_buffer_slots: 0,
  turnaround_buffer_slots: 0,
  layouts: [],
};

function noVenuesRequest() {
  return vi.fn(async () => response({ venues: [] }));
}

async function fillMandatoryFields() {
  fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Alumni Homecoming' } });
  fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Reconnect cohorts' } });
  fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2099-01-01' } });
  fireEvent.click(screen.getByRole('radio', { name: /Night/ }));
  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '150' } });
  await waitFor(() => expect(screen.getByRole('radio', { name: /Night/ })).toHaveProperty('checked', true));
}

it('asks unauthenticated visitors to sign in', () => {
  render(<EventRequestForm accessToken={null} />);
  expect(screen.getByRole('heading', { name: 'Sign in to create an event request' })).toBeTruthy();
});

it('requires the mandatory fields before saving', async () => {
  const request = noVenuesRequest();
  render(<EventRequestForm accessToken="token" request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues'));
  const save = screen.getByRole('button', { name: 'Submit event request' });
  expect(save).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Alumni Homecoming' } });
  fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Reconnect cohorts' } });
  fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2099-01-01' } });
  fireEvent.click(screen.getByRole('radio', { name: /Night/ }));
  expect(save).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '150' } });
  expect(save).toHaveProperty('disabled', false);
});

it('restricts the available time slots to the selected venue\'s operating slots', async () => {
  const request = vi.fn(async (path: string) => {
    if (path === '/api/venues') return response({ venues: [{ id: harbourHall.id, name: harbourHall.name, location: harbourHall.location }] });
    if (path === `/api/venues/${harbourHall.id}`) return response({ venue: harbourHall });
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'Harbour Hall' })).toBeTruthy());

  fireEvent.change(screen.getByRole('combobox', { name: /Venue/ }), { target: { value: String(harbourHall.id) } });

  await waitFor(() => expect(screen.getByRole('radio', { name: /^AM/ })).toHaveProperty('disabled', false));
  expect(screen.getByRole('radio', { name: /^PM/ })).toHaveProperty('disabled', true);
  expect(screen.getByRole('radio', { name: /Night/ })).toHaveProperty('disabled', true);
});

it('adds and removes equipment lines', async () => {
  const request = noVenuesRequest();
  render(<EventRequestForm accessToken="token" request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues'));
  expect(screen.getByText('None recorded.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Add equipment' }));
  expect(screen.getByLabelText('Equipment type 1')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Remove equipment line 1' }));
  expect(screen.getByText('None recorded.')).toBeTruthy();
});

it('submits the mandatory fields and shows the mapped slots on success', async () => {
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues') return response({ venues: [] });
    if (path === '/api/event-requests' && init?.method === 'POST') return response({ event_request: created }, 201);
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} />);
  await fillMandatoryFields();
  fireEvent.click(screen.getByRole('button', { name: 'Submit event request' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests', expect.objectContaining({ method: 'POST' })));
  const call = request.mock.calls.find(([path]) => path === '/api/event-requests');
  const body = JSON.parse(call?.[1]?.body as string);
  expect(body).toMatchObject({
    name: 'Alumni Homecoming',
    purpose: 'Reconnect cohorts',
    proposed_date: '2099-01-01',
    start_time: '19:00',
    end_time: '23:59',
    expected_attendance: 150,
    registration_required: false,
    venue_id: null,
    equipment_requirements: [],
  });
  expect(await screen.findByText('Event request created.')).toBeTruthy();
  expect(await screen.findByText('This falls in the NIGHT venue slot.')).toBeTruthy();
});

it('saves a draft with only the event name filled in', async () => {
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues') return response({ venues: [] });
    if (path === '/api/event-requests/drafts' && init?.method === 'POST') {
      return response({ event_request: { id: 9, name: 'Idea', last_saved_at: '2026-09-19T10:00:00+00:00' } }, 201);
    }
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues'));
  const saveDraft = screen.getByRole('button', { name: 'Save as draft' });
  expect(saveDraft).toHaveProperty('disabled', true);

  fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Idea' } });
  expect(saveDraft).toHaveProperty('disabled', false);
  fireEvent.click(saveDraft);

  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/drafts', expect.objectContaining({ method: 'POST' })));
  const call = request.mock.calls.find(([path]) => path === '/api/event-requests/drafts');
  const body = JSON.parse(call?.[1]?.body as string);
  expect(body).toMatchObject({ name: 'Idea', proposed_date: null, start_time: null, end_time: null, expected_attendance: null });
  expect(await screen.findByText('Draft saved.')).toBeTruthy();
  expect(screen.getByText(/Last saved/)).toBeTruthy();
});

it('loads an existing draft by id and resaves it with a PATCH', async () => {
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues') return response({ venues: [] });
    if (path === '/api/event-requests/42') return response({ event_request: {
      id: 42, name: 'Reunion', purpose: null, description: null, proposed_date: null,
      start_time: null, end_time: null, expected_attendance: null, preferred_room_layout: null,
      required_facilities: [], facilities_notes: null, accessibility_needs: null,
      location_preference: null, venue_notes: null, venue_id: null,
      registration_required: false, registration_notes: null,
      last_saved_at: '2026-09-19T09:00:00+00:00', equipment_requirements: [],
    } });
    if (path === '/api/event-requests/drafts/42' && init?.method === 'PATCH') {
      return response({ event_request: { id: 42, name: 'Reunion', last_saved_at: '2026-09-19T11:00:00+00:00' } });
    }
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} draftId={42} />);

  expect(await screen.findByDisplayValue('Reunion')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Save as draft' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/drafts/42', expect.objectContaining({ method: 'PATCH' })));
});

it('submits an in-progress draft through the drafts submit endpoint, not the plain create endpoint', async () => {
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues') return response({ venues: [] });
    if (path === '/api/event-requests/7') return response({ event_request: {
      id: 7, name: 'Alumni Homecoming', purpose: null, description: null, proposed_date: null,
      start_time: null, end_time: null, expected_attendance: null, preferred_room_layout: null,
      required_facilities: [], facilities_notes: null, accessibility_needs: null,
      location_preference: null, venue_notes: null, venue_id: null,
      registration_required: false, registration_notes: null,
      last_saved_at: '2026-09-19T09:00:00+00:00', equipment_requirements: [],
    } });
    if (path === '/api/event-requests/drafts/7/submit' && init?.method === 'POST') {
      return response({ event_request: created }, 200);
    }
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} draftId={7} />);
  await screen.findByDisplayValue('Alumni Homecoming');

  fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Reconnect cohorts' } });
  fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2099-01-01' } });
  fireEvent.click(screen.getByRole('radio', { name: /Night/ }));
  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '150' } });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Submit event request' })).toHaveProperty('disabled', false));

  fireEvent.click(screen.getByRole('button', { name: 'Submit event request' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/drafts/7/submit', expect.objectContaining({ method: 'POST' })));
  expect(request).not.toHaveBeenCalledWith('/api/event-requests', expect.anything());
  expect(await screen.findByText('Event request created.')).toBeTruthy();
});

it('shows a server error and only shows registration notes once registration is required', async () => {
  const request = vi.fn(async (path: string) => {
    if (path === '/api/venues') return response({ venues: [] });
    return response({ error: 'Complete the required fields before submitting.' }, 400);
  });
  render(<EventRequestForm accessToken="token" request={request} />);
  expect(screen.queryByLabelText('Registration notes')).toBeNull();
  fireEvent.click(screen.getByLabelText('Registration is required for this event'));
  expect(screen.getByLabelText('Registration notes')).toBeTruthy();

  await fillMandatoryFields();
  fireEvent.click(screen.getByRole('button', { name: 'Submit event request' }));
  expect(await screen.findByText('Complete the required fields before submitting.')).toBeTruthy();
});
