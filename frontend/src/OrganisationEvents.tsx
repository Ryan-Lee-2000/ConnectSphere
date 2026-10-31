import { useEffect, useState, type MouseEvent } from 'react';
import { ClarificationHistory, type Clarification } from './ClarificationHistory';
import { RegistrationAttendees } from './RegistrationAttendees';

type EventSummary = {
  id: number;
  name: string;
  proposed_date: string;
  responsible_organiser: string;
};

type EventDetail = EventSummary & {
  purpose: string;
  description: string | null;
  start_time: string;
  end_time: string;
  expected_attendance: number;
  preferred_room_layout?: string | null;
  required_facilities?: string[];
  accessibility_needs?: string[];
  venue_notes?: string | null;
  status: string;
  status_label: string;
  status_explanation: string;
  coordinator: { id: string; name: string } | null;
  venue_arrangements: VenueArrangement[];
  equipment_arrangements: EquipmentArrangement[];
  registration_settings: RegistrationSettings;
  clarifications: Clarification[];
};

type VenueArrangement = {
  booking_id: number;
  venue: string;
  location: string | null;
  date: string | null;
  start_time: string | null;
  end_time: string | null;
  status: 'approved' | 'requested' | 'review_required';
  status_label: string;
};

type EquipmentArrangement = {
  requirement_id: number;
  equipment: string;
  required_quantity: number;
  notes?: string | null;
  reserved_quantity: number;
  status: string;
  status_label: string;
  essentiality: string;
  essentiality_label: string;
};

type RegistrationSettings = {
  enabled: boolean;
  capacity: number | null;
  opens_at: string | null;
  closes_at: string | null;
};

type OrganisationEventRequest = (path: string, init?: RequestInit) => Promise<Response>;

function formatDate(value: string) {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatInstant(value: string | null) {
  if (!value) return 'Not configured';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('en-SG', {
    day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZone: 'Asia/Singapore',
  }).format(parsed);
}

function ArrangementsSummary({ event }: { event: EventDetail }) {
  const venues = event.venue_arrangements ?? [];
  const equipment = event.equipment_arrangements ?? [];
  const registration = event.registration_settings ?? {
    enabled: false, capacity: null, opens_at: null, closes_at: null,
  };
  return <section className="organisation-arrangements" aria-labelledby="organisation-arrangements-title">
    <header className="organisation-arrangements__header">
      <div>
        <p className="eyebrow">Current saved state</p>
        <h3 id="organisation-arrangements-title">Event arrangements</h3>
        <p>This summary is read-only. Pending decisions and reviews are labelled separately from approved arrangements.</p>
      </div>
    </header>

    <section className="organisation-arrangements__section" aria-labelledby="venue-arrangements-title">
      <h4 id="venue-arrangements-title">Venue arrangements</h4>
      {venues.length === 0
        ? <p className="organisation-arrangements__empty">No current venue arrangement.</p>
        : <div className="organisation-events__table-wrap"><table className="organisation-events__table">
          <thead><tr><th scope="col">Venue</th><th scope="col">Booked date and time</th><th scope="col">Status</th></tr></thead>
          <tbody>{venues.map(venue => <tr key={venue.booking_id}>
            <td><strong>{venue.venue}</strong><small>{venue.location || 'Location not recorded'}</small></td>
            <td>{venue.date ? formatDate(venue.date) : 'Date not recorded'}<small>{venue.start_time && venue.end_time ? `${venue.start_time} to ${venue.end_time}` : 'Time not recorded'}</small></td>
            <td><span className={`arrangement-status arrangement-status--${venue.status}`}>{venue.status_label}</span></td>
          </tr>)}</tbody>
        </table></div>}
    </section>

    <section className="organisation-arrangements__section" aria-labelledby="equipment-arrangements-title">
      <h4 id="equipment-arrangements-title">Equipment arrangements</h4>
      {equipment.length === 0
        ? <p className="organisation-arrangements__empty">No equipment requirements recorded.</p>
        : <div className="organisation-events__table-wrap"><table className="organisation-events__table">
          <thead><tr><th scope="col">Equipment</th><th scope="col">Quantity</th><th scope="col">Status</th></tr></thead>
          <tbody>{equipment.map(item => <tr key={item.requirement_id}>
            <td><strong>{item.equipment}</strong><small>{item.essentiality_label}</small>
              {'notes' in item && <small>Technical notes: {item.notes || 'None'}</small>}
            </td>
            <td><strong>{item.reserved_quantity}/{item.required_quantity}</strong><small>reserved / required</small></td>
            <td><span className={`arrangement-status arrangement-status--${item.status}`}>{item.status_label}</span></td>
          </tr>)}</tbody>
        </table></div>}
    </section>

    <section className="organisation-arrangements__section" aria-labelledby="registration-arrangements-title">
      <h4 id="registration-arrangements-title">Registration settings</h4>
      <dl className="organisation-arrangements__registration">
        <div><dt>Registration</dt><dd>{registration.enabled ? 'Enabled' : 'Not configured'}</dd></div>
        <div><dt>Capacity</dt><dd>{registration.enabled ? registration.capacity : 'Not configured'}</dd></div>
        <div><dt>Opens</dt><dd>{formatInstant(registration.opens_at)}</dd></div>
        <div><dt>Closes</dt><dd>{formatInstant(registration.closes_at)}</dd></div>
      </dl>
    </section>
  </section>;
}

export function OrganisationEvents({
  accessToken,
  eventId,
  onNavigate,
  request,
}: {
  accessToken: string;
  eventId?: number;
  onNavigate: (path: string) => void;
  request?: OrganisationEventRequest;
}) {
  const [events, setEvents] = useState<EventSummary[] | null>(null);
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [registrationListAvailable, setRegistrationListAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const api = request || ((path: string, init: RequestInit = {}) => fetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${accessToken}`, ...init.headers },
  }));

  useEffect(() => {
    let active = true;
    setError(null);
    setEvents(null);
    setEvent(null);
    setRegistrationListAvailable(false);

    async function load() {
      try {
        const path = eventId === undefined
          ? '/api/organisation/events'
          : `/api/organisation/events/${eventId}`;
        const response = await api(path);
        const body = await response.json().catch(() => null);
        if (!active) return;
        if (!response.ok) {
          setError(eventId === undefined
            ? "We couldn't load your organisation's events. Try again shortly."
            : "We couldn't find that event in your client organisation.");
          return;
        }
        if (eventId === undefined && Array.isArray(body?.events)) setEvents(body.events);
        else if (eventId !== undefined && body?.event) {
          setRegistrationListAvailable(
            response.headers?.get('X-ConnectSphere-Registration-List') === 'available',
          );
          setEvent(body.event);
        }
        else setError("We couldn't load this event information. Try again shortly.");
      } catch {
        if (active) setError("We couldn't load this event information. Try again shortly.");
      }
    }

    void load();
    return () => { active = false; };
  }, [eventId]); // The request function is stable for the life of this workspace view.

  function follow(event: MouseEvent<HTMLAnchorElement>, path: string) {
    event.preventDefault();
    onNavigate(path);
  }

  if (error) return <section className="organisation-events" aria-labelledby="organisation-events-title">
    <p className="eyebrow">Client organisation</p>
    <h2 id="organisation-events-title">Organisation events</h2>
    <p className="error" role="alert">{error}</p>
    {eventId !== undefined && <a
      className="organisation-events__back"
      href="/workspace/organisation-events"
      onClick={click => follow(click, '/workspace/organisation-events')}
    >Back to organisation events</a>}
  </section>;

  if ((eventId === undefined && events === null) || (eventId !== undefined && event === null)) {
    return <section className="organisation-events" aria-busy="true" aria-live="polite">
      <p className="visually-hidden">Loading organisation events</p>
      <div className="organisation-events__skeleton organisation-events__skeleton--title" />
      <div className="organisation-events__skeleton" />
      <div className="organisation-events__skeleton" />
    </section>;
  }

  if (event) return <section className="organisation-events" aria-labelledby="organisation-event-title">
    <a
      className="organisation-events__back"
      href="/workspace/organisation-events"
      onClick={click => follow(click, '/workspace/organisation-events')}
    >Back to organisation events</a>
    <div className="organisation-events__heading">
      <div>
        <p className="eyebrow">Read-only event information</p>
        <h2 id="organisation-event-title">{event.name}</h2>
      </div>
      <p><span>Responsible organiser</span><strong>{event.responsible_organiser}</strong></p>
    </div>
    <dl className="organisation-events__details">
      <div><dt>Status</dt><dd>{event.status_label}</dd></div>
      <div><dt>Purpose</dt><dd>{event.purpose}</dd></div>
      <div><dt>Description</dt><dd>{event.description || 'No description provided.'}</dd></div>
      <div><dt>Proposed date</dt><dd>{formatDate(event.proposed_date)}</dd></div>
      <div><dt>Time</dt><dd>{event.start_time} to {event.end_time}</dd></div>
      <div><dt>Expected attendance</dt><dd>{event.expected_attendance}</dd></div>
      <div><dt>Preferred room layout</dt><dd>{event.preferred_room_layout || 'Not set'}</dd></div>
      <div><dt>Required facilities</dt><dd>{event.required_facilities?.join(', ') || 'None'}</dd></div>
      <div><dt>Accessibility needs</dt><dd>{event.accessibility_needs?.join(', ') || 'None'}</dd></div>
      <div><dt>Venue preferences and notes</dt><dd>{event.venue_notes || 'None'}</dd></div>
      <div><dt>Assigned coordinator</dt><dd>{event.coordinator?.name || 'Not assigned'}</dd></div>
    </dl>
    {event.status === 'returned_for_clarification' && <p className="notice" role="status">{event.status_explanation}</p>}
    <ArrangementsSummary event={event} />
    {registrationListAvailable && <RegistrationAttendees accessToken={accessToken} eventId={event.id} request={request} />}
    <ClarificationHistory clarifications={event.clarifications ?? []} heading="Clarification requests" />
  </section>;

  return <section className="organisation-events" aria-labelledby="organisation-events-title">
    <p className="eyebrow">Client organisation</p>
    <div className="organisation-events__heading">
      <div>
        <h2 id="organisation-events-title">Organisation events</h2>
        <p>Submitted events managed by you and other organisers in your client organisation.</p>
      </div>
    </div>
    {events?.length === 0 ? <div className="organisation-events__empty" role="status">
      <strong>No submitted events yet.</strong>
      <span>Events will appear here after an organiser submits them.</span>
    </div> : <div className="organisation-events__table-wrap">
      <table className="organisation-events__table">
        <caption className="visually-hidden">Submitted events in your client organisation</caption>
        <thead><tr><th scope="col">Event</th><th scope="col">Proposed date</th><th scope="col">Responsible organiser</th></tr></thead>
        <tbody>{events?.map(item => <tr key={item.id}>
          <td><a
            href={`/workspace/organisation-events/${item.id}`}
            onClick={click => follow(click, `/workspace/organisation-events/${item.id}`)}
          >{item.name}</a></td>
          <td>{formatDate(item.proposed_date)}</td>
          <td>{item.responsible_organiser}</td>
        </tr>)}</tbody>
      </table>
    </div>}
  </section>;
}
