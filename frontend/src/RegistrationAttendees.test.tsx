import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { RegistrationAttendees } from './RegistrationAttendees';

function response(registrationList: unknown, ok = true) {
  return Promise.resolve({ ok, json: async () => ({ registration_list: registrationList }) } as Response);
}

const attendee = {
  id: 1,
  name: 'Avery Attendee',
  email: 'avery@example.test',
  contact_number: '+65 9000 1191',
  special_requirements: 'Step-free access',
};

const enabled = {
  enabled: true,
  capacity: 100,
  registered_count: 1,
  registered: [attendee],
  withdrawn: [],
};

// QA-SPL-119-029 | AC2 | BB rendered fields
it('QA-SPL-119-029: renders the count, capacity and every attendee field', async () => {
  const request = vi.fn().mockReturnValue(response(enabled));
  render(<RegistrationAttendees accessToken="token" eventId={119} request={request} />);

  expect(await screen.findByLabelText('1 of 100 places registered')).toBeTruthy();
  for (const value of ['1/100', 'Avery Attendee', 'avery@example.test', '+65 9000 1191', 'Step-free access']) {
    expect(screen.getByText(value)).toBeTruthy();
  }
  expect(request).toHaveBeenCalledWith('/api/organisation/events/119/registrations');
});

// QA-SPL-119-030 | AC3 | BB separate rendered groups
it('QA-SPL-119-030: renders withdrawn attendees in their own labelled table', async () => {
  const former = { ...attendee, id: 2, name: 'Former Attendee' };
  const request = vi.fn().mockReturnValue(response({ ...enabled, withdrawn: [former] }));
  render(<RegistrationAttendees accessToken="token" eventId={119} request={request} />);

  expect(await screen.findByRole('heading', { name: 'Current registrations' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Withdrawn registrations' })).toBeTruthy();
  expect(screen.getByRole('table', { name: 'Currently registered attendees' }).textContent).toContain('Avery Attendee');
  expect(screen.getByRole('table', { name: 'Withdrawn attendee registrations' }).textContent).toContain('Former Attendee');
});

// QA-SPL-119-020 | AC4 | BB disabled state
it('QA-SPL-119-020: explains disabled registration instead of showing empty lists', async () => {
  const request = vi.fn().mockReturnValue(response({
    enabled: false, capacity: null, registered_count: 0, registered: [], withdrawn: [],
  }));
  render(<RegistrationAttendees accessToken="token" eventId={119} request={request} />);

  expect(await screen.findByText('Registration is not enabled for this event.')).toBeTruthy();
  expect(screen.queryByRole('table')).toBeNull();
  expect(screen.queryByText('No attendees are currently registered.')).toBeNull();
});

// QA-SPL-119-024 | AC5 | BB UI scope
it('QA-SPL-119-024: offers no export or download control', async () => {
  const request = vi.fn().mockReturnValue(response(enabled));
  render(<RegistrationAttendees accessToken="token" eventId={119} request={request} />);
  await screen.findByRole('table', { name: 'Currently registered attendees' });

  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.queryByRole('link', { name: /export|download/i })).toBeNull();
});

// QA-SPL-119-025 | AC5 | BB link allowlist
it('QA-SPL-119-025: the only attendee link is the displayed email address', async () => {
  const request = vi.fn().mockReturnValue(response(enabled));
  render(<RegistrationAttendees accessToken="token" eventId={119} request={request} />);
  const links = await screen.findAllByRole('link');

  expect(links).toHaveLength(1);
  expect(links[0].getAttribute('href')).toBe('mailto:avery@example.test');
});

// QA-SPL-119-026 | AC2 | BB nullable presentation
it('QA-SPL-119-026: labels missing special requirements without inventing details', async () => {
  const request = vi.fn().mockReturnValue(response({
    ...enabled, registered: [{ ...attendee, special_requirements: null }],
  }));
  render(<RegistrationAttendees accessToken="token" eventId={119} request={request} />);
  expect(await screen.findByText('None recorded')).toBeTruthy();
});

// QA-SPL-119-027 | AC2,AC3 | BB empty boundaries
it('QA-SPL-119-027: labels both enabled empty groups while retaining zero capacity count', async () => {
  const request = vi.fn().mockReturnValue(response({
    enabled: true, capacity: 10, registered_count: 0, registered: [], withdrawn: [],
  }));
  render(<RegistrationAttendees accessToken="token" eventId={119} request={request} />);

  expect(await screen.findByLabelText('0 of 10 places registered')).toBeTruthy();
  expect(screen.getByText('No attendees are currently registered.')).toBeTruthy();
  expect(screen.getByText('No withdrawn registrations.')).toBeTruthy();
});

// QA-SPL-119-028 | AC1 | BB failure and retry
it('QA-SPL-119-028: exposes a safe load error and retries the same protected endpoint', async () => {
  const request = vi.fn()
    .mockRejectedValueOnce(new Error('network detail must stay hidden'))
    .mockReturnValueOnce(response(enabled));
  render(<RegistrationAttendees accessToken="token" eventId={119} request={request} />);

  expect((await screen.findByRole('alert')).textContent).toContain("We couldn't load this event's registrations.");
  expect(screen.queryByText('network detail must stay hidden')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  expect(await screen.findByText('Avery Attendee')).toBeTruthy();
});
