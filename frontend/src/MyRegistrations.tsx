import { useEffect, useMemo, useState } from 'react';
import { defaultRequest, type ApiRequest } from './api';
import { WithdrawRegistration, type WithdrawalResult } from './WithdrawRegistration';

// SPL-117 (CS-E19-S4): the attendee's own registrations, Registered and Withdrawn, soonest event
// first (AC1), with each event as it stands now (AC2) and a warning when it is no longer Confirmed
// (AC3). "Details" opens one registration from the server (AC4). The server decides which rows are
// the attendee's own (AC5); this page only shows them. SPL-118's withdraw control sits on each one.

export type MyRegistration = {
  registration: {
    id: number; status: string; name: string; email: string; contact_number: string;
    special_requirements: string | null; registered_at: string; withdrawn_at: string | null;
  };
  event: {
    id: number; name: string; description: string | null; date: string; start_time: string; end_time: string;
    venues: string[]; places_remaining: number; status: string; status_label: string;
  };
};

const LOAD_FAILED = 'Could not load your registrations. Try again.';

// The event date is a calendar date, so it is formatted in UTC to avoid shifting a day by time zone.
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));
const placesText = (places: number) => `${places} ${places === 1 ? 'place' : 'places'} remaining`;

export function MyRegistrations({ accessToken, request, now }: {
  accessToken: string;
  request?: ApiRequest;
  now?: () => Date;   // passed to the withdraw control, so tests can fix the time
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [entries, setEntries] = useState<MyRegistration[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The registration whose details are open, as the server returned it when opened (AC4).
  const [opened, setOpened] = useState<MyRegistration | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;   // ignore a reply that arrives after the page has been left
    void (async () => {
      try {
        const response = await api('/api/my-registrations');
        if (!response?.ok) throw new Error('load failed');
        const body = await response.json() as { registrations?: MyRegistration[] };
        if (active) setEntries(body.registrations ?? []);
      } catch { if (active) setError(LOAD_FAILED); }
    })();
    return () => { active = false; };
  }, [api]);

  async function open(entry: MyRegistration) {
    if (opened?.registration.id === entry.registration.id) { setOpened(null); return; }   // second click closes it
    setOpenError(null);
    try {
      const response = await api(`/api/my-registrations/${entry.registration.id}`);
      if (!response?.ok) throw new Error('open failed');
      setOpened(await response.json() as MyRegistration);
    } catch { setOpenError('Could not open this registration. Try again.'); }
  }

  // After SPL-118's withdrawal succeeds, show the new status from the server's own answer.
  function withdrawn(result: WithdrawalResult) {
    setEntries(current => current?.map(entry => entry.registration.id === result.registration.id
      ? { ...entry, registration: { ...entry.registration, status: result.registration.status,
        withdrawn_at: result.registration.withdrawn_at } }
      : entry) ?? null);
    setOpened(null);
  }

  return <section className="organisation-events my-registrations" aria-labelledby="my-registrations-title">
    <p className="eyebrow">Attendee</p>
    <h1 id="my-registrations-title">My registrations</h1>
    {error && <p className="error" role="alert">{error}</p>}
    {!entries && !error && <p role="status">Loading your registrations…</p>}
    {entries?.length === 0 && <p className="my-registrations__empty">You have not registered for any events yet.</p>}
    {entries && entries.length > 0 && <ul className="request-list my-registrations__list" aria-label="My registrations">
      {entries.map(entry => {
        const { event, registration } = entry;
        const isOpen = opened?.registration.id === registration.id;
        return <li key={registration.id} className="my-registrations__item">
          <div className="my-registrations__details">
            <h2>{event.name}</h2>
            <p>{dateName(event.date)} · {event.start_time}–{event.end_time} · {event.venues.join(', ')}</p>
          </div>
          <div className="request-list__actions">
            <span className={`venue-suitability__badge${registration.status === 'registered' ? ' venue-suitability__badge--pass' : ''}`}>
              {registration.status === 'registered' ? 'Registered' : 'Withdrawn'}
            </span>
            {/* AC3: a Confirmed event needs no badge; anything else is worth knowing about. */}
            {event.status !== 'confirmed' && <span className="venue-suitability__badge venue-suitability__badge--fail">
              Event {event.status_label.toLowerCase()}
            </span>}
            <button type="button" className="button button--secondary" aria-expanded={isOpen}
              aria-label={`Details for ${event.name}`} onClick={() => { void open(entry); }}>Details</button>
          </div>
          {isOpen && opened && <div className="my-registrations__panel" role="region"
            aria-label={`Registration details for ${event.name}`}>
            {opened.event.description && <p>{opened.event.description}</p>}
            <p>{placesText(opened.event.places_remaining)}</p>
            <p>{opened.registration.name} · {opened.registration.email} · {opened.registration.contact_number}</p>
            {opened.registration.special_requirements && <p>Special requirements: {opened.registration.special_requirements}</p>}
          </div>}
          {/* SPL-118: offered only while Registered and before the event starts. */}
          <div className="my-registrations__panel">
            <WithdrawRegistration api={api} registration={registration} event={event} now={now} onWithdrawn={withdrawn} />
          </div>
        </li>;
      })}
    </ul>}
    {openError && <p className="error" role="alert">{openError}</p>}
  </section>;
}
