import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { VenueOccupancyCalendar } from './VenueOccupancyCalendar';
afterEach(cleanup);

// QA-SPL-88 TC-SPL-88-22 and -23. The API is stubbed, so these prove what an authorised user can
// see and do with a given payload; the payload's own shape is proved server-side in
// backend/tests/test_venue_occupancy_calendar.py.

const VENUES = [
  { id: 1, name: 'Harbour Hall' },
  { id: 2, name: 'Riverside Room' },
];

function slot(name: string, status: string, reasons: { key: string; label: string; detail: string }[] = []) {
  return { slot: name, status, reasons };
}

const BLOCK_REASON = { key: 'block', label: 'Operational block', detail: 'Ceiling repair' };
const BOOKING_REASON = {
  key: 'booking',
  label: 'Approved booking',
  detail: 'The venue is committed for an approved booking.',
};

const CALENDAR = {
  venue: VENUES[0],
  start_date: '2026-10-14',
  end_date: '2026-10-15',
  days: [
    {
      date: '2026-10-14',
      slots: [
        slot('AM', 'preparation', [{ key: 'preparation', label: 'Preparation', detail: 'Venue setup time for a booking on a neighbouring slot.' }]),
        // A slot with two reasons: the headline is the more serious block (AC4).
        slot('PM', 'blocked', [BOOKING_REASON, BLOCK_REASON]),
        slot('NIGHT', 'available'),
      ],
    },
    {
      date: '2026-10-15',
      slots: [slot('AM', 'requested', [{ key: 'booking', label: 'Requested booking', detail: 'A venue-booking request is holding this slot while it awaits review.' }]), slot('PM', 'booked', [BOOKING_REASON]), slot('NIGHT', 'not_operated')],
    },
  ],
};

// A cell shows its headline status in a <strong>; reason labels below it can repeat the same word,
// so assertions target the headline specifically.
const headline = (cell: HTMLElement) => cell.querySelector('strong')?.textContent;

// Declared with the ApiRequest parameters so the assertions below can read back each call's path
// and init, rather than inferring an empty argument tuple.
function api(body: unknown = CALENDAR) {
  return vi.fn(async (_path: string, _init?: RequestInit) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }));
}

describe('VenueOccupancyCalendar', () => {
  // TC-SPL-88-23
  it('[TC-SPL-88-23] renders every state distinctly and shows a multi-reason slot in full', async () => {
    render(<VenueOccupancyCalendar accessToken="token" venues={VENUES} request={api()} />);

    const blocked = await screen.findByRole('gridcell', { name: /14 Oct 2026, PM/ });
    // AC2: the headline label is the most serious reason.
    expect(headline(blocked)).toBe('Blocked');
    // AC4: every applicable reason survives, not just the headline.
    expect(blocked.textContent).toContain('Ceiling repair');
    expect(blocked.textContent).toContain('The venue is committed for an approved booking.');

    // AC2/AC5: each state is rendered with its own label and its own modifier class, so Available
    // and Not operated can never look alike.
    for (const [name, label] of [
      ['14 Oct 2026, AM', 'Preparation'],
      ['14 Oct 2026, NIGHT', 'Available'],
      ['15 Oct 2026, AM', 'Requested'],
      ['15 Oct 2026, PM', 'Booked'],
      ['15 Oct 2026, NIGHT', 'Not operated'],
    ] as const) {
      expect(headline(screen.getByRole('gridcell', { name: new RegExp(name) }))).toBe(label);
    }
    const statuses = screen.getAllByRole('gridcell')
      .map(cell => cell.className.match(/occupancy-cell--(\w+)/)?.[1]);
    expect(new Set(statuses).size).toBe(6);
  });

  // TC-SPL-88-22
  it('[TC-SPL-88-22] refetches on venue or date change, and never issues a write', async () => {
    const request = api();
    render(<VenueOccupancyCalendar accessToken="token" venues={VENUES} request={request} />);
    await screen.findByRole('grid');
    expect(request).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText('Venue'), { target: { value: '2' } });
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    expect(String(request.mock.calls[1][0])).toContain('/api/venues/2/occupancy');

    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-11-01' } });
    await waitFor(() => expect(request).toHaveBeenCalledTimes(3));
    expect(String(request.mock.calls[2][0])).toContain('start_date=2026-11-01');

    // AC6: refreshing the view must never modify booking or block data.
    for (const [, init] of request.mock.calls) {
      expect(init?.method ?? 'GET').toBe('GET');
    }
  });
});
