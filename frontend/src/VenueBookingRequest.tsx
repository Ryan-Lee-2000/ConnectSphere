import { useEffect, useState } from 'react';
import { CalendarCheck } from 'lucide-react';
import { responseError, type ApiRequest } from './api';
import { ExactBookingTiming, type BookingTiming } from './ExactBookingTiming';

// SPL-77 (CS-E09-S3): the assigned coordinator requests a suitable venue for a Planning event.
// Legacy requests use saved slots; exact requests submit reviewed times and venue revision.
// The server owns identity, requirements, preparation calculation and status.

type Layout = { layout: string; capacity: number };
type BookedSlot = { date: string; slot: string };
export type VenueBooking = {
  timing?: BookingTiming | null; review_reasons?: string[];
  reviewed_requirements?: { required_facilities: string[]; accessibility_needs: string[]; preferred_room_layout: string | null; location_preference: string | null; facilities_notes: string | null; venue_notes: string | null } | null;
  id: number; venue: { id: number; name: string }; date: string; event_slots: string[];
  setup: BookedSlot | null; turnaround: BookedSlot | null; layout: string; expected_attendance: number; status: string;
};

const SLOT_NAMES: Record<string, string> = { AM: 'AM', PM: 'PM', NIGHT: 'Night' };
const layoutName = (layout: string) => layout.replace(/\b\w/g, letter => letter.toUpperCase());
const slotName = (slot: string) => SLOT_NAMES[slot] || slot;
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));

export function VenueBookingRequest({ api, eventId, venueId, venueName, expectedAttendance, preferredRoomLayout, timing, onRequested }: {
  api: ApiRequest; eventId: number; venueId: number; venueName: string;
  timing?: BookingTiming; expectedAttendance: number | null; preferredRoomLayout: string | null; onRequested: (booking: VenueBooking) => void;
}) {
  const [layouts, setLayouts] = useState<Layout[] | null>(null);
  const [layout, setLayout] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fitting = (layouts || []).filter(option => expectedAttendance !== null && option.capacity >= expectedAttendance
    && (!timing || !preferredRoomLayout?.trim() || option.layout.toLowerCase() === preferredRoomLayout.trim().toLowerCase()));

  // The venue profile is the source of supported layouts; search results are filtered by the
  // coordinator's exploratory criteria, so they cannot be relied on for the full list.
  useEffect(() => {
    let active = true;
    setLayouts(null); setError(null);
    void api(`/api/venues/${venueId}`).then(async response => {
      if (!response.ok) throw new Error('Unavailable');
      const body = await response.json() as { venue?: { layouts?: Layout[] } };
      if (!active) return;
      const supported = body.venue?.layouts || [];
      const usable = supported.filter(option => expectedAttendance !== null && option.capacity >= expectedAttendance);
      const preferred = usable.find(option => option.layout.toLowerCase() === preferredRoomLayout?.trim().toLowerCase());
      setLayouts(supported); setLayout((preferred || usable[0])?.layout || '');
    }).catch(() => { if (active) { setLayouts([]); setError('Could not load this venue’s layouts. Try again.'); } });
    return () => { active = false; };
  }, [api, venueId, expectedAttendance, preferredRoomLayout]);

  async function submit() {
    if (!layout || submitting) return;
    setSubmitting(true); setError(null);
    try {
      const response = await api(`/api/event-requests/${eventId}/venue-bookings`, {
        method: 'POST', body: JSON.stringify({ venue_id: venueId, layout, ...(timing ? {
          date: timing.event.start.slice(0, 10), start_time: timing.event.start.slice(11, 16),
          end_time: timing.event.end.slice(0, 10) !== timing.event.start.slice(0, 10) ? '24:00' : timing.event.end.slice(11, 16),
          venue_revision: timing.venue_revision,
        } : {}) }),
      });
      if (!response.ok) { setError(await responseError(response, 'Could not request this venue. Try again.')); return; }
      const body = await response.json() as { booking?: VenueBooking };
      if (!body.booking) throw new Error('Invalid response');
      onRequested(body.booking);
    } catch { setError('Could not request this venue. Try again.'); }
    finally { setSubmitting(false); }
  }

  if (layouts === null) return <p className="venue-booking-request__none" role="status">Loading layouts…</p>;
  if (error && !fitting.length) return <p className="error" role="alert">{error}</p>;
  if (!fitting.length) {
    return <p className="venue-booking-request__none">No layout at {venueName} holds {expectedAttendance ?? 'the expected'} guests, so it cannot be requested.</p>;
  }
  return <form className="venue-booking-request" aria-label={`Request ${venueName}`} onSubmit={event => { event.preventDefault(); void submit(); }}>
    {timing && <ExactBookingTiming timing={timing} />}
    <label className="field"><span>Booking layout</span>
      <select aria-label="Booking layout" onChange={event => setLayout(event.target.value)} value={layout}>
        {fitting.map(option => <option key={option.layout} value={option.layout}>{layoutName(option.layout)} — {option.capacity} guests</option>)}
      </select>
    </label>
    <button className="button button--primary" disabled={submitting} type="submit"><CalendarCheck size={17} />{submitting ? 'Requesting…' : 'Request booking'}</button>
    <p className="venue-booking-request__note">{timing ? 'Requests the times shown above using the saved event requirements. The full occupied interval is held while Venue Staff review the request.' : 'Uses the event’s saved date and time. Setup and turnaround are added from this venue’s requirements, and the slots are held until Venue Staff decide.'}</p>
    {error && <p className="error" role="alert">{error}</p>}
  </form>;
}

export function VenueBookingNotice({ booking }: { booking: VenueBooking }) {
  const slot = (value: BookedSlot) => `${slotName(value.slot)} · ${dateName(value.date)}`;
  return <div className="venue-booking-notice" role="status">
    <p><strong>Booking requested for {booking.venue.name}.</strong> Status: Requested · {layoutName(booking.layout)} · {booking.expected_attendance} guests</p>
    {booking.timing ? <ExactBookingTiming timing={booking.timing} /> : <dl>
      {booking.setup && <div><dt>Setup</dt><dd>{slot(booking.setup)}</dd></div>}
      <div><dt>Event</dt><dd>{booking.event_slots.map(slotName).join(', ')} · {dateName(booking.date)}</dd></div>
      {booking.turnaround && <div><dt>Turnaround</dt><dd>{slot(booking.turnaround)}</dd></div>}
    </dl>}
  </div>;
}
