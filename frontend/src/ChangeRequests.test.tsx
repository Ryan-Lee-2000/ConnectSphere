import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { AssignedEvents } from './AssignedEvents';
import { ChangeRequestsPanel, type ChangeRequest } from './ChangeRequests';
import { EventRequestDrafts } from './EventRequestDrafts';

afterEach(cleanup);

// SPL-111 (CS-E18-S1) component cases. The rules (owner, status, one pending, validation) are
// enforced by the server and proved in backend/tests/test_event_change_requests.py; these prove the
// panel offers the action only when it can work, sends exactly what was entered, and shows the
// server's answer. Search with: rg -n "QA-SPL-111-1" frontend/src

const PENDING: ChangeRequest = {
  id: 4,
  status: 'pending',
  submitted_at: '2026-10-20T12:00:00+08:00',
  items: [
    { id: 1, field: 'expected_attendance', field_label: 'Expected attendance', current_value: 150, requested_value: 50, reason: 'Fewer guests.' },
    { id: 2, field: 'required_facilities', field_label: 'Required facilities', current_value: [], requested_value: ['Stage', 'AV'], reason: 'Band.' },
    { id: 3, field: 'description', field_label: 'Description', current_value: null, requested_value: 'A new one', reason: 'Missing.' },
  ],
};

type Reply = { status?: number; body?: unknown };

// A scripted API: each call takes the next reply; the last one repeats.
function scripted(...replies: Reply[]) {
  let index = 0;
  return vi.fn(async () => {
    const reply = replies[Math.min(index++, replies.length - 1)];
    const status = reply.status ?? 200;
    return { ok: status < 300, status, json: async () => reply.body ?? {} };
  }) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
}
const list = (...items: ChangeRequest[]): Reply => ({ body: { change_requests: items } });

function panel(request: ApiRequest, props: Partial<Parameters<typeof ChangeRequestsPanel>[0]> = {}) {
  return render(<ChangeRequestsPanel api={request} eventId={12} eventStatus="planning" eventName="Gala" canSubmit {...props} />);
}

async function fill(index: number, field: string, value: string, reason: string) {
  const fields = screen.getAllByLabelText('Field to change');
  fireEvent.change(fields[index], { target: { value: field } });
  fireEvent.change(screen.getAllByLabelText(/New value/)[index], { target: { value } });
  fireEvent.change(screen.getAllByLabelText('Reason')[index], { target: { value: reason } });
}

// QA-SPL-111-100 | AC1 | BB
it('[QA-SPL-111-100] offers a change request in each allowed status and no other', async () => {
  for (const status of ['under_review', 'planning', 'confirmed']) {
    const { unmount } = panel(scripted(list()), { eventStatus: status });
    expect(await screen.findByRole('button', { name: 'Request a change' })).toBeTruthy();
    unmount();
  }
  for (const status of ['submitted', 'approved', 'returned_for_clarification', 'cancelled', 'completed']) {
    const { unmount } = panel(scripted(list()), { eventStatus: status });
    expect(await screen.findByText(/Change requests can be made while the event is under review/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Request a change' })).toBeNull();
    unmount();
  }
});

// QA-SPL-111-101 | AC1 | BB
it('[QA-SPL-111-101] a coordinator (read-only) is never offered the form', async () => {
  panel(scripted(list()), { canSubmit: false });
  expect(await screen.findByText('No pending change request.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Request a change' })).toBeNull();
});

// QA-SPL-111-102 | AC2 | BB
it('[QA-SPL-111-102] will not submit an incomplete item and sends nothing', async () => {
  const request = scripted(list());
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Complete every item');
  // Field and value but no reason is still incomplete.
  await fill(0, 'expected_attendance', '50', '');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Complete every item');
  expect(request).toHaveBeenCalledTimes(1); // only the initial read
});

// QA-SPL-111-103 | AC2 | BB
it('[QA-SPL-111-103] sends every item with the value typed for its kind of field', async () => {
  const request = scripted(list(), { status: 201, body: { change_request: PENDING } }, list(PENDING));
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'expected_attendance', '50', 'Fewer guests.');
  fireEvent.click(screen.getByRole('button', { name: 'Add another item' }));
  await fill(1, 'required_facilities', 'Stage, AV ,\n', 'Band.');
  fireEvent.click(screen.getByRole('button', { name: 'Add another item' }));
  await fill(2, 'proposed_date', '2026-12-12', 'Clash.');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));

  await waitFor(() => expect(request).toHaveBeenCalledTimes(3));
  const [path, init] = request.mock.calls[1] as [string, RequestInit];
  expect(path).toBe('/api/event-requests/12/change-requests');
  expect(init.method).toBe('POST');
  expect(JSON.parse(init.body as string)).toEqual({
    items: [
      { field: 'expected_attendance', requested_value: 50, reason: 'Fewer guests.' },
      { field: 'required_facilities', requested_value: ['Stage', 'AV'], reason: 'Band.' },
      { field: 'proposed_date', requested_value: '2026-12-12', reason: 'Clash.' },
    ],
  });
  // Nothing about status, owner or event id travels in the body.
  expect(Object.keys(JSON.parse(init.body as string))).toEqual(['items']);
});

// QA-SPL-111-104 | AC2 | BB
it('[QA-SPL-111-104] an item can be removed, a field cannot be picked twice, items are capped', async () => {
  panel(scripted(list()));
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  expect(screen.queryByRole('button', { name: /Remove item/ })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Add another item' }));
  fireEvent.change(screen.getAllByLabelText('Field to change')[0], { target: { value: 'name' } });
  const second = within(screen.getAllByLabelText('Field to change')[1]);
  expect((second.getByRole('option', { name: 'Event name' }) as HTMLOptionElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Remove item 2' }));
  expect(screen.getAllByLabelText('Field to change')).toHaveLength(1);
  // SPL-141 permits repeated equipment actions within the 100-item safety limit.
  const addButton = screen.getByRole('button', { name: 'Add another item' });
  for (let i = 0; i < 99; i += 1) fireEvent.click(addButton);
  expect(screen.getAllByLabelText('Field to change')).toHaveLength(100);
  expect((screen.getByRole('button', { name: 'Add another item' }) as HTMLButtonElement).disabled).toBe(true);
}, 20_000);

// QA-SPL-111-105 | AC3 | BB
it('[QA-SPL-111-105] after submitting, the request shows as Pending and the form closes', async () => {
  const request = scripted(list(), { status: 201, body: { change_request: PENDING } }, list(PENDING));
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'expected_attendance', '50', 'Fewer guests.');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  const group = await screen.findByRole('group', { name: 'Pending change request' });
  expect(within(group).getByText('Pending')).toBeTruthy();
  expect(screen.queryByRole('form', { name: 'New change request' })).toBeNull();
  // AC4 in the interface: a second request is not offered while one is pending.
  expect(screen.queryByRole('button', { name: 'Request a change' })).toBeNull();
  expect(screen.getByText(/once this one is Closed/)).toBeTruthy();
});

// QA-SPL-111-106 | AC4 | BB
it('[QA-SPL-111-106] a refused submission (409) shows the reason and the true state', async () => {
  const request = scripted(
    list(),
    { status: 409, body: { error: 'This event already has a pending change request. Wait until it is resolved.' } },
    list(PENDING),
  );
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'expected_attendance', '50', 'Fewer guests.');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  expect(await screen.findByRole('group', { name: 'Pending change request' })).toBeTruthy();
  expect(screen.getByText(/already has a pending change request/)).toBeTruthy();
  expect(request).toHaveBeenCalledTimes(4); // read, submit, re-read, event status re-read
});

// QA-SPL-111-117 | AC1 | BB | review finding 1
it('[QA-SPL-111-117] a status-change refusal stays visible and the form is not offered again', async () => {
  const request = scripted(
    list(),
    { status: 409, body: { error: 'A change request can only be made while the event is under review, in planning or confirmed.' } },
    list(),
    { body: { event_request: { id: 12, status: 'cancelled' } } },
  );
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'expected_attendance', '50', 'Fewer guests.');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toMatch(/can only be made while the event is under review/);
  // The refreshed status is ineligible, so the stale "Request a change" is not offered again.
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Request a change' })).toBeNull());
  expect(screen.getByText(/Change requests can be made while the event is under review/)).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12');
});

// QA-SPL-111-118 | AC1 | BB | review finding 1
it('[QA-SPL-111-118] after a refusal that leaves the event eligible, the typed values are kept', async () => {
  const request = scripted(
    list(),
    { status: 409, body: { error: 'This event already has a pending change request. Wait until it is resolved.' } },
    list(),
    { body: { event_request: { id: 12, status: 'planning' } } },
  );
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'expected_attendance', '50', 'Fewer guests.');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  expect((await screen.findByRole('alert')).textContent).toMatch(/already has a pending change request/);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  expect((screen.getByLabelText(/New value/) as HTMLInputElement).value).toBe('50');
  expect((screen.getByLabelText('Reason') as HTMLTextAreaElement).value).toBe('Fewer guests.');
});

// QA-SPL-111-119 | AC2 | BB | review finding 2
it('[QA-SPL-111-119] a list field can be cleared: an empty value sends an empty list', async () => {
  const request = scripted(list(), { status: 201, body: { change_request: PENDING } }, list(PENDING));
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'required_facilities', '', 'No facilities are needed any more.');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  await screen.findByRole('group', { name: 'Pending change request' });
  const post = request.mock.calls.find(call => (call as unknown[])[1] && (call as { method?: string }[])[1].method === 'POST') as unknown as [string, { body: string }];
  expect(JSON.parse(post[1].body).items).toEqual([
    { field: 'required_facilities', requested_value: [], reason: 'No facilities are needed any more.' },
  ]);
});

// QA-SPL-111-120 | AC2 | BB | review finding 2
it('[QA-SPL-111-120] a text field and a reason are still required even though a list may be empty', async () => {
  const request = scripted(list());
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'description', '', 'Reason given.');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  expect((await screen.findByRole('alert')).textContent).toMatch(/Complete every item/);
  await fill(0, 'accessibility_needs', '', '');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  expect((await screen.findByRole('alert')).textContent).toMatch(/Complete every item/);
  expect(request).toHaveBeenCalledTimes(1); // only the initial read: nothing was submitted
});

// QA-SPL-111-107 | AC2 | BB
it('[QA-SPL-111-107] a validation refusal (400) keeps the form and what was typed', async () => {
  const request = scripted(list(), { status: 400, body: { error: 'Event name must be 2000 characters or fewer.' } });
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'name', 'x'.repeat(5), 'Rebrand.');
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  expect((await screen.findByRole('alert')).textContent).toContain('2000 characters or fewer');
  expect((screen.getByLabelText(/New value/) as HTMLInputElement).value).toBe('xxxxx');
  expect((screen.getByLabelText('Reason') as HTMLTextAreaElement).value).toBe('Rebrand.');
  expect(screen.getByRole('button', { name: 'Submit change request' })).toBeTruthy();
});

// QA-SPL-111-115 | AC2 | BB: boundary, the attendance input itself refuses 0 before any request
it('[QA-SPL-111-115] an attendance of 0 or a fraction is stopped by the form before any request', async () => {
  const request = scripted(list());
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'expected_attendance', '0', 'Fewer guests.');
  const input = screen.getByLabelText(/New value/) as HTMLInputElement;
  expect(input.type).toBe('number');
  expect(input.min).toBe('1');
  expect(input.validity.rangeUnderflow).toBe(true);
  fireEvent.change(input, { target: { value: '1.5' } });
  expect(input.validity.stepMismatch).toBe(true);
  fireEvent.change(input, { target: { value: '1' } });
  expect(input.validity.valid).toBe(true);
});

// QA-SPL-111-108 | AC2 | BB (retries and network failure)
it('[QA-SPL-111-108] a network failure keeps the form, and a repeat click while saving sends once', async () => {
  let release: (value: unknown) => void = () => undefined;
  const slow = vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ change_requests: [] }) })
    .mockImplementationOnce(() => new Promise(resolve => { release = resolve; }))
    .mockRejectedValue(new Error('offline')) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
  panel(slow);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'expected_attendance', '50', 'Fewer guests.');
  const submit = screen.getByRole('button', { name: 'Submit change request' });
  fireEvent.click(submit);
  expect((await screen.findByRole('button', { name: 'Submitting…' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.submit(screen.getByRole('form', { name: 'New change request' }));
  expect(slow).toHaveBeenCalledTimes(2); // one read, one submit; the repeat was ignored
  release({ ok: false, status: 503, json: async () => ({}) });
  expect((await screen.findByRole('alert')).textContent).toContain('Could not submit the change request');
  expect((screen.getByLabelText(/New value/) as HTMLInputElement).value).toBe('50');
  // And a thrown error (offline) is reported the same way.
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  await waitFor(() => expect(slow).toHaveBeenCalledTimes(3));
  expect((await screen.findByRole('alert')).textContent).toContain('Could not submit the change request');
});

// QA-SPL-111-109 | AC5 | BB
it('[QA-SPL-111-109] shows the pending request with every item: field, at submission, requested, reason', async () => {
  panel(scripted(list(PENDING)));
  const group = await screen.findByRole('group', { name: 'Pending change request' });
  const text = group.textContent ?? '';
  for (const expected of [
    'Expected attendance', 'At submission: 150', 'Requested: 50', 'Reason: Fewer guests.',
    'Required facilities', 'At submission: None', 'Requested: Stage, AV', 'Reason: Band.',
    'Description', 'At submission: Not set', 'Requested: A new one',
  ]) expect(text).toContain(expected);
  expect(within(group).getAllByRole('listitem')).toHaveLength(3);
});

// QA-SPL-111-110 | AC5 | BB (loading, empty, error, retry)
it('[QA-SPL-111-110] shows loading, then an error with a working retry', async () => {
  const request = scripted({ status: 500, body: {} }, list(PENDING));
  panel(request);
  expect(screen.getByText('Loading change requests…')).toBeTruthy();
  expect((await screen.findByRole('alert')).textContent).toContain("couldn't load the change requests");
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(await screen.findByRole('group', { name: 'Pending change request' })).toBeTruthy();
});

// QA-SPL-111-111 | AC5 | BB
it('[QA-SPL-111-111] a malformed or failed read is an error, never an empty state', async () => {
  panel(scripted({ body: { change_requests: 'nope' } }));
  expect((await screen.findByRole('alert')).textContent).toContain("couldn't load");
  cleanup();
  const failing = vi.fn().mockRejectedValue(new Error('offline')) as unknown as ApiRequest;
  panel(failing);
  expect((await screen.findByRole('alert')).textContent).toContain("couldn't load");
  expect(screen.queryByText('No pending change request.')).toBeNull();
});

// QA-SPL-111-112 | AC5 | WB (cancel and reopen)
it('[QA-SPL-111-112] cancelling closes the form without a request; reopening starts clean', async () => {
  const request = scripted(list());
  panel(request);
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  await fill(0, 'name', 'Typed', 'Reason');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(request).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Request a change' }));
  expect((screen.getByLabelText(/New value/) as HTMLInputElement).value).toBe('');
  expect((screen.getByLabelText('Field to change') as HTMLSelectElement).value).toBe('');
});

// QA-SPL-111-113 | AC1/AC5 | BB: the organiser's My requests screen
it('[QA-SPL-111-113] My requests offers change request history for every submitted status and opens the panel', async () => {
  const rows = ['submitted', 'under_review', 'planning', 'confirmed', 'cancelled'].map((status, index) => ({
    id: index + 1, name: `Event ${status}`, status, status_label: status, status_explanation: '',
    status_changed_at: null, last_saved_at: null, coordinator: null,
  }));
  const request = vi.fn(async (path: string) => ({
    ok: true, status: 200,
    json: async () => (path === '/api/event-requests' ? { event_requests: rows } : { change_requests: [PENDING] }),
  })) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
  render(<EventRequestDrafts accessToken="t" request={request} />);
  await screen.findByText('Event planning');
  expect(screen.getAllByRole('button', { name: 'Change requests' })).toHaveLength(5);
  const row = screen.getByText('Event planning').closest('tr')!;
  fireEvent.click(within(row).getByRole('button', { name: 'Change requests' }));
  expect(await screen.findByRole('heading', { name: 'Change requests for Event planning' })).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/3/change-requests');
  // The organiser who owns it may submit, but a request is already pending here.
  expect(screen.queryByRole('button', { name: 'Request a change' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Back to my requests' }));
  expect(await screen.findByText('Event planning')).toBeTruthy();
});

// QA-SPL-111-114 | AC3 | BB: the coordinator's event view (read-only, on demand)
it('[QA-SPL-111-114] the coordinator reads change requests on demand and cannot submit', async () => {
  const detail = {
    id: 12, name: 'Community Forum', status: 'planning', status_label: 'In planning', proposed_date: '2026-12-05',
    mapped_slots: [], expected_attendance: 120, required_facilities: [], accessibility_needs: [],
  };
  const request = vi.fn(async (path: string) => ({
    ok: true, status: 200,
    json: async () => (path.endsWith('/change-requests') ? { change_requests: [PENDING] } : { event: detail }),
  })) as unknown as ApiRequest & ReturnType<typeof vi.fn>;
  render(<AssignedEvents accessToken="t" eventId={12} request={request} onNavigate={vi.fn()} />);
  const open = await screen.findByRole('button', { name: 'View change requests' });
  // Not loaded until asked for: opening the event costs no extra request.
  expect(request).not.toHaveBeenCalledWith('/api/event-requests/12/change-requests');
  fireEvent.click(open);
  expect(await screen.findByRole('group', { name: 'Pending change request' })).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/12/change-requests');
  expect(screen.queryByRole('button', { name: 'Request a change' })).toBeNull();
});

// QA-SPL-111-116 | AC2 | BB: defect D1 found in the recording; an old refusal must not outlive the fix
it('[QA-SPL-111-116] the incomplete-item message goes away as soon as the organiser edits', async () => {
  panel(scripted(list()));
  fireEvent.click(await screen.findByRole('button', { name: 'Request a change' }));
  fireEvent.click(screen.getByRole('button', { name: 'Submit change request' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Complete every item');
  fireEvent.change(screen.getByLabelText('Field to change'), { target: { value: 'name' } });
  expect(screen.queryByRole('alert')).toBeNull();
});
