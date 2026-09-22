import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ClipboardList, UserCheck } from 'lucide-react';
import type { ApiRequest } from './VenueCatalogue';

export type QueueEvent = {
  id: number;
  name: string;
  organisation_id: number;
  organisation_name: string;
  proposed_date: string | null;
  submitted_at: string | null;
};
type CoordinatorOption = { id: string; name: string };
type CoordinatorOptions = { coordinators: CoordinatorOption[]; unavailable_reason: string | null };

const dateFormat = new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const timestampFormat = new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' });

function authorisedRequest(token: string): ApiRequest {
  return (path, init = {}) => fetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init.headers },
  });
}

async function responseError(response: Response) {
  const body = await response.json().catch(() => ({}));
  return body.error || 'The coordinator assignment request could not be completed.';
}

function formatDate(value: string | null) {
  // Proposed dates are calendar dates, so they must not shift with the viewer's time zone.
  return value ? dateFormat.format(new Date(`${value}T00:00:00Z`)) : 'Not provided';
}

export function CoordinatorAssignmentQueue({ accessToken, request }: { accessToken: string; request?: ApiRequest }) {
  const api = useMemo(() => request || authorisedRequest(accessToken), [request, accessToken]);
  const [events, setEvents] = useState<QueueEvent[]>([]);
  const [count, setCount] = useState(0);
  const [view, setView] = useState<'loading' | 'ready' | 'hidden'>('loading');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<QueueEvent | null>(null);

  const loadQueue = async () => {
    setError(null);
    try {
      const response = await api('/api/event-requests/awaiting-assignment');
      // Only Event Operations Managers work this queue; other roles never see the section.
      if (response.status === 403) {
        setView('hidden');
        return;
      }
      if (response.ok) {
        const body = await response.json() as { events: QueueEvent[]; count: number };
        setEvents(body.events);
        setCount(body.count);
      } else {
        setError(await responseError(response));
      }
    } catch {
      setError('The assignment queue could not be loaded. Check your connection and try again.');
    }
    setView('ready');
  };

  useEffect(() => {
    void loadQueue();
    // The request function is memoised on the session; reloading on every render would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  if (view === 'hidden') return null;

  return <section className="assignment-queue" aria-labelledby="assignment-queue-heading">
    <header className="catalogue-header">
      <div><p className="eyebrow"><ClipboardList size={14} /> Coordinator assignment</p><h2 id="assignment-queue-heading">Events awaiting a coordinator</h2><p className="catalogue-subtitle">Submitted events with no Event Coordinator, oldest submission first.</p></div>
    </header>
    {view === 'ready' && !error && <div className="catalogue-intro"><p>{count} {count === 1 ? 'event' : 'events'} awaiting assignment</p></div>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {view === 'loading' && <p role="status">Loading events awaiting assignment…</p>}
    {view === 'ready' && !error && events.length === 0 && <div className="catalogue-empty"><UserCheck size={28} /><h3>No events are awaiting assignment</h3><p>Newly submitted events appear here until an Event Coordinator is assigned.</p></div>}
    {view === 'ready' && events.length > 0 && <div className="assignment-table">
      <table>
        <caption className="visually-hidden">Submitted events awaiting an Event Coordinator</caption>
        <thead><tr><th scope="col">Event</th><th scope="col">Client organisation</th><th scope="col">Proposed date</th><th scope="col">Submitted</th><th scope="col"><span className="visually-hidden">Action</span></th></tr></thead>
        <tbody>{events.map(event => <tr key={event.id}>
          <th scope="row">{event.name}</th>
          <td>{event.organisation_name}</td>
          <td>{formatDate(event.proposed_date)}</td>
          <td>{event.submitted_at ? timestampFormat.format(new Date(event.submitted_at)) : 'Not recorded yet'}</td>
          <td><button type="button" className="button button--secondary" aria-label={`Assign coordinator to ${event.name}`} onClick={() => { setNotice(null); setSelected(event); }}>Assign coordinator</button></td>
        </tr>)}</tbody>
      </table>
    </div>}
    {selected && <AssignCoordinatorPanel
      key={selected.id}
      api={api}
      event={selected}
      onCancel={() => setSelected(null)}
      onAssigned={coordinatorName => {
        setSelected(null);
        setNotice(`${coordinatorName} is now responsible for ${selected.name}.`);
        void loadQueue();
      }}
    />}
  </section>;
}

function AssignCoordinatorPanel({ api, event, onCancel, onAssigned }: { api: ApiRequest; event: QueueEvent; onCancel: () => void; onAssigned: (coordinatorName: string) => void }) {
  const [options, setOptions] = useState<CoordinatorOptions | null>(null);
  const [choice, setChoice] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => { heading.current?.focus(); }, []);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await api(`/api/event-requests/${event.id}/coordinator-options`);
        if (!response.ok) {
          const message = await responseError(response);
          if (active) setError(message);
          return;
        }
        const body = await response.json() as CoordinatorOptions;
        if (active) setOptions(body);
      } catch {
        if (active) setError('Event Coordinators could not be loaded. Check your connection and try again.');
      }
    })();
    return () => { active = false; };
  }, [api, event.id]);

  const submit = async (formEvent: FormEvent) => {
    formEvent.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/coordinator`, { method: 'POST', body: JSON.stringify({ coordinator_account_id: choice }) });
      if (!response.ok) {
        setError(await responseError(response));
        return;
      }
      const body = await response.json() as { assignment: { coordinator: CoordinatorOption } };
      onAssigned(body.assignment.coordinator.name);
    } catch {
      setError('The assignment could not be saved. Check your connection and try again.');
    } finally {
      setSaving(false);
    }
  };

  const canAssign = Boolean(options?.coordinators.length) && Boolean(choice) && !saving;

  return <form className="assignment-panel" onSubmit={submit} aria-labelledby="assign-coordinator-heading">
    <div><p className="eyebrow">Assign Event Coordinator</p><h3 id="assign-coordinator-heading" ref={heading} tabIndex={-1}>{event.name}</h3><p className="hint">The coordinator becomes responsible immediately, with no acceptance step, and the event moves to Under Review.</p></div>
    {error && <p className="error" role="alert">{error}</p>}
    {!options && !error && <p role="status">Loading Event Coordinators…</p>}
    {options?.unavailable_reason && <p className="error" role="alert">{options.unavailable_reason}</p>}
    {options && options.coordinators.length > 0 && <label>Event Coordinator
      <select value={choice} onChange={changeEvent => setChoice(changeEvent.target.value)} required>
        <option value="">Select a coordinator</option>
        {options.coordinators.map(coordinator => <option key={coordinator.id} value={coordinator.id}>{coordinator.name}</option>)}
      </select>
    </label>}
    <div className="form-actions"><button type="button" className="button button--secondary" onClick={onCancel}>Cancel</button><button type="submit" className="button button--primary" disabled={!canAssign}>{saving ? 'Assigning…' : 'Confirm assignment'}</button></div>
  </form>;
}
