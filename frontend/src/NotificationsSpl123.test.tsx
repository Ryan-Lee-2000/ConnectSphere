import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Notifications } from './Notifications';

afterEach(cleanup);
const event = { id: 123, name: 'QA Organiser Forum' };
function inbox(message: string) {
  return vi.fn(async () => new Response(JSON.stringify({
    notifications: [{ id: 1, event, message, link: '/workspace/organisation-events/123', created_at: '2026-10-26T01:00:00Z', read: false }],
    unread_count: 1,
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
}
function show(message: string) {
  const request = inbox(message);
  const onNavigate = vi.fn();
  render(<Notifications accessToken="synthetic-token" request={request} onNavigate={onNavigate} />);
  return { request, onNavigate };
}

// QA-SPL-123-101 | AC1 | BB
it('[QA-SPL-123-101] renders a confirmation notice addressed by the inbox API', async () => {
  show('QA Organiser Forum has been confirmed.');
  expect(await screen.findByText('QA Organiser Forum has been confirmed.')).toBeTruthy();
});

// QA-SPL-123-102 | AC2 | BB
it('[QA-SPL-123-102] explains that a significant change requires confirmation again', async () => {
  const message = 'QA Organiser Forum has returned to Planning after a significant change and must be confirmed again.';
  show(message);
  expect(await screen.findByText(message)).toBeTruthy();
});

// QA-SPL-123-103 | AC3 | BB
it('[QA-SPL-123-103] displays the organiser cancellation reason', async () => {
  const message = 'QA Organiser Forum has been cancelled. Reason: Venue flooded.';
  show(message);
  expect(await screen.findByText(message)).toBeTruthy();
});

// QA-SPL-123-104 | AC4 | BB
it('[QA-SPL-123-104] displays an item outcome and decline reason', async () => {
  const message = 'Your change request for QA Organiser Forum: Venue notes was declined. Reason: Access restricted.';
  show(message);
  expect(await screen.findByText(message)).toBeTruthy();
});

// QA-SPL-123-105 | AC1 AC2 AC3 AC4 AC5 | BB
it('[QA-SPL-123-105] follows the protected organiser event link without generating an action request', async () => {
  const { request, onNavigate } = show('QA Organiser Forum has been confirmed.');
  const link = await screen.findByRole('link', { name: event.name });
  expect(link.getAttribute('href')).toBe('/workspace/organisation-events/123');
  fireEvent.click(link);
  expect(onNavigate).toHaveBeenCalledWith('/workspace/organisation-events/123');
  expect(request).toHaveBeenCalledTimes(1);
  expect(request).toHaveBeenCalledWith('/api/notifications');
});
