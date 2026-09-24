import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { defaultRequest, type ApiRequest } from './api';

type AssignedEvent = {
  id: number;
  name: string;
  status: string;
  status_label: string;
  proposed_date: string | null;
};

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`))
    : 'Not provided';
}

export function AssignedEvents({ accessToken, eventId, onNavigate, request }: {
  accessToken: string;
  eventId?: number;
  onNavigate: (path: string) => void;
  request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [events, setEvents] = useState<AssignedEvent[] | null>(null);
  const [event, setEvent] = useState<AssignedEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);

  useEffect(() => {
    let active = true;
    setEvents(null);
    setEvent(null);
    setError(null);
    setNotice(null);
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
        setEvent(body.event);
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

  const back = <a className="organisation-events__back" href="/workspace/assigned-events"
    onClick={click => follow(click, '/workspace/assigned-events')}>Back to my assigned events</a>;

  return <section className="organisation-events" aria-labelledby="assigned-events-title">
    {eventId !== undefined && back}
    <p className="eyebrow">Event Coordinator</p>
    <h1 id="assigned-events-title">{event ? event.name : 'My assigned events'}</h1>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {!error && events === null && event === null && <p role="status">Loading assigned events…</p>}
    {event && <dl className="organisation-events__details">
      <div><dt>Status</dt><dd>{event.status_label}</dd></div>
      <div><dt>Proposed date</dt><dd>{formatDate(event.proposed_date)}</dd></div>
    </dl>}
    {event?.status === 'submitted' && <div className="organisation-events__actions">
      <button type="button" className="button button--primary" disabled={transitioning}
        onClick={() => { void beginReview(); }}>
        {transitioning ? 'Beginning review…' : 'Begin review'}
      </button>
    </div>}
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
