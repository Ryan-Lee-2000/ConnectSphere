import { useCallback, useEffect, useState, type FormEvent } from 'react';
import type { ApiRequest } from './api';
import { responseError } from './api';

// SPL-111 (CS-E18-S1): an organiser asks to change an event they already submitted, and the
// organiser and the event's assigned coordinator can read that request. The server owns every rule
// (the owner, the allowed statuses, one Pending request at a time, the status itself). This panel
// only decides whether to *offer* the form, collects the items and shows the server's answer.

export type ChangeRequestItem = {
  id: number;
  field: string;
  field_label: string;
  current_value: unknown;
  requested_value: unknown;
  reason: string;
};

export type ChangeRequest = {
  id: number;
  status: string;
  submitted_at: string;
  items: ChangeRequestItem[];
};

// AC1 in the interface. The server refuses every other status anyway; hiding the form avoids
// offering an action that would fail.
const CHANGEABLE_STATUSES = ['under_review', 'planning', 'confirmed'];

// Must match the fields the server accepts. `kind` only picks the input and how its text is read.
const FIELDS = [
  { value: 'name', label: 'Event name', kind: 'text' },
  { value: 'purpose', label: 'Purpose', kind: 'text' },
  { value: 'description', label: 'Description', kind: 'text' },
  { value: 'proposed_date', label: 'Proposed date', kind: 'date' },
  { value: 'start_time', label: 'Start time', kind: 'time' },
  { value: 'end_time', label: 'End time', kind: 'time' },
  { value: 'expected_attendance', label: 'Expected attendance', kind: 'number' },
  { value: 'preferred_room_layout', label: 'Preferred room layout', kind: 'text' },
  { value: 'required_facilities', label: 'Required facilities', kind: 'list' },
  { value: 'accessibility_needs', label: 'Accessibility needs', kind: 'list' },
  { value: 'venue_notes', label: 'Venue notes', kind: 'text' },
] as const;
type Kind = typeof FIELDS[number]['kind'];

type Draft = { key: number; field: string; value: string; reason: string };

const LOAD_FAILURE = "We couldn't load the change requests. Try again shortly.";
const SUBMIT_FAILURE = 'Could not submit the change request. Try again.';

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not set';
  return Array.isArray(value) ? (value.length ? value.join(', ') : 'None') : String(value);
}

// Turns what was typed into the JSON value the server expects for that kind of field.
function requestedValue(kind: Kind, text: string): unknown {
  if (kind === 'number') return text.trim() === '' ? text : Number(text);
  if (kind === 'list') return text.split(/[,\n]/).map(part => part.trim()).filter(Boolean);
  return text;
}

export function ChangeRequestItems({ items }: { items: ChangeRequestItem[] }) {
  return <ul className="request-list">
    {items.map(item => <li key={item.id}>
      <div>
        <strong>{item.field_label}</strong>
        <p>Now: {show(item.current_value)}</p>
        <p>Requested: {show(item.requested_value)}</p>
        <p>Reason: {item.reason}</p>
      </div>
    </li>)}
  </ul>;
}

export function ChangeRequestsPanel({ api, eventId, eventStatus, canSubmit = false, eventName }: {
  api: ApiRequest;
  eventId: number;
  eventStatus: string;
  canSubmit?: boolean;   // the organiser who owns the event; the coordinator only reads
  eventName?: string;
}) {
  const [requests, setRequests] = useState<ChangeRequest[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [drafts, setDrafts] = useState<Draft[]>([{ key: 1, field: '', value: '', reason: '' }]);
  const [nextKey, setNextKey] = useState(2);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // The status the panel offers the form for. It starts as the one the parent knew and is re-read
  // after the server refuses a submission, so a stale status can never offer the form again.
  const [status, setStatus] = useState(eventStatus);
  // True after a refusal closed the form: the next opening keeps what the organiser typed.
  const [keepDrafts, setKeepDrafts] = useState(false);

  useEffect(() => { setStatus(eventStatus); }, [eventStatus]);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const response = await api(`/api/event-requests/${eventId}/change-requests`);
      const body = await response.json().catch(() => null);
      if (!response.ok || !Array.isArray(body?.change_requests)) { setLoadError(LOAD_FAILURE); return; }
      setRequests(body.change_requests);
    } catch { setLoadError(LOAD_FAILURE); }
  }, [api, eventId]);

  useEffect(() => { void load(); }, [load]);

  const refreshStatus = useCallback(async () => {
    try {
      const response = await api(`/api/event-requests/${eventId}`);
      const body = await response.json().catch(() => null);
      if (response.ok && typeof body?.event_request?.status === 'string') setStatus(body.event_request.status);
    } catch { /* keep the status we have; the server still refuses an ineligible submission */ }
  }, [api, eventId]);

  const pending = requests?.find(item => item.status === 'pending') ?? null;
  const canStart = canSubmit && CHANGEABLE_STATUSES.includes(status) && requests !== null && !pending;

  function update(key: number, change: Partial<Draft>) {
    setDrafts(current => current.map(draft => draft.key === key ? { ...draft, ...change } : draft));
    setFormError(null);
  }

  function addItem() {
    setDrafts(current => [...current, { key: nextKey, field: '', value: '', reason: '' }]);
    setNextKey(nextKey + 1);
  }

  function open() {
    if (!keepDrafts) {
      setDrafts([{ key: nextKey, field: '', value: '', reason: '' }]);
      setNextKey(nextKey + 1);
    }
    setKeepDrafts(false);
    setFormError(null);
    setFormOpen(true);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    // AC2 in the interface: every item needs a field, a new value and a reason. The server checks
    // the values again; this only avoids a round trip for the obvious omissions.
    // A list field may be left empty on purpose: that asks for every entry to be removed.
    const incomplete = drafts.some(draft => {
      const kind = FIELDS.find(field => field.value === draft.field)?.kind;
      return !draft.field || !draft.reason.trim() || (kind !== 'list' && !draft.value.trim());
    });
    if (incomplete) {
      setFormError('Complete every item: choose a field and give the new value and a reason.');
      return;
    }
    setSaving(true); setFormError(null);
    try {
      const response = await api(`/api/event-requests/${eventId}/change-requests`, {
        method: 'POST',
        body: JSON.stringify({
          items: drafts.map(draft => ({
            field: draft.field,
            requested_value: requestedValue(FIELDS.find(field => field.value === draft.field)!.kind, draft.value),
            reason: draft.reason,
          })),
        }),
      });
      if (!response.ok) {
        setFormError(await responseError(response, SUBMIT_FAILURE));
        // A refusal can mean the world changed (a request is now pending, or the event left an
        // allowed status). Close the form so the true state shows, keep the typed values for the
        // next opening, and render the refusal outside the form so it stays visible.
        if (response.status === 409) {
          setKeepDrafts(true);
          setFormOpen(false);
          void load();
          void refreshStatus();
        }
        return;
      }
      setKeepDrafts(false);
      setFormOpen(false);
      await load();
    } catch { setFormError(SUBMIT_FAILURE); }
    finally { setSaving(false); }
  }

  const heading = eventName ? `Change requests for ${eventName}` : 'Change requests';

  return <section className="change-requests" aria-labelledby={`change-requests-${eventId}`}>
    <h2 id={`change-requests-${eventId}`}>{heading}</h2>
    {loadError && <div role="alert">
      <p className="error">{loadError}</p>
      <button className="button button--secondary" type="button" onClick={() => { void load(); }}>Try again</button>
    </div>}
    {!loadError && requests === null && <p role="status">Loading change requests…</p>}
    {formError && !formOpen && <p className="error" role="alert">{formError}</p>}

    {!loadError && requests !== null && !formOpen && <>
      {pending ? <div role="group" aria-label="Pending change request">
        <p><strong>Pending</strong> · submitted {new Date(pending.submitted_at).toLocaleString()}</p>
        <ChangeRequestItems items={pending.items} />
        {canSubmit && <p className="notice" role="status">
          You can submit another change request once this one is resolved.
        </p>}
      </div> : <p role="status">No pending change request.</p>}
      {canStart && <button className="button button--primary" type="button" onClick={open}>
        Request a change
      </button>}
      {canSubmit && !CHANGEABLE_STATUSES.includes(status) && <p role="status">
        Change requests can be made while the event is under review, in planning or confirmed.
      </p>}
    </>}

    {formOpen && <form className="request-form" onSubmit={event => { void submit(event); }} aria-label="New change request">
      {drafts.map((draft, index) => {
        const kind = FIELDS.find(field => field.value === draft.field)?.kind;
        const inputType = kind === 'date' ? 'date' : kind === 'time' ? 'time' : kind === 'number' ? 'number' : 'text';
        return <fieldset key={draft.key} className="request-equipment">
          <legend>Item {index + 1}</legend>
          <label className="field">
            <span>Field to change</span>
            <select value={draft.field} onChange={e => update(draft.key, { field: e.target.value, value: '' })}>
              <option value="">Choose a field</option>
              {FIELDS.map(field => <option key={field.value} value={field.value}
                disabled={drafts.some(other => other.key !== draft.key && other.field === field.value)}>
                {field.label}
              </option>)}
            </select>
          </label>
          <label className="field">
            <span>New value{kind === 'list' ? ' (separate items with commas; leave empty to remove them all)' : ''}</span>
            <input type={inputType} min={kind === 'number' ? 1 : undefined} step={kind === 'number' ? 1 : undefined}
              value={draft.value} onChange={e => update(draft.key, { value: e.target.value })} />
          </label>
          <label className="field">
            <span>Reason</span>
            <textarea rows={2} maxLength={1000} value={draft.reason}
              onChange={e => update(draft.key, { reason: e.target.value })} />
          </label>
          {drafts.length > 1 && <button className="button button--secondary" type="button"
            onClick={() => setDrafts(current => current.filter(item => item.key !== draft.key))}>
            Remove item {index + 1}
          </button>}
        </fieldset>;
      })}
      {formError && <p className="error" role="alert">{formError}</p>}
      <div className="form-actions">
        <button className="button button--secondary" type="button"
          disabled={drafts.length >= FIELDS.length} onClick={addItem}>
          Add another item
        </button>
        <button className="button button--secondary" type="button" disabled={saving} onClick={() => setFormOpen(false)}>Cancel</button>
        <button className="button button--primary" type="submit" disabled={saving}>
          {saving ? 'Submitting…' : 'Submit change request'}
        </button>
      </div>
    </form>}
  </section>;
}
