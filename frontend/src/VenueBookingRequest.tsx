import { useEffect, useState } from 'react';
import { CalendarCheck } from 'lucide-react';
import { responseError, type ApiRequest } from './api';
import { ExactBookingTiming, type BookingTiming } from './ExactBookingTiming';

// SPL-77 (CS-E09-S3): the assigned coordinator requests a suitable venue for a Planning event.
// Legacy requests use saved slots; exact requests submit reviewed times and venue revision.
// The server owns identity, requirements, preparation calculation and status.
// SPL-131: an event may hold several venues, so each request also records how many of the event's
// attendees use this space and the facilities it needs. Both default to the event's values and
// are only sent when changed, so the server applies the same defaults.

type Layout = { layout: string; capacity: number };
type BookedSlot = { date: string; slot: string };
export type VenueBooking = {
  timing?: BookingTiming | null; review_reasons?: string[];
  reviewed_requirements?: { required_facilities: string[]; accessibility_needs: string[]; preferred_room_layout: string | null; location_preference: string | null; facilities_notes: string | null; venue_notes: string | null } | null;
  id: number; venue: { id: number; name: string }; date: string; event_slots: string[];
  setup: BookedSlot | null; turnaround: BookedSlot | null; layout: string; expected_attendance: number; status: string;
  required_facilities?: string[];
};

const SLOT_NAMES: Record<string, string> = { AM: 'AM', PM: 'PM', NIGHT: 'Night' };
const layoutName = (layout: string) => layout.replace(/\b\w/g, letter => letter.toUpperCase());
const slotName = (slot: string) => SLOT_NAMES[slot] || slot;
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));

export function VenueBookingRequest({ api, eventId, venueId, venueName, expectedAttendance, preferredRoomLayout, timing, attendeeCount, requiredFacilities = NO_FACILITIES, proposedFacilities, onRequested }: {
  api: ApiRequest; eventId: number; venueId: number; venueName: string;
  timing?: BookingTiming; expectedAttendance: number | null; preferredRoomLayout: string | null; onRequested: (booking: VenueBooking) => void;
  attendeeCount?: number; requiredFacilities?: string[];
  // SPL-131: facilities chosen in the search for this booking; the event's are the default.
  proposedFacilities?: string[];
}) {
  const [layouts, setLayouts] = useState<Layout[] | null>(null);
  const [venueFacilities, setVenueFacilities] = useState<string[]>([]);
  const [layout, setLayout] = useState('');
  const [attendees, setAttendees] = useState(String(initialAttendees(attendeeCount, expectedAttendance) ?? ''));
  const [facilities, setFacilities] = useState<string[]>(proposedFacilities ?? requiredFacilities);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attendeeValue = Number(attendees);
  const attendeesValid = expectedAttendance !== null && Number.isInteger(attendeeValue) && attendeeValue >= 1 && attendeeValue <= expectedAttendance;
  // SPL-131 AC2/AC3: a layout fits this space's own attendee count; the event's preferred layout is the default.
  const fitting = (layouts || []).filter(option => attendeesValid && option.capacity >= attendeeValue);
  const facilityOptions = Array.from(new Set([...requiredFacilities, ...(proposedFacilities ?? []), ...venueFacilities]));

  // The venue profile is the source of supported layouts; search results are filtered by the
  // coordinator's exploratory criteria, so they cannot be relied on for the full list.
  useEffect(() => {
    let active = true;
    setLayouts(null); setError(null);
    void api(`/api/venues/${venueId}`).then(async response => {
      if (!response.ok) throw new Error('Unavailable');
      const body = await response.json() as { venue?: { layouts?: Layout[]; facilities?: string[] } };
      if (!active) return;
      const supported = body.venue?.layouts || [];
      const count = initialAttendees(attendeeCount, expectedAttendance);
      const usable = supported.filter(option => count !== null && option.capacity >= count);
      const preferred = usable.find(option => option.layout.toLowerCase() === preferredRoomLayout?.trim().toLowerCase());
      setLayouts(supported); setLayout((preferred || usable[0])?.layout || '');
      setVenueFacilities(Array.isArray(body.venue?.facilities) ? body.venue.facilities : []);
    }).catch(() => { if (active) { setLayouts([]); setError('Could not load this venue’s layouts. Try again.'); } });
    return () => { active = false; };
  }, [api, venueId, expectedAttendance, preferredRoomLayout, attendeeCount]);

  // Keep the chosen layout valid when the attendee count changes.
  useEffect(() => {
    if (layouts && !fitting.some(option => option.layout === layout)) {
      const preferred = fitting.find(option => option.layout.toLowerCase() === preferredRoomLayout?.trim().toLowerCase());
      setLayout((preferred || fitting[0])?.layout || '');
    }
  }, [layouts, fitting, layout, preferredRoomLayout]);

  async function submit() {
    if (!layout || submitting || !attendeesValid) return;
    setSubmitting(true); setError(null);
    const facilitiesChanged = facilities.length !== requiredFacilities.length || facilities.some(item => !requiredFacilities.includes(item));
    try {
      const response = await api(`/api/event-requests/${eventId}/venue-bookings`, {
        method: 'POST', body: JSON.stringify({ venue_id: venueId, layout, ...(timing ? {
          date: timing.event.start.slice(0, 10), start_time: timing.event.start.slice(11, 16),
          end_time: timing.event.end.slice(0, 10) !== timing.event.start.slice(0, 10) ? '24:00' : timing.event.end.slice(11, 16),
          venue_revision: timing.venue_revision,
        } : {}),
        ...(attendeeValue !== expectedAttendance ? { attendee_count: attendeeValue } : {}),
        ...(facilitiesChanged ? { required_facilities: facilities } : {}) }),
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
  const attendeeField = <label className="field"><span>Attendees in this venue</span>
    <input aria-label="Attendees in this venue" inputMode="numeric" max={expectedAttendance ?? undefined} min="1" type="number" value={attendees} onChange={event => setAttendees(event.target.value)} />
    <small>Up to the event’s {expectedAttendance ?? 'expected'} attendees. Capacities of different venues are never added together.</small>
  </label>;
  if (!fitting.length) {
    return <div className="venue-booking-request">
      {attendeeField}
      <p className="venue-booking-request__none">{attendeesValid
        ? `No layout at ${venueName} holds ${attendeeValue} guests, so it cannot be requested.`
        : `Enter between 1 and ${expectedAttendance ?? 'the expected'} attendees for this venue.`}</p>
    </div>;
  }
  return <form className="venue-booking-request" aria-label={`Request ${venueName}`} onSubmit={event => { event.preventDefault(); void submit(); }}>
    {timing && <ExactBookingTiming timing={timing} />}
    {attendeeField}
    <label className="field"><span>Booking layout</span>
      <select aria-label="Booking layout" onChange={event => setLayout(event.target.value)} value={layout}>
        {fitting.map(option => <option key={option.layout} value={option.layout}>{layoutName(option.layout)} — {option.capacity} guests</option>)}
      </select>
    </label>
    {facilityOptions.length > 0 && <fieldset className="venue-booking-request__facilities"><legend>Facilities this venue needs</legend>
      {facilityOptions.map(item => <label key={item}><input checked={facilities.includes(item)} type="checkbox"
        onChange={() => setFacilities(current => current.includes(item) ? current.filter(value => value !== item) : [...current, item])} />{item}</label>)}
    </fieldset>}
    <button className="button button--primary" disabled={submitting} type="submit"><CalendarCheck size={17} />{submitting ? 'Requesting…' : 'Request booking'}</button>
    <p className="venue-booking-request__note">{timing ? 'Requests the times shown above using the saved event requirements. The full occupied interval is held while Venue Staff review the request.' : 'Uses the event’s saved date and time. Setup and turnaround are added from this venue’s requirements, and the slots are held until Venue Staff decide.'}</p>
    {error && <p className="error" role="alert">{error}</p>}
  </form>;
}

const NO_FACILITIES: string[] = [];

function initialAttendees(attendeeCount: number | undefined, expectedAttendance: number | null) {
  if (expectedAttendance === null) return null;
  return attendeeCount && attendeeCount >= 1 && attendeeCount < expectedAttendance ? attendeeCount : expectedAttendance;
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
