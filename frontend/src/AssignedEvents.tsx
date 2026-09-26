import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';
import { defaultRequest, type ApiRequest } from './api';
import { ClarificationHistory, type Clarification } from './ClarificationHistory';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
import { slotLabel } from './slots';

type AssignedEvent = {
  id: number;
  name: string;
  status: string;
  status_label: string;
  proposed_date: string | null;
  mapped_slots: string[];
  expected_attendance?: number | null;
  preferred_room_layout?: string | null;
  required_facilities?: string[];
  accessibility_needs?: string[];
  location_preference?: string | null;
};

type EquipmentLine = { equipment_type: string; quantity: number; notes: string | null };

// Begin review answers with the summary shape only, so the full detail fields are optional here.
type AssignedEventDetail = AssignedEvent & Partial<{
  purpose: string | null;
  description: string | null;
  start_time: string | null;
  end_time: string | null;
  expected_attendance: number | null;
  venue_name: string | null;
  preferred_room_layout: string | null;
  required_facilities: string[];
  facilities_notes: string | null;
  accessibility_needs: string[];
  location_preference: string | null;
  venue_notes: string | null;
  equipment_requirements: EquipmentLine[];
  registration_required: boolean;
  registration_notes: string | null;
  client_organisation: string;
  responsible_organiser: string;
  submitted_at: string | null;
  clarifications: Clarification[];
}>;

const NOT_PROVIDED = 'Not provided';

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`))
    : NOT_PROVIDED;
}

function formatText(value: string | number | null | undefined) {
  return value === null || value === undefined || value === '' ? NOT_PROVIDED : String(value);
}

function formatList(values: string[] | undefined) {
  return values && values.length > 0 ? values.join(', ') : NOT_PROVIDED;
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) return NOT_PROVIDED;
  return new Intl.DateTimeFormat('en-SG', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Singapore' }).format(new Date(value));
}

function formatEquipment(lines: EquipmentLine[] | undefined) {
  if (!lines || lines.length === 0) return NOT_PROVIDED;
  return <ul className="organisation-events__list">{lines.map((line, index) => <li key={index}>
    {line.equipment_type} × {line.quantity}{line.notes ? ` (${line.notes})` : ''}
  </li>)}</ul>;
}

function detailRows(event: AssignedEventDetail): [string, string, [string, ReactNode][]][] {
  const time = event.start_time && event.end_time ? `${event.start_time}–${event.end_time}` : NOT_PROVIDED;
  return [
    ['core', 'Core details', [
      ['Status', event.status_label],
      ['Purpose', formatText(event.purpose)],
      ['Description', formatText(event.description)],
      ['Proposed date', formatDate(event.proposed_date)],
      ['Time', time],
      ['Expected attendance', formatText(event.expected_attendance)],
    ]],
    ['venue', 'Venue requirements', [
      ['Venue', formatText(event.venue_name)],
      ['Preferred room layout', formatText(event.preferred_room_layout)],
      ['Required facilities', formatList(event.required_facilities)],
      ['Facilities notes', formatText(event.facilities_notes)],
      ['Accessibility needs', formatList(event.accessibility_needs)],
      ['Location preference', formatText(event.location_preference)],
      ['Venue notes', formatText(event.venue_notes)],
    ]],
    ['equipment', 'Equipment requirements', [
      ['Equipment', formatEquipment(event.equipment_requirements)],
    ]],
    ['registration', 'Registration needs', [
      ['Registration required', event.registration_required === undefined ? NOT_PROVIDED : event.registration_required ? 'Yes' : 'No'],
      ['Registration notes', formatText(event.registration_notes)],
    ]],
    ['organisation', 'Organisation and submission', [
      ['Client organisation', formatText(event.client_organisation)],
      ['Responsible Event Organiser', formatText(event.responsible_organiser)],
      ['Submission date and time', formatTimestamp(event.submitted_at)],
    ]],
  ];
}

function labelLayout(value: string | null | undefined) {
  return value ? value.replace(/\b\w/g, character => character.toUpperCase()) : 'No preference recorded';
}

function listValue(values: string[] | undefined) {
  return values?.length ? values.join(', ') : 'No preference recorded';
}

function EventBrief({ event }: { event: AssignedEvent }) {
  const slots = event.mapped_slots.length
    ? event.mapped_slots.map(slot => slotLabel(slot).split(' · ')[0]).join(', ')
    : 'No slots recorded';
  return <section className="event-brief" aria-labelledby="event-brief-title">
    <header className="event-brief__header"><div><p className="eyebrow">Assigned event</p><h2 id="event-brief-title">Requirements to consider</h2></div><span className="event-brief__status">{event.status_label}</span></header>
    <dl className="event-brief__overview">
      <div><dt>Event date</dt><dd>{formatDate(event.proposed_date)}</dd></div>
      <div><dt>Required slots</dt><dd>{slots}</dd></div>
      <div><dt>Expected attendance</dt><dd>{event.expected_attendance ?? 'Not recorded'}</dd></div>
    </dl>
    <dl className="event-brief__requirements">
      <div><dt>Room layout</dt><dd>{labelLayout(event.preferred_room_layout)}</dd></div>
      <div><dt>Required facilities</dt><dd>{listValue(event.required_facilities)}</dd></div>
      <div><dt>Accessibility needs</dt><dd>{listValue(event.accessibility_needs)}</dd></div>
      <div><dt>Location preference</dt><dd>{event.location_preference || 'No preference recorded'}</dd></div>
    </dl>
  </section>;
}

export function AssignedEvents({ accessToken, eventId, onNavigate, request, view = 'detail' }: {
  accessToken: string;
  eventId?: number;
  onNavigate: (path: string) => void;
  request?: ApiRequest;
  view?: 'detail' | 'venue-search';
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [events, setEvents] = useState<AssignedEvent[] | null>(null);
  const [event, setEvent] = useState<AssignedEventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);
  const [clarification, setClarification] = useState('');

  useEffect(() => {
    let active = true;
    setEvents(null);
    setEvent(null);
    setError(null);
    setNotice(null);
    setClarification('');
    void (async () => {
      try {
        const response = await api(eventId === undefined
          ? '/api/event-requests/assigned'
          : `/api/event-requests/assigned/${eventId}`);
        const body = await response.json().catch(() => null);
        if (!active) return;
        if (!response.ok) {
          setError(eventId === undefined ? 'Could not load your assigned events. Try again.' : 'This assigned event is unavailable.');
        } else if (eventId === undefined && Array.isArray(body?.events)) {
          setEvents(body.events);
        } else if (eventId !== undefined && body?.event) {
          setEvent(body.event);
        } else {
          setError('Could not load your assigned events. Try again.');
        }
      } catch {
        if (active) setError('Could not load your assigned events. Try again.');
      }
    })();
    return () => { active = false; };
  }, [api, eventId]);

  function follow(click: MouseEvent<HTMLAnchorElement>, path: string) {
    click.preventDefault();
    onNavigate(path);
  }

  async function beginReview() {
    if (!event || event.status !== 'submitted' || transitioning) return;
    setTransitioning(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/begin-review`, { method: 'POST' });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setError(body?.error || 'Could not begin review. Try again.');
      } else if (body?.event) {
        setEvent(current => ({ ...current, ...body.event }));
        setNotice('Review started.');
      } else {
        setError('Could not begin review. Try again.');
      }
    } catch {
      setError('Could not begin review. Try again.');
    } finally {
      setTransitioning(false);
    }
  }

  async function requestClarification() {
    if (!event || event.status !== 'under_review' || transitioning) return;
    if (!clarification.trim()) {
      setError('Enter a clarification message.');
      return;
    }
    setTransitioning(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/request-clarification`, {
        method: 'POST',
        body: JSON.stringify({ message: clarification }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setError(body?.error || 'Could not request clarification. Try again.');
      } else if (body?.event) {
        setEvent(current => ({ ...current, ...body.event, clarifications: body.clarifications ?? current?.clarifications }));
        setClarification('');
        setNotice('Clarification requested. The event is returned to the Event Organiser.');
      } else {
        setError('Could not request clarification. Try again.');
      }
    } catch {
      setError('Could not request clarification. Try again.');
    } finally {
      setTransitioning(false);
    }
  }

  const back = <a className="organisation-events__back" href="/workspace/assigned-events"
    onClick={click => follow(click, '/workspace/assigned-events')}>Back to my assigned events</a>;

  if (view === 'venue-search') {
    return <section className="organisation-events venue-search-page" aria-labelledby="venue-search-title">
      {back}
      <p className="eyebrow">Event Coordinator · Venue planning</p>
      <h1 id="venue-search-title">Find available venues</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {!error && !event && <p role="status">Loading the assigned event…</p>}
      {event && <>
        <p className="venue-search-page__event-name">Searching for <strong>{event.name}</strong></p>
        <EventBrief event={event} />
        <VenueAvailabilitySearch accessToken={accessToken} eventId={event.id}
          initialDate={event.proposed_date} initialSlots={event.mapped_slots} request={api} />
      </>}
    </section>;
  }

  return <section className={`organisation-events${eventId !== undefined ? ' organisation-events--detail' : ''}`} aria-labelledby="assigned-events-title">
    {eventId !== undefined && back}
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {!error && events === null && event === null && <p role="status">Loading assigned events…</p>}
    {!event && <><p className="eyebrow">Event Coordinator</p><h1 id="assigned-events-title">My assigned events</h1></>}
    {event && <article className="organisation-events__detail-shell">
      <header className="organisation-events__detail-header">
        <p className="eyebrow">Event Coordinator</p>
        <h1 id="assigned-events-title">{event.name}</h1>
      </header>
      <EventBrief event={event} />
      <div className="organisation-events__table-wrap">
        <table className="organisation-events__table organisation-events__detail-table">
          <caption className="visually-hidden">Submitted request details for {event.name}</caption>
          {detailRows(event).map(([key, heading, rows]) => <tbody key={key}>
            <tr><th scope="colgroup" colSpan={2}>{heading}</th></tr>
            {rows.map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td>{value}</td></tr>)}
          </tbody>)}
        </table>
      </div>
      {event.status === 'submitted' && <div className="organisation-events__actions">
        <button type="button" className="button button--primary" disabled={transitioning}
          onClick={() => { void beginReview(); }}>
          {transitioning ? 'Beginning review…' : 'Begin review'}
        </button>
      </div>}
      {event.status === 'under_review' && <form className="request-form clarification-form"
        onSubmit={submit => { submit.preventDefault(); void requestClarification(); }}>
        <div className="field">
          <label htmlFor="clarification-message">Clarification for the Event Organiser</label>
          <textarea id="clarification-message" rows={4} maxLength={2000} value={clarification}
            onChange={change => setClarification(change.target.value)} />
        </div>
        <div className="organisation-events__actions">
          <button type="submit" className="button button--primary" disabled={transitioning}>
            {transitioning ? 'Requesting clarification…' : 'Request clarification'}
          </button>
        </div>
      </form>}
      {event.clarifications && <ClarificationHistory clarifications={event.clarifications} heading="Clarification history" />}
      <div className="organisation-events__actions organisation-events__actions--planning">
        <div><span className="organisation-events__planning-label">Next step</span><strong>Find a venue</strong><span>Search availability without changing this event or creating a booking.</span></div>
        <button type="button" className="button button--primary"
          onClick={() => onNavigate(`/workspace/assigned-events/${event.id}/venue-search`)}>
          Find venues
        </button>
      </div>
    </article>}
    {events?.length === 0 && <div className="organisation-events__empty" role="status">
      <strong>No events assigned to you yet.</strong>
      <span>Events appear here when an Event Operations Manager assigns them to you.</span>
    </div>}
    {events && events.length > 0 && <div className="organisation-events__table-wrap">
      <table className="organisation-events__table">
        <caption className="visually-hidden">Events currently assigned to you</caption>
        <thead><tr><th scope="col">Event</th><th scope="col">Status</th><th scope="col">Proposed date</th></tr></thead>
        <tbody>{events.map(item => <tr key={item.id}>
          <td><a href={`/workspace/assigned-events/${item.id}`}
            onClick={click => follow(click, `/workspace/assigned-events/${item.id}`)}>{item.name}</a></td>
          <td>{item.status_label}</td>
          <td>{formatDate(item.proposed_date)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
  </section>;
}
