import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  facilities: ['Projector', 'Step-free access'],
  accessibility_features: ['Wheelchair access', 'Hearing loop'],
  operating_slots: ['AM'],
  setup_buffer_slots: 0,
  turnaround_buffer_slots: 0,
  layouts: [{ id: 1, layout: 'Theatre', capacity: 100 }, { id: 2, layout: 'Boardroom', capacity: 20 }],
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

it('disables the layout, facilities and accessibility fields until a venue is selected', async () => {
  const request = noVenuesRequest();
  render(<EventRequestForm accessToken="token" request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/venues'));
  expect(screen.getByRole('combobox', { name: /Preferred room layout/ })).toHaveProperty('disabled', true);
  expect(screen.getByRole('group', { name: 'Required facilities' })).toHaveProperty('disabled', true);
  expect(screen.getByRole('group', { name: 'Accessibility needs' })).toHaveProperty('disabled', true);
});

it('populates layout, facility and accessibility options from the selected venue, with an Others option', async () => {
  const request = vi.fn(async (path: string) => {
    if (path === '/api/venues') return response({ venues: [{ id: harbourHall.id, name: harbourHall.name, location: harbourHall.location }] });
    if (path === `/api/venues/${harbourHall.id}`) return response({ venue: harbourHall });
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'Harbour Hall' })).toBeTruthy());
  fireEvent.change(screen.getByRole('combobox', { name: /Venue/ }), { target: { value: String(harbourHall.id) } });

  await waitFor(() => expect(screen.getByRole('combobox', { name: /Preferred room layout/ })).toHaveProperty('disabled', false));
  expect(screen.getByRole('option', { name: 'Theatre' })).toBeTruthy();
  expect(screen.getByRole('option', { name: 'Boardroom' })).toBeTruthy();
  expect(screen.getByLabelText('Projector')).toBeTruthy();
  expect(screen.getByLabelText('Step-free access')).toBeTruthy();
  expect(screen.getByLabelText('Wheelchair access')).toBeTruthy();
  expect(screen.getByLabelText('Hearing loop')).toBeTruthy();
  expect(screen.getAllByLabelText('Others')).toHaveLength(2);
});

it('lets the organiser type a custom layout, facility and accessibility value under Others', async () => {
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues') return response({ venues: [{ id: harbourHall.id, name: harbourHall.name, location: harbourHall.location }] });
    if (path === `/api/venues/${harbourHall.id}`) return response({ venue: harbourHall });
    if (path === '/api/event-requests' && init?.method === 'POST') return response({ event_request: created }, 201);
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'Harbour Hall' })).toBeTruthy());
  fireEvent.change(screen.getByRole('combobox', { name: /Venue/ }), { target: { value: String(harbourHall.id) } });
  await waitFor(() => expect(screen.getByRole('combobox', { name: /Preferred room layout/ })).toHaveProperty('disabled', false));

  fireEvent.change(screen.getByRole('combobox', { name: /Preferred room layout/ }), { target: { value: 'others' } });
  fireEvent.change(screen.getByLabelText('Custom room layout'), { target: { value: 'Cabaret' } });
  fireEvent.click(screen.getByLabelText('Projector'));
  fireEvent.click(screen.getAllByLabelText('Others')[0]);
  fireEvent.change(screen.getByPlaceholderText('Separate items with commas'), { target: { value: 'Stage lighting' } });
  fireEvent.click(screen.getByLabelText('Wheelchair access'));

  await fillMandatoryFields();
  fireEvent.click(screen.getByRole('button', { name: 'Submit event request' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests', expect.objectContaining({ method: 'POST' })));
  const call = request.mock.calls.find(([path]) => path === '/api/event-requests');
  const body = JSON.parse(call?.[1]?.body as string);
  expect(body).toMatchObject({
    preferred_room_layout: 'Cabaret',
    required_facilities: ['Projector', 'Stage lighting'],
    accessibility_needs: ['Wheelchair access'],
  });
});

it('clears previously chosen layout, facility and accessibility selections when the venue changes', async () => {
  const otherVenue = {
    id: 8,
    name: 'Garden Room',
    location: 'Level 1',
    description: null,
    facilities: ['Whiteboard'],
    accessibility_features: ['Ramp access'],
    operating_slots: ['AM'],
    setup_buffer_slots: 0,
    turnaround_buffer_slots: 0,
    layouts: [{ id: 3, layout: 'Classroom', capacity: 40 }],
  };
  const request = vi.fn(async (path: string) => {
    if (path === '/api/venues') {
      return response({ venues: [
        { id: harbourHall.id, name: harbourHall.name, location: harbourHall.location },
        { id: otherVenue.id, name: otherVenue.name, location: otherVenue.location },
      ] });
    }
    if (path === `/api/venues/${harbourHall.id}`) return response({ venue: harbourHall });
    if (path === `/api/venues/${otherVenue.id}`) return response({ venue: otherVenue });
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'Harbour Hall' })).toBeTruthy());
  fireEvent.change(screen.getByRole('combobox', { name: /Venue/ }), { target: { value: String(harbourHall.id) } });
  await waitFor(() => expect(screen.getByRole('combobox', { name: /Preferred room layout/ })).toHaveProperty('disabled', false));

  fireEvent.change(screen.getByRole('combobox', { name: /Preferred room layout/ }), { target: { value: 'Theatre' } });
  fireEvent.click(screen.getByLabelText('Projector'));
  fireEvent.click(screen.getByLabelText('Wheelchair access'));

  fireEvent.change(screen.getByRole('combobox', { name: /Venue/ }), { target: { value: String(otherVenue.id) } });
  await waitFor(() => expect(screen.getByRole('option', { name: 'Classroom' })).toBeTruthy());

  expect(screen.getByRole('combobox', { name: /Preferred room layout/ })).toHaveProperty('value', '');
  expect(screen.getByLabelText('Whiteboard')).toHaveProperty('checked', false);
  expect(screen.getByLabelText('Ramp access')).toHaveProperty('checked', false);
  expect(screen.queryByLabelText('Projector')).toBeNull();
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
      required_facilities: [], facilities_notes: null, accessibility_needs: [],
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

it('pulls a previously saved venue, layout, facilities and accessibility choices back onto the page when reopening a draft (SPL-128)', async () => {
  const request = vi.fn(async (path: string) => {
    if (path === '/api/venues') return response({ venues: [{ id: harbourHall.id, name: harbourHall.name, location: harbourHall.location }] });
    if (path === `/api/venues/${harbourHall.id}`) return response({ venue: harbourHall });
    if (path === '/api/event-requests/99') return response({ event_request: {
      id: 99, name: 'Reunion', purpose: 'Reconnect', description: null, proposed_date: '2099-01-01',
      start_time: '07:00', end_time: '12:00', expected_attendance: 60,
      preferred_room_layout: 'Boardroom',
      required_facilities: ['Projector', 'Custom AV cart'],
      facilities_notes: null,
      accessibility_needs: ['Wheelchair access', 'Sign language interpreter'],
      location_preference: null, venue_notes: null, venue_id: harbourHall.id,
      registration_required: false, registration_notes: null,
      last_saved_at: '2026-09-19T09:00:00+00:00', equipment_requirements: [],
    } });
    return response({}, 404);
  });
  render(<EventRequestForm accessToken="token" request={request} draftId={99} />);

  expect(await screen.findByDisplayValue('Reunion')).toBeTruthy();
  await waitFor(() => expect(screen.getByRole('combobox', { name: /Venue/ })).toHaveProperty('value', String(harbourHall.id)));

  // Known venue-scoped values are pulled back as the selected option/checkboxes...
  await waitFor(() => expect(screen.getByRole('combobox', { name: /Preferred room layout/ })).toHaveProperty('value', 'Boardroom'));
  expect(screen.getByLabelText('Projector')).toHaveProperty('checked', true);
  expect(screen.getByLabelText('Wheelchair access')).toHaveProperty('checked', true);

  // ...and values that aren't in the venue's own lists are preserved under Others, not dropped.
  const facilitiesFieldset = screen.getByRole('group', { name: 'Required facilities' });
  const accessibilityFieldset = screen.getByRole('group', { name: 'Accessibility needs' });
  expect(within(facilitiesFieldset).getByLabelText('Others')).toHaveProperty('checked', true);
  expect(within(facilitiesFieldset).getByDisplayValue('Custom AV cart')).toBeTruthy();
  expect(within(accessibilityFieldset).getByLabelText('Others')).toHaveProperty('checked', true);
  expect(within(accessibilityFieldset).getByDisplayValue('Sign language interpreter')).toBeTruthy();
});

it('submits an in-progress draft through the drafts submit endpoint, not the plain create endpoint', async () => {
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/venues') return response({ venues: [] });
    if (path === '/api/event-requests/7') return response({ event_request: {
      id: 7, name: 'Alumni Homecoming', purpose: null, description: null, proposed_date: null,
      start_time: null, end_time: null, expected_attendance: null, preferred_room_layout: null,
      required_facilities: [], facilities_notes: null, accessibility_needs: [],
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
