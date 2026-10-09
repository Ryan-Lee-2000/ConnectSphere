import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { RegisterForEvent } from './RegisterForEvent';
afterEach(cleanup);

// SPL-116 (CS-E19-S3) component cases. The server rules are proved in
// backend/tests/test_event_registrations.py; these prove an attendee can use them.

const EVENT = { id: 12, name: 'Harbour Lights Gala' };
const CONFIRMATION = {
  registration: {
    id: 7, status: 'registered', name: 'Avery Koh', email: 'avery@example.test', contact_number: '+65 9123 4567',
    special_requirements: 'Vegetarian meal', registered_at: '2026-10-20T12:00:00+08:00',
  },
  event: {
    id: 12, name: 'Harbour Lights Gala', description: 'An evening of music by the water.', date: '2026-11-20',
    start_time: '18:00', end_time: '22:00', venues: ['Harbour Hall'], places_remaining: 9,
  },
};

function api(reply: { status: number; body: unknown }) {
  return vi.fn(async () => ({ ok: reply.status < 300, status: reply.status, json: async () => reply.body })) as unknown as
    ApiRequest & ReturnType<typeof vi.fn>;
}

function fill(values: Partial<Record<'Name' | 'Email address' | 'Contact number' | 'Special requirements (optional)', string>>) {
  for (const [label, value] of Object.entries(values)) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
}

// TC-SPL-116-13
// SPL-116 AC-2 Test-13
it('[TC-SPL-116-13] marks name, email address and contact number as required, and special requirements as optional', () => {
  render(<RegisterForEvent api={api({ status: 201, body: CONFIRMATION })} event={EVENT} />);

  for (const label of ['Name', 'Email address', 'Contact number']) {
    expect((screen.getByLabelText(label) as HTMLInputElement).required).toBe(true);
  }
  expect((screen.getByLabelText('Special requirements (optional)') as HTMLTextAreaElement).required).toBe(false);
  expect((screen.getByLabelText('Email address') as HTMLInputElement).type).toBe('email');
});

// TC-SPL-116-13
// SPL-116 AC-1,7 Test-13
it('[TC-SPL-116-13] sends the details and shows the confirmation with the event and what was submitted', async () => {
  const request = api({ status: 201, body: CONFIRMATION });
  const onRegistered = vi.fn();
  render(<RegisterForEvent api={request} event={EVENT} onRegistered={onRegistered} />);

  fill({ Name: 'Avery Koh', 'Email address': 'avery@example.test', 'Contact number': '+65 9123 4567',
    'Special requirements (optional)': 'Vegetarian meal' });
  fireEvent.click(screen.getByRole('button', { name: 'Register' }));

  const confirmation = await screen.findByRole('region', { name: 'You are registered' });
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/registrations', {
    method: 'POST',
    body: JSON.stringify({ name: 'Avery Koh', email: 'avery@example.test', contact_number: '+65 9123 4567',
      special_requirements: 'Vegetarian meal' }),
  });
  const text = confirmation.textContent ?? '';
  for (const fact of ['Harbour Lights Gala', '20 Nov 2026', '18:00–22:00', 'Harbour Hall', 'Avery Koh',
    'avery@example.test', '+65 9123 4567', 'Vegetarian meal']) {
    expect(text).toContain(fact);
  }
  expect(screen.queryByRole('button', { name: 'Register' })).toBeNull();
  expect(onRegistered).toHaveBeenCalledWith(CONFIRMATION);
});

// TC-SPL-116-13
// SPL-116 AC-2 Test-13
it('[TC-SPL-116-13] shows a refusal beside the field the server names, and keeps what was typed', async () => {
  const request = api({ status: 400, body: { error: 'Enter an email address in the form name@domain.', field: 'email' } });
  render(<RegisterForEvent api={request} event={EVENT} />);

  fill({ Name: 'Avery Koh', 'Email address': 'avery@example', 'Contact number': '91234567' });
  fireEvent.click(screen.getByRole('button', { name: 'Register' }));

  const message = await screen.findByText('Enter an email address in the form name@domain.');
  const email = screen.getByLabelText('Email address') as HTMLInputElement;
  expect(email.getAttribute('aria-invalid')).toBe('true');
  expect(email.getAttribute('aria-describedby')).toBe(message.id);
  expect(email.value).toBe('avery@example');
  expect(screen.queryByRole('region', { name: 'You are registered' })).toBeNull();
});

// TC-SPL-116-13
// SPL-116 AC-3,5 Test-13
it('[TC-SPL-116-13] shows a refusal that is not about one field, such as a full event', async () => {
  render(<RegisterForEvent api={api({ status: 409, body: { error: 'This event is full.' } })} event={EVENT} />);

  fill({ Name: 'Avery Koh', 'Email address': 'avery@example.test', 'Contact number': '91234567' });
  fireEvent.click(screen.getByRole('button', { name: 'Register' }));

  expect((await screen.findByRole('alert')).textContent).toBe('This event is full.');
  expect(screen.queryByRole('region', { name: 'You are registered' })).toBeNull();
});
