import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Notifications } from './Notifications';

// SPL-122 QA cases (QA-SPL-122-NNN, see the QA-SPL-122 page). The API is stubbed: the server picks
// the link (backend/tests/test_qa_spl122.py); these prove the inbox follows it and nothing similar.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const NOTICE = {
  id: 3,
  message: 'Equipment requirement added to Founders Day: Wireless Microphone × 4.',
  event: { id: 7, name: 'Founders Day' },
  link: '/workspace/equipment-review-queue',
  created_at: '2026-10-22T09:05:00+08:00',
  read: false,
};

function inbox(notifications: unknown[]) {
  return vi.fn(async () => new Response(JSON.stringify({ notifications, unread_count: 1 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }));
}

describe('AC5 - each notice opens the Equipment review queue', () => {
  // QA-SPL-122-053 | AC5 | BB
  it('[QA-SPL-122-053] opens a Technical Support notice on the Equipment review queue', async () => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([NOTICE])} />);

    const link = await screen.findByRole('link', { name: 'Founders Day' });
    expect(link.getAttribute('href')).toBe('/workspace/equipment-review-queue');
    fireEvent.click(link);

    expect(onNavigate).toHaveBeenCalledWith('/workspace/equipment-review-queue');
    expect(screen.getByText(NOTICE.message)).toBeTruthy();
  });

  // QA-SPL-122-054 | AC5 | BB security
  it.each([
    '/workspace/equipment-review-queue/7',
    '/workspace/equipment-review-queuex',
    '/workspace/equipment-review-queue?line=7',
    '//evil.test/workspace/equipment-review-queue',
    '/workspace/equipment-review-queue/../admin',
  ])('[QA-SPL-122-054] does not follow a lookalike link %s', async link => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([{ ...NOTICE, link }])} />);

    fireEvent.click(await screen.findByRole('link', { name: 'Founders Day' }));

    expect(onNavigate).toHaveBeenCalledWith('/workspace/assigned-events/7');
  });
});
