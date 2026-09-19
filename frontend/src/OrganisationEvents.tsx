import { useEffect, useState, type MouseEvent } from 'react';

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
};

type OrganisationEventRequest = (path: string, init?: RequestInit) => Promise<Response>;

function formatDate(value: string) {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
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
        else if (eventId !== undefined && body?.event) setEvent(body.event);
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
      <div><dt>Purpose</dt><dd>{event.purpose}</dd></div>
      <div><dt>Description</dt><dd>{event.description || 'No description provided.'}</dd></div>
      <div><dt>Proposed date</dt><dd>{formatDate(event.proposed_date)}</dd></div>
      <div><dt>Time</dt><dd>{event.start_time} to {event.end_time}</dd></div>
      <div><dt>Expected attendance</dt><dd>{event.expected_attendance}</dd></div>
    </dl>
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
