import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Notifications } from './Notifications';

// SPL-124 QA cases (QA-SPL-124-NNN, see the QA-SPL-124 report). The API is stubbed: these prove
// where the inbox sends an attendee's notice. Which notices the server writes is proved in
// backend/tests/test_qa_spl124*.py.

afterEach(() => {
  cleanup();
});

const NOTICE = {
  id: 3,
  message: 'Harbour Lights Gala has been cancelled.',
  event: { id: 7, name: 'Harbour Lights Gala' },
  link: '/workspace/my-registrations',
  created_at: '2026-10-25T09:00:00+08:00',
  read: false,
};

function inbox(notifications: unknown[]) {
  return vi.fn(async () => new Response(
    JSON.stringify({ notifications, unread_count: notifications.length }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  ));
}

describe('SPL-124 AC6 - an attendee notice opens My registrations', () => {
  // QA-SPL-124-064 | AC6 | BB
  it('[QA-SPL-124-064] links an attendee notice to My registrations and opens it', async () => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([NOTICE])} />);

    const link = await screen.findByRole('link', { name: 'Harbour Lights Gala' });
    expect(link.getAttribute('href')).toBe('/workspace/my-registrations');
    fireEvent.click(link);

    expect(onNavigate).toHaveBeenCalledWith('/workspace/my-registrations');
  });

  // QA-SPL-124-065 | AC6 | BB negative (only the exact page is accepted)
  it.each(['/workspace/my-registrations/7', '/workspace/my-registrations?x=1'])(
    '[QA-SPL-124-065] does not follow the look-alike link %s',
    async link => {
      const onNavigate = vi.fn();
      render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([{ ...NOTICE, link }])} />);

      fireEvent.click(await screen.findByRole('link', { name: 'Harbour Lights Gala' }));

      expect(onNavigate).toHaveBeenCalledWith('/workspace/assigned-events/7');
    },
  );
});
