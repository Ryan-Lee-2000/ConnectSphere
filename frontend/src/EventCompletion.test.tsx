import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';

// SPL-105 interface cases from QA-SPL-105. The server decides whether an event can be completed;
// these tests prove the coordinator's page offers, sends and shows it faithfully.

afterEach(() => { cleanup(); vi.useRealTimers(); });
beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-11-20T18:00:00+08:00')); });

const preparing = {
  id: 12, name: 'Community Leadership Forum', status: 'preparing', status_label: 'Preparing',
  proposed_date: '2026-11-20', mapped_slots: ['PM'], start_time: '14:00', end_time: '17:00',
  expected_attendance: 80, equipment_requirements: [], registration_required: false,
  confirmed_by: null, confirmed_at: null, cancelled_by: null, cancelled_at: null, cancellation_reason: null,
  completed_by: null, completed_at: null, completion_note: null,
  completion_available_at: '2026-11-20T17:00:00+08:00',
};
const completed = {
  ...preparing, status: 'completed', status_label: 'Completed',
  completed_by: { id: 'c', name: 'Casey Coordinator' }, completed_at: '2026-11-20T18:00:00+08:00',
  completion_note: '142 attended.',
};

const json = (body: unknown, ok = true, status = 200) =>
  ({ ok, status, json: async () => body }) as unknown as Response;

function api(detail: unknown, completeResponse?: Response) {
  return vi.fn(async (path: string, _init?: RequestInit): Promise<Response> => {
    if (path === '/api/event-requests/assigned/12') return json({ event: detail });
    if (path === '/api/event-requests/12/complete') return completeResponse ?? json({ error: 'unexpected' }, false, 500);
    return json({ booking: null });
  });
}

const completeCalls = (request: ReturnType<typeof api>) =>
  request.mock.calls.filter(([path]) => path === '/api/event-requests/12/complete');

// QA-SPL-105-070 | AC1/AC4 | BB
it('[QA-SPL-105-070] completes in two steps and sends the trimmed note', async () => {
  const request = api(preparing, json({ event: completed, message: 'Event completed. It is now closed as a historical record.' }));
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  const panel = within(await screen.findByRole('region', { name: 'Mark this event completed' }));
  fireEvent.click(panel.getByRole('button', { name: 'Mark as completed' }));
  expect(completeCalls(request)).toHaveLength(0);
  const form = screen.getByRole('form', { name: 'Complete the event' });
  fireEvent.change(within(form).getByLabelText('Closing note (optional)'), { target: { value: '  142 attended.  ' } });
  fireEvent.click(within(form).getByRole('button', { name: 'Confirm completion' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/12/complete', {
    method: 'POST', body: JSON.stringify({ note: '142 attended.' }),
  }));
  expect(await screen.findByText('Event completed. It is now closed as a historical record.')).toBeTruthy();
  expect(screen.queryByRole('region', { name: 'Mark this event completed' })).toBeNull();
  expect(screen.getByText('Casey Coordinator, 20 Nov 2026, 6:00 pm')).toBeTruthy();
  expect(screen.getByText('142 attended.')).toBeTruthy();
});

// QA-SPL-105-070 | AC4 | BB
it('[QA-SPL-105-070] sends a null note when the optional note is left blank', async () => {
  const request = api(preparing, json({ event: { ...completed, completion_note: null } }));
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Mark as completed' }));
  fireEvent.change(screen.getByLabelText('Closing note (optional)'), { target: { value: '   ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm completion' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/12/complete', {
    method: 'POST', body: JSON.stringify({ note: null }),
  }));
});

// QA-SPL-105-071 | AC1 | BB
it('[QA-SPL-105-071] before the end the button is disabled and says when it opens', async () => {
  vi.setSystemTime(new Date('2026-11-20T16:59:00+08:00'));
  const request = api(preparing);
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  const panel = within(await screen.findByRole('region', { name: 'Mark this event completed' }));
  expect(panel.getByText('You can mark this event completed from 20 Nov 2026, 5:00 pm, once it has ended.')).toBeTruthy();
  expect((panel.getByRole('button', { name: 'Mark as completed' }) as HTMLButtonElement).disabled).toBe(true);
});

// QA-SPL-105-071 | AC1 | BB
it('[QA-SPL-105-071] with no recorded end the button stays disabled and explains why', async () => {
  const request = api({ ...preparing, completion_available_at: null });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  const panel = within(await screen.findByRole('region', { name: 'Mark this event completed' }));
  expect(panel.getByText('This event cannot be completed until its end time is recorded.')).toBeTruthy();
  expect((panel.getByRole('button', { name: 'Mark as completed' }) as HTMLButtonElement).disabled).toBe(true);
});

// QA-SPL-105-072 | AC2 | BB
it('[QA-SPL-105-072] Keep open sends nothing; a refusal is shown and the note kept', async () => {
  const request = api(preparing, json({ error: 'This event is already completed.' }, false, 409));
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Mark as completed' }));
  fireEvent.click(screen.getByRole('button', { name: 'Keep open' }));
  expect(completeCalls(request)).toHaveLength(0);

  fireEvent.click(screen.getByRole('button', { name: 'Mark as completed' }));
  fireEvent.change(screen.getByLabelText('Closing note (optional)'), { target: { value: 'Second try.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm completion' }));

  const form = screen.getByRole('form', { name: 'Complete the event' });
  expect((await within(form).findByRole('alert')).textContent).toBe('This event is already completed.');
  expect((screen.getByLabelText('Closing note (optional)') as HTMLTextAreaElement).value).toBe('Second try.');
});

// QA-SPL-105-072 | AC2 | BB
it('[QA-SPL-105-072] a network failure shows a retry message', async () => {
  const request = vi.fn(async (path: string) => {
    if (path === '/api/event-requests/assigned/12') return json({ event: preparing });
    if (path === '/api/event-requests/12/complete') throw new Error('offline');
    return json({ booking: null });
  });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);

  fireEvent.click(await screen.findByRole('button', { name: 'Mark as completed' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm completion' }));

  expect((await screen.findByRole('alert')).textContent).toBe('Could not complete the event. Try again.');
});

// QA-SPL-105-073 | AC1/AC2 | BB
it('[QA-SPL-105-073] only a Preparing event shows the completion panel', async () => {
  for (const status of ['planning', 'confirmed', 'completed', 'cancelled']) {
    const request = api({ ...preparing, status, status_label: status });
    render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);
    expect(await screen.findByRole('heading', { name: 'Community Leadership Forum' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Mark this event completed' })).toBeNull();
    cleanup();
  }
});

// Review round 1 (26 Oct 2026, Clive, PR #105): a page opened before the end must enable itself.
// Real timers keep advancing (shouldAdvanceTime) so the page can load; the tests then jump the clock.
function useTimerClock(at: string) {
  vi.useRealTimers();
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'], shouldAdvanceTime: true });
  vi.setSystemTime(new Date(at));
}

// QA-SPL-105-074 | AC1 | BB
it('[QA-SPL-105-074] a page opened before the end enables completion once the end passes', async () => {
  useTimerClock('2026-11-20T16:59:30+08:00');
  render(<AssignedEvents accessToken="token" eventId={12} request={api(preparing)} onNavigate={vi.fn()} />);
  const panel = within(await screen.findByRole('region', { name: 'Mark this event completed' }));
  expect((panel.getByRole('button', { name: 'Mark as completed' }) as HTMLButtonElement).disabled).toBe(true);
  await act(async () => {}); // let the panel register its refresh before the clock moves
  expect(vi.getTimerCount()).toBeGreaterThan(0);

  await act(async () => { vi.advanceTimersByTime(31_000); });

  expect((panel.getByRole('button', { name: 'Mark as completed' }) as HTMLButtonElement).disabled).toBe(false);
  expect(panel.getByText(/^Completing closes the event as a historical record/)).toBeTruthy();
});

// QA-SPL-105-074 | AC1 | WB
it('[QA-SPL-105-074] an end years away stays disabled instead of overflowing the timer', async () => {
  useTimerClock('2026-11-20T16:59:30+08:00');
  const request = api({ ...preparing, completion_available_at: '2031-01-22T12:00:00+08:00' });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);
  const panel = within(await screen.findByRole('region', { name: 'Mark this event completed' }));
  await act(async () => {});

  await act(async () => { vi.advanceTimersByTime(60_000); });

  expect((panel.getByRole('button', { name: 'Mark as completed' }) as HTMLButtonElement).disabled).toBe(true);
});

// QA-SPL-105-074 | AC1 | WB
it('[QA-SPL-105-074] leaving the page cancels the pending refresh', async () => {
  useTimerClock('2026-11-20T16:59:30+08:00');
  const clear = vi.spyOn(globalThis, 'clearTimeout');
  const { unmount } = render(<AssignedEvents accessToken="token" eventId={12} request={api(preparing)} onNavigate={vi.fn()} />);
  await screen.findByRole('region', { name: 'Mark this event completed' });
  await act(async () => {});
  const before = clear.mock.calls.length;

  unmount();

  expect(clear.mock.calls.length).toBeGreaterThan(before);
  clear.mockRestore();
});
