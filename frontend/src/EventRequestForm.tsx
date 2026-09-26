import { FormEvent, useEffect, useRef, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { defaultRequest, responseError, type ApiRequest } from './api';
import { SLOTS, type SlotKey } from './slots';
import type { Venue, VenueSummary } from './VenueCatalogue';

type EquipmentLineDraft = { id?: number; equipmentType: string; quantity: string; notes: string };
type EquipmentLine = { id: number; equipment_type: string; quantity: number; notes: string | null };
type EventRequest = {
  id: number;
  name: string;
  mapped_slots: string[];
  equipment_requirements: EquipmentLine[];
};
type EventRequestDetail = {
  id: number;
  name: string;
  purpose: string | null;
  description: string | null;
  proposed_date: string | null;
  start_time: string | null;
  end_time: string | null;
  expected_attendance: number | null;
  preferred_room_layout: string | null;
  required_facilities: string[];
  facilities_notes: string | null;
  accessibility_needs: string[];
  location_preference: string | null;
  venue_notes: string | null;
  venue_id: number | null;
  registration_required: boolean;
  registration_notes: string | null;
  last_saved_at: string | null;
  equipment_requirements: EquipmentLine[];
};

const EVENT_REQUEST_FALLBACK = 'The event request could not be created.';
const DRAFT_SAVE_FALLBACK = 'The draft could not be saved.';
const DRAFT_LOAD_FALLBACK = "We couldn't load this draft. Refresh the page or try again shortly.";

function listFromText(value: string) {
  return value.split(',').map(item => item.trim()).filter(Boolean);
}

const OTHERS = 'others';

function toggleInList(list: string[], value: string) {
  return list.includes(value) ? list.filter(item => item !== value) : [...list, value];
}

function partition(list: string[], allowed: string[]): [string[], string[]] {
  return [list.filter(item => allowed.includes(item)), list.filter(item => !allowed.includes(item))];
}

function slotBounds(key: SlotKey) {
  const slot = SLOTS.find(item => item.key === key);
  return slot ? { start_time: slot.start, end_time: slot.end } : null;
}

function slotForTimes(start: string | null, end: string | null): SlotKey | null {
  if (!start || !end) return null;
  return SLOTS.find(item => item.start === start && item.end === end)?.key ?? null;
}

export function EventRequestForm({ accessToken, request, draftId, onSubmitted, onUnsavedChanges, onCancel }: {
  accessToken: string | null;
  request?: ApiRequest;
  draftId?: number;
  onSubmitted?: () => void;
  onUnsavedChanges?: (hasUnsavedChanges: boolean) => void;
  onCancel?: () => void;
}) {
  const api = request || (accessToken ? defaultRequest(accessToken) : undefined);
  const [currentDraftId, setCurrentDraftId] = useState<number | null>(draftId ?? null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [loadingDraft, setLoadingDraft] = useState(Boolean(draftId));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [name, setName] = useState('');
  const [purpose, setPurpose] = useState('');
  const [description, setDescription] = useState('');
  const [proposedDate, setProposedDate] = useState('');
  const [slot, setSlot] = useState<SlotKey | null>(null);
  const [expectedAttendance, setExpectedAttendance] = useState('');
  const [layoutChoice, setLayoutChoice] = useState('');
  const [layoutOtherText, setLayoutOtherText] = useState('');
  const [selectedFacilities, setSelectedFacilities] = useState<string[]>([]);
  const [facilitiesOthersEnabled, setFacilitiesOthersEnabled] = useState(false);
  const [facilitiesOthersText, setFacilitiesOthersText] = useState('');
  const [facilitiesNotes, setFacilitiesNotes] = useState('');
  const [selectedAccessibilityNeeds, setSelectedAccessibilityNeeds] = useState<string[]>([]);
  const [accessibilityOthersEnabled, setAccessibilityOthersEnabled] = useState(false);
  const [accessibilityOthersText, setAccessibilityOthersText] = useState('');
  const [locationPreference, setLocationPreference] = useState('');
  const [venueNotes, setVenueNotes] = useState('');
  const [venues, setVenues] = useState<VenueSummary[]>([]);
  const [venueId, setVenueId] = useState<number | null>(null);
  const [selectedVenue, setSelectedVenue] = useState<Venue | null>(null);
  const [registrationRequired, setRegistrationRequired] = useState(false);
  const [registrationNotes, setRegistrationNotes] = useState('');
  const [equipmentLines, setEquipmentLines] = useState<EquipmentLineDraft[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mappedSlots, setMappedSlots] = useState<string[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const initialSnapshot = useRef<string | null>(null);

  const attendance = Number(expectedAttendance);
  const equipmentLinesAreValid = equipmentLines.every(line => {
    const quantity = Number(line.quantity);
    return Boolean(line.equipmentType.trim()) && Number.isInteger(quantity) && quantity > 0;
  });
  const canSave = Boolean(name.trim())
    && Boolean(purpose.trim())
    && Boolean(proposedDate)
    && Boolean(slot)
    && Number.isInteger(attendance) && attendance > 0
    && equipmentLinesAreValid;
  const canSaveDraft = Boolean(name.trim());

  const availableSlots = selectedVenue
    ? SLOTS.filter(item => selectedVenue.operating_slots.includes(item.key))
    : SLOTS;

  const venueLayoutOptions = selectedVenue ? selectedVenue.layouts.map(item => item.layout) : [];
  const venueFacilityOptions = selectedVenue ? selectedVenue.facilities : [];
  const venueAccessibilityOptions = selectedVenue ? selectedVenue.accessibility_features : [];
  const preferredRoomLayout = layoutChoice === OTHERS ? layoutOtherText.trim() : layoutChoice;
  const requiredFacilities = [
    ...selectedFacilities,
    ...(facilitiesOthersEnabled ? listFromText(facilitiesOthersText) : []),
  ];
  const accessibilityNeeds = [
    ...selectedAccessibilityNeeds,
    ...(accessibilityOthersEnabled ? listFromText(accessibilityOthersText) : []),
  ];

  useEffect(() => {
    if (!api) return;
    let active = true;
    void (async () => {
      const response = await api('/api/venues');
      if (!active || !response.ok) return;
      const body = await response.json() as { venues: VenueSummary[] };
      setVenues(body.venues);
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  useEffect(() => {
    if (venueId === null) {
      setSelectedVenue(null);
      return;
    }
    if (!api) return;
    let active = true;
    void (async () => {
      const response = await api(`/api/venues/${venueId}`);
      if (!active || !response.ok) return;
      const body = await response.json() as { venue: Venue };
      setSelectedVenue(body.venue);
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [venueId]);

  useEffect(() => {
    if (slot && !availableSlots.some(item => item.key === slot)) setSlot(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedVenue]);

  // Venue-scoped choices only make sense against the currently selected venue. The very first
  // time a venue resolves (covers reopening a draft/event that already has a venue and saved
  // choices) reconciles rather than clears: values matching the venue's own lists become the
  // selected checkboxes/option, and anything else is preserved as "Others" text instead of being
  // silently dropped, so previously saved data is genuinely pulled back onto the page. Only a
  // later, real venue change (the organiser picking a different venue) clears choices that no
  // longer belong to it, per the confirmed "venue selection comes first" behaviour.
  const venueReconciledOnce = useRef(false);
  useEffect(() => {
    if (!selectedVenue) return;
    if (!venueReconciledOnce.current) {
      venueReconciledOnce.current = true;
      setLayoutChoice(current => {
        if (!current || current === OTHERS || venueLayoutOptions.includes(current)) return current;
        setLayoutOtherText(current);
        return OTHERS;
      });
      setSelectedFacilities(current => {
        const [known, custom] = partition(current, venueFacilityOptions);
        if (custom.length) {
          setFacilitiesOthersEnabled(true);
          setFacilitiesOthersText(custom.join(', '));
        }
        return known;
      });
      setSelectedAccessibilityNeeds(current => {
        const [known, custom] = partition(current, venueAccessibilityOptions);
        if (custom.length) {
          setAccessibilityOthersEnabled(true);
          setAccessibilityOthersText(custom.join(', '));
        }
        return known;
      });
      return;
    }
    setLayoutChoice(current =>
      current && current !== OTHERS && !venueLayoutOptions.includes(current) ? '' : current
    );
    setLayoutOtherText('');
    setSelectedFacilities(current => current.filter(item => venueFacilityOptions.includes(item)));
    setFacilitiesOthersEnabled(false);
    setFacilitiesOthersText('');
    setSelectedAccessibilityNeeds(current =>
      current.filter(item => venueAccessibilityOptions.includes(item))
    );
    setAccessibilityOthersEnabled(false);
    setAccessibilityOthersText('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedVenue]);

  // Load an existing draft's fields once, when this form is opened to resume it.
  useEffect(() => {
    if (!draftId || !api) { initialSnapshot.current = snapshot(); return; }
    let active = true;
    void (async () => {
      const response = await api(`/api/event-requests/${draftId}`);
      if (!active) return;
      if (!response.ok) { setLoadError(DRAFT_LOAD_FALLBACK); setLoadingDraft(false); return; }
      const body = await response.json() as { event_request: EventRequestDetail };
      applyDraft(body.event_request);
      setLoadingDraft(false);
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftId]);

  function applyDraft(detail: EventRequestDetail) {
    setCurrentDraftId(detail.id);
    setLastSavedAt(detail.last_saved_at);
    setName(detail.name);
    setPurpose(detail.purpose || '');
    setDescription(detail.description || '');
    setProposedDate(detail.proposed_date || '');
    setSlot(slotForTimes(detail.start_time, detail.end_time));
    setExpectedAttendance(detail.expected_attendance !== null ? String(detail.expected_attendance) : '');
    setLayoutChoice(detail.preferred_room_layout || '');
    setLayoutOtherText('');
    setSelectedFacilities(detail.required_facilities);
    setFacilitiesOthersEnabled(false);
    setFacilitiesOthersText('');
    setFacilitiesNotes(detail.facilities_notes || '');
    setSelectedAccessibilityNeeds(detail.accessibility_needs);
    setAccessibilityOthersEnabled(false);
    setAccessibilityOthersText('');
    setLocationPreference(detail.location_preference || '');
    setVenueNotes(detail.venue_notes || '');
    setVenueId(detail.venue_id);
    setRegistrationRequired(detail.registration_required);
    setRegistrationNotes(detail.registration_notes || '');
    setEquipmentLines(detail.equipment_requirements.map(line => ({
      id: line.id, equipmentType: line.equipment_type, quantity: String(line.quantity), notes: line.notes || '',
    })));
  }

  function snapshot() {
    return JSON.stringify({
      name, purpose, description, proposedDate, slot, expectedAttendance,
      layoutChoice, layoutOtherText,
      selectedFacilities, facilitiesOthersEnabled, facilitiesOthersText, facilitiesNotes,
      selectedAccessibilityNeeds, accessibilityOthersEnabled, accessibilityOthersText,
      locationPreference, venueNotes,
      venueId, registrationRequired, registrationNotes, equipmentLines,
    });
  }

  useEffect(() => {
    if (initialSnapshot.current === null) return;
    onUnsavedChanges?.(!submitted && snapshot() !== initialSnapshot.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, purpose, description, proposedDate, slot, expectedAttendance,
    layoutChoice, layoutOtherText,
    selectedFacilities, facilitiesOthersEnabled, facilitiesOthersText, facilitiesNotes,
    selectedAccessibilityNeeds, accessibilityOthersEnabled, accessibilityOthersText,
    locationPreference, venueNotes,
    venueId, registrationRequired, registrationNotes, equipmentLines, submitted]);

  if (!accessToken) return <section className="catalogue-auth" aria-labelledby="event-request-heading">
    <p className="eyebrow">Event request</p>
    <h2 id="event-request-heading">Sign in to create an event request</h2>
    <p>Event Organisers can request a proposed event once signed in.</p>
  </section>;

  if (loadingDraft) return <section className="catalogue" aria-labelledby="event-request-heading">
    <p className="eyebrow">Event request</p>
    <h2 id="event-request-heading">Loading draft…</h2>
  </section>;

  if (loadError) return <section className="catalogue" aria-labelledby="event-request-heading">
    <p className="eyebrow">Event request</p>
    <h2 id="event-request-heading">Request an event</h2>
    <p className="error" role="alert">{loadError}</p>
  </section>;

  const equipmentPayload = () => equipmentLines.map(line => ({
    equipment_type: line.equipmentType,
    quantity: Number(line.quantity),
    notes: line.notes || null,
  }));

  const saveDraft = async () => {
    if (!api || !canSaveDraft) return;
    setSavingDraft(true);
    setError(null);
    const payload = {
      name,
      purpose: purpose || null,
      description: description || null,
      proposed_date: proposedDate || null,
      ...(slot ? slotBounds(slot) : { start_time: null, end_time: null }),
      expected_attendance: Number.isInteger(attendance) && attendance > 0 ? attendance : null,
      preferred_room_layout: preferredRoomLayout || null,
      required_facilities: requiredFacilities,
      facilities_notes: facilitiesNotes || null,
      accessibility_needs: accessibilityNeeds,
      location_preference: locationPreference || null,
      venue_notes: venueNotes || null,
      venue_id: venueId,
      registration_required: registrationRequired,
      registration_notes: registrationNotes || null,
      equipment_requirements: equipmentPayload(),
    };
    const response = currentDraftId
      ? await api(`/api/event-requests/drafts/${currentDraftId}`, { method: 'PATCH', body: JSON.stringify(payload) })
      : await api('/api/event-requests/drafts', { method: 'POST', body: JSON.stringify(payload) });
    setSavingDraft(false);
    if (!response.ok) { setError(await responseError(response, DRAFT_SAVE_FALLBACK)); return; }
    const body = await response.json() as { event_request: EventRequestDetail };
    setCurrentDraftId(body.event_request.id);
    setLastSavedAt(body.event_request.last_saved_at);
    setNotice('Draft saved.');
    initialSnapshot.current = snapshot();
    onUnsavedChanges?.(false);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!api || !slot) return;
    setSaving(true);
    setError(null);
    const payload = {
      name,
      purpose,
      description: description || null,
      proposed_date: proposedDate,
      ...slotBounds(slot),
      expected_attendance: attendance,
      preferred_room_layout: preferredRoomLayout || null,
      required_facilities: requiredFacilities,
      facilities_notes: facilitiesNotes || null,
      accessibility_needs: accessibilityNeeds,
      location_preference: locationPreference || null,
      venue_notes: venueNotes || null,
      venue_id: venueId,
      registration_required: registrationRequired,
      registration_notes: registrationNotes || null,
      equipment_requirements: equipmentPayload(),
    };
    const response = currentDraftId
      ? await api(`/api/event-requests/drafts/${currentDraftId}/submit`, { method: 'POST', body: JSON.stringify(payload) })
      : await api('/api/event-requests', { method: 'POST', body: JSON.stringify(payload) });
    setSaving(false);
    if (!response.ok) { setError(await responseError(response, EVENT_REQUEST_FALLBACK)); return; }
    const body = await response.json() as { event_request: EventRequest };
    setNotice('Event request created.');
    setMappedSlots(body.event_request.mapped_slots);
    setSubmitted(true);
    onUnsavedChanges?.(false);
    onSubmitted?.();
  };

  return <section className="catalogue" aria-labelledby="event-request-heading">
    <header className="catalogue-header">
      <div>
        <p className="eyebrow">{currentDraftId ? 'Draft event request' : 'New event request'}</p>
        <h2 id="event-request-heading">Request an event</h2>
        <p className="catalogue-subtitle">Tell us what you need; a coordinator will follow up on the details.</p>
      </div>
      {onCancel && <button type="button" className="button button--secondary" onClick={onCancel}>Back to my requests</button>}
    </header>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {mappedSlots && <p className="hint">This falls in the {mappedSlots.length ? mappedSlots.join(', ') : 'no'} venue slot{mappedSlots.length === 1 ? '' : 's'}.</p>}
    {lastSavedAt && !submitted && <p className="hint">Last saved {new Date(lastSavedAt).toLocaleString()}.</p>}
    <form className="venue-form" onSubmit={submit} aria-label="Create event request">
      <div className="detail-heading"><div><p className="eyebrow">Core details</p><h3>What is the event?</h3></div></div>
      <label>Event name<input value={name} onChange={event => setName(event.target.value)} required /></label>
      <label>Purpose<input value={purpose} onChange={event => setPurpose(event.target.value)} required /></label>
      <label>Description<textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} /></label>
      <label>Proposed date<input type="date" value={proposedDate} onChange={event => setProposedDate(event.target.value)} required /></label>
      <label>Expected attendance<input type="number" min="1" step="1" value={expectedAttendance} onChange={event => setExpectedAttendance(event.target.value)} required /></label>

      <div className="detail-heading"><div><p className="eyebrow">Venue requirements (optional)</p><h3>Where would this work best?</h3></div></div>
      <label>Venue <span className="hint">Choose a venue to see its layout, facility and accessibility options</span>
        <select value={venueId ?? ''} onChange={event => setVenueId(event.target.value ? Number(event.target.value) : null)}>
          <option value="">No preference</option>
          {venues.map(venue => <option key={venue.id} value={venue.id}>{venue.name}</option>)}
        </select>
      </label>
      <label>Preferred room layout
        <select
          value={layoutChoice}
          disabled={!selectedVenue}
          onChange={event => setLayoutChoice(event.target.value)}
        >
          <option value="">No preference</option>
          {venueLayoutOptions.map(option => <option key={option} value={option}>{option}</option>)}
          <option value={OTHERS}>Others</option>
        </select>
      </label>
      {layoutChoice === OTHERS && <label>Custom room layout
        <input value={layoutOtherText} onChange={event => setLayoutOtherText(event.target.value)} disabled={!selectedVenue} />
      </label>}
      <fieldset disabled={!selectedVenue}>
        <legend>Required facilities</legend>
        {!selectedVenue && <p className="hint">Select a venue first to choose its facilities.</p>}
        {venueFacilityOptions.map(option => <label key={option}>
          <input
            type="checkbox"
            checked={selectedFacilities.includes(option)}
            onChange={() => setSelectedFacilities(current => toggleInList(current, option))}
          />
          {option}
        </label>)}
        <label>
          <input
            type="checkbox"
            checked={facilitiesOthersEnabled}
            onChange={event => setFacilitiesOthersEnabled(event.target.checked)}
          />
          Others
        </label>
        {facilitiesOthersEnabled && <input
          placeholder="Separate items with commas"
          value={facilitiesOthersText}
          onChange={event => setFacilitiesOthersText(event.target.value)}
        />}
      </fieldset>
      <label>Facilities notes<textarea value={facilitiesNotes} onChange={event => setFacilitiesNotes(event.target.value)} rows={2} /></label>
      <fieldset disabled={!selectedVenue}>
        <legend>Accessibility needs</legend>
        {!selectedVenue && <p className="hint">Select a venue first to choose its accessibility options.</p>}
        {venueAccessibilityOptions.map(option => <label key={option}>
          <input
            type="checkbox"
            checked={selectedAccessibilityNeeds.includes(option)}
            onChange={() => setSelectedAccessibilityNeeds(current => toggleInList(current, option))}
          />
          {option}
        </label>)}
        <label>
          <input
            type="checkbox"
            checked={accessibilityOthersEnabled}
            onChange={event => setAccessibilityOthersEnabled(event.target.checked)}
          />
          Others
        </label>
        {accessibilityOthersEnabled && <input
          placeholder="Separate items with commas"
          value={accessibilityOthersText}
          onChange={event => setAccessibilityOthersText(event.target.value)}
        />}
      </fieldset>
      <label>Location preference<input value={locationPreference} onChange={event => setLocationPreference(event.target.value)} /></label>
      <fieldset>
        <legend>Time slot</legend>
        <div className="slot-options">
          {SLOTS.map(item => {
            const disabled = Boolean(selectedVenue) && !availableSlots.some(available => available.key === item.key);
            return <label key={item.key} className={disabled ? 'slot-option--unavailable' : undefined}>
              <input
                type="radio"
                name="slot"
                checked={slot === item.key}
                disabled={disabled}
                onChange={() => setSlot(item.key)}
              />
              {item.label}
            </label>;
          })}
        </div>
      </fieldset>
      <label>Venue notes<textarea value={venueNotes} onChange={event => setVenueNotes(event.target.value)} rows={2} /></label>

      <EquipmentLineManager lines={equipmentLines} onChange={setEquipmentLines} />

      <fieldset>
        <legend>Registration</legend>
        <label><input type="checkbox" checked={registrationRequired} onChange={event => setRegistrationRequired(event.target.checked)} />Registration is required for this event</label>
        {registrationRequired && <label>Registration notes<textarea value={registrationNotes} onChange={event => setRegistrationNotes(event.target.value)} rows={2} /></label>}
      </fieldset>

      <div className="form-actions">
        {!submitted && <button type="button" className="button button--secondary" disabled={savingDraft || saving || !canSaveDraft} onClick={() => void saveDraft()}>{savingDraft ? 'Saving draft…' : 'Save as draft'}</button>}
        <button className="primary" disabled={saving || savingDraft || !canSave}>{saving ? 'Submitting…' : 'Submit event request'}</button>
      </div>
    </form>
  </section>;
}

function EquipmentLineManager({ lines, onChange }: { lines: EquipmentLineDraft[]; onChange: (lines: EquipmentLineDraft[]) => void }) {
  const updateLine = (index: number, field: 'equipmentType' | 'quantity' | 'notes', value: string) =>
    onChange(lines.map((line, current) => current === index ? { ...line, [field]: value } : line));
  const addLine = () => onChange([...lines, { equipmentType: '', quantity: '', notes: '' }]);
  const removeLine = (index: number) => onChange(lines.filter((_, current) => current !== index));
  return <section className="layouts">
    <div className="detail-heading"><div><h4>Equipment requirements (optional)</h4><p className="hint">Add zero or more items Technical Support Staff should prepare.</p></div></div>
    {lines.length === 0 ? <p>None recorded.</p> : <div className="layout-editor-list">
      {lines.map((line, index) => <div className="layout-editor-row equipment-editor-row" key={line.id ?? `new-${index}`}>
        <span className="layout-row-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
        <label><span>Equipment type</span><input aria-label={`Equipment type ${index + 1}`} value={line.equipmentType} onChange={event => updateLine(index, 'equipmentType', event.target.value)} required /></label>
        <label><span>Quantity</span><input aria-label={`Equipment quantity ${index + 1}`} type="number" min="1" step="1" value={line.quantity} onChange={event => updateLine(index, 'quantity', event.target.value)} required /></label>
        <label><span>Technical notes</span><input aria-label={`Equipment notes ${index + 1}`} value={line.notes} onChange={event => updateLine(index, 'notes', event.target.value)} /></label>
        <button type="button" className="layout-remove" aria-label={`Remove equipment line ${index + 1}`} title="Remove equipment line" onClick={() => removeLine(index)}><Trash2 size={17} /></button>
      </div>)}
    </div>}
    <div className="layout-form"><button type="button" className="icon-button" onClick={addLine}><Plus size={16} />Add equipment</button></div>
  </section>;
}
