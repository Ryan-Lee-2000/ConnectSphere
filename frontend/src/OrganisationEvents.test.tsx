import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { OrganisationEvents } from './OrganisationEvents';

function response(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: async () => body } as Response);
}

function spl110Event(overrides: Record<string, unknown> = {}) {
  return {
    id: 110,
    name: 'Community Forum',
    purpose: 'Bring community partners together',
    description: 'A practical working session.',
    proposed_date: '2026-12-04',
    start_time: '09:30',
    end_time: '12:00',
    expected_attendance: 80,
    responsible_organiser: 'Aisha Rahman',
    status: 'confirmed',
    status_label: 'Confirmed',
    status_explanation: 'The event is confirmed.',
    coordinator: { id: 'c', name: 'Casey Lim' },
    venue_arrangements: [{
      booking_id: 1, venue: 'Harbour Hall', location: '8 Marina Way', date: '2026-12-04',
      start_time: '09:30', end_time: '12:00', status: 'approved', status_label: 'Approved',
    }],
    equipment_arrangements: [{
      requirement_id: 1, equipment: 'Wireless Microphone', required_quantity: 4,
      reserved_quantity: 4, status: 'reserved', status_label: 'Reserved',
      essentiality: 'essential', essentiality_label: 'Essential',
    }],
    registration_settings: {
      enabled: true, capacity: 75, opens_at: '2026-11-01T09:00:00+08:00',
      closes_at: '2026-12-03T18:00:00+08:00',
    },
    clarifications: [],
    ...overrides,
  };
}

// SPL-45 AC-1,2,3,4 Test-01
it('lists each submitted organisation event with the required summary fields', async () => {
  const request = vi.fn().mockReturnValue(response({ events: [
    { id: 7, name: 'Community Forum', proposed_date: '2026-12-04', responsible_organiser: 'Aisha Rahman' },
    { id: 8, name: 'Partner Briefing', proposed_date: '2026-12-08', responsible_organiser: 'Marcus Tan' },
  ] }));

  render(<OrganisationEvents accessToken="token" onNavigate={vi.fn()} request={request} />);

  expect(await screen.findByRole('link', { name: 'Community Forum' })).toBeTruthy();
  expect(screen.getByText('4 Dec 2026')).toBeTruthy();
  expect(screen.getByText('Aisha Rahman')).toBeTruthy();
  expect(screen.getByText('Partner Briefing')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/organisation/events');
});

// SPL-45 AC-5 Test-02
it('opens an event through the workspace route', async () => {
  const onNavigate = vi.fn();
  const request = vi.fn().mockReturnValue(response({ events: [
    { id: 7, name: 'Community Forum', proposed_date: '2026-12-04', responsible_organiser: 'Aisha Rahman' },
  ] }));
  render(<OrganisationEvents accessToken="token" onNavigate={onNavigate} request={request} />);

  fireEvent.click(await screen.findByRole('link', { name: 'Community Forum' }));

  expect(onNavigate).toHaveBeenCalledWith('/workspace/organisation-events/7');
});

// SPL-45 AC-5 Test-02
it('shows every approved detail field and identifies the view as read-only', async () => {
  const request = vi.fn().mockReturnValue(response({ event: {
    id: 7,
    name: 'Community Forum',
    purpose: 'Bring community partners together',
    description: 'A practical working session.',
    proposed_date: '2026-12-04',
    start_time: '09:30',
    end_time: '12:00',
    expected_attendance: 80,
    responsible_organiser: 'Aisha Rahman',
  } }));

  render(<OrganisationEvents accessToken="token" eventId={7} onNavigate={vi.fn()} request={request} />);

  expect(await screen.findByRole('heading', { name: 'Community Forum' })).toBeTruthy();
  for (const value of [
    'Read-only event information',
    'Bring community partners together',
    'A practical working session.',
    '4 Dec 2026',
    '09:30 to 12:00',
    '80',
    'Aisha Rahman',
  ]) expect(screen.getByText(value)).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/organisation/events/7');
});

// SPL-45 AC-9 Test-06
it('teaches an organiser what an empty result means', async () => {
  const request = vi.fn().mockReturnValue(response({ events: [] }));
  render(<OrganisationEvents accessToken="token" onNavigate={vi.fn()} request={request} />);

  const message = await screen.findByRole('status');
  expect(message.textContent).toContain('No submitted events yet.');
  expect(message.textContent).toContain('after an organiser submits them');
});

// SPL-45 AC-7 Test-03
it('does not render protected event information after a refused detail request', async () => {
  const request = vi.fn().mockReturnValue(response({ error: 'Event not found.' }, false));
  render(<OrganisationEvents accessToken="token" eventId={99} onNavigate={vi.fn()} request={request} />);

  expect((await screen.findByRole('alert')).textContent).toContain(
    "We couldn't find that event in your client organisation.",
  );
  expect(screen.queryByText('Other client event')).toBeNull();
});

// SPL-65 AC-5 Test-12
it('[TC-SPL-65-12] shows the returned status and the clarification message read-only', async () => {
  const request = vi.fn().mockReturnValue(response({ event: {
    id: 7, name: 'Community Forum', purpose: 'Bring partners together', description: null,
    proposed_date: '2026-12-04', start_time: '09:30', end_time: '12:00', expected_attendance: 80,
    responsible_organiser: 'Aisha Rahman', status: 'returned_for_clarification',
    status_label: 'Returned for clarification',
    status_explanation: 'Your Event Coordinator needs more information.',
    clarifications: [{
      id: 1, message: 'Please confirm the attendance.', author: { id: 'a', name: 'Alice Tan' },
      created_at: '2026-09-26T10:00:00+08:00',
    }],
  } }));

  render(<OrganisationEvents accessToken="token" eventId={7} onNavigate={vi.fn()} request={request} />);

  expect(await screen.findByText('Returned for clarification')).toBeTruthy();
  expect(screen.getByText('Please confirm the attendance.')).toBeTruthy();
  expect(screen.getByText(/Alice Tan/)).toBeTruthy();
  expect(screen.queryByRole('textbox')).toBeNull();
});

it('[TC-SPL-110-009] presents the configured arrangement summary and assigned coordinator', async () => {
  const request = vi.fn().mockReturnValue(response({ event: spl110Event() }));

  render(<OrganisationEvents accessToken="token" eventId={110} onNavigate={vi.fn()} request={request} />);

  expect(await screen.findByRole('heading', { name: 'Event arrangements' })).toBeTruthy();
  for (const value of [
    'Confirmed', 'Casey Lim', 'Harbour Hall', '8 Marina Way', 'Approved',
    'Wireless Microphone', '4/4', 'Reserved', 'Essential', 'Enabled', '75',
    '1 Nov 2026, 9:00 am', '3 Dec 2026, 6:00 pm',
  ]) expect(screen.getByText(value)).toBeTruthy();
});

it('[TC-SPL-110-010] distinguishes review and unavailable states from approved arrangements', async () => {
  const event = spl110Event({
    venue_arrangements: [{
      booking_id: 2, venue: 'Studio One', location: null, date: '2026-12-04',
      start_time: '09:30', end_time: '12:00', status: 'review_required',
      status_label: 'Review required',
    }],
    equipment_arrangements: [{
      requirement_id: 2, equipment: 'Projector', required_quantity: 2, reserved_quantity: 0,
      status: 'unavailable', status_label: 'Unavailable', essentiality: 'non_essential',
      essentiality_label: 'Non-essential',
    }],
    registration_settings: { enabled: false, capacity: null, opens_at: null, closes_at: null },
  });
  const request = vi.fn().mockReturnValue(response({ event }));

  render(<OrganisationEvents accessToken="token" eventId={110} onNavigate={vi.fn()} request={request} />);

  expect(await screen.findByText('Review required')).toBeTruthy();
  expect(screen.getByText('Unavailable')).toBeTruthy();
  expect(screen.getByText('0/2')).toBeTruthy();
  expect(screen.getByText('Non-essential')).toBeTruthy();
  expect(screen.getAllByText('Not configured')).toHaveLength(4);
  expect(screen.queryByText('Approved')).toBeNull();
});

it('[TC-SPL-110-011] keeps arrangements read-only and requests no mutation', async () => {
  const request = vi.fn().mockReturnValue(response({ event: spl110Event() }));

  render(<OrganisationEvents accessToken="token" eventId={110} onNavigate={vi.fn()} request={request} />);

  expect(await screen.findByText('This summary is read-only. Pending decisions and reviews are labelled separately from approved arrangements.')).toBeTruthy();
  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByRole('form')).toBeNull();
  expect(request).toHaveBeenCalledTimes(1);
  expect(request).toHaveBeenCalledWith('/api/organisation/events/110');
});
