import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { OrganisationEvents } from './OrganisationEvents';

function response(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: async () => body } as Response);
}

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

it('opens an event through the workspace route', async () => {
  const onNavigate = vi.fn();
  const request = vi.fn().mockReturnValue(response({ events: [
    { id: 7, name: 'Community Forum', proposed_date: '2026-12-04', responsible_organiser: 'Aisha Rahman' },
  ] }));
  render(<OrganisationEvents accessToken="token" onNavigate={onNavigate} request={request} />);

  fireEvent.click(await screen.findByRole('link', { name: 'Community Forum' }));

  expect(onNavigate).toHaveBeenCalledWith('/workspace/organisation-events/7');
});

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

it('teaches an organiser what an empty result means', async () => {
  const request = vi.fn().mockReturnValue(response({ events: [] }));
  render(<OrganisationEvents accessToken="token" onNavigate={vi.fn()} request={request} />);

  const message = await screen.findByRole('status');
  expect(message.textContent).toContain('No submitted events yet.');
  expect(message.textContent).toContain('after an organiser submits them');
});

it('does not render protected event information after a refused detail request', async () => {
  const request = vi.fn().mockReturnValue(response({ error: 'Event not found.' }, false));
  render(<OrganisationEvents accessToken="token" eventId={99} onNavigate={vi.fn()} request={request} />);

  expect((await screen.findByRole('alert')).textContent).toContain(
    "We couldn't find that event in your client organisation.",
  );
  expect(screen.queryByText('Other client event')).toBeNull();
});

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
