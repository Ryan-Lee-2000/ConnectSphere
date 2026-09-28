import { useEffect, useState } from 'react';
import { CircleAlert } from 'lucide-react';
import type { ApiRequest } from './api';

// SPL-79 (CS-E10-S1): the recorded history of the event's latest venue-booking request, its stored
// review marker (SPL-89) and the event's earlier requests. Read-only; rendered inside the panel.

type Actor = { id: string; name: string };
type HistoryEntry = { action: string; status: string; status_label: string; actor: Actor; changed_at: string; note: string | null };
type TriggerBlock = { id: number; start_date: string; end_date: string; slots: string[]; reason: string };
type Review = { requires_review: boolean; marked_at: string | null; trigger_block: TriggerBlock | null };
type EarlierRequest = { id: number; venue: { id: number; name: string }; date: string | null; status: string; status_label: string };
export type VenueBookingStatusBody = {
  venue_booking_request: object | null; current_status: { status: string; label: string } | null;
  history: HistoryEntry[]; review: Review | null; earlier_requests: EarlierRequest[]; message?: string;
};

const SLOT_NAMES: Record<string, string> = { AM: 'AM', PM: 'PM', NIGHT: 'Night' };
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));
const timeName = (instant: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Singapore',
}).format(new Date(instant));

export function VenueBookingHistory({ api, eventId, refreshKey = 0 }: { api: ApiRequest; eventId: number; refreshKey?: number }) {
  const [body, setBody] = useState<VenueBookingStatusBody | null>(null);

  useEffect(() => {
    let active = true;
    const pending = api(`/api/event-requests/${eventId}/venue-booking-status`);
    if (!pending) return () => { active = false; };
    void pending.then(async response => {
      if (!response.ok) return;
      const next = await response.json() as Partial<VenueBookingStatusBody>;
      if (active && Array.isArray(next.history)) setBody(next as VenueBookingStatusBody);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [api, eventId, refreshKey]);

  if (!body || !body.venue_booking_request) return null;
  const block = body.review?.requires_review ? body.review.trigger_block : null;
  return <div className="venue-booking-history">
    {body.review?.requires_review && (
      <p className="venue-booking-history__review" role="note">
        <CircleAlert size={16} aria-hidden="true" />
        <span><strong>Marked for review.</strong>{' '}
          {block ? <>Venue Staff recorded "{block.reason}" for {dateName(block.start_date)}{block.end_date !== block.start_date ? ` to ${dateName(block.end_date)}` : ''} ({block.slots.map(slot => SLOT_NAMES[slot] || slot).join(', ')}).</> : null}
          {body.review.marked_at ? <> Marked {timeName(body.review.marked_at)}.</> : null}
        </span>
      </p>
    )}
    <p className="venue-booking-history__heading" id={`venue-booking-history-${eventId}`}>History</p>
    <ol className="venue-booking-history__list" aria-label="History">
      {body.history.map((entry, index) => <li key={`${entry.changed_at}-${index}`}>
        <strong>{entry.status_label}</strong>
        <span>{entry.actor.name} · {timeName(entry.changed_at)}</span>
        {entry.note && <span className="venue-booking-history__note">{entry.note}</span>}
      </li>)}
    </ol>
    {body.earlier_requests.length > 0 && <>
      <p className="venue-booking-history__heading">Earlier requests</p>
      <ul className="venue-booking-history__earlier" aria-label="Earlier requests">
        {body.earlier_requests.map(request => <li key={request.id}>
          {request.venue.name}{request.date ? ` · ${dateName(request.date)}` : ''} · {request.status_label}
        </li>)}
      </ul>
    </>}
  </div>;
}
