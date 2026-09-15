import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EventRequestStatus } from './EventRequestStatus';

afterEach(() => {
  vi.restoreAllMocks();
});

function row(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: 'Regional Partner Conference',
    status_label: 'Submitted',
    status_explanation:
      'Your request has been received and is waiting to be picked up for review.',
    status_changed_at: '2026-09-18T09:30:00+08:00',
    ...overrides,
  };
}

function respondWith(event_requests: unknown[]) {
  return vi.spyOn(globalThis, 'fetch').mockReturnValue(
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ event_requests }),
    } as Response),
  );
}

// CS-E05-S2 AC6 and CS-E05-S3 AC6
it('names the Event Coordinator once one is responsible, and says so when none is', async () => {
  respondWith([
    row({ id: 1, name: 'Assigned', coordinator: { id: 'alice', name: 'Alice Tan' } }),
    row({ id: 2, name: 'Waiting', coordinator: null }),
  ]);

  render(<EventRequestStatus accessToken="token-123" />);

  await waitFor(() => expect(screen.getByText('Alice Tan')).toBeTruthy());
  expect(screen.getByText('Not assigned yet')).toBeTruthy();
});

// TC-CS-E07-S1-04
it('lists every one of the organiser requests with its status', async () => {
  respondWith([
    row({ id: 1, name: 'Waiting', status_label: 'Submitted' }),
    row({ id: 2, name: 'Being read', status_label: 'Under review' }),
    row({ id: 3, name: 'Accepted', status_label: 'Approved' }),
  ]);

  render(<EventRequestStatus accessToken="token-123" />);

  await screen.findByText('Waiting');
  for (const [name, status] of [
    ['Waiting', 'Submitted'],
    ['Being read', 'Under review'],
    ['Accepted', 'Approved'],
  ]) {
    expect(screen.getByText(name)).toBeTruthy();
    expect(screen.getByText(status)).toBeTruthy();
  }
});

// TC-CS-E07-S1-07
it('shows the plain-language name and the explanation for each status', async () => {
  respondWith([
    row({
      status_label: 'Under review',
      status_explanation: 'Your request is being assessed. Nothing is needed from you yet.',
    }),
  ]);

  render(<EventRequestStatus accessToken="token-123" />);

  expect(await screen.findByText('Under review')).toBeTruthy();
  expect(
    screen.getByText('Your request is being assessed. Nothing is needed from you yet.'),
  ).toBeTruthy();
});

// TC-CS-E07-S1-08
it('never shows the raw stored value', async () => {
  respondWith([
    row({ status: 'under_review', status_label: 'Under review' }),
    row({ id: 2, status: 'rejected', status_label: 'Not approved' }),
  ]);

  const { container } = render(<EventRequestStatus accessToken="token-123" />);

  await screen.findByText('Under review');
  expect(container.textContent).not.toContain('under_review');
  expect(container.textContent).not.toContain('rejected');
  expect(container.textContent).toContain('Not approved');
});

// TC-CS-E07-S1-13
it('conveys the status as text rather than by colour alone', async () => {
  respondWith([
    row({ id: 1, name: 'Accepted one', status_label: 'Approved' }),
    row({ id: 2, name: 'Refused one', status_label: 'Not approved' }),
  ]);

  render(<EventRequestStatus accessToken="token-123" />);

  // Both are identifiable from text content alone, with no styling consulted.
  expect((await screen.findByText('Approved')).textContent).toBe('Approved');
  expect(screen.getByText('Not approved').textContent).toBe('Not approved');
});

// TC-CS-E07-S1-10
it('shows the time the status last changed', async () => {
  respondWith([row({ status_changed_at: '2026-09-18T09:30:00+08:00' })]);

  render(<EventRequestStatus accessToken="token-123" />);

  await screen.findByText('Submitted');
  const expected = new Date('2026-09-18T09:30:00+08:00').toLocaleString();
  expect(screen.getByText(expected)).toBeTruthy();
});

// TC-CS-E07-S1-12
it('says so when no time was recorded, rather than inventing one', async () => {
  respondWith([row({ status_changed_at: null })]);

  render(<EventRequestStatus accessToken="token-123" />);

  expect(await screen.findByText('Not recorded')).toBeTruthy();
  // The request is still listed with its status.
  expect(screen.getByText('Submitted')).toBeTruthy();
});

// TC-CS-E07-S1-15
it('tells an organiser with no requests that there are none', async () => {
  respondWith([]);

  render(<EventRequestStatus accessToken="token-123" />);

  const message = await screen.findByRole('status');
  expect(message.textContent).toContain('You have not submitted any event requests yet.');
  expect(screen.queryByRole('table')).toBeNull();
});

// TC-CS-E07-S1-16
it('shows the table instead of the empty message once a request exists', async () => {
  respondWith([row()]);

  render(<EventRequestStatus accessToken="token-123" />);

  await screen.findByText('Regional Partner Conference');
  expect(screen.queryByRole('status')).toBeNull();
  expect(screen.getByRole('table')).toBeTruthy();
});

// TC-CS-E07-S1-18 — the newest request is at the top of the table.
it('orders the requests with the most recent change first', async () => {
  respondWith([
    row({ id: 1, name: 'Oldest', status_changed_at: '2026-09-16T09:00:00+08:00' }),
    row({ id: 2, name: 'Newest', status_changed_at: '2026-09-18T14:00:00+08:00' }),
    row({ id: 3, name: 'Middle', status_changed_at: '2026-09-17T11:00:00+08:00' }),
    row({ id: 4, name: 'Undated', status_changed_at: null }),
  ]);

  render(<EventRequestStatus accessToken="token-123" />);

  await screen.findByText('Newest');
  const names = screen
    .getAllByRole('row')
    .slice(1)
    .map(tableRow => tableRow.querySelector('strong')?.textContent);
  expect(names).toEqual(['Newest', 'Middle', 'Oldest', 'Undated']);
});

// TC-CS-E07-S1-09 — every member of the vocabulary renders, none falls through to a blank
// or a fallback. The wording is the server's; this asserts the view displays whatever it is
// given for all eleven, in one pass.
const EVERY_STATUS: [string, string][] = [
  ['Draft', 'You have not submitted this request yet. Only you can see it.'],
  ['Submitted', 'Your request has been received and is waiting to be picked up for review.'],
  ['Under review', 'Your request is being assessed. Nothing is needed from you yet.'],
  ['Approved', 'Your request has been accepted. Planning will begin shortly.'],
  ['In planning', 'Your event is being arranged — venue, equipment and staffing are being settled.'],
  ['Confirmed', 'Everything is arranged. Your event is going ahead on the agreed date.'],
  ['Completed', 'Your event has taken place and this request is now closed.'],
  ['Cancelled', 'Your event will not take place. Speak to your Event Coordinator if this is unexpected.'],
  ['Not approved', 'Your request was not accepted. Your Event Coordinator can explain why.'],
  ['Withdrawn', 'This request was taken back and will not be reviewed.'],
  ['Postponed', 'Your event is on hold. A new date has not been set yet.'],
];

it('renders every status in the vocabulary with its name and explanation', async () => {
  respondWith(
    EVERY_STATUS.map(([status_label, status_explanation], index) => ({
      id: index + 1,
      name: `Request ${index + 1}`,
      status_label,
      status_explanation,
      status_changed_at: '2026-09-18T09:30:00+08:00',
    })),
  );

  const { container } = render(<EventRequestStatus accessToken="token-123" />);

  await screen.findByText('Draft');
  for (const [label, explanation] of EVERY_STATUS) {
    expect(screen.getByText(label), `missing label: ${label}`).toBeTruthy();
    expect(screen.getByText(explanation), `missing explanation for ${label}`).toBeTruthy();
  }
  // Eleven rows plus the header, and no row left blank or showing a fallback.
  expect(screen.getAllByRole('row')).toHaveLength(EVERY_STATUS.length + 1);
  expect(container.textContent).not.toContain('Not recorded');
  expect(container.textContent).not.toContain('undefined');
});

it('reports a failure to load without pretending there are no requests', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network down'));

  render(<EventRequestStatus accessToken="token-123" />);

  const message = await screen.findByRole('alert');
  expect(message.textContent).toContain("We couldn't load your requests.");
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
});
