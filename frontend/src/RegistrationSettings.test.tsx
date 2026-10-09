import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { AssignedEvents } from './AssignedEvents';
import { RegistrationSettingsPanel } from './RegistrationSettings';
afterEach(cleanup);

// SPL-114 (CS-E19-S1) component cases. The server rules themselves are proved in
// backend/tests/test_registration_settings.py; these prove the coordinator can use them.

const OFF = {
  enabled: false, state: 'off', opens_at: null, closes_at: null, capacity: null,
  max_capacity: 120, event_starts_at: '2026-11-20T18:00:00+08:00', history: [],
};
const ENABLED = {
  ...OFF, enabled: true, state: 'not_yet_open', opens_at: '2026-10-10T09:00:00+08:00',
  closes_at: '2026-11-19T18:00:00+08:00', capacity: 100,
  history: [{
    previous: null,
    current: { opens_at: '2026-10-10T09:00:00+08:00', closes_at: '2026-11-19T18:00:00+08:00', capacity: 100 },
    changed_by: { id: 'casey', name: 'Casey Lim' }, changed_at: '2026-10-07T09:00:00+08:00',
  }],
};

type Reply = { status: number; body: unknown };
function api(settings: object, save?: Reply) {
  return vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      return { ok: (save?.status ?? 200) < 300, status: save?.status ?? 200, json: async () => save?.body };
    }
    return { ok: true, status: 200, json: async () => ({ registration: settings }) };
  }) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
}
const saves = (request: ReturnType<typeof vi.fn>) => request.mock.calls.filter(([, init]) => init?.method === 'PUT');

function fill(opens: string, closes: string, capacity: string) {
  fireEvent.change(screen.getByLabelText('Registration opens'), { target: { value: opens } });
  fireEvent.change(screen.getByLabelText('Registration closes'), { target: { value: closes } });
  fireEvent.change(screen.getByLabelText('Capacity'), { target: { value: capacity } });
}

// TC-SPL-114-19
// SPL-114 AC-1,3 Test-19
it('[TC-SPL-114-19] offers the three settings, with the booked layout limit, while registration is off', async () => {
  const request = api(OFF);
  render(<RegistrationSettingsPanel api={request} eventId={12} />);

  expect(await screen.findByText('Registration is off. Attendees cannot see or register for this event.')).toBeTruthy();
  expect(screen.getByLabelText('Registration opens')).toBeTruthy();
  expect(screen.getByLabelText('Registration closes')).toBeTruthy();
  expect((screen.getByLabelText('Capacity') as HTMLInputElement).max).toBe('120');
  expect(screen.getByText('Up to 120 places, the capacity of the booked layout.')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Enable registration' })).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/registration');
});

// TC-SPL-114-19
// SPL-114 AC-1,4,6 Test-19
it('[TC-SPL-114-19] saves Singapore times and a whole-number capacity, then shows the saved settings', async () => {
  const request = api(OFF, { status: 200, body: { registration: ENABLED } });
  render(<RegistrationSettingsPanel api={request} eventId={12} />);
  await screen.findByRole('button', { name: 'Enable registration' });

  fill('2026-10-10T09:00', '2026-11-19T18:00', '100');
  fireEvent.click(screen.getByRole('button', { name: 'Enable registration' }));

  expect((await screen.findByRole('status')).textContent).toBe('Registration enabled.');
  expect(saves(request)).toEqual([['/api/event-requests/12/registration', {
    method: 'PUT',
    body: JSON.stringify({ opens_at: '2026-10-10T09:00', closes_at: '2026-11-19T18:00', capacity: 100 }),
  }]]);
  // After saving, the form becomes a change form showing the saved values and the history.
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeTruthy();
  expect((screen.getByLabelText('Registration opens') as HTMLInputElement).value).toBe('2026-10-10T09:00');
  expect(screen.getByText(/Not yet open/)).toBeTruthy();
  expect(within(screen.getByRole('list', { name: 'Registration change history' })).getByText(/Casey Lim/)).toBeTruthy();
});

// TC-SPL-114-19
// SPL-114 AC-2 Test-19
it('[TC-SPL-114-19] shows a refused rule next to the field it names, and changes nothing', async () => {
  const refusal = { error: 'Registration must close before the event starts.', field: 'closes_at' };
  const request = api(OFF, { status: 400, body: refusal });
  render(<RegistrationSettingsPanel api={request} eventId={12} />);
  await screen.findByRole('button', { name: 'Enable registration' });

  fill('2026-10-10T09:00', '2026-11-20T18:00', '100');
  fireEvent.click(screen.getByRole('button', { name: 'Enable registration' }));

  const message = await screen.findByText(refusal.error);
  const closes = screen.getByLabelText('Registration closes');
  expect(closes.getAttribute('aria-invalid')).toBe('true');
  expect(closes.getAttribute('aria-describedby')).toBe(message.id);
  expect(screen.getByRole('button', { name: 'Enable registration' })).toBeTruthy();
  expect(screen.queryByText('Registration enabled.')).toBeNull();
});

// TC-SPL-114-19
// SPL-114 AC-3 Test-19
it('[TC-SPL-114-19] explains that an Approved booking is needed before capacity can be set', async () => {
  render(<RegistrationSettingsPanel api={api({ ...OFF, max_capacity: null })} eventId={12} />);

  expect(await screen.findByText('Registration needs an Approved venue booking to set its capacity against.')).toBeTruthy();
  expect((screen.getByRole('button', { name: 'Enable registration' }) as HTMLButtonElement).disabled).toBe(true);
});

// TC-SPL-114-19
// SPL-114 AC-7 Test-19
it('[TC-SPL-114-19] appears on the assigned event page only while the event is Confirmed', async () => {
  for (const [status, shown] of [['confirmed', true], ['planning', false], ['completed', false]] as const) {
    const request = vi.fn(async (path: string) => {
      if (path === '/api/event-requests/assigned/12') {
        return { ok: true, status: 200, json: async () => ({ event: { id: 12, name: 'Harbour Lights Gala', status, status_label: status, proposed_date: '2026-11-20', mapped_slots: [] } }) };
      }
      if (path.endsWith('/registration')) return { ok: true, status: 200, json: async () => ({ registration: OFF }) };
      return { ok: true, status: 200, json: async () => ({ booking: null, history: [] }) };
    }) as unknown as ApiRequest;
    render(<AssignedEvents accessToken="token" eventId={12} onNavigate={() => undefined} request={request} />);

    await screen.findByRole('heading', { name: 'Harbour Lights Gala' });
    if (shown) expect(await screen.findByRole('region', { name: 'Attendee registration' })).toBeTruthy();
    else expect(screen.queryByRole('region', { name: 'Attendee registration' })).toBeNull();
    cleanup();
  }
});
