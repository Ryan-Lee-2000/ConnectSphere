import { FormEvent, useEffect, useState } from 'react';
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

const EVENT_REQUEST_FALLBACK = 'The event request could not be created.';

function listFromText(value: string) {
  return value.split(',').map(item => item.trim()).filter(Boolean);
}

function slotBounds(key: SlotKey) {
  const slot = SLOTS.find(item => item.key === key);
  return slot ? { start_time: slot.start, end_time: slot.end } : null;
}

export function EventRequestForm({ accessToken, request, onSubmitted }: { accessToken: string | null; request?: ApiRequest; onSubmitted?: () => void }) {
  const api = request || (accessToken ? defaultRequest(accessToken) : undefined);
  const [name, setName] = useState('');
  const [purpose, setPurpose] = useState('');
  const [description, setDescription] = useState('');
  const [proposedDate, setProposedDate] = useState('');
  const [slot, setSlot] = useState<SlotKey | null>(null);
  const [expectedAttendance, setExpectedAttendance] = useState('');
  const [preferredRoomLayout, setPreferredRoomLayout] = useState('');
  const [requiredFacilities, setRequiredFacilities] = useState('');
  const [facilitiesNotes, setFacilitiesNotes] = useState('');
  const [accessibilityNeeds, setAccessibilityNeeds] = useState('');
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

  const availableSlots = selectedVenue
    ? SLOTS.filter(item => selectedVenue.operating_slots.includes(item.key))
    : SLOTS;

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

  if (!accessToken) return <section className="catalogue-auth" aria-labelledby="event-request-heading">
    <p className="eyebrow">Event request</p>
    <h2 id="event-request-heading">Sign in to create an event request</h2>
    <p>Event Organisers can request a proposed event once signed in.</p>
  </section>;

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
      required_facilities: listFromText(requiredFacilities),
      facilities_notes: facilitiesNotes || null,
      accessibility_needs: accessibilityNeeds || null,
      location_preference: locationPreference || null,
      venue_notes: venueNotes || null,
      venue_id: venueId,
      registration_required: registrationRequired,
      registration_notes: registrationNotes || null,
      equipment_requirements: equipmentLines.map(line => ({
        equipment_type: line.equipmentType,
        quantity: Number(line.quantity),
        notes: line.notes || null,
      })),
    };
    const response = await api('/api/event-requests', { method: 'POST', body: JSON.stringify(payload) });
    setSaving(false);
    if (!response.ok) { setError(await responseError(response, EVENT_REQUEST_FALLBACK)); return; }
    const body = await response.json() as { event_request: EventRequest };
    setNotice('Event request created.');
    setMappedSlots(body.event_request.mapped_slots);
    onSubmitted?.();
  };

  return <section className="catalogue" aria-labelledby="event-request-heading">
    <header className="catalogue-header">
      <div>
        <p className="eyebrow">New event request</p>
        <h2 id="event-request-heading">Request an event</h2>
        <p className="catalogue-subtitle">Tell us what you need; a coordinator will follow up on the details.</p>
      </div>
    </header>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {mappedSlots && <p className="hint">This falls in the {mappedSlots.length ? mappedSlots.join(', ') : 'no'} venue slot{mappedSlots.length === 1 ? '' : 's'}.</p>}
    <form className="venue-form" onSubmit={submit} aria-label="Create event request">
      <div className="detail-heading"><div><p className="eyebrow">Core details</p><h3>What is the event?</h3></div></div>
      <label>Event name<input value={name} onChange={event => setName(event.target.value)} required /></label>
      <label>Purpose<input value={purpose} onChange={event => setPurpose(event.target.value)} required /></label>
      <label>Description<textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} /></label>
      <label>Proposed date<input type="date" value={proposedDate} onChange={event => setProposedDate(event.target.value)} required /></label>
      <label>Expected attendance<input type="number" min="1" step="1" value={expectedAttendance} onChange={event => setExpectedAttendance(event.target.value)} required /></label>

      <div className="detail-heading"><div><p className="eyebrow">Venue requirements (optional)</p><h3>Where would this work best?</h3></div></div>
      <label>Preferred room layout<input value={preferredRoomLayout} onChange={event => setPreferredRoomLayout(event.target.value)} /></label>
      <label>Required facilities <span className="hint">Separate items with commas</span><input value={requiredFacilities} onChange={event => setRequiredFacilities(event.target.value)} /></label>
      <label>Facilities notes<textarea value={facilitiesNotes} onChange={event => setFacilitiesNotes(event.target.value)} rows={2} /></label>
      <label>Accessibility needs<textarea value={accessibilityNeeds} onChange={event => setAccessibilityNeeds(event.target.value)} rows={2} /></label>
      <label>Location preference<input value={locationPreference} onChange={event => setLocationPreference(event.target.value)} /></label>
      <label>Venue <span className="hint">Selecting a venue may restrict which time slots are available</span>
        <select value={venueId ?? ''} onChange={event => setVenueId(event.target.value ? Number(event.target.value) : null)}>
          <option value="">No preference</option>
          {venues.map(venue => <option key={venue.id} value={venue.id}>{venue.name}</option>)}
        </select>
      </label>
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

      <div className="form-actions"><button className="primary" disabled={saving || !canSave}>{saving ? 'Submitting…' : 'Submit event request'}</button></div>
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
