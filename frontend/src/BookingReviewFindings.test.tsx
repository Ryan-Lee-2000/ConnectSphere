import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { BookingReviewFindings } from './BookingReviewFindings';

it('TC-SPL-130-004 renders separate operational and historical reasons', () => {
  render(<BookingReviewFindings findings={[
    { id: 1, reason_type: 'operational_block', detail: 'Operational block: Inspection', original_occupancy: { start: '2026-12-20T10:00:00+08:00', end: '2026-12-20T11:00:00+08:00' }, current_occupancy: null, venue_timing_revision: 2, first_assessed_at: '2026-10-15T10:00:00Z', last_assessed_at: '2026-10-15T10:00:00Z' },
    { id: 2, reason_type: 'unresolved_historical_timing', detail: 'Exact occupied times must be supplied.', original_occupancy: { legacy_slots: [{ date: '2026-12-20', slot: 'PM', kind: 'event' }] }, current_occupancy: null, venue_timing_revision: 2, first_assessed_at: '2026-10-15T10:00:00Z', last_assessed_at: '2026-10-15T10:00:00Z' },
  ]} />);
  expect(screen.getByText('Operational block: Inspection')).toBeTruthy();
  expect(screen.getByText('Exact occupied times must be supplied.')).toBeTruthy();
  expect(screen.getByText(/2026-12-20 PM/)).toBeTruthy();
});
