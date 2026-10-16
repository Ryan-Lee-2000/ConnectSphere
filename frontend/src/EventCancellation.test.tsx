import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';
import { CoordinatorSupervision } from './CoordinatorSupervision';
import { EventRequestDrafts } from './EventRequestDrafts';

// SPL-86 (CS-E07-S5) interface cases from QA-SPL-86. The server owns which events can be cancelled
// and what is released; these tests prove the pages offer, send and show it faithfully.

afterEach(cleanup);

const planning = {
  id: 12, name: 'Community Leadership Forum', status: 'planning', status_label: 'In planning',
  proposed_date: '2026-11-20', mapped_slots: ['PM'], start_time: '14:00', end_time: '17:00',
  expected_attendance: 80, equipment_requirements: [], registration_required: false,
  confirmed_by: null, confirmed_at: null, cancelled_by: null, cancelled_at: null, cancellation_reason: null,
};
const cancelled = {
  ...planning, status: 'cancelled', status_label: 'Cancelled',
  cancelled_by: { id: 'c', name: 'Casey Coordinator' }, cancelled_at: '2026-10-16T21:00:00+08:00',
  cancellation_reason: 'The keynote speaker withdrew.',
};

const json = (body: unknown, ok = true, status = 200) =>
  ({ ok, status, json: async () => body }) as unknown as Response;

function api(detail: unknown, cancelResponse?: Response) {
  return vi.fn(async (path: string, _init?: RequestInit): Promise<Response> => {
    if (path === '/api/event-requests/assigned/12') return json({ event: detail });
    if (path === '/api/event-requests/12/cancel') return cancelResponse ?? json({ error: 'unexpected' }, false, 500);
    return json({ booking: null });
  });
}

const cancelCalls = (request: ReturnType<typeof api>) =>
  request.mock.calls.filter(([path]) => path === '/api/event-requests/12/cancel');

// TC-SPL-86-40 (BB) AC1/AC2: two steps; a blank reason sends nothing; the reason is sent trimmed
it('[TC-SPL-86-40] cancels only after a reason and the second step', async () => {
  const request = api(planning, json({
    event: cancelled, message: 'Event cancelled. Its venues and equipment are free for other events.',
  }));
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  const panel = within(await screen.findByRole('region', { name: 'Cancel this event' }));
  fireEvent.click(panel.getByRole('button', { name: 'Cancel event' }));
  const form = screen.getByRole('form', { name: 'Cancel the event' });
  fireEvent.change(within(form).getByLabelText('Cancellation reason'), { target: { value: '   ' } });
  fireEvent.submit(form);
  // Inside the form, beside the button, so it is on screen where the coordinator is looking.
  expect((await within(form).findByRole('alert')).textContent).toBe('Give a reason for cancelling this event.');
  expect(cancelCalls(request)).toHaveLength(0);

  fireEvent.change(within(form).getByLabelText('Cancellation reason'), { target: { value: ' The keynote speaker withdrew. ' } });
  fireEvent.click(within(form).getByRole('button', { name: 'Confirm cancellation' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/12/cancel', {
    method: 'POST', body: JSON.stringify({ reason: 'The keynote speaker withdrew.' }),
  }));
  expect(await screen.findByText('Event cancelled. Its venues and equipment are free for other events.')).toBeTruthy();
  expect(screen.queryByRole('region', { name: 'Cancel this event' })).toBeNull();
});

// TC-SPL-86-40 (BB) AC2: Keep event sends nothing; a server refusal is shown and the reason kept
it('[TC-SPL-86-40] keeps the event on Keep event and shows a refusal', async () => {
  const request = api(planning, json({ error: 'This event is already cancelled.' }, false, 409));
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  const panel = within(await screen.findByRole('region', { name: 'Cancel this event' }));
  fireEvent.click(panel.getByRole('button', { name: 'Cancel event' }));
  fireEvent.click(screen.getByRole('button', { name: 'Keep event' }));
  expect(cancelCalls(request)).toHaveLength(0);

  fireEvent.click(panel.getByRole('button', { name: 'Cancel event' }));
  fireEvent.change(screen.getByLabelText('Cancellation reason'), { target: { value: 'Duplicate click.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm cancellation' }));

  const form = screen.getByRole('form', { name: 'Cancel the event' });
  expect((await within(form).findByRole('alert')).textContent).toBe('This event is already cancelled.');
  expect((screen.getByLabelText('Cancellation reason') as HTMLTextAreaElement).value).toBe('Duplicate click.');
});

// TC-SPL-86-41 (BB) AC1/AC2: offered only in cancellable states
it.each([
  ['submitted', true], ['under_review', true], ['returned_for_clarification', true], ['approved', true],
  ['confirmed', true], ['postponed', true], ['rejected', false], ['withdrawn', false], ['completed', false], ['cancelled', false],
])('[TC-SPL-86-41] status %s offers cancellation: %s', async (status, offered) => {
  const request = api({ ...planning, status, status_label: status });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  await screen.findByRole('heading', { name: 'Community Leadership Forum' });
  expect(Boolean(screen.queryByRole('region', { name: 'Cancel this event' }))).toBe(offered);
});

// TC-SPL-86-42 (BB) AC6: the coordinator, organiser and Lead see who cancelled it, when and why
it('[TC-SPL-86-42] shows the cancellation on the coordinator page', async () => {
  render(<AssignedEvents accessToken="token" eventId={12} request={api(cancelled)} onNavigate={vi.fn()} />);

  const cancelledBy = await screen.findByRole('rowheader', { name: 'Cancelled by' });
  expect(cancelledBy.closest('tr')!.textContent).toContain('Casey Coordinator');
  expect(screen.getByRole('rowheader', { name: 'Cancellation reason' }).closest('tr')!.textContent).toContain('The keynote speaker withdrew.');
});

it('[TC-SPL-86-42] shows the cancellation on the organiser list', async () => {
  const request = vi.fn(async () => json({ event_requests: [{
    ...cancelled, status_explanation: 'Your event will not take place.', organisation_name: 'Northstar',
    submitted_at: '2026-10-01T09:00:00+08:00', status_changed_at: '2026-10-16T21:00:00+08:00',
    coordinator: { id: 'c', name: 'Casey Coordinator' },
  }] }));
  render(<EventRequestDrafts accessToken="token" request={request as never} />);

  expect(await screen.findByText(/Cancelled by Casey Coordinator on/)).toBeTruthy();
  expect(screen.getByText('Reason: The keynote speaker withdrew.')).toBeTruthy();
});

it('[TC-SPL-86-42] shows the cancellation in the Lead supervision view', async () => {
  const request = vi.fn(async (path: string) => json(path.includes('supervision')
    ? { events: [{
      id: 12, name: 'Community Leadership Forum', purpose: 'Forum', organisation_name: 'Northstar',
      proposed_date: '2026-11-20', start_time: '14:00', end_time: '17:00', expected_attendance: 80,
      status: 'cancelled', status_label: 'Cancelled', coordinator: { id: 'c', name: 'Casey Coordinator' },
      reassignable: false, cancelled_by: { id: 'c', name: 'Casey Coordinator' }, cancellation_reason: 'The keynote speaker withdrew.',
    }], count: 1 }
    : { events: [], count: 0 }));
  render(<CoordinatorSupervision accessToken="token" request={request as never} />);

  expect(await screen.findByText('Cancelled by Casey Coordinator: The keynote speaker withdrew.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Reassign coordinator for/ })).toBeNull();
});
