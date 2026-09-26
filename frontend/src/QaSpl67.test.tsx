// QA test scripts for SPL-67 (CS-E06-S4 — approve an event request), interface level.
//
// Each title starts with the QA test case ID used in the QA-SPL-67 Confluence report. Find any case
// with:  rg -n "QA-SPL-67-090" backend/tests frontend/src
// Backend cases (QA-SPL-67-001 to 086) are in backend/tests/test_qa_spl67*.py.
//
// AC1 only the assigned coordinator can approve an event Under Review
// AC2 refused while a clarification is outstanding (the button is only offered Under Review)
// AC3 records decision-maker and time, event moves to Planning
// AC4 the responsible organiser can retrieve the outcome
// AC5 approval books, reserves, enables and confirms nothing
// AC6 an invalid or unauthorised attempt leaves the event unchanged
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';
import { EventRequestDrafts } from './EventRequestDrafts';

afterEach(cleanup);

const APPROVE = 'Approve request';
const SUCCESS = 'Request approved. Event planning can begin.';
const summary = {
  id: 12, name: 'Community Forum', status: 'under_review', status_label: 'Under review', proposed_date: '2026-10-12',
  mapped_slots: ['AM', 'PM'], expected_attendance: 120, preferred_room_layout: 'theatre',
  required_facilities: ['Projector'], accessibility_needs: [], location_preference: 'Marina Centre',
};
const detail = { ...summary, purpose: 'Client showcase', clarifications: [] as unknown[], approved_by: null, approved_at: null };
const alice = { id: 'alice', name: 'Alice Tan' };
const approvedEvent = { ...summary, status: 'planning', status_label: 'In planning', approved_by: alice, approved_at: '2026-09-27T10:00:00+08:00' };

const ok = (body: unknown) => ({ ok: true, json: async () => body });
const refused = (error?: string) => ({ ok: false, json: async () => (error ? { error } : {}) });

function open(event: Record<string, unknown>, ...replies: unknown[]) {
  const request = vi.fn().mockResolvedValueOnce(ok({ event }));
  replies.forEach(reply => request.mockResolvedValueOnce(reply));
  const onNavigate = vi.fn();
  render(<AssignedEvents accessToken="t" eventId={12} request={request} onNavigate={onNavigate} />);
  return { request, onNavigate };
}

const approveButton = () => screen.findByRole('button', { name: APPROVE });
const approveNow = async () => fireEvent.click(await approveButton());
const approved = ok({ event: approvedEvent, message: SUCCESS });

// ---- AC1 / AC2 / AC6: when the button is offered ------------------------------------------------

it('[QA-SPL-67-087] offers an enabled Approve request button while the event is Under Review', async () => {
  open(detail);
  const button = (await approveButton()) as HTMLButtonElement;
  expect(button.disabled).toBe(false);
  expect(button.type).toBe('button');
});

it.each([
  'draft', 'submitted', 'returned_for_clarification', 'approved', 'planning',
  'confirmed', 'completed', 'cancelled', 'rejected', 'withdrawn', 'postponed',
])('[QA-SPL-67-088] does not offer approval when the event is %s', async status => {
  open({ ...detail, status, status_label: status });
  expect(await screen.findByText('Community Forum', { selector: 'h1' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: APPROVE })).toBeNull();
});

it('[QA-SPL-67-089] shows Approve request beside the clarification form, not instead of it', async () => {
  open(detail);
  await approveButton();
  expect(screen.getByRole('button', { name: 'Request clarification' })).toBeTruthy();
});

// ---- AC1 / AC6: what is sent --------------------------------------------------------------------

it('[QA-SPL-67-090] posts to the approve endpoint with no body, so no status can be chosen', async () => {
  const { request } = open(detail, approved);
  await approveNow();
  await screen.findByText(SUCCESS);
  expect(request).toHaveBeenLastCalledWith('/api/event-requests/12/approve', { method: 'POST' });
  expect(request).toHaveBeenCalledTimes(2);
});

it('[QA-SPL-67-091] does not send the unsent clarification text when approving', async () => {
  const { request } = open(detail, approved);
  fireEvent.change(await screen.findByLabelText('Clarification for the Event Organiser'), { target: { value: 'Half typed' } });
  await approveNow();
  await screen.findByText(SUCCESS);
  expect(request.mock.calls[1][1]).toEqual({ method: 'POST' });
});

it('[QA-SPL-67-092] disables the button while approving and sends only one request for a double click', async () => {
  let release: (value: unknown) => void = () => undefined;
  const pending = new Promise(resolve => { release = resolve; });
  const { request } = open(detail, pending);
  const button = await approveButton();
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect((screen.getByRole('button', { name: 'Working…' }) as HTMLButtonElement).disabled).toBe(true));
  expect(request).toHaveBeenCalledTimes(2);
  release(approved);
  expect(await screen.findByText(SUCCESS)).toBeTruthy();
});

// ---- AC3: the outcome the coordinator sees ------------------------------------------------------

it('[QA-SPL-67-093] shows the success message returned by the server', async () => {
  open(detail, ok({ event: approvedEvent, message: 'Approved, planning may start.' }));
  await approveNow();
  expect((await screen.findByRole('status')).textContent).toBe('Approved, planning may start.');
});

it('[QA-SPL-67-094] falls back to the standard message when the server sends none', async () => {
  open(detail, ok({ event: approvedEvent }));
  await approveNow();
  expect(await screen.findByText(SUCCESS)).toBeTruthy();
});

it('[QA-SPL-67-095] shows In planning in the summary and the Status row', async () => {
  open(detail, approved);
  await approveNow();
  await screen.findByText(SUCCESS);
  const brief = within(screen.getByRole('region', { name: 'Requirements to consider' }));
  expect(brief.getByText('In planning')).toBeTruthy();
  expect((screen.getByRole('rowheader', { name: 'Status' }).closest('tr') as HTMLElement).textContent).toContain('In planning');
  expect(screen.queryByText('Under review')).toBeNull();
});

it('[QA-SPL-67-096] shows who approved and when, in Singapore time', async () => {
  open(detail, approved);
  await approveNow();
  const row = (await screen.findByRole('rowheader', { name: 'Approved by' })).closest('tr') as HTMLElement;
  expect(row.textContent).toContain('Alice Tan');
  expect(row.textContent).toMatch(/27 Sep(t)? 2026, 10:00/);
});

it('[QA-SPL-67-097] removes the Approve button and the clarification form once approved', async () => {
  open(detail, approved);
  await approveNow();
  await screen.findByText(SUCCESS);
  expect(screen.queryByRole('button', { name: APPROVE })).toBeNull();
  expect(screen.queryByLabelText('Clarification for the Event Organiser')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Request clarification' })).toBeNull();
});

it('[QA-SPL-67-098] keeps the request details and clarification history on screen after approval', async () => {
  const history = [{ id: 1, message: 'Earlier question', author: alice, created_at: '2026-09-26T10:00:00+08:00' }];
  open({ ...detail, clarifications: history }, approved);
  await approveNow();
  await screen.findByText(SUCCESS);
  expect(screen.getByText('Client showcase')).toBeTruthy();
  expect(screen.getByText('Earlier question')).toBeTruthy();
});

// ---- AC5: nothing else happens ------------------------------------------------------------------

it('[QA-SPL-67-099] calls only the approve endpoint and does not navigate away', async () => {
  const { request, onNavigate } = open(detail, approved);
  await approveNow();
  await screen.findByText(SUCCESS);
  const paths = request.mock.calls.map(call => call[0]);
  expect(paths).toEqual(['/api/event-requests/assigned/12', '/api/event-requests/12/approve']);
  expect(onNavigate).not.toHaveBeenCalled();
});

it('[QA-SPL-67-100] does not start a venue booking or registration by itself', async () => {
  const { request } = open(detail, approved);
  await approveNow();
  await screen.findByText(SUCCESS);
  expect(request.mock.calls.some(call => /venue|booking|registration|confirm/i.test(String(call[0])))).toBe(false);
  expect(screen.getByRole('button', { name: 'Find venues' })).toBeTruthy();
});

// ---- AC6: refusals and failures leave the page unchanged ----------------------------------------

it('[QA-SPL-67-101] shows the server refusal, keeps the status and keeps the button', async () => {
  open(detail, refused('Only an event under review can be approved.'));
  await approveNow();
  expect((await screen.findByRole('alert')).textContent).toBe('Only an event under review can be approved.');
  expect(screen.getAllByText('Under review').length).toBeGreaterThan(0);
  expect((screen.getByRole('button', { name: APPROVE }) as HTMLButtonElement).disabled).toBe(false);
  expect(screen.queryByRole('rowheader', { name: 'Approved by' })).toBeNull();
});

it.each([
  ['Assigned event not found.'],
  ['Access denied.'],
  ['Sign in to continue.'],
])('[QA-SPL-67-102] shows the server message "%s" as the display message', async message => {
  open(detail, refused(message));
  await approveNow();
  expect((await screen.findByRole('alert')).textContent).toBe(message);
});

it('[QA-SPL-67-103] uses a fallback when a refusal carries no message', async () => {
  open(detail, refused());
  await approveNow();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not approve the request. Try again.');
});

it('[QA-SPL-67-104] uses a fallback when a refusal is not JSON', async () => {
  open(detail, { ok: false, json: async () => { throw new Error('not json'); } });
  await approveNow();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not approve the request. Try again.');
});

it('[QA-SPL-67-105] recovers from a network failure and lets the coordinator try again', async () => {
  const { request } = open(detail);
  request.mockImplementationOnce(() => Promise.reject(new Error('offline')));
  await approveNow();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not approve the request. Try again.');
  expect((screen.getByRole('button', { name: APPROVE }) as HTMLButtonElement).disabled).toBe(false);
  request.mockResolvedValueOnce(approved);
  fireEvent.click(screen.getByRole('button', { name: APPROVE }));
  expect(await screen.findByText(SUCCESS)).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});

it('[QA-SPL-67-106] treats a success reply without an event as a failure and changes nothing', async () => {
  open(detail, ok({ message: SUCCESS }));
  await approveNow();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not approve the request. Try again.');
  expect(screen.queryByText(SUCCESS)).toBeNull();
  expect(screen.getAllByText('Under review').length).toBeGreaterThan(0);
});

it('[QA-SPL-67-107] clears an earlier error when a retry succeeds', async () => {
  open(detail, refused('Only an event under review can be approved.'), approved);
  await approveNow();
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: APPROVE }));
  expect(await screen.findByText(SUCCESS)).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});

// ---- AC3 / AC4: reading an outcome that already exists ------------------------------------------

it('[QA-SPL-67-108] shows the decision-maker and time when an approved event is opened later', async () => {
  open({ ...detail, ...approvedEvent, clarifications: [] });
  const row = (await screen.findByRole('rowheader', { name: 'Approved by' })).closest('tr') as HTMLElement;
  expect(row.textContent).toContain('Alice Tan');
  expect(screen.queryByRole('button', { name: APPROVE })).toBeNull();
});

it('[QA-SPL-67-109] shows no Approved by row while nobody has approved', async () => {
  open(detail);
  await approveButton();
  expect(screen.queryByRole('rowheader', { name: 'Approved by' })).toBeNull();
});

// ---- AC4: the organiser's status table ----------------------------------------------------------

const listed = (overrides: Record<string, unknown>) => ({
  id: 1, name: 'Forum', status: 'under_review', status_label: 'Under review', status_explanation: 'Being reviewed.',
  status_changed_at: null, last_saved_at: null, proposed_date: null, coordinator: alice, ...overrides,
});
const organiserView = (rows: unknown[]) => {
  const request = vi.fn(async () => new Response(JSON.stringify({ event_requests: rows }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  render(<EventRequestDrafts accessToken="t" request={request} />);
};

it('[QA-SPL-67-110] tells the organiser who approved the request and when', async () => {
  organiserView([listed({ status: 'planning', status_label: 'In planning', approved_by: alice, approved_at: '2026-09-27T10:00:00+08:00' })]);
  expect(await screen.findByText(/Approved by Alice Tan on/)).toBeTruthy();
  expect(screen.getByText('In planning')).toBeTruthy();
});

it('[QA-SPL-67-111] shows no approval line while the request is not approved', async () => {
  organiserView([listed({ approved_by: null, approved_at: null }), listed({ id: 2, name: 'Older', approved_by: undefined })]);
  expect(await screen.findByText('Forum')).toBeTruthy();
  expect(screen.queryByText(/Approved by/)).toBeNull();
});

it('[QA-SPL-67-112] shows the approval line only against the approved request', async () => {
  organiserView([
    listed({ id: 1, name: 'Approved one', status: 'planning', status_label: 'In planning', approved_by: alice, approved_at: '2026-09-27T10:00:00+08:00' }),
    listed({ id: 2, name: 'Waiting one', status: 'submitted', status_label: 'Submitted' }),
  ]);
  const rows = await screen.findAllByRole('row');
  const approvedRow = rows.find(row => row.textContent?.includes('Approved one')) as HTMLElement;
  const waitingRow = rows.find(row => row.textContent?.includes('Waiting one')) as HTMLElement;
  expect(approvedRow.textContent).toContain('Approved by Alice Tan');
  expect(waitingRow.textContent).not.toContain('Approved by');
});

it('[QA-SPL-67-113] still lists an approved request whose approval time is missing', async () => {
  organiserView([listed({ status: 'planning', status_label: 'In planning', approved_by: alice, approved_at: null })]);
  expect(await screen.findByText('Approved by Alice Tan')).toBeTruthy();
});
