import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CoordinatorAssignmentQueue, type QueueEvent } from './CoordinatorAssignmentQueue';

afterEach(() => { vi.restoreAllMocks(); });

const harbourSummit: QueueEvent = {
  id: 7,
  name: 'Harbour Summit',
  organisation_id: 3,
  proposed_date: '2026-10-12',
  submitted_at: null,
};
const galaNight: QueueEvent = {
  id: 8,
  name: 'Gala Night',
  organisation_id: null,
  proposed_date: null,
  submitted_at: null,
};
const coordinators = [{ id: 'alice', name: 'Alice Tan' }, { id: 'bob', name: 'Bob Lim' }];

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

it('stays hidden for accounts without the Event Operations Manager role', async () => {
  const request = vi.fn(async () => response({ error: 'Access denied.' }, 403));
  const { container } = render(<CoordinatorAssignmentQueue accessToken="token" request={request} />);
  await waitFor(() => expect(container.innerHTML).toBe(''));
  expect(request).toHaveBeenCalledWith('/api/event-requests/awaiting-assignment');
});

it('lists submitted requests in server order with a matching count', async () => {
  const request = vi.fn(async () => response({ events: [harbourSummit, galaNight], count: 2 }));
  render(<CoordinatorAssignmentQueue accessToken="token" request={request} />);
  expect(await screen.findByText('2 events awaiting assignment')).toBeTruthy();
  const rows = screen.getAllByRole('row').slice(1);
  expect(rows.map(row => within(row).getByRole('rowheader').textContent)).toEqual(['Harbour Summit', 'Gala Night']);
  expect(within(rows[0]).getByText('Organisation 3')).toBeTruthy();
  // Client organisation and submission time stay unrecorded until SPL-45 and SPL-55 land.
  expect(within(rows[1]).getAllByText('Not recorded yet')).toHaveLength(2);
  expect(within(rows[1]).getByText('Not provided')).toBeTruthy();
});

it('shows an empty state when no requests are awaiting assignment', async () => {
  const request = vi.fn(async () => response({ events: [], count: 0 }));
  render(<CoordinatorAssignmentQueue accessToken="token" request={request} />);
  expect(await screen.findByRole('heading', { name: 'No events are awaiting assignment' })).toBeTruthy();
  expect(screen.getByText('0 events awaiting assignment')).toBeTruthy();
});

it('assigns the chosen coordinator and refreshes the queue', async () => {
  let assigned = false;
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/event-requests/awaiting-assignment') {
      return response(assigned ? { events: [], count: 0 } : { events: [harbourSummit], count: 1 });
    }
    if (path === '/api/event-requests/7/coordinator-options') {
      return response({ coordinators, current_coordinator: null, unavailable_reason: null });
    }
    if (path === '/api/event-requests/7/coordinator' && init?.method === 'POST') {
      assigned = true;
      return response({ assignment: { event_request_id: 7, status: 'under_review', coordinator: coordinators[1] } }, 201);
    }
    return response({ error: 'Unexpected request.' }, 500);
  });
  render(<CoordinatorAssignmentQueue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Assign coordinator to Harbour Summit' }));
  const confirm = screen.getByRole('button', { name: 'Confirm assignment' });
  expect(confirm).toHaveProperty('disabled', true);
  fireEvent.change(await screen.findByLabelText('Event Coordinator'), { target: { value: 'bob' } });
  expect(confirm).toHaveProperty('disabled', false);
  fireEvent.click(confirm);
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/7/coordinator', expect.objectContaining({ method: 'POST' })));
  const assignCall = request.mock.calls.find(([path, init]) => path === '/api/event-requests/7/coordinator' && init?.method === 'POST');
  expect(JSON.parse(assignCall?.[1]?.body as string)).toEqual({ coordinator_account_id: 'bob' });
  expect(await screen.findByText('Bob Lim is now responsible for Harbour Summit.')).toBeTruthy();
  expect(await screen.findByRole('heading', { name: 'No events are awaiting assignment' })).toBeTruthy();
});

it('explains why assignment is unavailable when no coordinator is active', async () => {
  const reason = 'No active Event Coordinator is available, so this event cannot be assigned yet.';
  const request = vi.fn(async (path: string) => path === '/api/event-requests/awaiting-assignment'
    ? response({ events: [harbourSummit], count: 1 })
    : response({ coordinators: [], current_coordinator: null, unavailable_reason: reason }));
  render(<CoordinatorAssignmentQueue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Assign coordinator to Harbour Summit' }));
  expect(await screen.findByText(reason)).toBeTruthy();
  expect(screen.queryByLabelText('Event Coordinator')).toBeNull();
  expect(screen.getByRole('button', { name: 'Confirm assignment' })).toHaveProperty('disabled', true);
});

it('keeps the panel open and shows the server refusal when assignment fails', async () => {
  const refusal = 'This event already has an Event Coordinator. Reassign it instead.';
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/event-requests/awaiting-assignment') return response({ events: [harbourSummit], count: 1 });
    if (init?.method === 'POST') return response({ error: refusal }, 409);
    return response({ coordinators, current_coordinator: null, unavailable_reason: null });
  });
  render(<CoordinatorAssignmentQueue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Assign coordinator to Harbour Summit' }));
  fireEvent.change(await screen.findByLabelText('Event Coordinator'), { target: { value: 'alice' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm assignment' }));
  expect((await screen.findByRole('alert')).textContent).toBe(refusal);
  expect(screen.getByRole('heading', { name: 'Harbour Summit' })).toBeTruthy();
});
