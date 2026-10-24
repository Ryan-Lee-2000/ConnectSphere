import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { OrganisationEvents } from './OrganisationEvents';

const event = {
  id: 119,
  name: 'SPL-119 Community Forum',
  purpose: 'Measure turnout',
  description: 'Registration-list fixture.',
  proposed_date: '2026-11-20',
  start_time: '14:00',
  end_time: '17:00',
  expected_attendance: 100,
  responsible_organiser: 'Olivia Organiser',
  status: 'submitted',
  status_label: 'Submitted',
  status_explanation: 'Submitted for review.',
  coordinator: null,
  venue_arrangements: [],
  equipment_arrangements: [],
  registration_settings: { enabled: true, capacity: 100, opens_at: null, closes_at: null },
  clarifications: [],
};

function detailResponse(capability: boolean) {
  return {
    ok: true,
    headers: new Headers(capability ? { 'X-ConnectSphere-Registration-List': 'available' } : {}),
    json: async () => ({ event }),
  } as Response;
}

const registrationResponse = {
  ok: true,
  json: async () => ({
    registration_list: {
      enabled: true, capacity: 100, registered_count: 0, registered: [], withdrawn: [],
    },
  }),
} as Response;

// QA-SPL-119-032 | AC2-AC4 | BB capability integration
it('QA-SPL-119-032: loads the attendee panel when the event endpoint advertises it', async () => {
  const request = vi.fn()
    .mockResolvedValueOnce(detailResponse(true))
    .mockResolvedValueOnce(registrationResponse);
  render(<OrganisationEvents accessToken="token" eventId={119} onNavigate={vi.fn()} request={request} />);

  expect(await screen.findByRole('heading', { name: 'Registered attendees' })).toBeTruthy();
  expect(await screen.findByLabelText('0 of 100 places registered')).toBeTruthy();
  expect(request).toHaveBeenNthCalledWith(1, '/api/organisation/events/119');
  expect(request).toHaveBeenNthCalledWith(2, '/api/organisation/events/119/registrations');
});

// QA-SPL-119-033 | AC1 | BB rolling-deploy boundary
it('QA-SPL-119-033: makes no attendee request against a server without the capability header', async () => {
  const request = vi.fn().mockResolvedValue(detailResponse(false));
  render(<OrganisationEvents accessToken="token" eventId={119} onNavigate={vi.fn()} request={request} />);

  expect(await screen.findByRole('heading', { name: 'SPL-119 Community Forum' })).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'Registered attendees' })).toBeNull();
  expect(request).toHaveBeenCalledTimes(1);
});
