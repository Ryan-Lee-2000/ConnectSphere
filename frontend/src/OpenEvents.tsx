import { useEffect, useMemo, useState } from 'react';
import { defaultRequest, type ApiRequest } from './api';
import { RegisterForEvent, type RegistrationConfirmation } from './RegisterForEvent';

// SPL-115 (CS-E19-S2): the attendee's entry point. Lists every event open for registration right
// now, earliest first, with its public details, the places left and a Registered badge (AC1-AC4).
// The server decides which events are open and which fields an attendee may see; this page only
// shows its answer. It is also where SPL-116's registration form is reached: "Register for …"
// opens that form under the event.

export type OpenEvent = {
  id: number; name: string; description: string | null; date: string; start_time: string; end_time: string;
  venues: string[]; places_remaining: number; registered: boolean;
};

const LOAD_FAILED = 'Could not load the events open for registration. Try again.';

// The event date is a calendar date, so it is formatted in UTC to avoid shifting a day by time zone.
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));

// AC2: places remaining in plain words. A full event stays listed (the working interpretation,
// pending the PO) but says it is full instead of offering to register.
const placesText = (places: number) => places === 0
  ? 'Full · no places remaining'
  : `${places} ${places === 1 ? 'place' : 'places'} remaining`;

export function OpenEvents({ accessToken, request }: { accessToken: string; request?: ApiRequest }) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [events, setEvents] = useState<OpenEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The event whose registration form is open, if any. Only one form is open at a time.
  const [registeringFor, setRegisteringFor] = useState<number | null>(null);

  useEffect(() => {
    let active = true;   // ignore a reply that arrives after the page has been left
    void (async () => {
      try {
        const response = await api('/api/open-events');
        if (!response?.ok) throw new Error('load failed');
        const body = await response.json() as { events?: OpenEvent[] };
        if (active) setEvents(body.events ?? []);
      } catch { if (active) setError(LOAD_FAILED); }
    })();
    return () => { active = false; };
  }, [api]);

  // AC4 after registering: update the entry from the server's own confirmation (its places
  // remaining already counts this registration), rather than guessing on the client.
  function registered(confirmation: RegistrationConfirmation) {
    setEvents(current => current?.map(event => event.id === confirmation.event.id
      ? { ...event, registered: true, places_remaining: confirmation.event.places_remaining }
      : event) ?? null);
  }

  return <section className="organisation-events open-events" aria-labelledby="open-events-title">
    <p className="eyebrow">Attendee</p>
    <h1 id="open-events-title">Events open for registration</h1>
    {error && <p className="error" role="alert">{error}</p>}
    {!events && !error && <p role="status">Loading events…</p>}
    {events?.length === 0 && <p className="open-events__empty">No events are open for registration right now.</p>}
    {events && events.length > 0 && <ul className="request-list open-events__list" aria-label="Events open for registration">
      {events.map(event => {
        // Registering is offered only while there is a place and the attendee does not hold one.
        const canRegister = !event.registered && event.places_remaining > 0;
        return <li key={event.id} className="open-events__item">
          <div className="open-events__details">
            <h2>{event.name}</h2>
            <p>{dateName(event.date)} · {event.start_time}–{event.end_time}</p>
            <p>{event.venues.join(', ')}</p>
            {event.description && <p>{event.description}</p>}
            <p className="open-events__places">{placesText(event.places_remaining)}</p>
          </div>
          <div className="request-list__actions">
            {event.registered && <span className="venue-suitability__badge venue-suitability__badge--pass">Registered</span>}
            {canRegister && registeringFor !== event.id && <button type="button" className="button button--secondary"
              aria-label={`Register for ${event.name}`} onClick={() => setRegisteringFor(event.id)}>Register</button>}
          </div>
          {/* SPL-116's form. It stays open after success so its confirmation (AC7) remains visible. */}
          {registeringFor === event.id && <div className="open-events__form">
            <RegisterForEvent api={api} event={event} onRegistered={registered} />
          </div>}
        </li>;
      })}
    </ul>}
  </section>;
}
