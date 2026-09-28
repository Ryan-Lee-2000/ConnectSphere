import { useEffect, useState } from 'react';
import { Undo2 } from 'lucide-react';
import { responseError, type ApiRequest } from './api';
import type { VenueBooking } from './VenueBookingRequest';

// SPL-78 (CS-E09-S4): the assigned coordinator sees the event's latest venue-booking request and can
// withdraw it while it is Requested. The full status history remains SPL-79.

type WithdrawableBooking = VenueBooking & {
  withdrawn_by?: { id: string; name: string } | null;
  withdrawn_at?: string | null;
};

const STATUS_NAMES: Record<string, string> = {
  requested: 'Requested', approved: 'Approved', rejected: 'Rejected', withdrawn: 'Withdrawn', cancelled: 'Cancelled',
};
const SLOT_NAMES: Record<string, string> = { AM: 'AM', PM: 'PM', NIGHT: 'Night' };
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));
const timeName = (instant: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Singapore',
}).format(new Date(instant));
const layoutName = (layout: string) => layout.replace(/\b\w/g, letter => letter.toUpperCase());

export function VenueBookingPanel({ api, eventId, refreshKey = 0, onWithdrawn }: {
  api: ApiRequest; eventId: number; refreshKey?: number; onWithdrawn?: () => void;
}) {
  const [booking, setBooking] = useState<WithdrawableBooking | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setConfirming(false); setError(null);
    const pending = api(`/api/event-requests/${eventId}/venue-bookings/latest`);
    if (!pending) return () => { active = false; };
    void pending.then(async response => {
      if (!response.ok) return;
      const body = await response.json() as { booking?: WithdrawableBooking | null };
      if (active) setBooking(body.booking ?? null);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [api, eventId, refreshKey]);

  async function withdraw() {
    if (!booking || withdrawing) return;
    setWithdrawing(true); setError(null);
    try {
      const response = await api(`/api/event-requests/${eventId}/venue-bookings/${booking.id}/withdraw`, { method: 'POST' });
      if (!response.ok) { setError(await responseError(response, 'Could not withdraw this request. Try again.')); return; }
      const body = await response.json() as { booking?: WithdrawableBooking };
      if (!body.booking) throw new Error('Invalid response');
      setBooking(body.booking);
      setNotice(`Request withdrawn. ${body.booking.venue.name}'s slots are released for other events.`);
      onWithdrawn?.();
    } catch { setError('Could not withdraw this request. Try again.'); }
    finally { setWithdrawing(false); setConfirming(false); }
  }

  if (!booking) return null;
  const slots = booking.event_slots.map(slot => SLOT_NAMES[slot] || slot).join(', ');
  return <section className="venue-booking-panel" aria-labelledby="venue-booking-panel-title">
    <p className="eyebrow" id="venue-booking-panel-title">Venue booking request</p>
    <div className="venue-booking-panel__summary">
      <strong>{booking.venue.name}</strong>
      <span>{dateName(booking.date)} · {slots} · {layoutName(booking.layout)}</span>
      <span className="venue-booking-panel__status">Status: <strong>{STATUS_NAMES[booking.status] || booking.status}</strong></span>
      {booking.status === 'withdrawn' && booking.withdrawn_by && booking.withdrawn_at && (
        <span>Withdrawn by {booking.withdrawn_by.name} on {timeName(booking.withdrawn_at)}</span>
      )}
    </div>
    {booking.status === 'requested' && !confirming && (
      <button className="button" onClick={() => { setConfirming(true); setNotice(null); }} type="button"><Undo2 size={16} />Withdraw request</button>
    )}
    {booking.status === 'requested' && confirming && (
      <div className="venue-booking-panel__confirm" role="group" aria-label="Confirm withdrawal">
        <p>Withdraw this request? Its event, setup and turnaround slots will be released, and it cannot be reinstated. You can submit a new request afterwards.</p>
        <button className="button button--primary" disabled={withdrawing} onClick={() => void withdraw()} type="button">{withdrawing ? 'Withdrawing…' : 'Confirm withdrawal'}</button>
        <button className="button" disabled={withdrawing} onClick={() => setConfirming(false)} type="button">Keep request</button>
      </div>
    )}
    {notice && <p className="venue-booking-panel__notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
