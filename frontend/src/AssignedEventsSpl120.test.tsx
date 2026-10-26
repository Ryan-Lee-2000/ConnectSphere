import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';

afterEach(cleanup);

const event = {
  id: 120,
  name: 'SPL-120 Registration List',
  status: 'planning',
  status_label: 'In planning',
  proposed_date: '2026-11-20',
  mapped_slots: ['PM'],
  expected_attendance: 80,
  purpose: 'Coordinator registration overview',
  equipment_requirements: [],
  equipment_readiness: {
    ready: true,
    has_equipment_blocker: false,
    active_requirement_count: 0,
    blockers: [],
  },
};

const attendee = {
  id: 1,
  name: 'Avery Attendee',
  email: 'avery@example.test',
  contact_number: '+65 9000 1200',
  special_requirements: 'Step-free access',
};

const enabledList = {
  enabled: true,
  capacity: 80,
  registered_count: 1,
  registered: [attendee],
  withdrawn: [],
};

function detailResponse(capability = true) {
  return Promise.resolve({
    ok: true,
    headers: new Headers(capability ? { 'X-ConnectSphere-Registration-List': 'available' } : {}),
    json: async () => ({ event }),
  } as Response);
}

function listResponse(registrationList: unknown = enabledList) {
  return Promise.resolve({
    ok: true,
    json: async () => ({ registration_list: registrationList }),
  } as Response);
}

function renderPage(registrationList: unknown = enabledList) {
  const request = vi.fn((path: string) => path.endsWith('/registrations')
    ? listResponse(registrationList)
    : detailResponse());
  render(<AssignedEvents accessToken="token" eventId={120} request={request} onNavigate={vi.fn()} />);
  return request;
}

// QA-SPL-120-014 | AC3 | BB accessible from event page
it('QA-SPL-120-014: renders the registration list inside the assigned event page', async () => {
  renderPage();
  expect(await screen.findByRole('heading', { name: 'Registered attendees' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'SPL-120 Registration List' })).toBeTruthy();
});

// QA-SPL-120-015 | AC3 | WB coordinator endpoint wiring
it('QA-SPL-120-015: loads the panel through the assigned-event endpoint', async () => {
  const request = renderPage();
  await screen.findByRole('heading', { name: 'Registered attendees' });
  expect(request).toHaveBeenCalledWith('/api/event-requests/assigned/120/registrations');
  expect(request).not.toHaveBeenCalledWith('/api/organisation/events/120/registrations');
});

// QA-SPL-120-016 | AC3 | BB rolling-deploy boundary
it('QA-SPL-120-016: omits the panel when the event response has no capability header', async () => {
  const request = vi.fn((_path: string) => detailResponse(false));
  render(<AssignedEvents accessToken="token" eventId={120} request={request} onNavigate={vi.fn()} />);
  expect(await screen.findByRole('heading', { name: 'SPL-120 Registration List' })).toBeTruthy();
  await waitFor(() => expect(request).toHaveBeenCalled());
  expect(request.mock.calls.map(call => call[0]).filter(path => path.endsWith('/registrations'))).toHaveLength(0);
  expect(screen.queryByRole('heading', { name: 'Registered attendees' })).toBeNull();
});

// QA-SPL-120-017 | AC3 | BB disabled-registration presentation
it('QA-SPL-120-017: explains disabled registration on the assigned event page', async () => {
  renderPage({
    enabled: false,
    capacity: null,
    registered_count: 0,
    registered: [],
    withdrawn: [],
  });
  expect(await screen.findByText('Registration is not enabled for this event.')).toBeTruthy();
  expect(screen.queryByRole('table', { name: 'Currently registered attendees' })).toBeNull();
});

// QA-SPL-120-018 | AC3 | BB safe error and retry
it('QA-SPL-120-018: exposes a safe load error and retries from the event page', async () => {
  let registrationAttempts = 0;
  const request = vi.fn((path: string) => {
    if (!path.endsWith('/registrations')) return detailResponse();
    registrationAttempts += 1;
    if (registrationAttempts === 1) return Promise.reject(new Error('private network detail'));
    return listResponse();
  });
  render(<AssignedEvents accessToken="token" eventId={120} request={request} onNavigate={vi.fn()} />);

  expect((await screen.findByRole('alert')).textContent).toContain("We couldn't load this event's registrations.");
  expect(screen.queryByText('private network detail')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('Avery Attendee')).toBeTruthy();
  expect(registrationAttempts).toBe(2);
});

// QA-SPL-120-019 | AC2 | BB same approved fields as CS-E19-S6
it('QA-SPL-120-019: displays count, capacity and every approved attendee field', async () => {
  renderPage();
  expect(await screen.findByLabelText('1 of 80 places registered')).toBeTruthy();
  for (const value of [
    '1/80',
    'Avery Attendee',
    'avery@example.test',
    '+65 9000 1200',
    'Step-free access',
  ]) {
    expect(screen.getByText(value)).toBeTruthy();
  }
});
