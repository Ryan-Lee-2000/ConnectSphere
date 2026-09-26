// QA test scripts for SPL-65 (CS-E06-S2 — request clarification), interface level.
//
// Each title starts with the QA test case ID used in the QA-SPL-65 Confluence report. Find any case
// with:  rg -n "QA-SPL-65-083" backend/tests frontend/src
// Backend cases (QA-SPL-65-001 to 071) are in backend/tests/test_qa_spl65*.py.
//
// AC1 assigned coordinator can request while Under Review    AC5 organiser can retrieve the message
// AC2 non-blank message required                              AC6 history retained
// AC3 message, author, date/time recorded                     AC7 refused where not permitted
// AC4 event moves to Returned for Clarification
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';
import { ClarificationHistory } from './ClarificationHistory';
import { OrganisationEvents } from './OrganisationEvents';

afterEach(cleanup);

const LABEL = 'Clarification for the Event Organiser';
const summary = {
  id: 12, name: 'Community Forum', status: 'under_review', status_label: 'Under review', proposed_date: '2026-10-12',
  mapped_slots: ['AM', 'PM'], expected_attendance: 120, preferred_room_layout: 'theatre',
  required_facilities: ['Projector', 'PA system'], accessibility_needs: ['Step-free access'],
  location_preference: 'Marina Centre',
};
const detail = { ...summary, purpose: 'Forum', clarifications: [] as unknown[] };
const returned = { ...summary, status: 'returned_for_clarification', status_label: 'Returned for clarification' };
const asker = { id: 'alice', name: 'Alice Tan' };
const item = (id: number, message: string, created_at = '2026-09-26T10:00:00+08:00') => ({ id, message, author: asker, created_at });

const ok = (body: unknown) => ({ ok: true, json: async () => body });
const refused = (error?: string) => ({ ok: false, json: async () => (error ? { error } : {}) });

function open(event: Record<string, unknown>, ...replies: unknown[]) {
  const request = vi.fn().mockResolvedValueOnce(ok({ event }));
  replies.forEach(reply => request.mockResolvedValueOnce(reply));
  render(<AssignedEvents accessToken="t" eventId={12} request={request} onNavigate={vi.fn()} />);
  return request;
}

const textbox = () => screen.findByLabelText(LABEL) as Promise<HTMLTextAreaElement>;
const type = async (text: string) => fireEvent.change(await textbox(), { target: { value: text } });
const send = () => fireEvent.click(screen.getByRole('button', { name: /Request clarification|Requesting clarification/ }));

// ---- AC1 / AC7: when the form is offered --------------------------------------------------------

it('[QA-SPL-65-072] offers a labelled message box and an enabled button while Under Review', async () => {
  open(detail);
  expect((await textbox()).tagName).toBe('TEXTAREA');
  expect((screen.getByRole('button', { name: 'Request clarification' }) as HTMLButtonElement).disabled).toBe(false);
});

it.each([
  'draft', 'submitted', 'returned_for_clarification', 'approved', 'planning',
  'confirmed', 'completed', 'cancelled', 'rejected', 'withdrawn', 'postponed',
])('[QA-SPL-65-073] does not offer the form when the event is %s', async status => {
  open({ ...detail, status, status_label: status });
  expect(await screen.findByText('Community Forum', { selector: 'h1' })).toBeTruthy();
  expect(screen.queryByLabelText(LABEL)).toBeNull();
  expect(screen.queryByRole('button', { name: 'Request clarification' })).toBeNull();
});

// ---- AC3 / AC4: the happy flow ------------------------------------------------------------------

it('[QA-SPL-65-074] sends the message to the action endpoint and shows the returned status', async () => {
  const request = open(detail, ok({ event: returned, clarifications: [item(1, 'Please confirm the attendance.')] }));
  await type('Please confirm the attendance.');
  send();

  expect(await screen.findByText(/Clarification requested/)).toBeTruthy();
  expect(request).toHaveBeenLastCalledWith('/api/event-requests/12/request-clarification', {
    method: 'POST', body: JSON.stringify({ message: 'Please confirm the attendance.' }),
  });
  expect(screen.getAllByText('Returned for clarification').length).toBeGreaterThan(0);
});

it('[QA-SPL-65-075] hides the form and empties nothing else after success', async () => {
  open({ ...detail, purpose: 'Client showcase' }, ok({ event: returned, clarifications: [item(1, 'Why?')] }));
  await type('Why?');
  send();
  await screen.findByText(/Clarification requested/);
  expect(screen.queryByLabelText(LABEL)).toBeNull();
  expect(screen.getByText('Client showcase')).toBeTruthy();
});

it('[QA-SPL-65-076] shows the message, author and Singapore date and time in the history', async () => {
  open(detail, ok({ event: returned, clarifications: [item(1, 'Check the layout.', '2026-09-26T10:05:00+08:00')] }));
  await type('Check the layout.');
  send();
  const history = await screen.findByRole('list');
  expect(within(history).getByText('Check the layout.')).toBeTruthy();
  expect(within(history).getByText(/Alice Tan · 26 Sept 2026, 10:05/)).toBeTruthy();
});

it('[QA-SPL-65-077] posts the text exactly as typed, including line breaks (the server trims)', async () => {
  const request = open(detail, ok({ event: returned, clarifications: [item(1, 'a')] }));
  await type('  Line one\n\nLine two  ');
  send();
  await screen.findByText(/Clarification requested/);
  expect(JSON.parse((request.mock.calls[1][1] as { body: string }).body)).toEqual({ message: '  Line one\n\nLine two  ' });
});

// ---- AC2: a non-blank message -------------------------------------------------------------------

it.each(['', ' ', '   \n\t  '])('[QA-SPL-65-078] refuses %j without contacting the server', async blank => {
  const request = open(detail);
  await type(blank);
  send();
  expect((await screen.findByRole('alert')).textContent).toBe('Enter a clarification message.');
  expect(request).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Request clarification' })).toBeTruthy();
});

it('[QA-SPL-65-079] limits the box to 2000 characters', async () => {
  open(detail);
  expect((await textbox()).maxLength).toBe(2000);
});

it('[QA-SPL-65-080] clears the blank-message error once a real message is sent', async () => {
  open(detail, ok({ event: returned, clarifications: [item(1, 'Real')] }));
  await type('');
  send();
  await screen.findByRole('alert');
  await type('Real');
  send();
  await screen.findByText(/Clarification requested/);
  expect(screen.queryByRole('alert')).toBeNull();
});

// ---- AC7 and failure handling -------------------------------------------------------------------

it('[QA-SPL-65-081] shows the server refusal and keeps both the form and the typed text', async () => {
  open(detail, refused('Clarification can only be requested while the event is under review.'));
  await type('My question');
  send();
  expect((await screen.findByRole('alert')).textContent).toContain('only be requested while the event is under review');
  expect((await textbox()).value).toBe('My question');
  expect(screen.getAllByText('Under review').length).toBeGreaterThan(0);
});

it('[QA-SPL-65-082] falls back to a generic message when the server gives no reason', async () => {
  open(detail, refused());
  await type('Question');
  send();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not request clarification. Try again.');
});

it('[QA-SPL-65-083] survives a network failure and lets the coordinator try again', async () => {
  const request = open(detail);
  request.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(ok({ event: returned, clarifications: [item(1, 'Question')] }));
  await type('Question');
  send();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not request clarification. Try again.');
  expect((await textbox()).value).toBe('Question');
  send();
  expect(await screen.findByText(/Clarification requested/)).toBeTruthy();
});

it('[QA-SPL-65-084] treats a success reply without an event as a failure', async () => {
  open(detail, ok({}));
  await type('Question');
  send();
  expect((await screen.findByRole('alert')).textContent).toBe('Could not request clarification. Try again.');
  expect(screen.getAllByText('Under review').length).toBeGreaterThan(0);
});

it('[QA-SPL-65-085] sends once when the button is pressed repeatedly while the request is pending', async () => {
  let finish: (value: unknown) => void = () => {};
  const request = open(detail);
  request.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  await type('Question');
  send();
  const pending = await screen.findByRole('button', { name: 'Requesting clarification…' }) as HTMLButtonElement;
  expect(pending.disabled).toBe(true);
  fireEvent.click(pending);
  fireEvent.submit(pending.closest('form')!);
  await act(async () => { finish(ok({ event: returned, clarifications: [item(1, 'Question')] })); });
  await screen.findByText(/Clarification requested/);
  expect(request).toHaveBeenCalledTimes(2); // one load, one clarification
});

// ---- AC6: history in the coordinator's view -----------------------------------------------------

it('[QA-SPL-65-086] lists earlier clarifications newest first beside the returned status', async () => {
  open({ ...returned, clarifications: [item(3, 'Third'), item(2, 'Second'), item(1, 'First')] });
  const entries = await screen.findAllByRole('listitem');
  expect(entries.map(entry => entry.textContent!.match(/First|Second|Third/)![0])).toEqual(['Third', 'Second', 'First']);
});

it('[QA-SPL-65-087] shows no history section when there is nothing to show', async () => {
  open(detail);
  await textbox();
  expect(screen.queryByRole('heading', { name: 'Clarification history' })).toBeNull();
});

it('[QA-SPL-65-088] keeps the older history when a new clarification is added', async () => {
  open({ ...detail, clarifications: [item(1, 'Earlier question')] },
    ok({ event: returned, clarifications: [item(2, 'Newer question'), item(1, 'Earlier question')] }));
  expect(await screen.findByText('Earlier question')).toBeTruthy();
  await type('Newer question');
  send();
  await screen.findByText(/Clarification requested/);
  expect(screen.getAllByRole('listitem').map(entry => entry.textContent)).toEqual([
    expect.stringContaining('Newer question'), expect.stringContaining('Earlier question'),
  ]);
});

it('[QA-SPL-65-089] does not carry a typed draft over to a different event', async () => {
  const request = vi.fn().mockResolvedValue(ok({ event: detail }));
  const { rerender } = render(<AssignedEvents accessToken="t" eventId={12} request={request} onNavigate={vi.fn()} />);
  await type('Half-written question');
  rerender(<AssignedEvents accessToken="t" eventId={13} request={request} onNavigate={vi.fn()} />);
  await screen.findByLabelText(LABEL);
  expect(((await textbox()) as HTMLTextAreaElement).value).toBe('');
});

it('[QA-SPL-65-090] shows the Returned for clarification status in the coordinator\'s event list', async () => {
  const request = vi.fn().mockResolvedValue(ok({ events: [returned, { ...summary, id: 13, name: 'Other' }] }));
  render(<AssignedEvents accessToken="t" request={request} onNavigate={vi.fn()} />);
  const row = (await screen.findByRole('link', { name: 'Community Forum' })).closest('tr')!;
  expect(row.textContent).toContain('Returned for clarification');
  expect(screen.getByRole('columnheader', { name: 'Status' })).toBeTruthy();
});

it('[QA-SPL-65-091] gives the form, error and notice accessible roles and names', async () => {
  open(detail, ok({ event: returned, clarifications: [item(1, 'Q')] }));
  const box = await textbox();
  expect(box.id).toBe('clarification-message');
  fireEvent.change(box, { target: { value: ' ' } });
  send();
  expect((await screen.findByRole('alert')).textContent).toBeTruthy();
  fireEvent.change(box, { target: { value: 'Q' } });
  send();
  expect((await screen.findByRole('status')).textContent).toContain('Clarification requested');
  expect(screen.getByRole('heading', { name: 'Clarification history' })).toBeTruthy();
});

// ---- AC5: what the Event Organiser sees ---------------------------------------------------------

const organiserEvent = {
  id: 7, name: 'Community Forum', purpose: 'Partners', description: null, proposed_date: '2026-12-04',
  start_time: '09:30', end_time: '12:00', expected_attendance: 80, responsible_organiser: 'Olivia Owner',
  status: 'returned_for_clarification', status_label: 'Returned for clarification',
  status_explanation: 'Your Event Coordinator needs more information. Update your request with what they asked for.',
  clarifications: [item(2, 'Second question', '2026-09-27T09:00:00+08:00'), item(1, 'First question')],
};
const organiserView = (event: Record<string, unknown>) => render(
  <OrganisationEvents accessToken="t" eventId={7} onNavigate={vi.fn()} request={vi.fn().mockResolvedValue(ok({ event }))} />);

it('[QA-SPL-65-092] shows the organiser the status and what they need to do about it', async () => {
  organiserView(organiserEvent);
  expect(await screen.findByText('Returned for clarification')).toBeTruthy();
  expect(screen.getByRole('status').textContent).toContain('Update your request with what they asked for.');
});

it('[QA-SPL-65-093] shows the organiser every clarification, newest first, with author and time', async () => {
  organiserView(organiserEvent);
  const entries = await screen.findAllByRole('listitem');
  expect(entries[0].textContent).toContain('Second question');
  expect(entries[1].textContent).toContain('First question');
  expect(entries[0].textContent).toMatch(/Alice Tan · 27 Sept 2026, 9:00\s*am/i);
  expect(screen.getByRole('heading', { name: 'Clarification requests' })).toBeTruthy();
});

it('[QA-SPL-65-094] gives the organiser a read-only view with no message box or action', async () => {
  organiserView(organiserEvent);
  await screen.findByText('Second question');
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
});

it('[QA-SPL-65-095] shows no guidance banner or history when the event was never returned', async () => {
  organiserView({ ...organiserEvent, status: 'submitted', status_label: 'Submitted', clarifications: [] });
  expect(await screen.findByText('Submitted')).toBeTruthy();
  expect(screen.queryByRole('status')).toBeNull();
  expect(screen.queryByRole('heading', { name: 'Clarification requests' })).toBeNull();
});

it('[QA-SPL-65-096] keeps earlier clarifications visible after the event is Under Review again', async () => {
  organiserView({ ...organiserEvent, status: 'under_review', status_label: 'Under review' });
  expect(await screen.findByText('First question')).toBeTruthy();
  expect(screen.queryByRole('status')).toBeNull();
});

it('[QA-SPL-65-097] tolerates an older response that has no clarifications field', async () => {
  const { clarifications: _omitted, ...withoutHistory } = organiserEvent;
  organiserView(withoutHistory);
  expect(await screen.findByText('Returned for clarification')).toBeTruthy();
  expect(screen.queryByRole('list')).toBeNull();
});

// ---- The shared history component, on its own ---------------------------------------------------

it('[QA-SPL-65-098] renders nothing at all for an empty history', () => {
  const { container } = render(<ClarificationHistory clarifications={[]} heading="History" />);
  expect(container.innerHTML).toBe('');
});

it('[QA-SPL-65-099] shows an unparseable timestamp as received instead of "Invalid Date"', () => {
  render(<ClarificationHistory clarifications={[item(1, 'Odd', 'not-a-date')]} heading="History" />);
  expect(screen.getByText('Alice Tan · not-a-date')).toBeTruthy();
});

it('[QA-SPL-65-100] displays the time in Singapore whatever offset the server used', () => {
  render(<ClarificationHistory clarifications={[item(1, 'UTC stamp', '2026-09-27T01:00:00+00:00')]} heading="History" />);
  expect(screen.getByText(/Alice Tan · 27 Sept 2026, 9:00\s*am/i)).toBeTruthy();
});

it('[QA-SPL-65-101] renders message text as text, never as markup', () => {
  render(<ClarificationHistory clarifications={[item(1, '<img src=x onerror=alert(1)> **bold**')]} heading="History" />);
  expect(screen.getByText('<img src=x onerror=alert(1)> **bold**')).toBeTruthy();
  expect(document.querySelector('img')).toBeNull();
});
