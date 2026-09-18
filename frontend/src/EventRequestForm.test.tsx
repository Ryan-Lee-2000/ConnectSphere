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
  equipment_lines: [],
};

it('asks unauthenticated visitors to sign in', () => {
  render(<EventRequestForm accessToken={null} />);
  expect(screen.getByRole('heading', { name: 'Sign in to create an event request' })).toBeTruthy();
});

it('requires the mandatory fields before saving', async () => {
  const request = vi.fn();
  render(<EventRequestForm accessToken="token" request={request} />);
  const save = screen.getByRole('button', { name: 'Submit event request' });
  expect(save).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Alumni Homecoming' } });
  fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Reconnect cohorts' } });
  fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2099-01-01' } });
  fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '18:00' } });
  fireEvent.change(screen.getByLabelText('End time'), { target: { value: '21:00' } });
  expect(save).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '150' } });
  expect(save).toHaveProperty('disabled', false);
});

it('disables saving when start time is not before end time', () => {
  render(<EventRequestForm accessToken="token" request={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Alumni Homecoming' } });
  fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Reconnect cohorts' } });
  fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2099-01-01' } });
  fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '21:00' } });
  fireEvent.change(screen.getByLabelText('End time'), { target: { value: '18:00' } });
  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '150' } });
  expect(screen.getByRole('button', { name: 'Submit event request' })).toHaveProperty('disabled', true);
});

it('adds and removes equipment lines', () => {
  render(<EventRequestForm accessToken="token" request={vi.fn()} />);
  expect(screen.getByText('None recorded.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Add equipment' }));
  expect(screen.getByLabelText('Equipment type 1')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Remove equipment line 1' }));
  expect(screen.getByText('None recorded.')).toBeTruthy();
});

it('submits the mandatory fields and shows the mapped slots on success', async () => {
  const request = vi.fn(async (_path: string, _init?: RequestInit) => response({ event_request: created }, 201));
  render(<EventRequestForm accessToken="token" request={request} />);
  fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Alumni Homecoming' } });
  fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Reconnect cohorts' } });
  fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2099-01-01' } });
  fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '18:00' } });
  fireEvent.change(screen.getByLabelText('End time'), { target: { value: '21:00' } });
  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '150' } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit event request' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests', expect.objectContaining({ method: 'POST' })));
  const body = JSON.parse(request.mock.calls[0][1]?.body as string);
  expect(body).toMatchObject({
    name: 'Alumni Homecoming',
    purpose: 'Reconnect cohorts',
    proposed_date: '2099-01-01',
    start_time: '18:00',
    end_time: '21:00',
    expected_attendance: 150,
    registration_required: false,
    equipment_lines: [],
  });
  expect(await screen.findByText('Event request created.')).toBeTruthy();
  expect(await screen.findByText('This falls in the NIGHT venue slot.')).toBeTruthy();
});

it('shows a server error and only shows registration notes once registration is required', async () => {
  const request = vi.fn(async () => response({ error: 'Start time must be before end time.' }, 400));
  render(<EventRequestForm accessToken="token" request={request} />);
  expect(screen.queryByLabelText('Registration notes')).toBeNull();
  fireEvent.click(screen.getByLabelText('Registration is required for this event'));
  expect(screen.getByLabelText('Registration notes')).toBeTruthy();

  fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Alumni Homecoming' } });
  fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Reconnect cohorts' } });
  fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2099-01-01' } });
  fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '21:00' } });
  fireEvent.change(screen.getByLabelText('End time'), { target: { value: '23:00' } });
  fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '150' } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit event request' }));
  expect(await screen.findByText('Start time must be before end time.')).toBeTruthy();
});
