import { useState } from 'react';
import { responseError, type ApiRequest } from './api';
import { ChangeRequestItems, type ChangeRequest } from './ChangeRequests';
import type { AssignedEventDetail } from './AssignedEvents';

type Choice = { decision: string; reason: string };
type Preview = {
  preview_token: string;
  arrangements: { kind: string; id: number; name: string; reason: string }[];
  returns_to_planning: boolean;
};
const ACTIVE = new Set(['submitted', 'under_review', 'returned_for_clarification', 'approved', 'planning', 'confirmed', 'postponed']);

export function ChangeRequestDecisions({ api, eventId, eventStatus, request, onSaved, onReload }: {
  api: ApiRequest; eventId: number; eventStatus: string; request: ChangeRequest;
  onSaved: (event: AssignedEventDetail) => void; onReload: () => void;
}) {
  const [choices, setChoices] = useState<Record<number, Choice>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const editable = request.status === 'pending' && ACTIVE.has(eventStatus);
  const endpoint = `/api/event-requests/assigned/${eventId}/change-requests/${request.id}/decisions`;
  const selected = request.items.filter(item => (!item.decision || item.decision === 'pending') && choices[item.id]?.decision);
  function update(id: number, change: Partial<Choice>) {
    setChoices(current => ({ ...current, [id]: { ...(current[id] ?? { decision: '', reason: '' }), ...change } }));
    setPreview(null); setError(null); setNotice(null);
  }
  async function save() {
    if (busy) return;
    if (!selected.length) { setError('Select at least one item to decide.'); return; }
    if (selected.some(item => choices[item.id].decision === 'declined' && !choices[item.id].reason.trim())) {
      setError('Give a reason for every declined item.'); return;
    }
    setBusy(true); setError(null);
    try {
      const response = await api(preview ? endpoint : `${endpoint}/preview`, {
        method: 'POST', body: JSON.stringify({
          decisions: selected.map(item => ({ item_id: item.id, decision: choices[item.id].decision,
            ...(choices[item.id].decision === 'declined' ? { decline_reason: choices[item.id].reason.trim() } : {}) })),
          ...(preview ? { preview_token: preview.preview_token } : {}),
        }),
      });
      if (!response.ok) {
        setError(await responseError(response, 'Could not save decisions. Try again.'));
        setPreview(null); return;
      }
      const body = await response.json();
      if (preview) {
        setChoices({}); setPreview(null); setNotice('Decisions saved.'); onSaved(body.event);
      } else setPreview(body);
    } catch { setError('Could not save decisions. Try again.'); setPreview(null); }
    finally { setBusy(false); }
  }
  return <section aria-label={`Decisions for change request ${request.id}`}>
    <p><strong>{request.status === 'closed' ? 'Closed' : 'Pending'}</strong> · submitted {new Date(request.submitted_at).toLocaleString()}</p>
    {request.items.map(item => {
      const decided = item.decision && item.decision !== 'pending';
      const equipmentBlocked = item.field.startsWith('equipment:') && !['planning', 'confirmed'].includes(eventStatus);
      return <div key={item.id}>
        <ChangeRequestItems items={[item]} />
        {decided ? <div>
          <p><strong>{item.decision === 'accepted' ? 'Accepted' : 'Declined'}</strong>
            {item.decided_by && ` by ${item.decided_by.display_name}`}
            {item.decided_at && ` · ${new Date(item.decided_at).toLocaleString()}`}</p>
          {item.decline_reason && <p>Decline reason: {item.decline_reason}</p>}
        </div> : editable ? <fieldset disabled={busy} className="request-equipment">
          <legend>Decision: {item.field_label}</legend>
          <label className="field"><span>Outcome for {item.field_label}</span>
            <select value={choices[item.id]?.decision ?? ''} onChange={e => update(item.id, { decision: e.target.value })}>
              <option value="">Leave pending</option>
              <option value="accepted" disabled={equipmentBlocked}>Accept</option>
              <option value="declined">Decline</option>
            </select>
          </label>
          {equipmentBlocked && <p className="notice">Equipment acceptance is available in Planning or Confirmed. You can leave this item pending or decline it.</p>}
          {choices[item.id]?.decision === 'declined' && <label className="field"><span>Decline reason for {item.field_label}</span>
            <textarea maxLength={1000} value={choices[item.id]?.reason ?? ''} onChange={e => update(item.id, { reason: e.target.value })} />
          </label>}
        </fieldset> : <p>Pending · decisions are unavailable in this event status.</p>}
      </div>;
    })}
    {notice && <p role="status">{notice}</p>}
    {error && <div role="alert"><p className="error">{error}</p>
      <button className="button button--secondary" disabled={busy} onClick={() => {
        setChoices({}); setPreview(null); setError(null); onReload();
      }}>Reload change requests</button>
    </div>}
    {editable && <>
      {preview && <div role="region" aria-label="Review decision impacts" className="notice">
        <h3>Review before saving</h3>
        <p>{selected.length} item(s) will be decided. Saved decisions are final; unselected items stay pending.</p>
        {preview.returns_to_planning && <p>This event will return to Planning.</p>}
        {preview.arrangements.length ? <ul>{preview.arrangements.map((impact, index) => <li key={`${impact.kind}-${impact.id}-${index}`}>
          <strong>{impact.name}</strong>: {impact.reason}
        </li>)}</ul> : <p>No arrangement impacts identified.</p>}
      </div>}
      <div className="form-actions">
        {preview && <button className="button button--secondary" disabled={busy} onClick={() => setPreview(null)}>Cancel review</button>}
        <button className="button button--primary" disabled={busy || !selected.length} onClick={() => { void save(); }}>
          {busy ? 'Working…' : preview ? 'Confirm decisions' : 'Review decisions'}
        </button>
      </div>
    </>}
  </section>;
}
