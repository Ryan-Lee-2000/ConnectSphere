import { useState } from 'react';
import { responseError, type ApiRequest } from './api';

type EventValues = {
  id: number; status: string; proposed_date: string | null;
  start_time?: string | null; end_time?: string | null; expected_attendance?: number | null;
  preferred_room_layout?: string | null; required_facilities?: string[];
  accessibility_needs?: string[]; location_preference?: string | null;
};
export type ChangePreview = {
  preview_token: string;
  changes: Record<string, { previous: unknown; new: unknown }>;
  arrangements: { kind: string; id: number; name: string; reason: string }[];
  returns_to_planning: boolean;
};

export function SignificantEventChanges<T extends EventValues>({ event, api, onSaved }: {
  event: T; api: ApiRequest; onSaved: (event: T) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => initialDraft(event));
  const [preview, setPreview] = useState<ChangePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const endpoint = `/api/event-requests/assigned/${event.id}/significant-changes`;
  const update = (key: keyof typeof draft, value: string) => {
    setDraft(current => ({ ...current, [key]: value })); setPreview(null); setError(null);
  };
  const values = () => ({ ...draft, expected_attendance: Number(draft.expected_attendance),
    required_facilities: split(draft.required_facilities), accessibility_needs: split(draft.accessibility_needs) });
  async function submit() {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const response = await api(preview ? endpoint : `${endpoint}/preview`, {
        method: preview ? 'PATCH' : 'POST',
        body: JSON.stringify({ values: values(), ...(preview ? { preview_token: preview.preview_token } : {}) }),
      });
      if (!response.ok) {
        setError(await responseError(response, 'Could not save these changes. Try again.'));
        setPreview(null); return;
      }
      const body = await response.json();
      if (preview) {
        onSaved(body.event); setEditing(false); setPreview(null);
        setNotice(body.change ? 'Event requirements saved. Affected arrangements are marked for review.' : 'No changes to save.');
      } else if (Object.keys(body.changes).length === 0) {
        onSaved(body.event); setNotice('No changes to save.'); setEditing(false);
      } else { setPreview(body); }
    } catch { setError('Could not save these changes. Try again.'); setPreview(null); }
    finally { setBusy(false); }
  }
  return <section className="event-information-editor" aria-label="Significant event changes">
    {notice && <p role="status">{notice}</p>}
    {!editing ? <button type="button" className="button button--secondary" onClick={() => {
      setDraft(initialDraft(event)); setEditing(true); setPreview(null); setError(null); setNotice(null);
    }}>Edit event requirements</button> : <form className="request-form" onSubmit={submitEvent => { submitEvent.preventDefault(); void submit(); }}>
      <h2>Edit event requirements</h2>
      <p>Review the effect on existing arrangements before saving. Each venue keeps its own allocation, layout and facilities.</p>
      <fieldset disabled={busy || Boolean(preview)}>
        <legend>Event requirements</legend>
        <div className="event-information-editor__contacts">
          {([['proposed_date', 'Date', 'date'], ['start_time', 'Start time', 'time'], ['end_time', 'End time', 'time'],
            ['expected_attendance', 'Expected attendance', 'number']] as const).map(([key, label, type]) => <div className="field" key={key}>
            <label htmlFor={`significant-${key}`}>{label}</label>
            <input id={`significant-${key}`} type={type} required min={type === 'number' ? 1 : undefined}
              step={type === 'number' ? 1 : undefined} value={draft[key]} onChange={e => update(key, e.target.value)} />
          </div>)}
        </div>
        {([['preferred_room_layout', 'Preferred room layout'], ['required_facilities', 'Required facilities (comma-separated)'],
          ['accessibility_needs', 'Accessibility needs (comma-separated)'], ['location_preference', 'Location preference']] as const).map(([key, label]) => <div className="field" key={key}>
          <label htmlFor={`significant-${key}`}>{label}</label>
          <input id={`significant-${key}`} maxLength={2000} value={draft[key]} onChange={e => update(key, e.target.value)} />
        </div>)}
      </fieldset>
      {preview && <div role="region" aria-label="Review significant changes" className="equipment-requirements__release-warning">
        <h3>Review before saving</h3>
        {preview.arrangements.length ? <ul>{preview.arrangements.map(item => <li key={`${item.kind}-${item.id}`}>
          <strong>{item.name} ({item.kind} #{item.id})</strong>: {item.reason}
        </li>)}</ul> : <p>No existing arrangement requires review for these changes.</p>}
        {preview.returns_to_planning && <p><strong>This event will return from {event.status === 'preparing' ? 'Preparing' : 'Confirmed'} to Planning.</strong></p>}
        <p>Cancel saves nothing.</p>
      </div>}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="organisation-events__actions">
        <button type="button" className="button button--secondary" disabled={busy} onClick={() => { setEditing(false); setPreview(null); setError(null); }}>Cancel</button>
        {preview && <button type="button" className="button button--secondary" disabled={busy} onClick={() => setPreview(null)}>Back to editing</button>}
        <button type="submit" className="button button--primary" disabled={busy}>{busy ? 'Working…' : preview ? 'Confirm and save changes' : 'Review changes'}</button>
      </div>
    </form>}
  </section>;
}
function split(value: string) { return value.split(',').map(item => item.trim()).filter(Boolean); }
function initialDraft(event: EventValues) {
  return { proposed_date: event.proposed_date ?? '', start_time: event.start_time ?? '', end_time: event.end_time ?? '',
    expected_attendance: String(event.expected_attendance ?? ''), preferred_room_layout: event.preferred_room_layout ?? '',
    required_facilities: (event.required_facilities ?? []).join(', '), accessibility_needs: (event.accessibility_needs ?? []).join(', '),
    location_preference: event.location_preference ?? '' };
}
