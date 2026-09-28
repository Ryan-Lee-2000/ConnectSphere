import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PendingBookingRequests } from './PendingBookingRequests';

// QA-SPL-80 TC-SPL-80-13 to -16. The API is stubbed, so these prove what Venue Staff can see and
// do with a given payload; the payload's own shape is proved server-side in
// backend/tests/test_venue_booking_queue.py.

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

const COASTAL = {
  id: 12,
  event: { id: 7, name: 'Coastal Forum' },
  venue: { id: 2, name: 'Harbour Hall' },
  date: '2026-10-14',
  event_slots: ['PM'],
  setup: { date: '2026-10-14', slot: 'AM' },
  turnaround: { date: '2026-10-14', slot: 'NIGHT' },
  layout: 'theatre',
  expected_attendance: 150,
  requested_by: { id: 'casey', name: 'Casey Lim' },
  requested_at: '2026-09-28T09:00:00+08:00',
  requires_review: false,
};
const SOUTHBANK = {
  ...COASTAL,
  id: 13,
  event: { id: 8, name: 'Southbank Summit' },
  requires_review: true,
};

function queue(body: unknown) {
  return vi.fn(async () => response(body));
}

describe('PendingBookingRequests', () => {
  // TC-SPL-80-13
  it('[TC-SPL-80-13] lists pending requests with event, venue, date, slots and requester', async () => {
    render(<PendingBookingRequests
      accessToken="token"
      onOpen={vi.fn()}
      request={queue({ requests: [COASTAL], count: 1 })}
    />);

    const row = await screen.findByRole('row', { name: /Coastal Forum/ });
    expect(within(row).getByText('Harbour Hall')).toBeTruthy();
    expect(within(row).getByText('14 Oct 2026')).toBeTruthy();
    expect(within(row).getByText(/PM/)).toBeTruthy();
    // The preparation slots SPL-87 derived are shown, not just the event slot.
    expect(within(row).getByText(/Setup AM · 14 Oct 2026/)).toBeTruthy();
    expect(within(row).getByText(/Turnaround Night · 14 Oct 2026/)).toBeTruthy();
    expect(within(row).getByText('Theatre')).toBeTruthy();
    expect(within(row).getByText('150')).toBeTruthy();
    expect(within(row).getByText('Casey Lim')).toBeTruthy();
    expect(screen.getByText('1 request awaiting review')).toBeTruthy();
  });

  // TC-SPL-80-14
  it('[TC-SPL-80-14] opens the review page for the chosen request', async () => {
    const onOpen = vi.fn();
    render(<PendingBookingRequests
      accessToken="token"
      onOpen={onOpen}
      request={queue({ requests: [COASTAL, SOUTHBANK], count: 2 })}
    />);

    fireEvent.click(await screen.findByRole('button', {
      name: 'Review the booking request for Southbank Summit',
    }));

    // The booking id, not the event id: opening the wrong one would still "work" on screen.
    expect(onOpen).toHaveBeenCalledWith(13);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  // TC-SPL-80-15
  it('[TC-SPL-80-15] tells Venue Staff when nothing is awaiting review', async () => {
    render(<PendingBookingRequests
      accessToken="token"
      onOpen={vi.fn()}
      request={queue({
        requests: [], count: 0, message: 'No venue-booking requests are awaiting review.',
      })}
    />);

    expect(await screen.findByText('No venue-booking requests are awaiting review.')).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
  });

  // TC-SPL-80-16
  it('[TC-SPL-80-16] flags a request marked for review', async () => {
    render(<PendingBookingRequests
      accessToken="token"
      onOpen={vi.fn()}
      request={queue({ requests: [COASTAL, SOUTHBANK], count: 2 })}
    />);

    const flagged = await screen.findByRole('row', { name: /Southbank Summit/ });
    const clean = screen.getByRole('row', { name: /Coastal Forum/ });

    expect(within(flagged).getByText(/Marked for review/)).toBeTruthy();
    expect(within(clean).queryByText(/Marked for review/)).toBeNull();
  });
});
