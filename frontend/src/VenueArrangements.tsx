import { useEffect, useState } from 'react';
import { Ban, CircleAlert, Undo2 } from 'lucide-react';
import { responseError, type ApiRequest } from './api';
import { BookingReviewFindings, type BookingReviewFinding } from './BookingReviewFindings';
import { BookingReviewReasons, ExactBookingTiming } from './ExactBookingTiming';
import type { VenueBooking } from './VenueBookingRequest';

// SPL-131 (Week 7 change 3): every venue booking the event holds, oldest first, each with its own
// times, attendee count, status and history (AC8). The event's original single booking is the
// first item (AC9). A Requested booking can be withdrawn (SPL-78) and an Approved one cancelled
// with a reason while the event is in Planning (AC7); either changes only that booking (AC6).

type Actor = { id: string; name: string };
type HistoryEntry = { action: string; status: string; status_label: string; actor: Actor; changed_at: string; note: string | null };
type Arrangement = {
  booking: VenueBooking;
  current_status: { status: string; label: string };
  history: HistoryEntry[];
  review: { requires_review: boolean; findings?: BookingReviewFinding[] } | null;
};

const MAX_REASON_LENGTH = 1000;
const SLOT_NAMES: Record<string, string> = { AM: 'AM', PM: 'PM', NIGHT: 'Night' };
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));
const timeName = (instant: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Singapore',
}).format(new Date(instant));
const layoutName = (layout: string) => layout.replace(/\b\w/g, letter => letter.toUpperCase());

export function VenueArrangements({ api, eventId, eventStatus, refreshKey = 0, onChanged, emptyMessage = false }: {
  api: ApiRequest; eventId: number; eventStatus?: string; refreshKey?: number; onChanged?: () => void;
  // On the event page, say so explicitly when nothing has been requested yet.
  emptyMessage?: boolean;
}) {
  const [arrangements, setArrangements] = useState<Arrangement[] | null>(null);
  const [version, setVersion] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const pending = api(`/api/event-requests/${eventId}/venue-booking-status`);
    if (!pending) return () => { active = false; };
    void pending.then(async response => {
      if (!response.ok) return;
      const body = await response.json() as { bookings?: unknown; venue_booking_request?: unknown };
      if (!active) return;
      // No request yet: the status body has no bookings list, which is an empty one.
      if (Array.isArray(body.bookings)) setArrangements(body.bookings as Arrangement[]);
      else if (body.venue_booking_request === null) setArrangements([]);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [api, eventId, refreshKey, version]);

  if (arrangements === null) return null;
  if (!arrangements.length) {
    if (!emptyMessage) return null;
    return <section className="venue-booking-panel" aria-labelledby={`venue-arrangements-${eventId}`}>
      <p className="eyebrow" id={`venue-arrangements-${eventId}`}>Venue bookings</p>
      <p className="venue-booking-panel__empty">No venue-booking request has been made for this event yet.</p>
    </section>;
  }
  const changed = (message: string) => { setNotice(message); setVersion(next => next + 1); onChanged?.(); };
  return <section className="venue-arrangements" aria-labelledby={`venue-arrangements-${eventId}`}>
    <p className="eyebrow" id={`venue-arrangements-${eventId}`}>Venue bookings · {arrangements.length}</p>
    {notice && <p className="venue-booking-panel__notice" role="status">{notice}</p>}
    <ol className="venue-arrangements__list" aria-label="Venue bookings">
      {arrangements.map(arrangement => <li key={arrangement.booking.id}>
        <ArrangementCard api={api} eventId={eventId} eventStatus={eventStatus} arrangement={arrangement} onChanged={changed} />
      </li>)}
    </ol>
  </section>;
}

function ArrangementCard({ api, eventId, eventStatus, arrangement, onChanged }: {
  api: ApiRequest; eventId: number; eventStatus?: string; arrangement: Arrangement; onChanged: (message: string) => void;
}) {
  const { booking, current_status: status, history, review } = arrangement;
  const [action, setAction] = useState<'withdraw' | 'cancel' | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const facilities = booking.required_facilities ?? [];
  const canCancel = booking.status === 'approved' && eventStatus === 'planning';

  async function submit() {
    if (busy || !action) return;
    if (action === 'cancel' && !reason.trim()) { setError('Give a reason for cancelling this venue booking.'); return; }
    setBusy(true); setError(null);
    try {
      const response = await api(`/api/event-requests/${eventId}/venue-bookings/${booking.id}/${action}`, action === 'cancel'
        ? { method: 'POST', body: JSON.stringify({ reason: reason.trim() }) }
        : { method: 'POST' });
      if (!response.ok) { setError(await responseError(response, `Could not ${action} this booking. Try again.`)); return; }
      const time = booking.timing ? 'occupied time is' : 'slots are';
      setAction(null); setReason('');
      onChanged(action === 'cancel'
        ? `${booking.venue.name} booking cancelled. Its ${time} available to other events; the event's other venues are unchanged.`
        : `Request withdrawn. ${booking.venue.name}'s ${time} released for other events.`);
    } catch { setError(`Could not ${action} this booking. Try again.`); }
    finally { setBusy(false); }
  }

  const heading = `venue-arrangement-${booking.id}`;
  return <article className="venue-booking-panel venue-arrangements__item" aria-labelledby={heading}>
    <div className="venue-booking-panel__summary">
      <strong id={heading}>{booking.venue.name}</strong>
      <span>{booking.timing ? dateName(booking.date) : `${dateName(booking.date)} · ${booking.event_slots.map(slot => SLOT_NAMES[slot] || slot).join(', ')}`} · {layoutName(booking.layout)}</span>
      <span>{booking.expected_attendance} attendees{facilities.length ? ` · Facilities: ${facilities.join(', ')}` : ''}</span>
      <span className="venue-booking-panel__status">Status: <strong>{status.label}</strong></span>
    </div>
    {booking.timing && <ExactBookingTiming timing={booking.timing} />}
    <BookingReviewReasons reasons={booking.review_reasons} />
    {review?.requires_review && !booking.review_reasons?.length && <p className="venue-booking-history__review" role="note">
      <CircleAlert size={16} aria-hidden="true" /><span><strong>Marked for review.</strong></span>
    </p>}
    <BookingReviewFindings findings={review?.findings || []} />
    {action === null && booking.status === 'requested' && <button className="button" type="button" onClick={() => { setAction('withdraw'); setError(null); }}><Undo2 size={16} />Withdraw request</button>}
    {action === null && canCancel && <button className="button" type="button" onClick={() => { setAction('cancel'); setError(null); }}><Ban size={16} />Cancel booking</button>}
    {action === 'withdraw' && <div className="venue-booking-panel__confirm" role="group" aria-label={`Confirm withdrawal of ${booking.venue.name}`}>
      <p>Withdraw this request? Its held time will be released, and it cannot be reinstated. The event's other venue bookings are unchanged.</p>
      <button className="button button--primary" disabled={busy} type="button" onClick={() => void submit()}>{busy ? 'Withdrawing…' : 'Confirm withdrawal'}</button>
      <button className="button" disabled={busy} type="button" onClick={() => setAction(null)}>Keep request</button>
    </div>}
    {action === 'cancel' && <form className="venue-booking-panel__confirm" aria-label={`Cancel ${booking.venue.name} booking`} onSubmit={event => { event.preventDefault(); void submit(); }}>
      <p>Cancel this approved booking? {booking.venue.name}'s time is released for other events and cannot be reinstated; request it again if you need it. The event's other venue bookings are unchanged.</p>
      <div className="field venue-arrangements__reason">
        <label htmlFor={`cancel-reason-${booking.id}`}>Cancellation reason</label>
        <textarea id={`cancel-reason-${booking.id}`} rows={3} maxLength={MAX_REASON_LENGTH} required value={reason} onChange={change => setReason(change.target.value)} />
      </div>
      <button className="button button--primary" disabled={busy} type="submit">{busy ? 'Cancelling…' : 'Confirm cancellation'}</button>
      <button className="button" disabled={busy} type="button" onClick={() => { setAction(null); setReason(''); setError(null); }}>Keep booking</button>
    </form>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="venue-booking-history">
      <p className="venue-booking-history__heading">History</p>
      <ol className="venue-booking-history__list" aria-label={`History of ${booking.venue.name} booking`}>
        {history.map((entry, index) => <li key={`${entry.changed_at}-${index}`}>
          <strong>{entry.status_label}</strong>
          <span>{entry.actor.name} · {timeName(entry.changed_at)}</span>
          {entry.note && <span className="venue-booking-history__note">{entry.note}</span>}
        </li>)}
      </ol>
    </div>
  </article>;
}
