import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { WithdrawRegistration } from './WithdrawRegistration';
afterEach(cleanup);

// SPL-118 (CS-E19-S5) component cases. The rules (own registration, still Registered, before the
// start) are enforced by the server and proved in backend/tests/test_registration_withdrawal.py;
// these prove the control asks first, sends nothing on cancel, and is only offered when it can work.

const EVENT = { name: 'Harbour Lights Gala', date: '2026-11-20', start_time: '18:00' };
const REGISTERED = { id: 7, status: 'registered' };
// 20 Nov 2026, 18:00 in Singapore is 10:00 UTC.
const START = new Date('2026-11-20T10:00:00Z');
const BEFORE = () => new Date('2026-10-20T04:00:00Z');
const WITHDRAWN_REPLY = {
  registration: { id: 7, status: 'withdrawn', withdrawn_at: '2026-10-20T12:00:00+08:00' },
  event: { id: 12, name: 'Harbour Lights Gala', places_remaining: 10 },
};

function api(reply: { status: number; body: unknown }) {
  return vi.fn(async () => ({ ok: reply.status < 300, status: reply.status, json: async () => reply.body })) as unknown as
    ApiRequest & ReturnType<typeof vi.fn>;
}

// TC-SPL-118-08
// SPL-118 AC-3 Test-08
it('[TC-SPL-118-08] asks for confirmation first, and cancelling sends nothing', () => {
  const request = api({ status: 200, body: WITHDRAWN_REPLY });
  render(<WithdrawRegistration api={request} registration={REGISTERED} event={EVENT} now={BEFORE} />);

  fireEvent.click(screen.getByRole('button', { name: 'Withdraw from Harbour Lights Gala' }));
  expect(screen.getByText('Withdraw your registration for Harbour Lights Gala? Your place will be released for someone else.')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Keep my registration' }));
  expect(request).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Withdraw from Harbour Lights Gala' })).toBeTruthy();
});

// TC-SPL-118-08
// SPL-118 AC-2 Test-08
it('[TC-SPL-118-08] confirming withdraws and reports the server\'s answer', async () => {
  const request = api({ status: 200, body: WITHDRAWN_REPLY });
  const onWithdrawn = vi.fn();
  render(<WithdrawRegistration api={request} registration={REGISTERED} event={EVENT} now={BEFORE} onWithdrawn={onWithdrawn} />);

  fireEvent.click(screen.getByRole('button', { name: 'Withdraw from Harbour Lights Gala' }));
  fireEvent.click(screen.getByRole('button', { name: 'Yes, withdraw' }));

  expect((await screen.findByRole('status')).textContent).toBe('You have withdrawn from Harbour Lights Gala.');
  // No body: the status and the time are decided by the server.
  expect(request).toHaveBeenCalledWith('/api/registrations/7/withdraw', { method: 'POST' });
  expect(onWithdrawn).toHaveBeenCalledWith(WITHDRAWN_REPLY);
});

// TC-SPL-118-08
// SPL-118 AC-3 Test-08
it('[TC-SPL-118-08] is not offered for a registration that is already Withdrawn', () => {
  const { rerender } = render(<WithdrawRegistration api={api({ status: 200, body: {} })}
    registration={{ id: 7, status: 'withdrawn' }} event={EVENT} now={BEFORE} />);
  expect(screen.queryByRole('button', { name: /Withdraw/ })).toBeNull();

  // Control: the same event and time with a Registered registration does offer it, so an empty
  // component cannot pass this test.
  rerender(<WithdrawRegistration api={api({ status: 200, body: {} })} registration={REGISTERED}
    event={EVENT} now={BEFORE} />);
  expect(screen.getByRole('button', { name: 'Withdraw from Harbour Lights Gala' })).toBeTruthy();
});

// TC-SPL-118-08
// SPL-118 AC-3 Test-08
it('[TC-SPL-118-08] is not offered once the event has started, and is one minute before', () => {
  const { rerender } = render(<WithdrawRegistration api={api({ status: 200, body: {} })} registration={REGISTERED}
    event={EVENT} now={() => START} />);
  expect(screen.queryByRole('button', { name: /Withdraw/ })).toBeNull();

  rerender(<WithdrawRegistration api={api({ status: 200, body: {} })} registration={REGISTERED}
    event={EVENT} now={() => new Date(START.getTime() - 60_000)} />);
  expect(screen.getByRole('button', { name: 'Withdraw from Harbour Lights Gala' })).toBeTruthy();
});

// TC-SPL-118-08
// SPL-118 AC-3 Test-08
it('[TC-SPL-118-08] shows the server\'s refusal and does not claim the withdrawal happened', async () => {
  const request = api({ status: 409, body: { error: 'This event has already started.' } });
  render(<WithdrawRegistration api={request} registration={REGISTERED} event={EVENT} now={BEFORE} />);

  fireEvent.click(screen.getByRole('button', { name: 'Withdraw from Harbour Lights Gala' }));
  fireEvent.click(screen.getByRole('button', { name: 'Yes, withdraw' }));

  expect((await screen.findByRole('alert')).textContent).toBe('This event has already started.');
  expect(screen.queryByRole('status')).toBeNull();
});
