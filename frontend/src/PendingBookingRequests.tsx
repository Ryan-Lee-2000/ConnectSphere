import { useEffect, useMemo, useState } from 'react';
import { CircleAlert, ClipboardList, Inbox } from 'lucide-react';
import { defaultRequest, responseError, type ApiRequest } from './api';
import { bookingInterval, type BookingTiming } from './ExactBookingTiming';

// SPL-80 (CS-E10-S2): Venue Staff's queue of venue-booking requests awaiting review. Read-only —
// deciding on a request happens on SPL-81's review page, which each row opens.

type Person = { id: string; name: string };
type PreparationSlot = { date: string; slot: string } | null;
type PendingRequest = {
  timing?: BookingTiming | null;
  id: number;
  event: { id: number; name: string };
  venue: { id: number; name: string };
  date: string | null;
  event_slots: string[];
  setup: PreparationSlot;
  turnaround: PreparationSlot;
  layout: string | null;
  expected_attendance: number | null;
  requested_by: Person | null;
  requested_at: string | null;
  requires_review: boolean;
};
type QueueBody = { requests: PendingRequest[]; count: number; message?: string };

const SLOT_NAMES: Record<string, string> = { AM: 'AM', PM: 'PM', NIGHT: 'Night' };
const slotName = (slot: string) => SLOT_NAMES[slot] || slot;
// Proposed dates are calendar dates, so they must not shift with the viewer's time zone.
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
}).format(new Date(`${day}T00:00:00Z`));
const timeName = (instant: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  timeZone: 'Asia/Singapore',
}).format(new Date(instant));
const layoutName = (layout: string) => layout.replace(/\b\w/g, letter => letter.toUpperCase());
const preparation = (slot: PreparationSlot) => slot ? `${slotName(slot.slot)} · ${dateName(slot.date)}` : 'None';

export function PendingBookingRequests({ accessToken, onOpen, request }: {
  accessToken: string;
  onOpen: (bookingId: number) => void;
  request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [body, setBody] = useState<QueueBody | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api('/api/venue-bookings/pending').then(async response => {
      if (!response.ok) {
        const message = await responseError(response, 'Could not load the booking requests.');
        if (active) setError(message);
        return;
      }
      const next = await response.json() as QueueBody;
      if (active) setBody(next);
    }).catch(() => { if (active) setError('Could not load the booking requests.'); });
    return () => { active = false; };
  }, [api]);

  return <section className="assignment-queue" aria-labelledby="booking-requests-heading">
    <header className="catalogue-header">
      <div>
        <p className="eyebrow"><ClipboardList size={14} /> Venue booking</p>
        <h1 id="booking-requests-heading">Booking requests awaiting review</h1>
        <p className="catalogue-subtitle">
          Every request in Requested status, across all client organisations, oldest first.
        </p>
      </div>
    </header>
    {error && <p className="error" role="alert">{error}</p>}
    {!body && !error && <p role="status">Loading booking requests…</p>}
    {body && body.count > 0 && (
      <div className="catalogue-intro">
        <p>{body.count} {body.count === 1 ? 'request' : 'requests'} awaiting review</p>
      </div>
    )}
    {/* AC6: the server sends the sentence, so the empty state cannot drift from the API. */}
    {body && body.count === 0 && (
      <div className="catalogue-empty">
        <Inbox size={28} />
        <h2>Nothing is awaiting review</h2>
        <p>{body.message ?? 'No venue-booking requests are awaiting review.'}</p>
      </div>
    )}
    {body && body.count > 0 && <div className="assignment-table">
      <table>
        <caption className="visually-hidden">
          Venue-booking requests awaiting review, longest waiting first
        </caption>
        <thead>
          <tr>
            <th scope="col">Event</th>
            <th scope="col">Venue</th>
            <th scope="col">Date</th>
            <th scope="col">Time</th>
            <th scope="col">Layout</th>
            <th scope="col">Attendance</th>
            <th scope="col">Requested by</th>
            <th scope="col">Requested</th>
            <th scope="col"><span className="visually-hidden">Action</span></th>
          </tr>
        </thead>
        <tbody>
          {body.requests.map(item => <tr key={item.id}>
            <th scope="row">
              {item.event.name}
              {/* SPL-89 marked this request when an operational block landed on one of its
                  slots. Surfacing it in the queue means it is seen before the request is
                  opened, rather than only on the review page (Q120). */}
              {item.requires_review && (
                <span className="request-flag" role="note">
                  <CircleAlert size={14} aria-hidden="true" /> Marked for review
                </span>
              )}
            </th>
            <td>{item.venue.name}</td>
            <td>{item.date ? dateName(item.date) : 'Not recorded'}</td>
            <td>
              {item.timing ? <>
                {bookingInterval(item.timing.event)}
                <span className="request-preparation">Occupied: {bookingInterval(item.timing.occupied)}</span>
              </> : <>
                {item.event_slots.map(slotName).join(', ') || 'None'}
                <span className="request-preparation">Setup {preparation(item.setup)} · Turnaround {preparation(item.turnaround)}</span>
              </>}
            </td>
            <td>{item.layout ? layoutName(item.layout) : 'Not recorded'}</td>
            <td>{item.expected_attendance ?? 'Not recorded'}</td>
            <td>{item.requested_by?.name ?? 'Not recorded'}</td>
            <td>{item.requested_at ? timeName(item.requested_at) : 'Not recorded'}</td>
            <td>
              <button
                aria-label={`Review the booking request for ${item.event.name}`}
                className="button button--secondary"
                onClick={() => onOpen(item.id)}
                type="button"
              >
                Review
              </button>
            </td>
          </tr>)}
        </tbody>
      </table>
    </div>}
  </section>;
}
