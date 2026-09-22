import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AssignedEvents } from './AssignedEvents';

afterEach(cleanup);

const assigned = {
  id: 12, name: 'Community Forum', status: 'under_review',
  status_label: 'Under review', proposed_date: '2026-10-12',
};

it('shows an assigned event with status and proposed date, then opens its route', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [assigned] }) });
  const onNavigate = vi.fn();
  render(<AssignedEvents accessToken="token" request={request} onNavigate={onNavigate} />);
  expect(await screen.findByRole('link', { name: 'Community Forum' })).toBeTruthy();
  expect(screen.getByText('Under review')).toBeTruthy();
  expect(screen.getByText('12 Oct 2026')).toBeTruthy();
  fireEvent.click(screen.getByRole('link', { name: 'Community Forum' }));
  expect(onNavigate).toHaveBeenCalledWith('/workspace/assigned-events/12');
  expect(request).toHaveBeenCalledWith('/api/event-requests/assigned');
});

it('opens the selected event using the assigned-only detail endpoint', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ event: assigned }) });
  render(<AssignedEvents accessToken="token" eventId={12} request={request} onNavigate={vi.fn()} />);
  expect(await screen.findByRole('heading', { name: 'Community Forum' })).toBeTruthy();
  expect(screen.getByText('Under review')).toBeTruthy();
  expect(request).toHaveBeenCalledWith('/api/event-requests/assigned/12');
});

it('shows an empty state when nothing is assigned', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [] }) });
  render(<AssignedEvents accessToken="token" request={request} onNavigate={vi.fn()} />);
  expect(await screen.findByText('No events assigned to you yet.')).toBeTruthy();
});
