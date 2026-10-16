import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';
import { EventRequestDrafts } from './EventRequestDrafts';

// SPL-85 (CS-E07-S3) interface cases from QA-SPL-85. The server owns the confirmation gate; these
// tests prove the coordinator page displays it faithfully and the organiser sees the outcome.

afterEach(cleanup);

const planning = {
  id: 12, name: 'Community Leadership Forum', status: 'planning', status_label: 'In planning',
  proposed_date: '2026-11-20', mapped_slots: ['PM'], start_time: '14:00', end_time: '17:00',
  expected_attendance: 80, equipment_requirements: [], registration_required: true,
  confirmed_by: null, confirmed_at: null,
};

const blocked = {
  ...planning,
  confirmation_readiness: {
    ready: false,
    blockers: [
      { code: 'no_approved_venue_booking', booking_id: null, message: 'Get a venue booking approved by Venue Staff.' },
      { code: 'essential_not_fully_reserved', requirement_id: 41, message: 'Reserve 1 more unit(s) of Wireless Microphone.' },
    ],
  },
};

const ready = { ...planning, confirmation_readiness: { ready: true, blockers: [] } };

// Only ok, status and json() are read by the components, so a partial Response is enough here.
const json = (body: unknown, ok = true, status = 200) =>
  ({ ok, status, json: async () => body }) as unknown as Response;

// Answer the detail read with ``detail``, the booking panel with nothing, and the confirm call
// with ``confirmResponse``. Every call is recorded so a test can prove what was (not) sent.
function api(detail: unknown, confirmResponse?: Response) {
  return vi.fn(async (path: string, _init?: RequestInit): Promise<Response> => {
    if (path === '/api/event-requests/assigned/12') return json({ event: detail });
    if (path === '/api/event-requests/12/confirm') return confirmResponse ?? json({ error: 'unexpected' }, false, 500);
    if (path.startsWith('/api/event-requests/12/registration')) return json({ settings: null, history: [] });
    return json({ booking: null });
  });
}

const confirmCalls = (request: ReturnType<typeof api>) =>
  request.mock.calls.filter(([path]) => path === '/api/event-requests/12/confirm');

// TC-SPL-85-24 (a) — AC2-4 in the interface: every blocker is listed and Confirm is disabled.
it('[TC-SPL-85-24] lists every confirmation blocker and keeps Confirm event disabled', async () => {
  const request = api(blocked);
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  const panel = within(await screen.findByRole('region', { name: 'Confirm this event' }));
  expect(panel.getByText('Not ready to confirm')).toBeTruthy();
  expect(panel.getByText('Get a venue booking approved by Venue Staff.')).toBeTruthy();
  expect(panel.getByText('Reserve 1 more unit(s) of Wireless Microphone.')).toBeTruthy();
  const button = panel.getByRole('button', { name: 'Confirm event' }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(confirmCalls(request)).toHaveLength(0);
});

// TC-SPL-85-24 (b) — AC1/AC5: two steps; Keep planning sends nothing; Confirm sends one POST.
it('[TC-SPL-85-24] confirms only after the second step and shows who confirmed it', async () => {
  const request = api(ready, json({
    event: { ...planning, status: 'confirmed', status_label: 'Confirmed',
      confirmed_by: { id: 'c', name: 'Casey Coordinator' }, confirmed_at: '2026-10-16T10:00:00+08:00' },
    message: 'Event confirmed. Everyone involved can now see it will go ahead.',
  }));
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  const panel = within(await screen.findByRole('region', { name: 'Confirm this event' }));
  expect(panel.getByText('Ready to confirm')).toBeTruthy();
  fireEvent.click(panel.getByRole('button', { name: 'Confirm event' }));
  fireEvent.click(screen.getByRole('button', { name: 'Keep planning' }));
  expect(confirmCalls(request)).toHaveLength(0);

  fireEvent.click(panel.getByRole('button', { name: 'Confirm event' }));
  fireEvent.click(within(screen.getByRole('group', { name: 'Confirm the event' })).getByRole('button', { name: 'Confirm' }));

  expect(await screen.findByText('Event confirmed. Everyone involved can now see it will go ahead.')).toBeTruthy();
  expect(confirmCalls(request)).toHaveLength(1);
  expect(confirmCalls(request)[0][1]).toEqual({ method: 'POST' });
  const confirmedRow = screen.getByRole('rowheader', { name: 'Confirmed by' }).closest('tr')!;
  expect(confirmedRow.textContent).toContain('Casey Coordinator, 16 Oct 2026');
  expect(screen.queryByRole('region', { name: 'Confirm this event' })).toBeNull();
});

// TC-SPL-85-24 (c) — AC2-4: a server refusal is shown with its blockers; no optimistic success.
it('[TC-SPL-85-24] shows the server refusal and its blockers, and stays In planning', async () => {
  const request = api(ready, json({
    error: 'This event cannot be confirmed yet.',
    blockers: [{ code: 'venue_booking_review_required', booking_id: 5, message: 'Resolve the review flagged on the Harbour Hall booking.' }],
  }, false, 409));
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Confirm event' }));
  fireEvent.click(within(screen.getByRole('group', { name: 'Confirm the event' })).getByRole('button', { name: 'Confirm' }));

  expect((await screen.findByRole('alert')).textContent).toBe('This event cannot be confirmed yet.');
  const panel = within(screen.getByRole('region', { name: 'Confirm this event' }));
  await waitFor(() => expect(panel.getByText('Resolve the review flagged on the Harbour Hall booking.')).toBeTruthy());
  expect(panel.getByText('Not ready to confirm')).toBeTruthy();
  expect((panel.getByRole('button', { name: 'Confirm event' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole('rowheader', { name: 'Confirmed by' })).toBeNull();
});

// TC-SPL-85-24 (d) — AC1: the panel is offered only while the event is in Planning.
it('[TC-SPL-85-24] does not offer confirmation outside Planning', async () => {
  const request = api({ ...ready, status: 'under_review', status_label: 'Under review' });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  expect(await screen.findByRole('button', { name: 'Approve request' })).toBeTruthy();
  expect(screen.queryByRole('region', { name: 'Confirm this event' })).toBeNull();
});

// TC-SPL-85-24 (e) — a network failure is reported, not mistaken for success.
it('[TC-SPL-85-24] reports a failed confirmation request', async () => {
  const request = api(ready);
  request.mockImplementation(async (path: string) => {
    if (path === '/api/event-requests/assigned/12') return json({ event: ready });
    if (path === '/api/event-requests/12/confirm') throw new Error('offline');
    return json({ booking: null });
  });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Confirm event' }));
  fireEvent.click(within(screen.getByRole('group', { name: 'Confirm the event' })).getByRole('button', { name: 'Confirm' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Could not confirm the event. Try again.');
  expect(screen.getByRole('region', { name: 'Confirm this event' })).toBeTruthy();
});

// TC-SPL-85-25 — AC5 / Q98: the organiser sees Confirmed, who confirmed it, and the arrangements.
it('[TC-SPL-85-25] shows the organiser who confirmed the event and its arrangements', async () => {
  const confirmed = {
    id: 12, name: 'Community Leadership Forum', status: 'confirmed', status_label: 'Confirmed',
    status_explanation: 'Everything is arranged. Your event is going ahead on the agreed date.',
    status_changed_at: '2026-10-16T10:00:00+08:00', last_saved_at: null,
    coordinator: { id: 'c', name: 'Casey Coordinator' },
    confirmed_by: { id: 'c', name: 'Casey Coordinator' }, confirmed_at: '2026-10-16T10:00:00+08:00',
    confirmed_arrangements: {
      venues: [{ booking_id: 5, venue: 'Harbour Hall', date: '2026-11-20', start_time: '14:00', end_time: '17:00', layout: 'theatre' }],
      equipment: [
        { requirement_id: 41, equipment: 'Wireless Microphone', quantity: 4, reserved_quantity: 4, essential: true },
        { requirement_id: 42, equipment: 'Wireless Microphone', quantity: 3, reserved_quantity: 0, essential: false },
      ],
    },
  };
  const planningRow = { ...confirmed, id: 13, name: 'Spring Gala', status: 'planning', status_label: 'In planning',
    confirmed_by: null, confirmed_at: null, confirmed_arrangements: null };
  const request = vi.fn().mockResolvedValue(json({ event_requests: [confirmed, planningRow] }));
  render(<EventRequestDrafts accessToken="token" request={request} />);

  const row = (await screen.findByText('Community Leadership Forum')).closest('tr')!;
  const cells = within(row);
  expect(cells.getByText('Confirmed')).toBeTruthy();
  expect(cells.getByText(/^Confirmed by Casey Coordinator on /)).toBeTruthy();
  expect(within(cells.getByRole('list', { name: 'Confirmed venues' })).getByText(/Harbour Hall, .*, 14:00–17:00 \(theatre layout\)/)).toBeTruthy();
  const equipment = within(cells.getByRole('list', { name: 'Confirmed equipment' }));
  expect(equipment.getByText('Wireless Microphone: 4 of 4 reserved (essential)')).toBeTruthy();
  expect(equipment.getByText('Wireless Microphone: 0 of 3 reserved')).toBeTruthy();

  const planningCells = within(screen.getByText('Spring Gala').closest('tr')!);
  expect(planningCells.queryByText(/Confirmed by/)).toBeNull();
  expect(planningCells.queryByRole('list', { name: 'Confirmed venues' })).toBeNull();
});
