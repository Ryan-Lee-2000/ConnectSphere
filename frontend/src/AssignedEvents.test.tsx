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

it('lets the assigned coordinator begin review from a submitted event', async () => {
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

it('keeps the submitted status available when begin review is refused', async () => {
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
