import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BookingTimingReviews } from './BookingTimingReviews';

const json = (body: object) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
const finding = {
  id: 7,
  reason_type: 'overlap' as const,
  detail: 'The revised occupied interval overlaps Strategy Forum (booking 42).',
  original_occupancy: { start: '2026-12-20T10:00:00+08:00', end: '2026-12-20T11:00:00+08:00' },
  current_occupancy: { start: '2026-12-20T09:30:00+08:00', end: '2026-12-20T11:30:00+08:00' },
  venue_timing_revision: 2,
  first_assessed_at: '2026-10-15T10:00:00+08:00',
  last_assessed_at: '2026-10-15T10:00:00+08:00',
};

describe('SPL-130 timing review queue', () => {
  it('TC-SPL-130-003 shows event, coordinator, status, reason and both occupancies', async () => {
    const request = vi.fn(() => json({ reviews: [{ booking_id: 9, status: 'approved', event: { id: 1, name: 'Leadership Forum', advertised_interval: { start: '2026-12-20T10:00:00+08:00', end: '2026-12-20T11:00:00+08:00' } }, venue: { id: 2, name: 'Atlas Hall' }, coordinator: { id: 'c', name: 'Casey Lim' }, findings: [finding] }], count: 1 }));
    render(<BookingTimingReviews accessToken="token" onOpen={vi.fn()} request={request} />);
    expect(await screen.findByText('Leadership Forum')).toBeTruthy();
    expect(screen.getByText('Casey Lim')).toBeTruthy();
    expect(screen.getByText('Approved')).toBeTruthy();
    expect(screen.getByText(finding.detail)).toBeTruthy();
    expect(screen.getByText(/Advertised:/)).toBeTruthy();
    expect(screen.getByText(/Original:/)).toBeTruthy();
    expect(screen.getByText(/Current:/)).toBeTruthy();
  });

  it('TC-SPL-130-005 opens the selected affected booking for Venue Staff', async () => {
    const onOpen = vi.fn();
    render(<BookingTimingReviews accessToken="token" onOpen={onOpen} request={() => json({ reviews: [{ booking_id: 9, status: 'requested', event: { id: 1, name: 'Forum', advertised_interval: null }, venue: { id: 2, name: 'Hall' }, coordinator: null, findings: [finding] }], count: 1 })} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
    expect(onOpen).toHaveBeenCalledWith(9);
  });

  it('TC-SPL-130-007 presents an explicit empty state when no findings remain', async () => {
    render(<BookingTimingReviews accessToken="token" onOpen={vi.fn()} request={() => json({ reviews: [], count: 0 })} />);
    expect(await screen.findByText('No timing reviews')).toBeTruthy();
    expect(screen.getByText(/No active booking has an outstanding timing finding/)).toBeTruthy();
  });
});
