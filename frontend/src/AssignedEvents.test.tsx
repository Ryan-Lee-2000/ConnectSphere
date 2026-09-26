import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';

afterEach(cleanup);

const assigned = {
  id: 12, name: 'Community Forum', status: 'submitted',
  status_label: 'Submitted', proposed_date: '2026-10-12',
};

it('shows an assigned event with status and proposed date, then opens its route', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [assigned] }) });
  const onNavigate = vi.fn();
  render(<AssignedEvents accessToken="token" request={request} onNavigate={onNavigate} />);
  expect(await screen.findByRole('link', { name: 'Community Forum' })).toBeTruthy();
  expect(screen.getByText('Submitted')).toBeTruthy();
  expect(screen.getByText('12 Oct 2026')).toBeTruthy();
  fireEvent.click(screen.getByRole('link', { name: 'Community Forum' }));
  expect(onNavigate).toHaveBeenCalledWith('/workspace/assigned-events/12');
  expect(request).toHaveBeenCalledWith('/api/event-requests/assigned');
});

it('opens the selected event using the assigned-only detail endpoint', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ event: assigned }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);
  expect(await screen.findByRole('heading', { name: 'Community Forum' })).toBeTruthy();
  expect(screen.getByText('Submitted')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/assigned/12');
});

const fullDetail = {
  ...assigned,
  purpose: 'Client showcase', description: null, start_time: '09:00', end_time: '12:00',
  expected_attendance: 120, venue_name: 'Harbour Hall', preferred_room_layout: 'Theatre',
  required_facilities: ['Projector', 'Microphone'], facilities_notes: null,
  accessibility_needs: [], location_preference: null, venue_notes: null,
  equipment_requirements: [{ equipment_type: 'Podium', quantity: 2, notes: 'Lockable' }],
  registration_required: true, registration_notes: 'Ticketed',
  client_organisation: 'Northstar Community Partners', responsible_organiser: 'Olivia Organiser',
  submitted_at: '2026-09-01T09:00:00+08:00',
};

it('[TC-SPL-64-01, TC-SPL-64-02] shows every request field in a table, marking empty ones', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ event: fullDetail }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  const row = async (label: string) => (await screen.findByRole('rowheader', { name: label })).closest('tr')!;
  expect((await row('Purpose')).textContent).toContain('Client showcase');
  expect((await row('Time')).textContent).toContain('09:00–12:00');
  expect((await row('Venue')).textContent).toContain('Harbour Hall');
  expect((await row('Required facilities')).textContent).toContain('Projector, Microphone');
  expect((await row('Equipment')).textContent).toContain('Podium × 2 (Lockable)');
  expect((await row('Registration required')).textContent).toContain('Yes');
  expect((await row('Client organisation')).textContent).toContain('Northstar Community Partners');
  expect((await row('Responsible Event Organiser')).textContent).toContain('Olivia Organiser');
  expect((await row('Submission date and time')).textContent).toContain('1 Sept 2026');
  expect((await row('Description')).textContent).toContain('Not provided');
  expect((await row('Accessibility needs')).textContent).toContain('Not provided');
  expect(screen.queryByRole('textbox')).toBeNull();
});

it('[TC-SPL-64-03] shows only the unavailable message when the request cannot be retrieved', async () => {
  const request = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'Assigned event not found.' }) });
  render(<AssignedEvents accessToken="token" eventId={99} request={request} onNavigate={vi.fn()} />);
  expect((await screen.findByRole('alert')).textContent).toBe('This assigned event is unavailable.');
  expect(screen.queryByRole('table')).toBeNull();
});

it('[TC-SPL-64-06] keeps the full detail visible after begin review returns the summary shape', async () => {
  const underReview = { ...assigned, status: 'under_review', status_label: 'Under review' };
  const request = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ event: fullDetail }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ event: underReview }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Begin review' }));
  expect(await screen.findByText('Review started.')).toBeTruthy();
  expect(screen.getByText('Under review')).toBeTruthy();
  expect(screen.getByText('Harbour Hall')).toBeTruthy();
});

function renderDetail(event: Record<string, unknown>) {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ event }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);
  return async (label: string) => (await screen.findByRole('rowheader', { name: label })).closest('tr')!.textContent!;
}

it('[TC-SPL-64-10] renders registration as No when false and Not provided when the field is absent', async () => {
  const row = renderDetail({ ...fullDetail, registration_required: false });
  expect(await row('Registration required')).toContain('No');
  cleanup();
  const absent = renderDetail(assigned);
  expect(await absent('Registration required')).toContain('Not provided');
});

it('[TC-SPL-64-11] shows Not provided for every empty value and an empty equipment list', async () => {
  const row = renderDetail({ ...assigned, proposed_date: null, description: '', equipment_requirements: [], required_facilities: [], submitted_at: null });
  expect(await row('Proposed date')).toContain('Not provided');
  expect(await row('Description')).toContain('Not provided');
  expect(await row('Equipment')).toContain('Not provided');
  expect(await row('Required facilities')).toContain('Not provided');
  expect(await row('Submission date and time')).toContain('Not provided');
  expect(await row('Time')).toContain('Not provided');
});

it('[TC-SPL-64-12] shows Time only when both a start and an end are present', async () => {
  const row = renderDetail({ ...fullDetail, end_time: null });
  expect(await row('Time')).toContain('Not provided');
});

it('[TC-SPL-64-13] lists several equipment lines and omits empty notes', async () => {
  const row = renderDetail({
    ...fullDetail,
    equipment_requirements: [
      { equipment_type: 'Podium', quantity: 2, notes: 'Lockable' },
      { equipment_type: 'Lamp', quantity: 1, notes: null },
    ],
  });
  const text = await row('Equipment');
  expect(text).toContain('Podium × 2 (Lockable)');
  expect(text).toContain('Lamp × 1');
  expect(text).not.toContain('Lamp × 1 (');
});

it('[TC-SPL-64-14] keeps zero attendance rather than treating it as empty', async () => {
  const row = renderDetail({ ...fullDetail, expected_attendance: 0 });
  expect(await row('Expected attendance')).toContain('0');
  expect(await row('Expected attendance')).not.toContain('Not provided');
});

it('[TC-SPL-64-15] shows the submission time in Singapore time whatever offset arrives', async () => {
  const row = renderDetail({ ...fullDetail, submitted_at: '2026-09-01T17:00:00Z' });
  const text = await row('Submission date and time');
  expect(text).toContain('2 Sept 2026');
});

it('[TC-SPL-64-16] shows a retry message when the detail response is malformed or the request throws', async () => {
  const malformed = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  render(<AssignedEvents accessToken="token" eventId={12} request={malformed} onNavigate={vi.fn()} />);
  expect((await screen.findByRole('alert')).textContent).toBe('Could not load your assigned events. Try again.');
  cleanup();
  const thrown = vi.fn().mockRejectedValue(new Error('offline'));
  render(<AssignedEvents accessToken="token" eventId={12} request={thrown} onNavigate={vi.fn()} />);
  expect((await screen.findByRole('alert')).textContent).toBe('Could not load your assigned events. Try again.');
  expect(screen.queryByRole('table')).toBeNull();
});

it('[TC-SPL-64-17] hides Begin review once the event is under review but keeps the full detail', async () => {
  renderDetail({ ...fullDetail, status: 'under_review', status_label: 'Under review' });
  expect(await screen.findByText('Harbour Hall')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Begin review' })).toBeNull();
});

it('[TC-SPL-64-18] exposes the detail as one accessible table with a caption and row headers', async () => {
  renderDetail(fullDetail);
  const table = await screen.findByRole('table', { name: /Submitted request details for Community Forum/ });
  expect(table).toBeTruthy();
  expect(screen.getAllByRole('rowheader').length).toBeGreaterThanOrEqual(19);
  expect(screen.getAllByRole('columnheader').map(cell => cell.textContent)).toEqual([
    'Core details', 'Venue requirements', 'Equipment requirements', 'Registration needs', 'Organisation and submission',
  ]);
  expect(screen.queryAllByRole('button').filter(b => b.textContent !== 'Begin review')).toEqual([]);
});

it('[TC-SPL-70-01, TC-SPL-70-05] lets the assigned coordinator begin review from a submitted event', async () => {
  const underReview = { ...assigned, status: 'under_review', status_label: 'Under review' };
  const request = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ event: assigned }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ event: underReview }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Begin review' }));

  expect(await screen.findByText('Review started.')).toBeTruthy();
  expect(screen.getByText('Under review')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Begin review' })).toBeNull();
  expect(request).toHaveBeenLastCalledWith(
    '/api/event-requests/12/begin-review',
    { method: 'POST' },
  );
});

it('[TC-SPL-70-05] keeps the submitted status available when begin review is refused', async () => {
  const request = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ event: assigned }) })
    .mockResolvedValueOnce({ ok: false, json: async () => ({ error: 'Only a submitted event can begin review.' }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Begin review' }));

  expect((await screen.findByRole('alert')).textContent).toContain('Only a submitted event can begin review.');
  expect(screen.getByText('Submitted')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Begin review' })).toBeTruthy();
});

it('shows an empty state when nothing is assigned', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [] }) });
  render(<AssignedEvents accessToken="token" request={request} onNavigate={vi.fn()} />);
  expect(await screen.findByText('No events assigned to you yet.')).toBeTruthy();
});

const underReviewDetail = { ...fullDetail, status: 'under_review', status_label: 'Under review', clarifications: [] };
const clarificationAnswer = {
  event: { ...assigned, status: 'returned_for_clarification', status_label: 'Returned for clarification' },
  clarifications: [{
    id: 1, message: 'Please confirm the attendance.', author: { id: 'a', name: 'Alice Tan' },
    created_at: '2026-09-26T10:00:00+08:00',
  }],
};

it('[TC-SPL-65-09] shows the clarification form only while the event is under review', async () => {
  renderDetail(fullDetail);
  expect(await screen.findByText('Harbour Hall')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Request clarification' })).toBeNull();
  cleanup();
  renderDetail(underReviewDetail);
  expect(await screen.findByRole('button', { name: 'Request clarification' })).toBeTruthy();
  expect(screen.getByLabelText('Clarification for the Event Organiser')).toBeTruthy();
});

it('[TC-SPL-65-09] sends the message, then shows the new status and history without the form', async () => {
  const request = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ event: underReviewDetail }) })
    .mockResolvedValueOnce({ ok: true, json: async () => clarificationAnswer });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.change(await screen.findByLabelText('Clarification for the Event Organiser'), {
    target: { value: 'Please confirm the attendance.' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Request clarification' }));

  expect(await screen.findByText(/Clarification requested/)).toBeTruthy();
  expect(screen.getAllByText('Returned for clarification').length).toBeGreaterThan(0);
  expect(screen.getByText('Please confirm the attendance.')).toBeTruthy();
  expect(screen.getByText('Harbour Hall')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Request clarification' })).toBeNull();
  expect(request).toHaveBeenLastCalledWith('/api/event-requests/12/request-clarification', {
    method: 'POST',
    body: JSON.stringify({ message: 'Please confirm the attendance.' }),
  });
});

it('[TC-SPL-65-10] refuses a blank message without calling the server', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ event: underReviewDetail }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.change(await screen.findByLabelText('Clarification for the Event Organiser'), { target: { value: '   ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Request clarification' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Enter a clarification message.');
  expect(request).toHaveBeenCalledTimes(1);
});

it('[TC-SPL-65-10] keeps the form and message when the server refuses the request', async () => {
  const request = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ event: underReviewDetail }) })
    .mockResolvedValueOnce({ ok: false, json: async () => ({ error: 'Clarification can only be requested while the event is under review.' }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.change(await screen.findByLabelText('Clarification for the Event Organiser'), { target: { value: 'Why?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Request clarification' }));

  expect((await screen.findByRole('alert')).textContent).toContain('only be requested while the event is under review');
  expect((screen.getByLabelText('Clarification for the Event Organiser') as HTMLTextAreaElement).value).toBe('Why?');
});

it('[TC-SPL-65-11] lists the clarification history newest first', async () => {
  renderDetail({
    ...fullDetail, status: 'returned_for_clarification', status_label: 'Returned for clarification',
    clarifications: [
      { id: 2, message: 'Second question', author: { id: 'a', name: 'Alice Tan' }, created_at: '2026-09-27T10:00:00+08:00' },
      { id: 1, message: 'First question', author: { id: 'a', name: 'Alice Tan' }, created_at: '2026-09-26T10:00:00+08:00' },
    ],
  });
  const items = await screen.findAllByRole('listitem');
  expect(items.map(item => item.textContent).join('|')).toMatch(/Second question.*First question/);
});
