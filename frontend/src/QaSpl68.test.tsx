// QA test scripts for SPL-68 (CS-E06-S5 - reject an event request), interface level.
//
// Each title starts with the QA test case ID used in the QA-SPL-68 Confluence report. Find any case
// with:  rg -n "QA-SPL-68-110" backend/tests frontend/src
// Backend cases (QA-SPL-68-001 to 103, 142, 143) are in backend/tests/test_qa_spl68*.py.
//
// AC1 only the assigned coordinator can reject an event Under Review (the button is only offered then)
// AC2 a non-blank reason is required
// AC3 records reason, decision-maker and time, event moves to Rejected
// AC4 the responsible organiser can retrieve the outcome and reason
// AC5 a rejected request cannot be reviewed or planned further
// AC6 an invalid or unauthorised attempt leaves the event unchanged
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';
import { EventRequestDrafts } from './EventRequestDrafts';

afterEach(cleanup);

const REJECT = 'Reject request';
const REASON_LABEL = 'Reason for rejecting this request';
const SUCCESS = 'Request rejected. The Event Organiser can see your reason.';
const summary = {
  id: 12, name: 'Community Forum', status: 'under_review', status_label: 'Under review', proposed_date: '2026-10-12',
  mapped_slots: ['AM', 'PM'], expected_attendance: 120, preferred_room_layout: 'theatre',
  required_facilities: ['Projector'], accessibility_needs: [], location_preference: 'Marina Centre',
};
const detail = {
  ...summary, purpose: 'Client showcase', clarifications: [] as unknown[],
  approved_by: null, approved_at: null, rejected_by: null, rejected_at: null, rejection_reason: null,
};
const alice = { id: 'alice', name: 'Alice Tan' };
const rejectedEvent = (reason = 'Clashes with exams.') => ({
  ...summary, status: 'rejected', status_label: 'Not approved',
  rejected_by: alice, rejected_at: '2026-09-27T10:00:00+08:00', rejection_reason: reason,
});

const ok = (body: unknown) => ({ ok: true, json: async () => body });
const refused = (error?: string) => ({ ok: false, json: async () => (error ? { error } : {}) });
const rejectedReply = (reason?: string) => ok({ event: rejectedEvent(reason), message: SUCCESS });

function open(event: Record<string, unknown>, ...replies: unknown[]) {
  const request = vi.fn().mockResolvedValueOnce(ok({ event }));
  replies.forEach(reply => request.mockResolvedValueOnce(reply));
  const onNavigate = vi.fn();
  const view = render(<AssignedEvents accessToken="t" eventId={12} request={request} onNavigate={onNavigate} />);
  return { request, onNavigate, view };
}

const rejectButton = () => screen.findByRole('button', { name: REJECT });
const openForm = async () => fireEvent.click(await rejectButton());
const reasonBox = () => screen.getByLabelText(REASON_LABEL) as HTMLTextAreaElement;
const typeReason = (value: string) => fireEvent.change(reasonBox(), { target: { value } });
const goToConfirm = (value = 'Clashes with exams.') => {
  typeReason(value);
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
};
const confirm = () => fireEvent.click(screen.getByRole('button', { name: 'Confirm rejection' }));

// ---- AC1 / AC5 / AC6: when the button is offered -------------------------------------------------

it('[QA-SPL-68-104] offers an enabled Reject request button while the event is Under Review', async () => {
  open(detail);
  const button = (await rejectButton()) as HTMLButtonElement;
  expect(button.disabled).toBe(false);
  expect(button.type).toBe('button');
});

it.each([
  'draft', 'submitted', 'returned_for_clarification', 'approved', 'planning',
  'confirmed', 'completed', 'cancelled', 'rejected', 'withdrawn', 'postponed',
])('[QA-SPL-68-105] does not offer rejection when the event is %s', async status => {
  open({ ...detail, status, status_label: status });
  expect(await screen.findByText('Community Forum', { selector: 'h1' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: REJECT })).toBeNull();
});

it('[QA-SPL-68-106] shows Reject request beside Approve and Request clarification', async () => {
  open(detail);
  await rejectButton();
  expect(screen.getByRole('button', { name: 'Approve request' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Request clarification' })).toBeTruthy();
});

it('[QA-SPL-68-107] sends nothing until the coordinator confirms', async () => {
  const { request } = open(detail, rejectedReply());
  await openForm();
  goToConfirm();
  expect(request).toHaveBeenCalledTimes(1);
});

// ---- AC2: the reason is required -----------------------------------------------------------------

it('[QA-SPL-68-108] opens a labelled reason box that starts empty, without sending anything', async () => {
  const { request } = open(detail);
  await openForm();
  expect(reasonBox().value).toBe('');
  expect(screen.getByRole('button', { name: 'Continue' })).toBeTruthy();
  expect(request).toHaveBeenCalledTimes(1);
});

it.each(['', ' ', '   ', '\n', ' \n\t '])('[QA-SPL-68-109] refuses a blank reason %j before anything is sent', async blank => {
  const { request } = open(detail);
  await openForm();
  typeReason(blank);
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Enter a reason for rejecting the request.');
  expect(screen.queryByRole('button', { name: 'Confirm rejection' })).toBeNull();
  expect(request).toHaveBeenCalledTimes(1);
});

it('[QA-SPL-68-110] clears the blank-reason error once a reason is entered', async () => {
  open(detail);
  await openForm();
  typeReason('  ');
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('alert');
  goToConfirm('A real reason');
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByRole('button', { name: 'Confirm rejection' })).toBeTruthy();
});

it('[QA-SPL-68-111] keeps a long multi-line reason in the box exactly as typed', async () => {
  open(detail);
  await openForm();
  const long = `Line one\nLine two ${'x'.repeat(1900)}`;
  typeReason(long);
  expect(reasonBox().value).toBe(long);
});

it('[QA-SPL-68-140] limits the reason box to 2,000 characters, matching the server', async () => {
  open(detail);
  await openForm();
  expect(reasonBox().maxLength).toBe(2000);
});

it('[QA-SPL-68-141] shows the server message when the reason is too long', async () => {
  open(detail, refused('Keep the reason to 2000 characters or fewer.'));
  await openForm();
  goToConfirm('x'.repeat(50));
  confirm();
  expect((await screen.findByRole('alert')).textContent).toContain('2000 characters or fewer');
  expect(screen.getByRole('button', { name: 'Confirm rejection' })).toBeTruthy();
});

// ---- AC3 / AC6: the final confirmation -----------------------------------------------------------

it('[QA-SPL-68-112] states that rejection is final and shows the reason before confirming', async () => {
  open(detail);
  await openForm();
  goToConfirm('  Clashes with exams.  ');
  expect(screen.getByText(/Rejection is final/)).toBeTruthy();
  expect(screen.getByText(/must submit a new event request/)).toBeTruthy();
  const group = screen.getByRole('group', { name: 'Confirm rejection' });
  expect(group.textContent).toContain('Clashes with exams.');
});

it('[QA-SPL-68-113] goes back from the confirmation with the typed reason still in the box', async () => {
  const { request } = open(detail);
  await openForm();
  goToConfirm('Keep this text');
  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
  expect(reasonBox().value).toBe('Keep this text');
  expect(request).toHaveBeenCalledTimes(1);
});

it('[QA-SPL-68-114] cancelling closes the form, clears the reason and leaves the event untouched', async () => {
  const { request } = open(detail);
  await openForm();
  typeReason('Half typed');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.queryByLabelText(REASON_LABEL)).toBeNull();
  await openForm();
  expect(reasonBox().value).toBe('');
  expect(request).toHaveBeenCalledTimes(1);
});

it('[QA-SPL-68-115] cancelling clears an earlier blank-reason error', async () => {
  open(detail);
  await openForm();
  typeReason('');
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.queryByRole('alert')).toBeNull();
});

it('[QA-SPL-68-116] posts only the reason, to the reject endpoint, with no status or decision-maker', async () => {
  const { request } = open(detail, rejectedReply());
  await openForm();
  goToConfirm('Clashes with exams.');
  confirm();
  await screen.findByText(SUCCESS);
  expect(request).toHaveBeenLastCalledWith('/api/event-requests/12/reject', {
    method: 'POST', body: JSON.stringify({ reason: 'Clashes with exams.' }),
  });
  expect(Object.keys(JSON.parse(request.mock.calls[1][1].body))).toEqual(['reason']);
  expect(request).toHaveBeenCalledTimes(2);
});

it('[QA-SPL-68-117] disables Confirm while rejecting and sends one request for a double click', async () => {
  let release: (value: unknown) => void = () => undefined;
  const pending = new Promise(resolve => { release = resolve; });
  const { request } = open(detail, pending);
  await openForm();
  goToConfirm();
  const button = screen.getByRole('button', { name: 'Confirm rejection' }) as HTMLButtonElement;
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Rejecting…' })).toBeTruthy());
  expect((screen.getByRole('button', { name: 'Rejecting…' }) as HTMLButtonElement).disabled).toBe(true);
  expect(request).toHaveBeenCalledTimes(2);
  release(rejectedReply());
  await screen.findByText(SUCCESS);
});

// ---- AC3 / AC4 / AC5: what the coordinator sees after success ------------------------------------

it('[QA-SPL-68-118] shows the server message, the new status, the decision-maker and the reason', async () => {
  open(detail, rejectedReply('Clashes with exams.'));
  await openForm();
  goToConfirm();
  confirm();
  expect(await screen.findByText(SUCCESS)).toBeTruthy();
  expect(screen.getAllByText('Not approved').length).toBeGreaterThan(0);
  expect((await screen.findByRole('rowheader', { name: 'Rejected by' })).closest('tr')!.textContent).toContain('Alice Tan');
  expect(screen.getByRole('rowheader', { name: 'Rejection reason' }).closest('tr')!.textContent).toContain('Clashes with exams.');
});

it('[QA-SPL-68-119] shows the decision time in Singapore time', async () => {
  open(detail, rejectedReply());
  await openForm();
  goToConfirm();
  confirm();
  const row = (await screen.findByRole('rowheader', { name: 'Rejected by' })).closest('tr')!;
  expect(row.textContent).toMatch(/27 Sept?\.? 2026/);
  expect(row.textContent).toMatch(/10:00\s?am/i);
});

it('[QA-SPL-68-120] removes every review action once the event is rejected', async () => {
  open(detail, rejectedReply());
  await openForm();
  goToConfirm();
  confirm();
  await screen.findByText(SUCCESS);
  for (const name of [REJECT, 'Approve request', 'Request clarification', 'Begin review', 'Confirm rejection', 'Continue']) {
    expect(screen.queryByRole('button', { name })).toBeNull();
  }
  expect(screen.queryByLabelText(REASON_LABEL)).toBeNull();
  expect(screen.queryByLabelText('Clarification for the Event Organiser')).toBeNull();
});

it('[QA-SPL-68-121] opens an already rejected event with its decision and no action to take', async () => {
  open({ ...detail, ...rejectedEvent('Out of scope.') });
  expect((await screen.findByRole('rowheader', { name: 'Rejection reason' })).closest('tr')!.textContent).toContain('Out of scope.');
  expect(screen.queryByRole('button', { name: REJECT })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Approve request' })).toBeNull();
});

it('[QA-SPL-68-122] shows no rejection rows for an event that has not been rejected', async () => {
  open(detail);
  await rejectButton();
  expect(screen.queryByRole('rowheader', { name: 'Rejected by' })).toBeNull();
  expect(screen.queryByRole('rowheader', { name: 'Rejection reason' })).toBeNull();
});

it('[QA-SPL-68-123] shows an approved event without any rejection rows', async () => {
  open({ ...detail, status: 'planning', status_label: 'In planning', approved_by: alice, approved_at: '2026-09-27T10:00:00+08:00' });
  expect(await screen.findByRole('rowheader', { name: 'Approved by' })).toBeTruthy();
  expect(screen.queryByRole('rowheader', { name: 'Rejected by' })).toBeNull();
});

it('[QA-SPL-68-124] renders a reason containing markup as plain text', async () => {
  const hostile = '<img src=x onerror="alert(1)"><b>bold</b>';
  const { view } = open({ ...detail, ...rejectedEvent(hostile) });
  const cell = (await screen.findByRole('rowheader', { name: 'Rejection reason' })).closest('tr')!;
  expect(cell.textContent).toContain(hostile);
  expect(view.container.querySelector('img')).toBeNull();
  expect(view.container.querySelector('td b')).toBeNull();
});

// ---- AC6: refusals and failures leave the event as it was ----------------------------------------

it('[QA-SPL-68-125] shows the server message when rejection is refused and keeps the event under review', async () => {
  open(detail, refused('Only an event under review can be rejected.'));
  await openForm();
  goToConfirm();
  confirm();
  expect((await screen.findByRole('alert')).textContent).toContain('Only an event under review can be rejected.');
  expect(screen.getByRole('button', { name: 'Confirm rejection' })).toBeTruthy();
  expect(screen.queryByText(SUCCESS)).toBeNull();
  expect(screen.queryByRole('rowheader', { name: 'Rejected by' })).toBeNull();
});

it('[QA-SPL-68-126] keeps the typed reason after a refusal so the coordinator can go back and retry', async () => {
  open(detail, refused('Assigned event not found.'));
  await openForm();
  goToConfirm('Keep me');
  confirm();
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
  expect(reasonBox().value).toBe('Keep me');
});

it('[QA-SPL-68-127] can retry successfully after a refusal', async () => {
  open(detail, refused('Something went wrong.'), rejectedReply());
  await openForm();
  goToConfirm();
  confirm();
  await screen.findByRole('alert');
  confirm();
  expect(await screen.findByText(SUCCESS)).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});

it('[QA-SPL-68-128] falls back to a plain message when the refusal has no body', async () => {
  open(detail, refused());
  await openForm();
  goToConfirm();
  confirm();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not reject the request. Try again.');
});

it('[QA-SPL-68-129] shows a plain message when the network fails and keeps the confirmation open', async () => {
  const request = vi.fn().mockResolvedValueOnce(ok({ event: detail })).mockRejectedValueOnce(new Error('offline'));
  render(<AssignedEvents accessToken="t" eventId={12} request={request} onNavigate={vi.fn()} />);
  fireEvent.click(await rejectButton());
  goToConfirm();
  confirm();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not reject the request. Try again.');
  expect((screen.getByRole('button', { name: 'Confirm rejection' }) as HTMLButtonElement).disabled).toBe(false);
});

it('[QA-SPL-68-130] treats a success answer with no event as a failure', async () => {
  open(detail, ok({ message: SUCCESS }));
  await openForm();
  goToConfirm();
  confirm();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not reject the request. Try again.');
  expect(screen.queryByText(SUCCESS)).toBeNull();
});

it('[QA-SPL-68-131] treats an unreadable success answer as a failure', async () => {
  open(detail, { ok: true, json: async () => { throw new Error('bad json'); } });
  await openForm();
  goToConfirm();
  confirm();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not reject the request. Try again.');
});

it('[QA-SPL-68-132] falls back to the standard success message when the server sends none', async () => {
  open(detail, ok({ event: rejectedEvent() }));
  await openForm();
  goToConfirm();
  confirm();
  expect(await screen.findByText(SUCCESS)).toBeTruthy();
});

it('[QA-SPL-68-133] does not carry an unsent reason over to a different event', async () => {
  const request = vi.fn().mockImplementation(async (path: string) =>
    ok({ event: path.endsWith('/13') ? { ...detail, id: 13, name: 'Other Forum' } : detail }));
  const view = render(<AssignedEvents accessToken="t" eventId={12} request={request} onNavigate={vi.fn()} />);
  fireEvent.click(await rejectButton());
  typeReason('Belongs to event 12');
  view.rerender(<AssignedEvents accessToken="t" eventId={13} request={request} onNavigate={vi.fn()} />);
  expect(await screen.findByText('Other Forum', { selector: 'h1' })).toBeTruthy();
  expect(screen.queryByLabelText(REASON_LABEL)).toBeNull();
  fireEvent.click(await rejectButton());
  expect(reasonBox().value).toBe('');
});

it('[QA-SPL-68-134] does not send an unsent clarification when rejecting', async () => {
  const { request } = open(detail, rejectedReply());
  fireEvent.change(await screen.findByLabelText('Clarification for the Event Organiser'), { target: { value: 'Half typed' } });
  fireEvent.click(await rejectButton());
  goToConfirm('Real reason');
  confirm();
  await screen.findByText(SUCCESS);
  expect(request.mock.calls[1][1].body).toBe(JSON.stringify({ reason: 'Real reason' }));
});

// ---- AC4: the organiser's own status table -------------------------------------------------------

const organiserRow = (extra: Record<string, unknown>) => ({
  id: 1, name: 'Forum', status: 'rejected', status_label: 'Not approved', status_explanation: 'Not accepted.',
  status_changed_at: null, last_saved_at: null, proposed_date: null, coordinator: alice, ...extra,
});
const organiserView = async (rows: unknown[]) => {
  const request = vi.fn(async () => ({ ok: true, json: async () => ({ event_requests: rows }) }));
  render(<EventRequestDrafts accessToken="token" request={request as never} />);
};

it('[QA-SPL-68-135] shows the organiser who rejected the request, when, and why', async () => {
  await organiserView([organiserRow({ rejected_by: alice, rejected_at: '2026-09-27T10:00:00+08:00', rejection_reason: 'Clashes with exams.' })]);
  expect(await screen.findByText(/Rejected by Alice Tan on/)).toBeTruthy();
  expect(screen.getByText('Reason: Clashes with exams.')).toBeTruthy();
  expect(screen.getByText('Not approved')).toBeTruthy();
});

it('[QA-SPL-68-136] shows no rejection lines for a request that was not rejected', async () => {
  await organiserView([organiserRow({ status: 'planning', status_label: 'In planning', rejected_by: null, rejected_at: null, rejection_reason: null })]);
  expect(await screen.findByText('In planning')).toBeTruthy();
  expect(screen.queryByText(/Rejected by/)).toBeNull();
  expect(screen.queryByText(/Reason:/)).toBeNull();
});

it('[QA-SPL-68-137] shows who rejected the request even when the time is missing', async () => {
  await organiserView([organiserRow({ rejected_by: alice, rejected_at: null, rejection_reason: 'No time.' })]);
  expect((await screen.findByText(/Rejected by Alice Tan/)).textContent).toBe('Rejected by Alice Tan');
});

it('[QA-SPL-68-138] shows the outcome for each request in a mixed list', async () => {
  await organiserView([
    organiserRow({ id: 1, name: 'Rejected one', rejected_by: alice, rejected_at: '2026-09-27T10:00:00+08:00', rejection_reason: 'Reason A' }),
    organiserRow({ id: 2, name: 'Approved one', status: 'planning', status_label: 'In planning', approved_by: alice, approved_at: '2026-09-27T11:00:00+08:00' }),
  ]);
  expect(await screen.findByText('Reason: Reason A')).toBeTruthy();
  expect(screen.getByText(/Approved by Alice Tan on/)).toBeTruthy();
  expect(screen.getAllByText(/Rejected by/).length).toBe(1);
});

it('[QA-SPL-68-139] renders the organiser-facing reason as plain text', async () => {
  const hostile = '<script>alert(1)</script>';
  await organiserView([organiserRow({ rejected_by: alice, rejected_at: null, rejection_reason: hostile })]);
  expect(await screen.findByText(`Reason: ${hostile}`)).toBeTruthy();
  expect(document.querySelector('script')).toBeNull();
});
