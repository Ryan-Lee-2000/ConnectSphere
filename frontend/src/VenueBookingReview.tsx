import { useEffect, useMemo, useState } from 'react';
import { CircleAlert, Check, X } from 'lucide-react';
import { defaultRequest, responseError, type ApiRequest } from './api';
import type { VenueBooking } from './VenueBookingRequest';

// SPL-81 (CS-E10-S3): Venue Staff review one venue-booking request and approve it with an optional
// note. SPL-80's pending list links here. SPL-82 (CS-E10-S4) adds Reject beside Approve, with a
// required reason and an optional free-text alternative suggestion — two separate fields, so a
// rejection can never carry a suggestion with no reason (docs/tasks/SPL-82.md).

type Person = { id: string; name: string };
type ReviewedBooking = VenueBooking & {
  requested_by: Person | null; requested_at: string | null;
  approved_by: Person | null; approved_at: string | null; approval_note: string | null;
  rejected_by: Person | null; rejected_at: string | null; rejection_reason: string | null;
  rejection_alternative_suggestion: string | null;
};
type TriggerBlock = { start_date: string; end_date: string; slots: string[]; reason: string };
type Review = { requires_review: boolean; marked_at: string | null; trigger_block: TriggerBlock | null };
// SPL-80 (CS-E10-S2 AC3) widens this with what Venue Staff need in order to decide. The server
// sends an allowlist, so there is deliberately no registration or organiser field to render (AC4).
type DecisionEvent = {
  id: number; name: string; status: string;
  organisation: { id: number; name: string } | null;
  purpose: string | null; description: string | null;
  proposed_date: string | null; start_time: string | null; end_time: string | null;
  expected_attendance: number | null; preferred_room_layout: string | null;
  required_facilities: string[]; accessibility_needs: string[];
  facilities_notes: string | null; location_preference: string | null; venue_notes: string | null;
};
type ReviewBody = { booking: ReviewedBooking; event: DecisionEvent; review: Review };

const MAX_NOTE_LENGTH = 1000;
const MAX_REASON_LENGTH = 1000;
const MAX_SUGGESTION_LENGTH = 1000;
const STATUS_NAMES: Record<string, string> = {
  requested: 'Requested', approved: 'Approved', rejected: 'Rejected', withdrawn: 'Withdrawn', cancelled: 'Cancelled',
};
const SLOT_NAMES: Record<string, string> = { AM: 'AM', PM: 'PM', NIGHT: 'Night' };
const slotName = (slot: string) => SLOT_NAMES[slot] || slot;
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));
const timeName = (instant: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Singapore',
}).format(new Date(instant));
const layoutName = (layout: string) => layout.replace(/\b\w/g, letter => letter.toUpperCase());
const preparation = (slot: { date: string; slot: string } | null) => slot ? `${slotName(slot.slot)} · ${dateName(slot.date)}` : 'None';

export function VenueBookingReview({ accessToken, bookingId, request }: {
  accessToken: string; bookingId: number; request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [body, setBody] = useState<ReviewBody | null>(null);
  const [note, setNote] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [approving, setApproving] = useState(false);
  const [rejectingForm, setRejectingForm] = useState(false);
  const [reason, setReason] = useState('');
  const [suggestion, setSuggestion] = useState('');
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api(`/api/venue-bookings/${bookingId}`).then(async response => {
      if (!response.ok) {
        const message = await responseError(response, 'Could not load this venue-booking request.');
        if (active) setError(message);
        return;
      }
      const next = await response.json() as ReviewBody;
      if (active) setBody(next);
    }).catch(() => { if (active) setError('Could not load this venue-booking request.'); });
    return () => { active = false; };
  }, [api, bookingId]);

  async function approve() {
    if (!body || approving) return;
    setApproving(true); setError(null);
    try {
      const response = await api(`/api/venue-bookings/${bookingId}/approve`, {
        method: 'POST', body: JSON.stringify(note.trim() ? { note } : {}),
      });
      if (!response.ok) { setError(await responseError(response, 'Could not approve this request. Try again.')); return; }
      const next = await response.json() as { booking?: ReviewedBooking };
      if (!next.booking) throw new Error('Invalid response');
      setBody({ ...body, booking: next.booking });
    } catch { setError('Could not approve this request. Try again.'); }
    finally { setApproving(false); setConfirming(false); }
  }

  async function reject() {
    if (!body || rejecting || !reason.trim()) return;
    setRejecting(true); setError(null);
    try {
      const response = await api(`/api/venue-bookings/${bookingId}/reject`, {
        method: 'POST',
        body: JSON.stringify(
          suggestion.trim() ? { reason, alternative_suggestion: suggestion } : { reason },
        ),
      });
      if (!response.ok) { setError(await responseError(response, 'Could not reject this request. Try again.')); return; }
      const next = await response.json() as { booking?: ReviewedBooking };
      if (!next.booking) throw new Error('Invalid response');
      setBody({ ...body, booking: next.booking });
    } catch { setError('Could not reject this request. Try again.'); }
    finally { setRejecting(false); setRejectingForm(false); }
  }

  if (!body) {
    return <section className="venue-booking-review" aria-labelledby="venue-booking-review-title">
      <h1 id="venue-booking-review-title">Review venue-booking request</h1>
      {error ? <p className="error" role="alert">{error}</p> : <p>Loading the request…</p>}
    </section>;
  }
  const { booking, event, review } = body;
  const block = review.requires_review ? review.trigger_block : null;
  const details: [string, string][] = [
    ['Event', event.name],
    ['Venue', booking.venue.name],
    ['Date', dateName(booking.date)],
    ['Event slots', booking.event_slots.map(slotName).join(', ')],
    ['Setup', preparation(booking.setup)],
    ['Turnaround', preparation(booking.turnaround)],
    ['Layout', layoutName(booking.layout)],
    ['Expected attendance', String(booking.expected_attendance)],
    ['Requested by', booking.requested_by?.name ?? 'Not recorded'],
    ['Requested at', booking.requested_at ? timeName(booking.requested_at) : 'Not recorded'],
    ['Status', STATUS_NAMES[booking.status] || booking.status],
  ];
  // SPL-80 AC3: what the event needs of a venue, so the decision can be made here rather than by
  // chasing the coordinator. Empty values are dropped rather than shown as "None", because an
  // absent requirement and a requirement of "none" read differently to someone deciding.
  const eventDetails: [string, string][] = ([
    ['Client', event.organisation?.name ?? ''],
    ['Purpose', event.purpose ?? ''],
    ['Description', event.description ?? ''],
    ['Times', event.start_time && event.end_time ? `${event.start_time}–${event.end_time}` : ''],
    ['Expected attendance', event.expected_attendance ? String(event.expected_attendance) : ''],
    ['Preferred layout', event.preferred_room_layout ? layoutName(event.preferred_room_layout) : ''],
    ['Required facilities', event.required_facilities.join(', ')],
    ['Accessibility needs', event.accessibility_needs.join(', ')],
    ['Facilities notes', event.facilities_notes ?? ''],
    ['Location preference', event.location_preference ?? ''],
    ['Venue notes', event.venue_notes ?? ''],
  ] as [string, string][]).filter(([, value]) => value !== '');
  return <section className="venue-booking-review" aria-labelledby="venue-booking-review-title">
    <p className="eyebrow">Venue booking</p>
    <h1 id="venue-booking-review-title">Review venue-booking request</h1>
    <ul className="venue-booking-review__details" aria-label="Request details">
      {details.map(([label, value]) => <li key={label}><span>{label}</span><strong>{value}</strong></li>)}
    </ul>
    <h2 className="venue-booking-review__subheading">Event details</h2>
    <ul className="venue-booking-review__details" aria-label="Event details">
      {eventDetails.map(([label, value]) => <li key={label}><span>{label}</span><strong>{value}</strong></li>)}
    </ul>
    {review.requires_review && (
      <p className="venue-booking-history__review" role="note">
        <CircleAlert size={16} aria-hidden="true" />
        <span><strong>Marked for review.</strong>{' '}
          {block ? <>Venue Staff recorded "{block.reason}" for {dateName(block.start_date)}{block.end_date !== block.start_date ? ` to ${dateName(block.end_date)}` : ''} ({block.slots.map(slotName).join(', ')}).</> : null}
          {review.marked_at ? <> Marked {timeName(review.marked_at)}.</> : null}
          {' '}Approval rechecks every slot before it goes ahead.
        </span>
      </p>
    )}
    {booking.status === 'approved' && booking.approved_by && booking.approved_at && (
      <p className="venue-booking-review__outcome" role="status">
        <Check size={16} aria-hidden="true" />
        <span>Approved by {booking.approved_by.name} on {timeName(booking.approved_at)}.
          {booking.approval_note ? <> Note: {booking.approval_note}</> : null}</span>
      </p>
    )}
    {booking.status === 'rejected' && booking.rejected_by && booking.rejected_at && (
      <p className="venue-booking-review__outcome venue-booking-review__outcome--rejected" role="status">
        <X size={16} aria-hidden="true" />
        <span>Rejected by {booking.rejected_by.name} on {timeName(booking.rejected_at)}.
          {booking.rejection_reason ? <> Reason: {booking.rejection_reason}</> : null}
          {booking.rejection_alternative_suggestion ? <> Suggested alternative: {booking.rejection_alternative_suggestion}</> : null}
        </span>
      </p>
    )}
    {booking.status === 'requested' && <div className="venue-booking-review__decision">
      {!rejectingForm && (
        <label>Approval note (optional)
          <textarea maxLength={MAX_NOTE_LENGTH} onChange={change => setNote(change.target.value)} rows={3} value={note} />
        </label>
      )}
      {!confirming && !rejectingForm && (
        <div className="venue-booking-review__actions">
          <button className="button button--primary" onClick={() => { setConfirming(true); setError(null); }} type="button">Approve booking</button>
          <button className="button button--secondary" onClick={() => { setRejectingForm(true); setError(null); }} type="button">Reject booking</button>
        </div>
      )}
      {confirming && (
        <div className="venue-booking-panel__confirm" role="group" aria-label="Confirm approval">
          <p>Approve this request? Its event, setup and turnaround slots stay reserved for {event.name}. Every slot is rechecked first.</p>
          <button className="button button--primary" disabled={approving} onClick={() => void approve()} type="button">{approving ? 'Approving…' : 'Confirm approval'}</button>
          <button className="button" disabled={approving} onClick={() => setConfirming(false)} type="button">Keep reviewing</button>
        </div>
      )}
      {rejectingForm && (
        <div className="venue-booking-panel__confirm" role="group" aria-label="Reject request">
          <label>Rejection reason
            <textarea maxLength={MAX_REASON_LENGTH} onChange={change => setReason(change.target.value)} rows={3} value={reason} />
          </label>
          <label>Alternative suggestion (optional)
            <textarea maxLength={MAX_SUGGESTION_LENGTH} onChange={change => setSuggestion(change.target.value)} rows={2} value={suggestion} />
          </label>
          <button className="button button--primary" disabled={rejecting || !reason.trim()} onClick={() => void reject()} type="button">{rejecting ? 'Rejecting…' : 'Confirm rejection'}</button>
          <button className="button" disabled={rejecting} onClick={() => setRejectingForm(false)} type="button">Keep reviewing</button>
        </div>
      )}
    </div>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
