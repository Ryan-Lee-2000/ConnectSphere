import { useEffect, useState, type FormEvent } from 'react';

export type EventRequestApi = (path: string, init?: RequestInit) => Promise<Response>;

type FormValues = {
  name: string;
  purpose: string;
  description: string;
  proposedDate: string;
  startTime: string;
  endTime: string;
  expectedAttendance: string;
  preferredRoomLayout: string;
  requiredFacilities: string;
  facilitiesNotes: string;
  accessibilityNeeds: string;
  locationPreference: string;
  venueNotes: string;
  preferredVenueName: string;
  registrationRequired: boolean;
  registrationNotes: string;
  equipmentRequirements: { equipment_type: string; quantity: string; notes: string }[];
};

type CreatedRequest = {
  id: number;
  name: string;
  status: string;
  mapped_slots: string[];
  last_saved_at?: string;
  purpose?: string | null;
  description?: string | null;
  proposed_date?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  expected_attendance?: number | null;
  preferred_room_layout?: string | null;
  required_facilities?: string[];
  facilities_notes?: string | null;
  accessibility_needs?: string | null;
  location_preference?: string | null;
  venue_notes?: string | null;
  preferred_venue_name?: string | null;
  registration_required?: boolean;
  registration_notes?: string | null;
  equipment_requirements?: { equipment_type: string; quantity: number; notes: string | null }[];
};

const emptyForm: FormValues = {
  name: '',
  purpose: '',
  description: '',
  proposedDate: '',
  startTime: '',
  endTime: '',
  expectedAttendance: '',
  preferredRoomLayout: '', requiredFacilities: '', facilitiesNotes: '',
  accessibilityNeeds: '', locationPreference: '', venueNotes: '',
  preferredVenueName: '', registrationRequired: false, registrationNotes: '',
  equipmentRequirements: [],
};

function formFromRequest(value: CreatedRequest): FormValues {
  return {
    name: value.name, purpose: value.purpose || '', description: value.description || '',
    proposedDate: value.proposed_date || '', startTime: value.start_time || '',
    endTime: value.end_time || '', expectedAttendance: value.expected_attendance?.toString() || '',
    preferredRoomLayout: value.preferred_room_layout || '',
    requiredFacilities: (value.required_facilities || []).join(', '),
    facilitiesNotes: value.facilities_notes || '', accessibilityNeeds: value.accessibility_needs || '',
    locationPreference: value.location_preference || '', venueNotes: value.venue_notes || '',
    preferredVenueName: value.preferred_venue_name || '',
    registrationRequired: value.registration_required || false,
    registrationNotes: value.registration_notes || '',
    equipmentRequirements: (value.equipment_requirements || []).map(line => ({
      equipment_type: line.equipment_type, quantity: line.quantity.toString(), notes: line.notes || '',
    })),
  };
}

function authorisedRequest(token: string): EventRequestApi {
  return (path, init = {}) => fetch(path, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...init.headers,
    },
  });
}

async function responseError(response: Response): Promise<string> {
  const body = await response.json().catch(() => ({}));
  return body.error || 'The event request could not be submitted. Please try again.';
}

export function EventRequestCreate({
  accessToken,
  draftId,
  onReturn,
  onUnsavedChanges,
  request,
}: {
  accessToken: string;
  draftId?: number;
  onReturn?: () => void;
  onUnsavedChanges?: (hasUnsavedChanges: boolean) => void;
  request?: EventRequestApi;
}) {
  const [values, setValues] = useState<FormValues>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedRequest | null>(null);
  const [activeDraftId, setActiveDraftId] = useState<number | undefined>(draftId);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(draftId));
  const [baseline, setBaseline] = useState(JSON.stringify(emptyForm));
  const api = request || authorisedRequest(accessToken);

  useEffect(() => {
    onUnsavedChanges?.(!created && JSON.stringify(values) !== baseline);
  }, [baseline, created, onUnsavedChanges, values]);

  useEffect(() => {
    if (!draftId) return;
    let active = true;
    void api(`/api/event-requests/${draftId}`).then(async response => {
      if (!response.ok) throw new Error(await responseError(response));
      const body = await response.json() as { event_request: CreatedRequest };
      if (body.event_request.status !== 'draft') throw new Error('This request is no longer a draft.');
      if (active) {
        const next = formFromRequest(body.event_request);
        setValues(next); setBaseline(JSON.stringify(next));
        setLastSavedAt(body.event_request.last_saved_at || null);
      }
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Could not load the draft.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // The request gateway is supplied once for this mounted editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftId]);

  const update = <K extends keyof FormValues>(field: K, value: FormValues[K]) => {
    setValues(current => ({ ...current, [field]: value }));
  };

  const payload = (draft: boolean) => {
    const data: Record<string, unknown> = {
      name: values.name, purpose: values.purpose, description: values.description,
      proposed_date: values.proposedDate || null, start_time: values.startTime || null,
      end_time: values.endTime || null,
      expected_attendance: values.expectedAttendance ? Number(values.expectedAttendance) : null,
      preferred_room_layout: values.preferredRoomLayout || null,
      required_facilities: values.requiredFacilities.split(',').map(item => item.trim()).filter(Boolean),
      facilities_notes: values.facilitiesNotes || null, accessibility_needs: values.accessibilityNeeds || null,
      location_preference: values.locationPreference || null, venue_notes: values.venueNotes || null,
      preferred_venue_name: values.preferredVenueName || null,
      registration_required: values.registrationRequired, registration_notes: values.registrationNotes || null,
      equipment_requirements: values.equipmentRequirements.map(line => ({
        equipment_type: line.equipment_type, quantity: Number(line.quantity), notes: line.notes || null,
      })),
    };
    if (!draft && !activeDraftId) {
      for (const [key, value] of Object.entries(data)) {
        if (value === null || value === '' || (Array.isArray(value) && value.length === 0) || value === false) delete data[key];
      }
    }
    return data;
  };

  async function saveDraft() {
    if (saving || loading) return;
    if (!values.name.trim()) { setError('Event name is required.'); return; }
    setError(null); setSaving(true);
    try {
      const response = await api(activeDraftId ? `/api/event-requests/drafts/${activeDraftId}` : '/api/event-requests/drafts', {
        method: activeDraftId ? 'PATCH' : 'POST', body: JSON.stringify(payload(true)),
      });
      if (!response.ok) { setError(await responseError(response)); return; }
      const body = await response.json() as { event_request: CreatedRequest };
      setActiveDraftId(body.event_request.id);
      setLastSavedAt(body.event_request.last_saved_at || null);
      setBaseline(JSON.stringify(values));
      onUnsavedChanges?.(false);
    } catch {
      setError('The draft could not be saved. Check your connection and try again.');
    } finally { setSaving(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    setError(null);
    setSaving(true);
    try {
      const response = await api(activeDraftId ? `/api/event-requests/drafts/${activeDraftId}/submit` : '/api/event-requests', {
        method: 'POST',
        body: JSON.stringify(payload(false)),
      });
      if (!response.ok) {
        setError(await responseError(response));
        return;
      }
      const body = await response.json() as { event_request: CreatedRequest };
      setCreated(body.event_request);
      onUnsavedChanges?.(false);
    } catch {
      setError('The event request could not be submitted. Check your connection and try again.');
    } finally {
      setSaving(false);
    }
  }

  if (created) {
    return <section className="request-workspace" aria-labelledby="request-saved-heading">
      <p className="eyebrow">Event request</p>
      <h2 id="request-saved-heading">Request submitted</h2>
      <p role="status"><strong>{created.name}</strong> has been submitted as request #{created.id}.</p>
      <p>Mapped venue slots: {created.mapped_slots.length ? created.mapped_slots.join(', ') : 'None for the selected times'}.</p>
      <p className="hint">These slots describe the requested time. They do not reserve a venue.</p>
      {onReturn ? (
        <button className="button button--secondary" type="button" onClick={onReturn}>Back to requests</button>
      ) : (
        <button className="button button--secondary" type="button" onClick={() => {
          setValues(emptyForm); setBaseline(JSON.stringify(emptyForm));
          setActiveDraftId(undefined); setLastSavedAt(null); setCreated(null);
        }}>Create another request</button>
      )}
    </section>;
  }

  if (loading) return <section className="request-workspace" aria-busy="true"><p>Loading draft…</p></section>;

  return <section className="request-workspace" aria-labelledby="request-heading">
    <p className="eyebrow">Event Organiser</p>
    <h2 id="request-heading">{activeDraftId ? 'Edit event request draft' : 'Create an event request'}</h2>
    <p className="request-intro">Only the event name is needed to save a draft. Complete the fields labelled “required to submit” before submitting. Submitting does not reserve a venue.</p>
    {lastSavedAt && <p role="status">Draft saved. Last saved: {new Date(lastSavedAt).toLocaleString()}.</p>}
    {onReturn && <button className="button button--secondary" type="button" onClick={onReturn}>Back to requests</button>}
    <form className="request-form" onSubmit={event => void submit(event)}>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="field">
        <label data-required htmlFor="request-name">Event name</label>
        <input id="request-name" value={values.name} onChange={event => update('name', event.target.value)} required />
      </div>
      <div className="field">
        <label data-submit-required htmlFor="request-purpose">Purpose</label>
        <input id="request-purpose" value={values.purpose} onChange={event => update('purpose', event.target.value)} required />
      </div>
      <div className="field">
        <label htmlFor="request-description">Description <span className="hint">Optional</span></label>
        <textarea id="request-description" rows={4} value={values.description} onChange={event => update('description', event.target.value)} />
      </div>
      <div className="request-form__row">
        <div className="field">
          <label data-submit-required htmlFor="request-date">Proposed date</label>
          <input id="request-date" type="date" value={values.proposedDate} onChange={event => update('proposedDate', event.target.value)} required />
        </div>
        <div className="field">
          <label data-submit-required htmlFor="request-attendance">Expected attendance</label>
          <input id="request-attendance" type="number" min="1" step="1" value={values.expectedAttendance} onChange={event => update('expectedAttendance', event.target.value)} required />
        </div>
      </div>
      <div className="request-form__row">
        <div className="field">
          <label data-submit-required htmlFor="request-start">Start time</label>
          <input id="request-start" type="time" value={values.startTime} onChange={event => update('startTime', event.target.value)} required />
        </div>
        <div className="field">
          <label data-submit-required htmlFor="request-end">End time</label>
          <input id="request-end" type="time" value={values.endTime} onChange={event => update('endTime', event.target.value)} required />
        </div>
      </div>
      <div className="request-form__row">
        <div className="field"><label htmlFor="request-layout">Preferred room layout</label><input id="request-layout" value={values.preferredRoomLayout} onChange={event => update('preferredRoomLayout', event.target.value)} /></div>
        <div className="field"><label htmlFor="request-facilities">Required facilities (comma separated)</label><input id="request-facilities" value={values.requiredFacilities} onChange={event => update('requiredFacilities', event.target.value)} /></div>
      </div>
      {([
        ['facilitiesNotes', 'Facilities notes'], ['accessibilityNeeds', 'Accessibility needs'],
        ['locationPreference', 'Location preference'], ['venueNotes', 'Venue notes'],
        ['preferredVenueName', 'Preferred venue name'], ['registrationNotes', 'Registration notes'],
      ] as const).map(([field, label]) => <div className="field" key={field}>
        <label htmlFor={`request-${field}`}>{label}</label>
        <textarea id={`request-${field}`} rows={2} value={values[field]} onChange={event => update(field, event.target.value)} />
      </div>)}
      <label className="request-checkbox"><input type="checkbox" checked={values.registrationRequired} onChange={event => update('registrationRequired', event.target.checked)} /> Registration required</label>
      <fieldset className="request-equipment"><legend>Equipment requirements</legend>
        {values.equipmentRequirements.map((line, index) => <div className="request-form__row" key={index}>
          <div className="field"><label data-line-required htmlFor={`equipment-type-${index}`}>Equipment type {index + 1}</label><input id={`equipment-type-${index}`} value={line.equipment_type} onChange={event => update('equipmentRequirements', values.equipmentRequirements.map((item, i) => i === index ? { ...item, equipment_type: event.target.value } : item))} required /></div>
          <div className="field"><label data-line-required htmlFor={`equipment-quantity-${index}`}>Quantity {index + 1}</label><input id={`equipment-quantity-${index}`} type="number" min="1" value={line.quantity} onChange={event => update('equipmentRequirements', values.equipmentRequirements.map((item, i) => i === index ? { ...item, quantity: event.target.value } : item))} required /></div>
          <div className="field"><label htmlFor={`equipment-notes-${index}`}>Equipment notes {index + 1}</label><input id={`equipment-notes-${index}`} value={line.notes} onChange={event => update('equipmentRequirements', values.equipmentRequirements.map((item, i) => i === index ? { ...item, notes: event.target.value } : item))} /></div>
          <button className="button button--secondary" type="button" onClick={() => update('equipmentRequirements', values.equipmentRequirements.filter((_, i) => i !== index))}>Remove equipment {index + 1}</button>
        </div>)}
        <button className="button button--secondary" type="button" onClick={() => update('equipmentRequirements', [...values.equipmentRequirements, { equipment_type: '', quantity: '', notes: '' }])}>Add equipment</button>
      </fieldset>
      <div className="request-form__actions">
        <p className="hint">Your request is submitted when you select Submit request.</p>
        <button className="button button--secondary" disabled={saving} type="button" onClick={() => void saveDraft()}>{saving ? 'Saving…' : activeDraftId ? 'Save draft again' : 'Save draft'}</button>
        <button className="button button--primary" disabled={saving} type="submit">{saving ? 'Submitting…' : 'Submit request'}</button>
      </div>
    </form>
  </section>;
}
