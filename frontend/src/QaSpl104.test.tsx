import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Notifications } from './Notifications';

// SPL-104 QA cases (QA-SPL-104-NNN, see the QA-SPL-104 page). The API is stubbed: the server picks
// the link (backend/tests/test_qa_spl104.py); these prove the inbox follows it and nothing similar.

afterEach(() => {
  cleanup();
});

const NOTICE = {
  id: 4,
  message:
    'Venue booking requested for Coastal Forum: Harbour Hall on Wed 14 Oct 2026, 10:00–12:00 SGT; '
    + 'venue occupied 09:30–12:45 including setup and turnaround.',
  event: { id: 7, name: 'Coastal Forum' },
  link: '/workspace/booking-requests',
  created_at: '2026-10-24T09:05:00+08:00',
  read: false,
};

function inbox(notifications: unknown[]) {
  return vi.fn(async () => new Response(JSON.stringify({ notifications, unread_count: 1 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }));
}

describe('SPL-104 notices open the Venue Staff booking queue', () => {
  // QA-SPL-104-083 | AC1 AC2 | BB
  it('[QA-SPL-104-083] opens a Venue Staff notice on the booking queue and shows its details', async () => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([NOTICE])} />);

    const link = await screen.findByRole('link', { name: 'Coastal Forum' });
    expect(link.getAttribute('href')).toBe('/workspace/booking-requests');
    fireEvent.click(link);

    expect(onNavigate).toHaveBeenCalledWith('/workspace/booking-requests');
    expect(screen.getByText(NOTICE.message)).toBeTruthy();
  });

  // QA-SPL-104-084 | AC1 AC2 | BB security
  it.each([
    '/workspace/booking-requests/7',
    '/workspace/booking-requestsx',
    '/workspace/booking-requests?booking=7',
    '//evil.test/workspace/booking-requests',
    '/workspace/booking-requests/../admin',
  ])('[QA-SPL-104-084] does not follow a lookalike link %s', async link => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([{ ...NOTICE, link }])} />);

    fireEvent.click(await screen.findByRole('link', { name: 'Coastal Forum' }));

    expect(onNavigate).toHaveBeenCalledWith('/workspace/assigned-events/7');
  });

  // QA-SPL-104-085 | AC1 AC2 | BB regression
  it.each([
    '/workspace/equipment-review-queue',
    '/workspace/organisation-events/7',
    '/workspace/assigned-events/7',
  ])('[QA-SPL-104-085] still follows the existing link %s', async link => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([{ ...NOTICE, link }])} />);

    fireEvent.click(await screen.findByRole('link', { name: 'Coastal Forum' }));

    expect(onNavigate).toHaveBeenCalledWith(link);
  });
});
