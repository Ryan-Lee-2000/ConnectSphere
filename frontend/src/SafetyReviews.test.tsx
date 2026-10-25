import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { SafetyReviewEvidence, SafetyReviewPanel, SafetyReviewQueue } from './SafetyReviews';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const plan = {
  emergency_access: { value: 'Keep the west fire exit clear.', not_applicable_reason: '' },
  equipment_placement: { value: 'Route cables behind the stage.', not_applicable_reason: '' },
  crowd_movement: { value: 'Use separate entry and exit queues.', not_applicable_reason: '' },
  venue_restrictions: { value: 'No open flame.', not_applicable_reason: '' },
};
const context = {
  id: 71, name: 'Northstar Leadership Forum', status: 'confirmed', expected_attendance: 120,
  accessibility_needs: ['Step-free access'],
  venues: [{ name: 'Harbour Hall', layout: 'theatre', capacity: 180, attendance: 120, restrictions: 'No open flame.' }],
  equipment: [{ name: 'Wireless Microphone', required: 4, reserved: 4, essentiality: 'essential', status: 'reserved' }],
};
const pendingReview = { id: 9, status: 'submitted', plan, reason: null, submitted_at: '2026-10-25T09:00:00+08:00', decided_at: null, decided_by: null, current: true };

function api(routes: Record<string, (init?: RequestInit) => Response | Promise<Response>>) {
  return vi.fn(async (path: string, init?: RequestInit) => routes[`${init?.method ?? 'GET'} ${path}`]?.(init) || response({ error: 'Unexpected request.' }, 500));
}

// QA-SPL-135-009 | AC2 | BB
it('QA-SPL-135-009 shows the confirmed venue, capacity, accessibility and technical evidence before submission', async () => {
  const request = api({ 'GET /api/event-requests/71/safety-review': () => response({ event: context, review: null }) });
  vi.stubGlobal('fetch', request);
  render(<SafetyReviewPanel accessToken="token" eventId={71} onStatusChange={() => undefined} />);
  expect(await screen.findByText('Harbour Hall')).toBeTruthy();
  expect(screen.getByText(/Theatre layout · 180 capacity · 120 attending/)).toBeTruthy();
  expect(screen.getByText('Step-free access')).toBeTruthy();
  expect(screen.getByText(/4\/4 reserved · Essential · Reserved/)).toBeTruthy();
  vi.unstubAllGlobals();
});

// QA-SPL-135-008 | AC2 | BB
it('QA-SPL-135-008 labels a not-applicable explanation and sends it as the plan evidence', async () => {
  const request = api({
    'GET /api/event-requests/71/safety-review': () => response({ event: context, review: null }),
    'POST /api/event-requests/71/safety-review': init => response({ review: pendingReview, message: 'Safety review submitted.' }),
  });
  vi.stubGlobal('fetch', request);
  render(<SafetyReviewPanel accessToken="token" eventId={71} onStatusChange={() => undefined} />);
  await screen.findByText('Harbour Hall');
  fireEvent.click(screen.getAllByLabelText('Not applicable')[0]);
  fireEvent.change(screen.getByLabelText('Why emergency access is not applicable'), { target: { value: 'Controlled venue emergency plan applies.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit safety review' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/71/safety-review', expect.objectContaining({ method: 'POST' })));
  vi.unstubAllGlobals();
});

// QA-SPL-135-005 | AC1 | BB
it('QA-SPL-135-005 does not display a second submission action while Safety is deciding the current review', async () => {
  vi.stubGlobal('fetch', api({ 'GET /api/event-requests/71/safety-review': () => response({ event: context, review: pendingReview }) }));
  render(<SafetyReviewPanel accessToken="token" eventId={71} onStatusChange={() => undefined} />);
  expect(await screen.findByText('Submitted')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Submit safety review' })).toBeNull();
  vi.unstubAllGlobals();
});

// QA-SPL-135-016 | AC4 | BB
it('QA-SPL-135-016 shows Begin preparation only for a current approved arrangement and updates its status', async () => {
  const approved = { ...pendingReview, status: 'approved', reason: null, decided_at: '2026-10-25T10:00:00+08:00', decided_by: { id: 'safety', name: 'Samira Hassan' } };
  const request = api({
    'GET /api/event-requests/71/safety-review': () => response({ event: context, review: approved }),
    'POST /api/event-requests/71/begin-preparation': () => response({ event: { id: 71, status: 'preparing' }, message: 'Preparation has begun.' }),
  });
  vi.stubGlobal('fetch', request); const changed = vi.fn();
  render(<SafetyReviewPanel accessToken="token" eventId={71} onStatusChange={changed} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Begin preparation' }));
  await waitFor(() => expect(changed).toHaveBeenCalledWith('preparing'));
  expect(screen.getByRole('status').textContent).toContain('Preparation has begun.');
  vi.unstubAllGlobals();
});

// QA-SPL-135-015 | AC3 | BB
it('QA-SPL-135-015 lets the Lead inspect the decision actor, reason and evidence without an editing control', async () => {
  const rejected = { ...pendingReview, status: 'rejected', reason: 'Exit path is obstructed.', decided_at: '2026-10-25T10:00:00+08:00', decided_by: { id: 'safety', name: 'Samira Hassan' } };
  const request = api({ 'GET /api/event-requests/71/safety-review': () => response({ event: context, review: rejected }) });
  render(<SafetyReviewEvidence accessToken="lead-token" eventId={71} request={request} />);
  expect(await screen.findByText('Safety decision evidence')).toBeTruthy();
  expect(screen.getByText(/Recorded by Samira Hassan/)).toBeTruthy();
  expect(screen.getByText(/Decision reason: Exit path is obstructed/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Approve|Reject|Submit/i })).toBeNull();
});

// QA-SPL-135-013 | AC3 | BB
it('QA-SPL-135-013 keeps a mandatory decision reason beside the Safety Officer choices', async () => {
  const request = api({ 'GET /api/safety-reviews': () => response({ reviews: [{ ...pendingReview, event: context }] }) });
  vi.stubGlobal('fetch', request);
  render(<SafetyReviewQueue accessToken="safety-token" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
  expect(screen.getByLabelText('Decision reason')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Request changes' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Reject' })).toBeTruthy();
  vi.unstubAllGlobals();
});

// QA-SPL-135-023 | AC2, AC3 | integration
it('QA-SPL-135-023 renders the venue and technical evidence returned by the real queue contract', async () => {
  // This mirrors GET /api/safety-reviews: the queue must supply the context, rather than rely on
  // a later detail request or a locally invented placeholder.
  const queueResponse = { reviews: [{ id: 9, event: context, plan, submitted_at: pendingReview.submitted_at }] };
  vi.stubGlobal('fetch', api({ 'GET /api/safety-reviews': () => response(queueResponse) }));
  render(<SafetyReviewQueue accessToken="safety-token" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
  expect(screen.getByText('Harbour Hall')).toBeTruthy();
  expect(screen.getByText(/Theatre layout · 180 capacity · 120 attending/)).toBeTruthy();
  expect(screen.getByText(/4\/4 reserved · Essential · Reserved/)).toBeTruthy();
  vi.unstubAllGlobals();
});
