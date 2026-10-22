import { useEffect, useMemo, useState, type FormEvent } from 'react';
import type { ChangePreview } from './SignificantEventChanges';
import { defaultRequest, responseError, type ApiRequest } from './api';

type EquipmentType = {
  id: number;
  name: string;
  description: string | null;
  location: string | null;
  total_stock: number;
};

type TechnicalSupportStaff = { id: string; name: string };

type Requirement = {
  id: number;
  organiser_equipment_text: string;
  equipment_type: EquipmentType | null;
  quantity: number;
  notes: string | null;
  required_start_date: string | null;
  required_end_date: string | null;
  collection_date: string | null;
  planned_return_date: string | null;
  status: string;
  essentiality: 'undecided' | 'essential' | 'non_essential';
  consulted_technical_support: TechnicalSupportStaff | null;
  essentiality_decision_note: string | null;
  essentiality_decided_at: string | null;
  essentiality_decided_by: TechnicalSupportStaff | null;
  // SPL-96 AC4: why Technical Support flagged this line, and when. Null unless flagged.
  review_reason: string | null;
  review_flagged_at: string | null;
  unavailability_history?: Array<{
    id: number;
    action: 'marked_unavailable' | 'restored_to_requested';
    reason: string | null;
    alternative_suggestion: string | null;
    recorded_at: string;
    recorded_by: { id: string; name: string | null };
  }>;
};

type EquipmentRequirementPayload = {
  event: { id: number; name: string; proposed_date: string | null; status: string };
  requirements: Requirement[];
  removed_requirements: Requirement[];
  equipment_types: EquipmentType[];
  technical_support_staff: TechnicalSupportStaff[];
};

type Draft = {
  equipment_type_id: string;
  quantity: string;
  notes: string;
  required_start_date: string;
  required_end_date: string;
  essentiality: Requirement['essentiality'];
  consulted_technical_support_account_id: string;
  essentiality_decision_note: string;
};

function newDraft(eventDate: string | null, requirement?: Requirement): Draft {
  // Start the editor from saved data when mapping/editing, or from safe event defaults when adding.
  return {
    equipment_type_id: requirement?.equipment_type ? String(requirement.equipment_type.id) : '',
    quantity: String(requirement?.quantity ?? 1),
    notes: requirement?.notes ?? '',
    required_start_date: eventDate ?? requirement?.required_start_date ?? '',
    required_end_date: eventDate ?? requirement?.required_end_date ?? '',
    essentiality: requirement?.essentiality ?? 'undecided',
    consulted_technical_support_account_id: requirement?.consulted_technical_support?.id ?? '',
    essentiality_decision_note: requirement?.essentiality_decision_note ?? '',
  };
}

function statusLabel(status: string) {
  return status === 'unmapped' ? 'Needs mapping' : status.replace(/_/g, ' ');
}

function essentialityLabel(value: Requirement['essentiality']) {
  return value === 'non_essential' ? 'Non-essential' : value[0].toUpperCase() + value.slice(1);
}

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat('en-SG', {
      day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
    }).format(new Date(`${value}T00:00:00Z`))
    : 'Not recorded';
}

function formatTimestamp(value: string | null) {
  return value
    ? new Intl.DateTimeFormat('en-SG', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Singapore',
    }).format(new Date(value))
    : 'Not recorded';
}

function asPayload(draft: Draft) {
  // Send only fields owned by SPL-90. Identity, status and audit time are assigned by Flask.
  const payload: Record<string, unknown> = {
    equipment_type_id: Number(draft.equipment_type_id),
    quantity: Number(draft.quantity),
    notes: draft.notes,
    required_start_date: draft.required_start_date,
    required_end_date: draft.required_end_date,
    essentiality: draft.essentiality,
  };
  if (draft.essentiality !== 'undecided') {
    payload.consulted_technical_support_account_id = draft.consulted_technical_support_account_id;
    payload.essentiality_decision_note = draft.essentiality_decision_note;
  }
  return payload;
}

// SPL-91: the statuses in which a line may hold stock. Changing one of these lines releases
// whatever it holds and sends it back to Technical Support, so the editor warns before saving.
const HOLDING_STATUSES = new Set(['reserved', 'partially_reserved', 'review_required']);

function RequirementEditor({
  eventDate,
  catalogue,
  technicalSupport,
  initial,
  onCancel,
  onSave,
  saving,
  error,
}: {
  eventDate: string | null;
  catalogue: EquipmentType[];
  technicalSupport: TechnicalSupportStaff[];
  initial?: Requirement;
  onCancel: () => void;
  onSave: (draft: Draft) => void;
  saving: boolean;
  error?: string | null;
}) {
  // This single editor handles four user actions: add a catalogue item, map organiser wording,
  // update an unreserved requirement, and (SPL-91) revise a line Technical Support has already
  // reserved stock for. It never offers a reservation action of its own.
  const [draft, setDraft] = useState(() => newDraft(eventDate, initial));
  const holdsStock = Boolean(initial && HOLDING_STATUSES.has(initial.status));
  const mapped = Boolean(initial?.equipment_type);
  const selectingDecision = draft.essentiality !== 'undecided';
  const decisionLocked = Boolean(initial && initial.essentiality !== 'undecided');
  const update = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft(current => ({ ...current, [key]: value }));
  };

  return <form className="equipment-requirements__editor" onSubmit={event => {
    event.preventDefault();
    onSave(draft);
  }}>
    <div className="equipment-requirements__editor-heading">
      <div>
        <p className="eyebrow">{initial ? mapped ? 'Update requirement' : 'Map organiser request' : 'New requirement'}</p>
        <h3>{initial?.organiser_equipment_text ?? 'Add equipment to this event'}</h3>
      </div>
      {initial && !mapped && <p className="equipment-requirements__history-note">Original organiser wording is retained as history.</p>}
    </div>
    {/* SPL-91 AC2, said before the coordinator commits to it rather than discovered after: a
        change to a line holding stock costs it that stock and a fresh Technical Support review. */}
    {holdsStock && <p className="equipment-requirements__release-warning" role="note">
      Technical Support has already reviewed this line: {initial?.organiser_equipment_text} (equipment #{initial?.id}). Changing the equipment, quantity, dates
      or technical notes releases any units reserved for it and sends it back to Technical Support
      for review. Recording criticality does not.
    </p>}
    <div className="equipment-requirements__form-grid">
      <label className="equipment-requirements__wide">Catalogue equipment <span>Required</span>
        <select value={draft.equipment_type_id} onChange={event => update('equipment_type_id', event.target.value)} required>
          <option value="">Choose an equipment type</option>
          {catalogue.map(item => <option key={item.id} value={item.id}>{item.name}{item.location ? ` — ${item.location}` : ''}</option>)}
        </select>
      </label>
      <label>Quantity <span>Required</span>
        <input min="1" step="1" inputMode="numeric" type="number" value={draft.quantity}
          onChange={event => update('quantity', event.target.value)} required />
      </label>
      <label>Required from <span>Event date</span>
        <input type="date" value={draft.required_start_date}
          onChange={event => update('required_start_date', event.target.value)} disabled={Boolean(eventDate)} required />
      </label>
      <label>Required until <span>Event date</span>
        <input type="date" value={draft.required_end_date}
          onChange={event => update('required_end_date', event.target.value)} disabled={Boolean(eventDate)} required />
      </label>
      <label className="equipment-requirements__wide">Technical notes <span>Optional</span>
        <textarea rows={3} maxLength={2000} value={draft.notes}
          onChange={event => update('notes', event.target.value)} placeholder="Setup, compatibility, placement, or handling notes" />
      </label>
    </div>
    {eventDate && <p className="equipment-requirements__date-guidance">This is a one-day event. Equipment is collected the day before and planned for return on the event date.</p>}
    <fieldset className="equipment-requirements__essentiality">
      <legend>Event criticality</legend>
      <p>Keep this Undecided until you have consulted Technical Support. Essential requirements later contribute to event readiness.</p>
      <div className="equipment-requirements__choices">
        {(['undecided', 'essential', 'non_essential'] as const).map(value => <label key={value}>
          <input type="radio" name={`essentiality-${initial?.id ?? 'new'}`} value={value}
            checked={draft.essentiality === value} onChange={() => update('essentiality', value)} disabled={decisionLocked} />
          <span>{essentialityLabel(value)}</span>
        </label>)}
      </div>
      {decisionLocked ? <div className="equipment-requirements__decision-record">
        <strong>Decision recorded</strong>
        <span>{essentialityLabel(initial!.essentiality)} after consulting {initial!.consulted_technical_support?.name ?? 'Technical Support'}.</span>
        <span>{initial!.essentiality_decision_note}</span>
        <span>Recorded by {initial!.essentiality_decided_by?.name ?? 'the assigned Event Coordinator'} · {formatTimestamp(initial!.essentiality_decided_at)}</span>
      </div> : selectingDecision && <div className="equipment-requirements__consultation">
        <label>Consulted Technical Support Staff <span>Required</span>
          <select value={draft.consulted_technical_support_account_id}
            onChange={event => update('consulted_technical_support_account_id', event.target.value)} required>
            <option value="">Choose the consulted staff member</option>
            {technicalSupport.map(staff => <option key={staff.id} value={staff.id}>{staff.name}</option>)}
          </select>
        </label>
        <label>Decision note <span>Required</span>
          <textarea rows={3} maxLength={2000} value={draft.essentiality_decision_note}
            onChange={event => update('essentiality_decision_note', event.target.value)}
            placeholder="Why this requirement is essential or non-essential" required />
        </label>
      </div>}
    </fieldset>
    {/* A refused save is shown here, inside the form being edited and just above Save, rather
        than at the top of the page (TC-SPL-91-10). The server's validation messages name the
        field in their wording ("Quantity must be…") rather than as a separate key, so the form
        cannot pin a message to one input; it sits with the form as a whole instead. */}
    {error && <p className="error equipment-requirements__editor-error" role="alert">{error}</p>}
    <div className="equipment-requirements__editor-actions">
      <button className="button button--secondary" type="button" onClick={onCancel} disabled={saving}>Cancel</button>
      <button className="button button--primary" type="submit" disabled={saving || !draft.equipment_type_id}>
        {saving ? 'Saving…' : initial ? initial.equipment_type ? 'Save requirement' : 'Map requirement' : 'Add requirement'}
      </button>
    </div>
  </form>;
}

export function EquipmentRequirements({ accessToken, eventId, onNavigate, request }: {
  accessToken: string;
  eventId: number;
  onNavigate: (path: string) => void;
  request?: ApiRequest;
}) {
  // The page is intentionally scoped to one assigned Planning event. API authorisation still
  // rechecks that assignment on every request; route visibility alone is not security.
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [data, setData] = useState<EquipmentRequirementPayload | null>(null);
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);
  // SPL-91: a refused save belongs to the form that was being saved, not to the page. Kept
  // separate from `error` so a failed removal on one line can never appear inside another
  // line's open form.
  const [editorError, setEditorError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showRemoved, setShowRemoved] = useState(false);
  // SPL-122 AC4: one id per opened Add form, resent by every attempt to save it, so a retry
  // after a lost response gets the same line back instead of adding a second one.
  const [addRequestId, setAddRequestId] = useState('');
  const openEditor = (target: number | 'new' | null) => {
    if (target === 'new') setAddRequestId(crypto.randomUUID());
    setEditorError(null); setEditing(target);
  };

  const endpoint = `/api/event-requests/${eventId}/equipment-requirements`;
  const load = async () => {
    // Refresh after every save/remove so the visible counts and retained history stay authoritative.
    const response = await api(endpoint);
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(body?.error || 'Could not load equipment requirements. Try again.');
    setData(body);
  };

  useEffect(() => {
    let current = true;
    setData(null); setEditing(null); setError(null); setEditorError(null); setNotice(null);
    void load().catch((reason: unknown) => { if (current) setError(reason instanceof Error ? reason.message : 'Could not load equipment requirements. Try again.'); });
    return () => { current = false; };
  }, [api, endpoint]);

  async function save(draft: Draft, requirement?: Requirement) {
    // POST adds a new catalogue-backed line; PATCH maps or updates an existing unreserved line.
    setSaving(true); setError(null); setEditorError(null); setNotice(null);
    try {
      let response: Response;
      if (data?.event.status === 'confirmed' && requirement) {
        const significant = `/api/event-requests/assigned/${eventId}/significant-changes`;
        const payload = { values: asPayload(draft), equipment_requirement_id: requirement.id };
        const proposed = await api(`${significant}/preview`, { method: 'POST', body: JSON.stringify(payload) });
        if (!proposed.ok) { setEditorError(await responseError(proposed, 'Could not review these changes.')); return; }
        const preview = await proposed.json() as ChangePreview;
        if (!Object.keys(preview.changes).length) { await load(); setEditing(null); setNotice('No changes to save.'); return; }
        const warning = preview.arrangements.map(item => `${item.name} (equipment #${item.id}): ${item.reason}`).join('\n');
        if (!window.confirm(`${warning}\nThis event will return from Confirmed to Planning. Save changes?`)) return;
        response = await api(significant, { method: 'PATCH', body: JSON.stringify({ ...payload, preview_token: preview.preview_token }) });
      } else {
        response = await api(requirement ? `${endpoint}/${requirement.id}` : endpoint, {
          method: requirement ? 'PATCH' : 'POST',
          body: JSON.stringify(requirement ? asPayload(draft) : { ...asPayload(draft), request_id: addRequestId }),
        });
      }
      if (!response.ok) {
        setEditorError(await responseError(response, 'Could not save this equipment requirement.'));
        return;
      }
      // SPL-91: say what the save cost, from the server's own count, so the coordinator is
      // never left to infer that their reservation has gone.
      const body = await response.json().catch(() => ({}));
      const released = typeof body.released_quantity === 'number' ? body.released_quantity : 0;
      await load();
      setEditing(null);
      setNotice(!requirement
        ? 'Equipment requirement added.'
        : released > 0
          ? `Equipment requirement saved. ${released} reserved unit(s) were released, and the line is back with Technical Support for review.`
          : 'Equipment requirement saved.');
    } catch {
      setEditorError('Could not save this equipment requirement. Try again.');
    } finally { setSaving(false); }
  }

  async function remove(requirement: Requirement) {
    if (data?.event.status !== 'planning') return;
    // Removing is a soft removal: the record remains in event history for traceability. SPL-91:
    // for a line holding stock, the confirmation says the units go too, before they do.
    const releases = HOLDING_STATUSES.has(requirement.status)
      ? ' Any units reserved for it will be released.'
      : '';
    if (!window.confirm(`Remove “${requirement.organiser_equipment_text}” from active planning?${releases} It will remain in the event history.`)) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      const response = await api(`${endpoint}/${requirement.id}`, { method: 'DELETE' });
      if (!response.ok) {
        setError(await responseError(response, 'Could not remove this equipment requirement.'));
        return;
      }
      await load();
      setEditing(null);
      setNotice('Equipment requirement removed from active planning.');
    } catch {
      setError('Could not remove this equipment requirement. Try again.');
    } finally { setSaving(false); }
  }

  if (error && !data) return <section className="equipment-requirements" aria-labelledby="equipment-requirements-title">
    <a className="organisation-events__back" href={`/workspace/assigned-events/${eventId}`} onClick={event => { event.preventDefault(); onNavigate(`/workspace/assigned-events/${eventId}`); }}>Back to assigned event</a>
    <p className="error" role="alert">{error}</p>
  </section>;
  if (!data) return <p role="status">Loading equipment requirements…</p>;

  return <section className="equipment-requirements" aria-labelledby="equipment-requirements-title">
    <a className="organisation-events__back" href={`/workspace/assigned-events/${eventId}`} onClick={event => { event.preventDefault(); onNavigate(`/workspace/assigned-events/${eventId}`); }}>Back to assigned event</a>
    <header className="equipment-requirements__header">
      <div><p className="eyebrow">Event coordinator · planning</p><h1 id="equipment-requirements-title">Equipment requirements</h1>
        <p>Turn this event’s equipment requests into clear requirements for Technical Support to review. Recording a requirement does not reserve stock.</p></div>
      <dl><div><dt>Event</dt><dd>{data.event.name}</dd></div><div><dt>Event date</dt><dd>{data.event.proposed_date ?? 'Not recorded'}</dd></div></dl>
    </header>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {data.event.status === 'confirmed' && <p role="note">Editing an equipment requirement returns this event to Planning. Adding or removing lines is available in Planning.</p>}
    {editing === 'new' ? <RequirementEditor eventDate={data.event.proposed_date} catalogue={data.equipment_types}
      technicalSupport={data.technical_support_staff} onCancel={() => openEditor(null)} onSave={draft => { void save(draft); }} saving={saving} error={editorError} /> : <>
      <section className="equipment-requirements__overview" aria-label="Equipment planning guidance">
        <div><strong>{data.requirements.filter(line => line.status === 'unmapped').length}</strong><span>Needs mapping</span></div>
        <div><strong>{data.requirements.filter(line => line.status !== 'unmapped').length}</strong><span>Active requirements</span></div>
        <p>Map organiser wording to the shared catalogue, then mark criticality only after consulting Technical Support.</p>
        <button className="button button--primary" type="button" disabled={data.event.status !== 'planning'} onClick={() => openEditor('new')}>Add requirement</button>
      </section>
      <section className="equipment-requirements__list" aria-label="Active equipment requirements">
        {data.requirements.length === 0 && <div className="equipment-requirements__empty"><strong>No equipment requirements yet.</strong><span>Add a requirement when this event needs equipment or technical preparation.</span></div>}
        {data.requirements.map(requirement => <article className="equipment-requirements__card" key={requirement.id}>
          {editing === requirement.id ? <RequirementEditor eventDate={data.event.proposed_date} catalogue={data.equipment_types}
            technicalSupport={data.technical_support_staff} initial={requirement} onCancel={() => openEditor(null)}
            onSave={draft => { void save(draft, requirement); }} saving={saving} error={editorError} /> : <>
            <header><div><p className="equipment-requirements__card-label">{requirement.status === 'unmapped' ? 'Organiser request' : 'Equipment requirement'}</p>
              <h2>{requirement.equipment_type?.name ?? requirement.organiser_equipment_text}</h2>
              {requirement.equipment_type && <p className="equipment-requirements__original">Organiser wording: {requirement.organiser_equipment_text}</p>}</div>
              <span className={`equipment-requirements__status equipment-requirements__status--${requirement.status}`}>{statusLabel(requirement.status)}</span></header>
            {/* SPL-96 AC4: the coordinator sees the flag and its reason on their own line. The
                status badge above already carries the flag; this says why it is there. The label
                is deliberately neutral about who raised it: SPL-96 flags a line when Technical
                Support takes units out of service, and SPL-91 when the coordinator changes it.
                The reason text itself says which. It is shown only while the line is actually
                Review Required: a reason arriving with any other status describes a review that
                is already over, so it must not read as an active warning (TC-SPL-91-16). */}
            {requirement.status === 'review_required' && requirement.review_reason && <p className="equipment-requirements__review-reason" role="status">
              Back with Technical Support for review: {requirement.review_reason}
            </p>}
            {(requirement.unavailability_history || []).length > 0 && <section className="equipment-requirements__unavailability" aria-label="Unavailable requirement history">
              <strong>Technical Support availability history</strong>
              <ul>{requirement.unavailability_history!.map(entry => <li key={entry.id}>
                <span>{entry.action === 'marked_unavailable' ? 'Marked unavailable' : 'Restored to requested'} · {formatTimestamp(entry.recorded_at)} · {entry.recorded_by.name ?? 'Technical Support'}</span>
                {entry.reason && <span>Reason: {entry.reason}</span>}
                {entry.alternative_suggestion && <span>Alternative suggestion: {entry.alternative_suggestion}</span>}
              </li>)}</ul>
            </section>}
            <dl className="equipment-requirements__facts">
              <div><dt>Quantity</dt><dd>{requirement.quantity}</dd></div>
              <div><dt>Required date</dt><dd>{requirement.required_start_date ? formatDate(requirement.required_start_date) : 'Set when mapped'}</dd></div>
              <div><dt>Collection</dt><dd>{formatDate(requirement.collection_date)}</dd></div>
              <div><dt>Planned return</dt><dd>{formatDate(requirement.planned_return_date)}</dd></div>
              <div><dt>Criticality</dt><dd>{essentialityLabel(requirement.essentiality)}</dd></div>
              <div><dt>Catalogue source</dt><dd>{requirement.equipment_type?.location ?? 'Not mapped'}</dd></div>
            </dl>
            {requirement.notes && <p className="equipment-requirements__notes"><strong>Technical notes</strong>{requirement.notes}</p>}
            {requirement.essentiality !== 'undecided' && <div className="equipment-requirements__decision"><strong>{essentialityLabel(requirement.essentiality)}</strong><span>Consulted {requirement.consulted_technical_support?.name} · {requirement.essentiality_decision_note}</span><span>Recorded by {requirement.essentiality_decided_by?.name ?? 'the assigned Event Coordinator'} · {formatTimestamp(requirement.essentiality_decided_at)}</span></div>}
            <footer><button className="button button--secondary" type="button" onClick={() => openEditor(requirement.id)} disabled={saving}>{requirement.status === 'unmapped' ? 'Map to catalogue' : 'Edit requirement'}</button>
              <button className="equipment-requirements__remove" type="button" onClick={() => { void remove(requirement); }} disabled={saving || data.event.status !== 'planning'}>Remove</button></footer>
          </>}
        </article>)}
      </section>
      {data.removed_requirements.length > 0 && <section className="equipment-requirements__removed"><button type="button" onClick={() => setShowRemoved(current => !current)} aria-expanded={showRemoved}> {showRemoved ? 'Hide' : 'Show'} removed requirements ({data.removed_requirements.length})</button>
        {showRemoved && <ul>{data.removed_requirements.map(item => <li key={item.id}>{item.organiser_equipment_text} <span>Removed from active planning</span></li>)}</ul>}</section>}
    </>}
  </section>;
}
