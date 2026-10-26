import { useEffect, useState } from 'react';

type RegistrationAttendee = {
  id: number;
  name: string;
  email: string;
  contact_number: string;
  special_requirements: string | null;
};

type RegistrationList = {
  enabled: boolean;
  capacity: number | null;
  registered_count: number;
  registered: RegistrationAttendee[];
  withdrawn: RegistrationAttendee[];
};

type RegistrationRequest = (path: string, init?: RequestInit) => Promise<Response>;

function AttendeeTable({ attendees, caption }: { attendees: RegistrationAttendee[]; caption: string }) {
  return <div className="organisation-events__table-wrap"><table className="organisation-events__table registration-attendees__table">
    <caption className="visually-hidden">{caption}</caption>
    <thead><tr>
      <th scope="col">Attendee</th>
      <th scope="col">Email</th>
      <th scope="col">Contact number</th>
      <th scope="col">Special requirements</th>
    </tr></thead>
    <tbody>{attendees.map(attendee => <tr key={attendee.id}>
      <td>{attendee.name}</td>
      <td><a href={`mailto:${attendee.email}`}>{attendee.email}</a></td>
      <td>{attendee.contact_number}</td>
      <td>{attendee.special_requirements || 'None recorded'}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function RegistrationAttendees({
  accessToken,
  eventId,
  endpoint,
  request,
}: {
  accessToken: string;
  eventId: number;
  endpoint?: string;
  request?: RegistrationRequest;
}) {
  const [registrationList, setRegistrationList] = useState<RegistrationList | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    const api = request || ((path: string, init: RequestInit = {}) => fetch(path, {
      ...init,
      headers: { Authorization: `Bearer ${accessToken}`, ...init.headers },
    }));
    setRegistrationList(null);
    setError(false);

    async function load() {
      try {
        const response = await api(endpoint ?? `/api/organisation/events/${eventId}/registrations`);
        const body = await response.json().catch(() => null);
        if (!active) return;
        if (!response.ok || !body?.registration_list) {
          setError(true);
          return;
        }
        setRegistrationList(body.registration_list);
      } catch {
        if (active) setError(true);
      }
    }

    void load();
    return () => { active = false; };
  }, [accessToken, attempt, endpoint, eventId, request]);

  return <section className="registration-attendees" aria-labelledby="registration-attendees-title">
    <div className="registration-attendees__heading">
      <div>
        <p className="eyebrow">Expected turnout</p>
        <h3 id="registration-attendees-title">Registered attendees</h3>
      </div>
      {registrationList?.enabled && <p aria-label={`${registrationList.registered_count} of ${registrationList.capacity} places registered`}>
        <strong>{registrationList.registered_count}/{registrationList.capacity}</strong>
        <span>registered / capacity</span>
      </p>}
    </div>

    {error && <div className="registration-attendees__error">
      <p className="error" role="alert">We couldn't load this event's registrations. Try again.</p>
      <button className="button button--secondary" onClick={() => setAttempt(value => value + 1)} type="button">Retry</button>
    </div>}
    {!error && registrationList === null && <p aria-live="polite" role="status">Loading registrations…</p>}
    {registrationList && !registrationList.enabled && <p className="organisation-arrangements__empty">Registration is not enabled for this event.</p>}
    {registrationList?.enabled && <>
      <section className="registration-attendees__group" aria-labelledby="active-registrations-title">
        <h4 id="active-registrations-title">Current registrations</h4>
        {registrationList.registered.length === 0
          ? <p className="organisation-arrangements__empty">No attendees are currently registered.</p>
          : <AttendeeTable attendees={registrationList.registered} caption="Currently registered attendees" />}
      </section>
      <section className="registration-attendees__group" aria-labelledby="withdrawn-registrations-title">
        <h4 id="withdrawn-registrations-title">Withdrawn registrations</h4>
        {registrationList.withdrawn.length === 0
          ? <p className="organisation-arrangements__empty">No withdrawn registrations.</p>
          : <AttendeeTable attendees={registrationList.withdrawn} caption="Withdrawn attendee registrations" />}
      </section>
    </>}
  </section>;
}
