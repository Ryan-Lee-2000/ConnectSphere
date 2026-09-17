import { FormEvent, ReactNode, useEffect, useState } from 'react';
import {
  Accessibility,
  ArrowUpRight,
  Armchair,
  Building2,
  CalendarClock,
  Clock3,
  MapPin,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react';
import { AnimatePresence, m } from 'motion/react';
import type { AccountRole } from './roles';

export type VenueLayout = { id: number; layout: string; capacity: number };
type LayoutDraft = { id?: number; layout: string; customLayout: string; capacity: string };
export type Venue = {
  id: number;
  name: string;
  location: string | null;
  description: string | null;
  facilities: string[];
  accessibility_features: string[];
  operating_slots: string[];
  setup_buffer_slots: number;
  turnaround_buffer_slots: number;
  layouts: VenueLayout[];
};
type VenueSummary = Pick<Venue, 'id' | 'name' | 'location'>;
export type ApiRequest = (path: string, init?: RequestInit) => Promise<Response>;

const slots = [
  ['AM', 'AM · 7am–12pm'],
  ['PM', 'PM · 1pm–6pm'],
  ['NIGHT', 'Night · 7pm–12am'],
] as const;
const standardRoomLayouts = ['classroom', 'theatre', 'boardroom', 'banquet', 'exhibition'];
const roomLayouts = [...standardRoomLayouts, 'other'];

function defaultRequest(token: string): ApiRequest {
  return (path, init = {}) => fetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init.headers },
  });
}

async function responseError(response: Response) {
  const body = await response.json().catch(() => ({}));
  return body.error || 'The venue catalogue request could not be completed.';
}

function listFromText(value: string) {
  return value.split(',').map(item => item.trim()).filter(Boolean);
}

function layoutLabel(layout: string) {
  return layout.replace(/\b\w/g, letter => letter.toUpperCase());
}

function layoutDraft(layout: VenueLayout): LayoutDraft {
  const name = layout.layout.toLowerCase();
  return standardRoomLayouts.includes(name)
    ? { id: layout.id, layout: name, customLayout: '', capacity: String(layout.capacity) }
    : { id: layout.id, layout: 'other', customLayout: layout.layout, capacity: String(layout.capacity) };
}

function layoutName(layout: LayoutDraft) {
  return layout.layout === 'other' ? layout.customLayout : layout.layout;
}

export function VenueCatalogue({
  accessToken,
  activeRole = 'venue_staff',
  onUnsavedChanges,
  request,
}: {
  accessToken: string | null;
  activeRole?: AccountRole;
  onUnsavedChanges?: (hasUnsavedChanges: boolean) => void;
  request?: ApiRequest;
}) {
  const api = request || (accessToken ? defaultRequest(accessToken) : undefined);
  const [venues, setVenues] = useState<VenueSummary[]>([]);
  const [selected, setSelected] = useState<Venue | null>(null);
  const [serverCanManage, setServerCanManage] = useState(false);
  const [loading, setLoading] = useState(Boolean(accessToken));
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editor, setEditor] = useState<'create' | 'edit' | null>(null);
  const [editingVenue, setEditingVenue] = useState<Venue | null>(null);

  const loadCatalogue = async (selectId?: number, keepEditor = false) => {
    if (!api) return;
    setLoading(true);
    setError(null);
    const response = await api('/api/venues');
    if (!response.ok) {
      setError(await responseError(response));
      setLoading(false);
      return;
    }
    const body = await response.json() as { venues: VenueSummary[]; capabilities: { can_manage: boolean } };
    setVenues(body.venues);
    setServerCanManage(body.capabilities.can_manage);
    const nextId = selectId ?? selected?.id;
    if (nextId && body.venues.some(venue => venue.id === nextId)) {
      await selectVenue(nextId, keepEditor);
    }
    setLoading(false);
  };

  const selectVenue = async (venueId: number, keepEditor = false) => {
    if (!api) return;
    if (!keepEditor) setEditor(null);
    setError(null);
    const response = await api(`/api/venues/${venueId}`);
    if (!response.ok) {
      setError(await responseError(response));
      return;
    }
    const body = await response.json() as { venue: Venue; capabilities: { can_manage: boolean } };
    setSelected(body.venue);
    setServerCanManage(body.capabilities.can_manage);
  };

  const toggleVenue = (venueId: number) => {
    if (selected?.id === venueId) {
      setSelected(null);
      return;
    }
    void selectVenue(venueId);
  };

  useEffect(() => {
    if (!accessToken) {
      setLoading(false);
      return;
    }
    void loadCatalogue();
    // The access token is the only session input; callers provide a stable request function in tests.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  const selectedIndex = selected ? venues.findIndex(venue => venue.id === selected.id) : -1;
  const canManage = serverCanManage && activeRole === 'venue_staff';
  const detailOrder = selectedIndex < 0
    ? 0
    : (selectedIndex % 2 === 0 && selectedIndex < venues.length - 1 ? selectedIndex + 1 : selectedIndex) * 2 + 1;

  if (!accessToken) return <section className="catalogue-auth" aria-labelledby="catalogue-heading">
    <p className="eyebrow">Venue catalogue</p>
    <h2 id="catalogue-heading">Sign in to view venues</h2>
    <p>Your signed-in role determines whether you can browse or manage venue information.</p>
  </section>;

  return <section className="catalogue" aria-labelledby="catalogue-heading">
    <header className="catalogue-header">
      <div><p className="eyebrow"><Building2 size={14} /> Venue catalogue</p><h2 id="catalogue-heading">Find the right space, faster.</h2><p className="catalogue-subtitle">A complete visual catalogue for confident event planning.</p></div>
      {canManage && <button type="button" className="primary icon-button" onClick={() => { setSelected(null); setEditingVenue(null); setEditor('create'); }}><Plus size={18} />Add venue</button>}
    </header>
    <div className="catalogue-intro"><div><span className="catalogue-kicker">Explore the collection</span><p>{venues.length} {venues.length === 1 ? 'venue' : 'venues'} in the catalogue</p></div><span className="catalogue-scope">Browse venue profiles and compare their recorded details.</span></div>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {loading ? <p role="status">Loading venue catalogue…</p> : <>
      {!editor && venues.length > 0 && <div className="venue-marketplace" aria-label="Venue catalogue results">
        {venues.map((venue, index) => <VenueCard key={venue.id} venue={venue} index={index} selected={selected?.id === venue.id} onSelect={() => toggleVenue(venue.id)} order={index * 2} />)}
        <AnimatePresence initial={false}>
          {selected && <m.div className="venue-card-details" key={selected.id} style={{ order: detailOrder }} layout initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: .2, ease: 'easeOut' }}><VenueDetails venue={selected} canManage={canManage} onEdit={() => { setEditingVenue(selected); setEditor('edit'); }} /></m.div>}
        </AnimatePresence>
      </div>}
      {!editor && venues.length === 0 && <div className="catalogue-empty"><Building2 size={28} /><h3>No venues to browse yet</h3><p>{canManage ? 'Build the catalogue by creating the first venue profile.' : 'Venue profiles will appear here when Venue Staff add them.'}</p>{canManage && <button type="button" className="primary icon-button" onClick={() => setEditor('create')}><Plus size={18} />Create first venue</button>}</div>}
      {editor === 'create' && api && <div className="venue-workspace"><VenueEditor api={api} onUnsavedChanges={onUnsavedChanges} onSaved={(venue, message) => { setNotice(message); setEditor(null); void loadCatalogue(venue.id); }} onCancel={() => setEditor(null)} /></div>}
      {editor === 'edit' && editingVenue && api && <div className="venue-workspace"><VenueEditor venue={editingVenue} api={api} onUnsavedChanges={onUnsavedChanges} onSaved={(venue, message) => { setNotice(message); setEditingVenue(null); setEditor(null); void loadCatalogue(venue.id); }} onCancel={() => { setEditingVenue(null); setEditor(null); }} /></div>}
    </>}
  </section>;
}

function VenueCard({ venue, index, selected, onSelect, order }: { venue: VenueSummary; index: number; selected: boolean; onSelect: () => void; order: number }) {
  const palette = index % 3;
  return <m.button type="button" className={`venue-card palette-${palette}${selected ? ' selected' : ''}`} style={{ order }} onClick={onSelect} aria-expanded={selected} aria-pressed={selected} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .16, ease: 'easeOut', delay: Math.min(index * .04, .16) }} whileHover={{ y: -2 }} whileTap={{ y: 0 }}>
    <span className="venue-card-art" aria-hidden="true"><span className="venue-card-index">{String(index + 1).padStart(2, '0')}</span><Building2 size={32} /><span className="venue-card-grid" /></span>
    <span className="venue-card-body"><span className="venue-card-label">Venue profile</span><strong>{venue.name}</strong><span className="venue-card-location"><MapPin size={15} />{venue.location || 'Location to be confirmed'}</span><span className="venue-card-action">Open profile <ArrowUpRight size={16} /></span></span>
  </m.button>;
}

function VenueDetails({ venue, canManage, onEdit }: { venue: Venue; canManage: boolean; onEdit: () => void }) {
  return <article aria-labelledby="venue-name">
    <div className="detail-heading"><div><p className="eyebrow">Venue details</p><h3 id="venue-name">{venue.name}</h3><p className="location"><MapPin size={16} />{venue.location || 'Location not recorded'}</p></div>{canManage && <button type="button" className="icon-button" onClick={onEdit}><Pencil size={16} />Edit venue</button>}</div>
    {venue.description && <p>{venue.description}</p>}
    <div className="detail-grid">
      <DetailList title="Facilities" icon={<Armchair size={18} />} values={venue.facilities} />
      <DetailList title="Accessibility features" icon={<Accessibility size={18} />} values={venue.accessibility_features} />
      <section><h4><Clock3 size={18} />Operating slots</h4>{venue.operating_slots.length ? <ul className="chips">{venue.operating_slots.map(slot => <li key={slot}>{slot === 'NIGHT' ? 'Night · 7pm–12am' : slots.find(item => item[0] === slot)?.[1]}</li>)}</ul> : <p>None recorded</p>}</section>
      <section className="preparation-card"><h4><CalendarClock size={18} />Preparation requirements</h4><dl><div><dt>Setup required</dt><dd>{venue.setup_buffer_slots ? 'Yes — one full slot immediately before an event' : 'No'}</dd></div><div><dt>Turnaround required</dt><dd>{venue.turnaround_buffer_slots ? 'Yes — one full slot immediately after an event' : 'No'}</dd></div></dl><p className="hint">These are stored venue requirements. Calendar availability and booking will apply the directly adjacent slots in a later story.</p></section>
    </div>
    <LayoutList layouts={venue.layouts} />
  </article>;
}

function DetailList({ title, icon, values }: { title: string; icon: ReactNode; values: string[] }) {
  return <section><h4>{icon}{title}</h4>{values.length ? <ul className="chips">{values.map(value => <li key={value}>{value}</li>)}</ul> : <p>None recorded</p>}</section>;
}

function VenueEditor({ venue, api, onSaved, onCancel, onUnsavedChanges }: { venue?: Venue; api: ApiRequest; onSaved: (venue: Venue, message: string) => void; onCancel: () => void; onUnsavedChanges?: (hasUnsavedChanges: boolean) => void }) {
  const [name, setName] = useState(venue?.name || '');
  const [location, setLocation] = useState(venue?.location || '');
  const [description, setDescription] = useState(venue?.description || '');
  const [facilities, setFacilities] = useState(venue?.facilities.join(', ') || '');
  const [accessibility, setAccessibility] = useState(venue?.accessibility_features.join(', ') || '');
  const [operatingSlots, setOperatingSlots] = useState(venue?.operating_slots || []);
  const [requiresSetup, setRequiresSetup] = useState(Boolean(venue?.setup_buffer_slots));
  const [requiresTurnaround, setRequiresTurnaround] = useState(Boolean(venue?.turnaround_buffer_slots));
  const [layouts, setLayouts] = useState<LayoutDraft[]>(() => venue?.layouts.map(layoutDraft) || []);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const initialDraft = JSON.stringify({
    name: venue?.name || '',
    location: venue?.location || '',
    description: venue?.description || '',
    facilities: venue?.facilities.join(', ') || '',
    accessibility: venue?.accessibility_features.join(', ') || '',
    operatingSlots: venue?.operating_slots || [],
    requiresSetup: Boolean(venue?.setup_buffer_slots),
    requiresTurnaround: Boolean(venue?.turnaround_buffer_slots),
    layouts: venue?.layouts.map(layoutDraft) || [],
  });
  const layoutsAreValid = layouts.every(layout => {
    const capacity = Number(layout.capacity);
    return Number.isInteger(capacity) && capacity > 0
      && (layout.layout !== 'other' || Boolean(layout.customLayout.trim()));
  });
  const canSave = Boolean(name.trim()) && operatingSlots.length > 0 && layoutsAreValid;

  useEffect(() => {
    const currentDraft = JSON.stringify({
      name,
      location,
      description,
      facilities,
      accessibility,
      operatingSlots,
      requiresSetup,
      requiresTurnaround,
      layouts,
    });
    onUnsavedChanges?.(currentDraft !== initialDraft);
  }, [accessibility, description, facilities, initialDraft, layouts, location, name, onUnsavedChanges, operatingSlots, requiresSetup, requiresTurnaround]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true); setError(null);
    const payload = { name, location, description, facilities: listFromText(facilities), accessibility_features: listFromText(accessibility), operating_slots: operatingSlots, setup_buffer_slots: requiresSetup ? 1 : 0, turnaround_buffer_slots: requiresTurnaround ? 1 : 0, layouts: layouts.map(layout => ({ layout: layoutName(layout), capacity: Number(layout.capacity) })) };
    const response = await api(venue ? `/api/venues/${venue.id}` : '/api/venues', { method: venue ? 'PATCH' : 'POST', body: JSON.stringify(payload) });
    setSaving(false);
    if (!response.ok) { setError(await responseError(response)); return; }
    const body = await response.json() as { venue: Venue };
    onUnsavedChanges?.(false);
    onSaved(body.venue, venue ? 'Venue profile and room layouts updated.' : 'Venue and its room layouts created.');
  };

  return <form className="venue-form" onSubmit={submit} aria-label={venue ? 'Edit venue' : 'Create venue'}>
    <div className="detail-heading"><div><p className="eyebrow">{venue ? 'Update venue' : 'New venue'}</p><h3>{venue ? `Edit ${venue.name}` : 'Create a venue'}</h3><p className="form-intro">Maintain the venue profile, its fixed operating slots, and supported room layouts in one place.</p></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    <label>Venue name<input value={name} onChange={event => setName(event.target.value)} required /></label>
    <label>Location<input value={location} onChange={event => setLocation(event.target.value)} /></label>
    <label>Description<textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} /></label>
    <label>Facilities <span className="hint">Separate items with commas</span><input value={facilities} onChange={event => setFacilities(event.target.value)} /></label>
    <label>Accessibility features <span className="hint">Separate items with commas</span><input value={accessibility} onChange={event => setAccessibility(event.target.value)} /></label>
    <fieldset><legend><Clock3 size={18} />Operating slots</legend><p className="hint">The same selected AM, PM and Night slots apply every day in Release 1. Select at least one slot.</p><div className="slot-options">{slots.map(([value, label]) => <label key={value}><input type="checkbox" checked={operatingSlots.includes(value)} onChange={() => setOperatingSlots(current => current.includes(value) ? current.filter(slot => slot !== value) : [...current, value])} />{label}</label>)}</div></fieldset>
    <section className="buffer-section"><div><h4><CalendarClock size={18} />Preparation requirements</h4><p className="hint">Each requirement uses at most one full operating slot. Setup uses the slot immediately before an event and turnaround uses the slot immediately after it; calendar availability will apply this rule in a later story.</p></div><div className="buffer-fields"><label><input type="checkbox" checked={requiresSetup} onChange={event => setRequiresSetup(event.target.checked)} />Require one setup slot immediately before an event</label><label><input type="checkbox" checked={requiresTurnaround} onChange={event => setRequiresTurnaround(event.target.checked)} />Require one turnaround slot immediately after an event</label></div></section>
    <LayoutManager layouts={layouts} onChange={setLayouts} />
    <div className="form-actions"><button type="button" onClick={() => { onUnsavedChanges?.(false); onCancel(); }}>Cancel</button><button className="primary" disabled={saving || !canSave}>{saving ? 'Saving…' : 'Save venue'}</button></div>
  </form>;
}

function LayoutList({ layouts }: { layouts: VenueLayout[] }) {
  return <section className="layouts"><div className="detail-heading"><div><h4><Armchair size={18} />Supported room layouts</h4><p className="hint">Stated capacities are specific to each room arrangement.</p></div></div>
    {layouts.length === 0 ? <p>None recorded</p> : <table><thead><tr><th>Layout</th><th>Stated capacity</th></tr></thead><tbody>{layouts.map(layout => <tr key={layout.id}><td>{layoutLabel(layout.layout)}</td><td>{layout.capacity}</td></tr>)}</tbody></table>}
  </section>;
}

function LayoutManager({ layouts, onChange }: { layouts: LayoutDraft[]; onChange: (layouts: LayoutDraft[]) => void }) {
  const updateLayout = (index: number, field: 'layout' | 'customLayout' | 'capacity', value: string) => onChange(layouts.map((layout, current) => current === index ? { ...layout, [field]: value } : layout));
  const addLayout = () => onChange([...layouts, { layout: roomLayouts[0], customLayout: '', capacity: '' }]);
  const removeLayout = (index: number) => onChange(layouts.filter((_, current) => current !== index));
  return <section className="layouts"><div className="detail-heading"><div><h4><Armchair size={18} />Supported room layouts</h4><p className="hint">Choose a standard layout, or select Other to name a custom arrangement.</p></div></div>
    {layouts.length === 0 ? <p>None recorded. Add a room layout before saving if you want to record one now.</p> : <div className="layout-editor-list">{layouts.map((layout, index) => <div className="layout-editor-row" key={layout.id ?? `new-${index}`}><span className="layout-row-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span><label><span>Layout</span><select aria-label={`Room layout ${index + 1}`} value={layout.layout} onChange={event => updateLayout(index, 'layout', event.target.value)}>{roomLayouts.map(option => <option key={option} value={option}>{layoutLabel(option)}</option>)}</select>{layout.layout === 'other' && <input className="custom-layout-name" aria-label={`Custom room layout ${index + 1}`} placeholder="e.g. Cabaret or U-shape" value={layout.customLayout} onChange={event => updateLayout(index, 'customLayout', event.target.value)} required />}</label><label><span>Capacity</span><span className="capacity-input"><input aria-label={`Stated capacity ${index + 1}`} type="number" min="1" step="1" value={layout.capacity} onChange={event => updateLayout(index, 'capacity', event.target.value)} required /><span>Guests</span></span></label><button type="button" className="layout-remove" aria-label={`Remove ${layoutLabel(layoutName(layout) || 'custom')} layout`} title="Remove layout" onClick={() => removeLayout(index)}><Trash2 size={17} /></button></div>)}</div>}
    <div className="layout-form"><button type="button" className="icon-button" onClick={addLayout}><Plus size={16} />Add layout</button><p className="hint">Changes are saved only when you select Save venue.</p></div>
  </section>;
}
