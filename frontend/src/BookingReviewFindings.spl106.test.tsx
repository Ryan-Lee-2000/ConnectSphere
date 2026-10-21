import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { BookingReviewFindings, type BookingReviewFinding } from './BookingReviewFindings';

afterEach(cleanup);

const finding = (reason_type: BookingReviewFinding['reason_type'], id = 1): BookingReviewFinding => ({
  id, reason_type, detail: `Failed check ${id}`,
  original_occupancy: { start: '2030-06-15T10:00:00+08:00', end: '2030-06-15T11:00:00+08:00' },
  current_occupancy: null, venue_timing_revision: 1,
  first_assessed_at: '2030-06-01T10:00:00+08:00', last_assessed_at: '2030-06-01T10:00:00+08:00',
});

// QA-SPL-106-031 | AC2 | BB
it('[QA-SPL-106-031] shows every requirement failure with occupancy evidence', () => {
  const reasons: BookingReviewFinding['reason_type'][] = ['layout_capacity', 'facilities', 'accessibility', 'location', 'attendance', 'event_times'];
  render(<BookingReviewFindings findings={reasons.map((reason, index) => finding(reason, index + 1))} />);
  const region = screen.getByRole('region', { name: /booking review/i });
  expect(within(region).getAllByRole('listitem')).toHaveLength(6);
  reasons.forEach((_, index) => expect(within(region).getByText(`Failed check ${index + 1}`)).toBeTruthy());
  expect(within(region).getAllByText('Original occupancy')).toHaveLength(6);
  expect(within(region).getAllByText('Under current rules')).toHaveLength(6);
});

// QA-SPL-106-032 | AC2 | BB
it('[QA-SPL-106-032] gives multiple booking regions distinct accessible labels', () => {
  render(<><BookingReviewFindings findings={[finding('layout_capacity')]} /><BookingReviewFindings findings={[finding('facilities', 2)]} /></>);
  const regions = screen.getAllByRole('region', { name: /booking review/i });
  expect(regions).toHaveLength(2);
  expect(new Set(regions.map(region => region.getAttribute('aria-labelledby'))).size).toBe(2);
  expect(within(regions[0]).queryByText('Failed check 2')).toBeNull();
  expect(within(regions[1]).queryByText('Failed check 1')).toBeNull();
});

// QA-SPL-106-033 | AC4 | BB
it('[QA-SPL-106-033] removes resolved findings on reload without a misleading empty region', () => {
  const view = render(<BookingReviewFindings findings={[finding('attendance')]} />);
  expect(screen.getByRole('region')).toBeTruthy();
  view.rerender(<BookingReviewFindings findings={[]} />);
  expect(screen.queryByRole('region')).toBeNull();
  view.rerender(<BookingReviewFindings findings={[finding('attendance')]} />);
  expect(screen.getByRole('region')).toBeTruthy();
});

// QA-SPL-106-034 | AC2 | BB
it('[QA-SPL-106-034] preserves timing-only and mixed findings without an acknowledgement action', () => {
  const view = render(<BookingReviewFindings findings={[finding('overlap')]} />);
  expect(screen.getByRole('region', { name: /timing review/i })).toBeTruthy();
  view.rerender(<BookingReviewFindings findings={[finding('overlap'), finding('facilities', 2)]} />);
  expect(screen.getByRole('region', { name: /booking review/i })).toBeTruthy();
  expect(screen.getAllByRole('listitem')).toHaveLength(2);
  expect(screen.queryByRole('button')).toBeNull();
});
