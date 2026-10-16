import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Eye } from 'lucide-react';
import type { ApiRequest } from './VenueCatalogue';
import { CoordinatorAssignmentQueue } from './CoordinatorAssignmentQueue';

export type SupervisedEvent = {
  id: number;
  name: string;
  purpose: string | null;
  organisation_name: string;
  proposed_date: string | null;
  start_time: string | null;
  end_time: string | null;
  expected_attendance: number | null;
  status: string;
  status_label: string;
  coordinator: { id: string; name: string } | null;
  reassignable: boolean;
  // SPL-86: who cancelled the event and why; null unless it is cancelled.
  cancelled_by?: { id: string; name: string } | null;
  cancellation_reason?: string | null;
};
type CoordinatorOption = { id: string; name: string };
type CoordinatorOptions = { coordinators: CoordinatorOption[]; unavailable_reason: string | null };

const dateFormat = new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

function authorisedRequest(token: string): ApiRequest {
  return (path, init = {}) => fetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init.headers },
  });
}

async function responseError(response: Response) {
  const body = await response.json().catch(() => ({}));
  return body.error || 'The coordinator supervision request could not be completed.';
}

function formatWhen(event: SupervisedEvent) {
  if (!event.proposed_date) return 'Not provided';
  const day = dateFormat.format(new Date(`${event.proposed_date}T00:00:00Z`));
  return event.start_time && event.end_time ? `${day}, ${event.start_time}–${event.end_time}` : day;
}

// SPL-134. The Event Coordinator Lead's organisation-wide view of every active event and every
// coordinator assignment, with reassignment. `refreshKey` reloads it after the queue assigns.
export function CoordinatorSupervision({ accessToken, request, refreshKey = 0, onChanged }: { accessToken: string; request?: ApiRequest; refreshKey?: number; onChanged?: () => void }) {
  const api = useMemo(() => request || authorisedRequest(accessToken), [request, accessToken]);
  const [events, setEvents] = useState<SupervisedEvent[]>([]);
  const [view, setView] = useState<'loading' | 'ready' | 'hidden'>('loading');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<SupervisedEvent | null>(null);

  const load = async () => {
    setError(null);
    try {
      const response = await api('/api/event-requests/supervision');
      if (response.status === 403) {
        setView('hidden');
        return;
      }
      if (response.ok) {
        const body = await response.json() as { events: SupervisedEvent[] };
        setEvents(body.events);
      } else {
        setError(await responseError(response));
      }
    } catch {
      setError('Active events could not be loaded. Check your connection and try again.');
    }
    setView('ready');
  };

  useEffect(() => {
    void load();
    // The request function is memoised on the session; reloading on every render would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, refreshKey]);

  if (view === 'hidden') return null;

  return <section className="assignment-queue" aria-labelledby="supervision-heading">
    <header className="catalogue-header">
      <div><p className="eyebrow"><Eye size={14} /> Supervision</p><h2 id="supervision-heading">Active events and coordinators</h2><p className="catalogue-subtitle">Every active submitted event across the organisation and who is responsible for it.</p></div>
    </header>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {view === 'loading' && <p role="status">Loading active events…</p>}
    {view === 'ready' && !error && events.length === 0 && <div className="catalogue-empty"><h3>No active events</h3><p>Submitted events appear here with their coordinator once they are in progress.</p></div>}
    {view === 'ready' && events.length > 0 && <div className="assignment-table">
      <table>
        <caption className="visually-hidden">Active events and their Event Coordinators</caption>
        <thead><tr><th scope="col">Event</th><th scope="col">Purpose</th><th scope="col">Client organisation</th><th scope="col">Date and time</th><th scope="col">Attendance</th><th scope="col">Status</th><th scope="col">Coordinator</th><th scope="col"><span className="visually-hidden">Action</span></th></tr></thead>
        <tbody>{events.map(event => <tr key={event.id}>
          <th scope="row">{event.name}</th>
          <td>{event.purpose || 'Not provided'}</td>
          <td>{event.organisation_name}</td>
          <td>{formatWhen(event)}</td>
          <td>{event.expected_attendance ?? 'Not provided'}</td>
          <td>{event.status_label}{event.cancelled_by && <small className="supervision__cancellation">Cancelled by {event.cancelled_by.name}{event.cancellation_reason ? `: ${event.cancellation_reason}` : ''}</small>}</td>
          <td>{event.coordinator ? event.coordinator.name : 'Awaiting assignment'}</td>
          <td>{event.reassignable && <button type="button" className="button button--secondary" aria-label={`Reassign coordinator for ${event.name}`} onClick={() => { setNotice(null); setSelected(event); }}>Reassign</button>}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {selected && <ReassignPanel
      key={selected.id}
      api={api}
      event={selected}
      onCancel={() => setSelected(null)}
      onReassigned={coordinatorName => {
        setSelected(null);
        setNotice(`${coordinatorName} is now responsible for ${selected.name}.`);
        void load();
        onChanged?.();
      }}
    />}
  </section>;
}

function ReassignPanel({ api, event, onCancel, onReassigned }: { api: ApiRequest; event: SupervisedEvent; onCancel: () => void; onReassigned: (coordinatorName: string) => void }) {
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
      const response = await api(`/api/event-requests/${event.id}/coordinator`, { method: 'PUT', body: JSON.stringify({ coordinator_account_id: choice }) });
      if (!response.ok) {
        setError(await responseError(response));
        return;
      }
      const body = await response.json() as { assignment: { coordinator: CoordinatorOption } };
      onReassigned(body.assignment.coordinator.name);
    } catch {
      setError('The reassignment could not be saved. Check your connection and try again.');
    } finally {
      setSaving(false);
    }
  };

  const canReassign = Boolean(options?.coordinators.length) && Boolean(choice) && !saving;

  return <form className="assignment-panel" onSubmit={submit} aria-labelledby="reassign-coordinator-heading">
    <div><p className="eyebrow">Reassign Event Coordinator</p><h3 id="reassign-coordinator-heading" ref={heading} tabIndex={-1}>{event.name}</h3><p className="hint">{event.coordinator?.name} stops being responsible immediately. The event keeps its status and arrangements, and the former coordinator, new coordinator and organiser are notified.</p></div>
    {error && <p className="error" role="alert">{error}</p>}
    {!options && !error && <p role="status">Loading Event Coordinators…</p>}
    {options?.unavailable_reason && <p className="error" role="alert">{options.unavailable_reason}</p>}
    {options && options.coordinators.length > 0 && <label>New Event Coordinator
      <select value={choice} onChange={changeEvent => setChoice(changeEvent.target.value)} required>
        <option value="">Select a coordinator</option>
        {options.coordinators.map(coordinator => <option key={coordinator.id} value={coordinator.id}>{coordinator.name}</option>)}
      </select>
    </label>}
    <div className="form-actions"><button type="button" className="button button--secondary" onClick={onCancel}>Cancel</button><button type="submit" className="button button--primary" disabled={!canReassign}>{saving ? 'Reassigning…' : 'Confirm reassignment'}</button></div>
  </form>;
}

// The Lead's assignments page: the unassigned queue above, supervision below. Either one changing
// an assignment reloads the other so neither shows a stale coordinator.
export function CoordinatorLeadWorkspace({ accessToken, request }: { accessToken: string; request?: ApiRequest }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = () => setRefreshKey(key => key + 1);
  return <>
    <CoordinatorAssignmentQueue accessToken={accessToken} request={request} onAssigned={refresh} />
    <CoordinatorSupervision accessToken={accessToken} request={request} refreshKey={refreshKey} />
  </>;
}
