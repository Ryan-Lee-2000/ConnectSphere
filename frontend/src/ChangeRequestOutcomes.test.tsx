import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { ChangeRequestItems, ChangeRequestsPanel, type ChangeRequest } from './ChangeRequests';

afterEach(cleanup);

const items: ChangeRequest['items'] = [
  { id: 1, field: 'name', field_label: 'Event name', current_value: 'Original', requested_value: 'Updated', reason: 'New programme', decision: 'accepted' },
  { id: 2, field: 'venue_notes', field_label: 'Venue notes', current_value: null, requested_value: 'South door', reason: 'Access', decision: 'declined', decline_reason: 'South door is closed' },
  { id: 3, field: 'expected_attendance', field_label: 'Expected attendance', current_value: 150, requested_value: 100, reason: 'Fewer guests', decision: 'pending' },
];

function panel(requests: ChangeRequest[]) {
  const api = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ change_requests: requests }) })) as unknown as ApiRequest;
  return render(<ChangeRequestsPanel api={api} eventId={12} eventName="Gala" eventStatus="completed" canSubmit />);
}

// QA-SPL-113-001 | AC1 | BB
it('[QA-SPL-113-001] shows each outcome beside its own item in a partially decided request', async () => {
  panel([{ id: 7, status: 'pending', submitted_at: '2026-10-20T12:00:00Z', items }]);
  const group = await screen.findByRole('group', { name: 'Pending change request' });
  const rows = within(group).getAllByRole('listitem');
  ['Accepted', 'Declined', 'Pending'].forEach((status, index) => {
    expect(within(rows[index]).getByText(`Outcome: ${status}`)).toBeTruthy();
  });
  expect(within(rows[1]).getByText('Decline reason: South door is closed')).toBeTruthy();
});

// QA-SPL-113-002 | AC1 | BB
it('[QA-SPL-113-002] renders a decline reason as text rather than executable markup', () => {
  render(<ChangeRequestItems items={[{ ...items[1], decline_reason: '<img src=x onerror=alert(1)>' }]} showOutcomes />);
  expect(screen.getByText('Decline reason: <img src=x onerror=alert(1)>')).toBeTruthy();
  expect(screen.queryByRole('img')).toBeNull();
});

// QA-SPL-113-003 | AC1 | WB
it('[QA-SPL-113-003] omits decline reasons for accepted and pending items', () => {
  render(<ChangeRequestItems items={[{ ...items[0], decline_reason: 'Stale reason' }, items[2]]} showOutcomes />);
  expect(screen.getByText('Outcome: Accepted')).toBeTruthy();
  expect(screen.getByText('Outcome: Pending')).toBeTruthy();
  expect(screen.queryByText(/Decline reason:/)).toBeNull();
});

// QA-SPL-113-004 | AC1 | WB
it('[QA-SPL-113-004] labels a legacy undecided item Pending and its old value At submission', () => {
  render(<ChangeRequestItems items={[{ ...items[0], decision: undefined }]} showOutcomes />);
  expect(screen.getByText('Outcome: Pending')).toBeTruthy();
  expect(screen.getByText('At submission: Original')).toBeTruthy();
  expect(screen.queryByText('Now: Original')).toBeNull();
});

// QA-SPL-113-005 | AC1 | BB
it('[QA-SPL-113-005] keeps final outcomes and reasons visible in Closed history', async () => {
  panel([{ id: 7, status: 'closed', submitted_at: '2026-10-20T12:00:00Z', items: items.slice(0, 2) }]);
  const history = await screen.findByRole('region', { name: 'Closed change request history' });
  expect(within(history).getByText('Outcome: Accepted')).toBeTruthy();
  expect(within(history).getByText('Outcome: Declined')).toBeTruthy();
  expect(within(history).getByText('Decline reason: South door is closed')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Request a change' })).toBeNull();
});
