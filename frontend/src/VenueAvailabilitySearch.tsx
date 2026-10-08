import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Accessibility, ArrowUpRight, BadgeCheck, Building2, CalendarDays, CircleAlert, CircleCheck, ListChecks, MapPin, Search, UsersRound, X } from 'lucide-react';
import { AnimatePresence, m } from 'motion/react';
import { defaultRequest, responseError, type ApiRequest } from './api';
import { SLOTS, type SlotKey } from './slots';
import { VenueBookingNotice, VenueBookingRequest, type VenueBooking } from './VenueBookingRequest';
import { VenueBookingPanel } from './VenueBookingWithdrawal';

type MatchingLayout = { layout: string; capacity: number };
type SuitabilityCheck = { key: string; label: string; passed: boolean; detail: string };
type Suitability = { suitable: boolean; checks: SuitabilityCheck[]; timing?: Timing | null };
type Timing = { event: { start: string; end: string }; occupied: { start: string; end: string }; setup_minutes: number; turnaround_minutes: number };
type AvailableVenue = { timing?: Timing; id: number; name: string; location: string | null; maximum_layout_capacity: number | null; matching_layouts: MatchingLayout[]; suitability?: Suitability };
type FilterOptions = { facilities: string[]; accessibility_needs: string[]; locations: string[] };
const ROOM_LAYOUT_OPTIONS = ['Theatre', 'Classroom', 'Boardroom', 'Banquet', 'Cabaret', 'U-shaped'];
const EMPTY_REQUIREMENTS: string[] = [];
const EMPTY_FILTER_OPTIONS: FilterOptions = { facilities: [], accessibility_needs: [], locations: [] };

export function VenueAvailabilitySearch({ accessToken, eventId, initialDate, initialSlots, initialStartTime, initialEndTime, expectedAttendance, preferredRoomLayout, requiredFacilities = EMPTY_REQUIREMENTS, accessibilityNeeds: initialAccessibilityNeeds = EMPTY_REQUIREMENTS, locationPreference = null, request }: {
  accessToken: string; eventId: number; initialDate: string | null; initialSlots?: string[]; initialStartTime?: string | null; initialEndTime?: string | null; expectedAttendance: number | null; preferredRoomLayout: string | null; requiredFacilities?: string[]; accessibilityNeeds?: string[]; locationPreference?: string | null; request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [accessToken, request]);
  const selectableSlots = (slots: string[]) => slots.filter((slot): slot is SlotKey => SLOTS.some(candidate => candidate.key === slot));
  // Search controls are local copies; editing filters never writes back to the event.
  const [searchDate, setSearchDate] = useState(initialDate || '');
  const [selectedSlots, setSelectedSlots] = useState<SlotKey[]>(selectableSlots(initialSlots || []));
  const [attendance, setAttendance] = useState(initialAttendance(expectedAttendance));
  const [layout, setLayout] = useState(normaliseLayoutChoice(preferredRoomLayout));
  const [facilities, setFacilities] = useState(normaliseRequirementValues(requiredFacilities));
  const [accessibilityNeeds, setAccessibilityNeeds] = useState(normaliseRequirementValues(initialAccessibilityNeeds));
  const [location, setLocation] = useState(locationPreference || '');
  const [filterOptions, setFilterOptions] = useState<FilterOptions>(EMPTY_FILTER_OPTIONS);
  const [venues, setVenues] = useState<AvailableVenue[] | null>(null);
  const [searched, setSearched] = useState(false);
  const [exactTiming, setExactTiming] = useState(false);
  const [startTime, setStartTime] = useState(initialTime(initialStartTime));
  const [endTime, setEndTime] = useState(initialTime(initialEndTime));
  const [appliedSummary, setAppliedSummary] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedVenueId, setSelectedVenueId] = useState<number | null>(null);
  const [requestedBooking, setRequestedBooking] = useState<VenueBooking | null>(null);
  const [bookingVersion, setBookingVersion] = useState(0);

  // These controls start from the event snapshot; reopening search remounts this component with fresh data.
  // Keeping later parent renders from resetting local edits prevents a cleared filter from reappearing.
  useEffect(() => {
    let active = true;
    const optionsRequest = api(`/api/event-requests/${eventId}/venue-filter-options`);
    if (!optionsRequest) return () => { active = false; };
    void optionsRequest.then(async response => {
      if (!response.ok || !active) return;
      const body = await response.json() as { filter_options?: Partial<FilterOptions>; capabilities?: { exact_venue_timing?: boolean } };
      if (!active) return;
      setExactTiming(body.capabilities?.exact_venue_timing === true);
      if (!body.filter_options) return;
      setFilterOptions({
        facilities: normaliseRequirementValues(body.filter_options.facilities || []),
        accessibility_needs: normaliseRequirementValues(body.filter_options.accessibility_needs || []),
        locations: normaliseRequirementValues(body.filter_options.locations || []),
      });
    }).catch(() => undefined);
    return () => { active = false; };
  }, [api, eventId]);

  function toggleSlot(slot: SlotKey) {
    setSelectedSlots(current => current.includes(slot)
      ? current.filter(candidate => candidate !== slot)
      : SLOTS.filter(candidate => [...current, slot].includes(candidate.key)).map(candidate => candidate.key));
  }
  async function search() {
    if (!canSearch || loading) return;
    setLoading(true); setError(null);
    const parameters = new URLSearchParams({ date: searchDate });
    if (exactTiming) { parameters.set('start_time', startTime); parameters.set('end_time', endTime); }
    else selectedSlots.forEach(slot => parameters.append('slot', slot));
    parameters.set('expected_attendance', attendance);
    parameters.set('preferred_room_layout', layout.trim());
    appendRequirementFilters(parameters, 'required_facility', facilities);
    appendRequirementFilters(parameters, 'accessibility_need', accessibilityNeeds);
    parameters.set('location_preference', location.trim());
    try {
      const response = await api(`/api/event-requests/${eventId}/available-venues?${parameters.toString()}`);
      if (!response.ok) { setError(await responseError(response, 'Could not search venue availability. Try again.')); return; }
      const body = await response.json() as { venues?: unknown };
      if (!Array.isArray(body.venues)) throw new Error('Invalid response');
      setVenues(body.venues as AvailableVenue[]); setAppliedSummary(summary); setSearched(true); setSelectedVenueId(null);
    } catch { setError('Could not search venue availability. Try again.'); }
    finally { setLoading(false); }
  }
  const attendanceValue = Number(attendance);
  const canSearch = Boolean(searchDate && (exactTiming ? validExactTimes(startTime, endTime) : selectedSlots.length) && Number.isInteger(attendanceValue) && attendanceValue > 0);
  const summary = `${searchDate || 'No date'} · ${exactTiming ? `${startTime}–${endTime} SGT` : selectedSlots.map(slot => SLOTS.find(item => item.key === slot)?.label.split(' · ')[0] || slot).join(', ') || 'No slots'}`;
  const selectedVenue = venues?.find(venue => venue.id === selectedVenueId) || null;
  const selectedIndex = selectedVenue ? venues?.findIndex(venue => venue.id === selectedVenue.id) ?? -1 : -1;
  const detailOrder = selectedIndex < 0 ? 0 : (selectedIndex % 2 === 0 && selectedIndex < (venues?.length || 0) - 1 ? selectedIndex + 1 : selectedIndex) * 2 + 1;
  const layoutLabel = (layout: string) => layout.replace(/\b\w/g, letter => letter.toUpperCase());
  const layoutOptions = layout && !ROOM_LAYOUT_OPTIONS.some(option => option.toLowerCase() === layout.toLowerCase())
    ? [layout, ...ROOM_LAYOUT_OPTIONS] : ROOM_LAYOUT_OPTIONS;
  const locationOptions = mergeOptions(filterOptions.locations, location ? [location] : []);
  return <section className="venue-availability" aria-labelledby="venue-availability-title">
    <VenueBookingPanel api={api} eventId={eventId} refreshKey={bookingVersion} onWithdrawn={() => { setRequestedBooking(null); if (searched) void search(); }} />
    <form className="venue-availability__panel" onSubmit={submit => { submit.preventDefault(); void search(); }}>
      <header className="venue-availability__filter-header"><div><p className="eyebrow">Venue catalogue search</p><h2 id="venue-availability-title">Search filters</h2></div><p>Start with the event’s details, then adjust any filter to compare venue options.</p></header>
      <div className="venue-availability__fields">
        <label className="field venue-availability__date"><span><CalendarDays size={15} /> Singapore date</span><input aria-label="Singapore date" onChange={event => setSearchDate(event.target.value)} type="date" value={searchDate} /></label>
        <label className="field venue-availability__attendance"><span><UsersRound size={15} /> Expected attendance</span><input aria-label="Expected attendance" min="1" onChange={event => setAttendance(event.target.value)} inputMode="numeric" type="number" value={attendance} /></label>
        {exactTiming ? <fieldset className="venue-availability__exact-times"><legend>Event times · Singapore</legend>
          <label className="field">Event start (SGT)<input type="time" step="900" value={startTime} onChange={event => setStartTime(event.target.value)} /></label>
          <label className="field">Event end (SGT)<input type="time" step="900" disabled={endTime === '24:00'} value={endTime === '24:00' ? '' : endTime} onChange={event => setEndTime(event.target.value)} /></label>
          <label><input type="checkbox" checked={endTime === '24:00'} onChange={event => setEndTime(event.target.checked ? '24:00' : '')} />End at midnight (24:00)</label>
        </fieldset> : <fieldset className="venue-availability__slots"><legend>Required slots</legend><div>{SLOTS.map(slot => <label key={slot.key}><input checked={selectedSlots.includes(slot.key)} onChange={() => toggleSlot(slot.key)} type="checkbox" /><span>{slot.label}</span></label>)}</div></fieldset>}
        <label className="field venue-availability__layout"><span>Room layout <em>Optional</em></span><span className="venue-availability__layout-control"><select aria-label="Room layout" onChange={event => setLayout(event.target.value)} value={layout}><option value="">Any supported layout</option>{layoutOptions.map(option => <option key={option} value={option}>{option}</option>)}</select>{layout && <button className="venue-availability__clear-layout" onClick={() => setLayout('')} type="button">Clear</button>}</span></label>
        <RequirementPicker icon={<ListChecks size={15} />} label="Required facilities" options={filterOptions.facilities} selected={facilities} onChange={setFacilities} />
        <RequirementPicker icon={<Accessibility size={15} />} label="Accessibility needs" options={filterOptions.accessibility_needs} selected={accessibilityNeeds} onChange={setAccessibilityNeeds} />
        <label className="field venue-availability__location"><span><MapPin size={15} /> Preferred venue location <em>Optional</em></span><select aria-label="Preferred venue location" onChange={event => setLocation(event.target.value)} value={location}><option value="">Any location</option>{locationOptions.map(option => <option key={option} value={option}>{option}</option>)}</select><small>Choose an area or address recorded on a venue profile.</small></label>
      </div>
      <footer className="venue-availability__actions"><p>Searches are read-only. A result is not a booking or a hold.</p><button className="button button--primary venue-availability__submit" disabled={!canSearch || loading} type="submit"><Search size={17} />{loading ? 'Checking…' : 'Search venues'}</button></footer>
    </form>
    {!canSearch && <p className="venue-availability__hint" role="status">{exactTiming ? 'Choose a date, quarter-hour start/end times and positive attendance. End must follow start.' : 'Choose a date, at least one slot and a positive expected attendance to search.'}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {requestedBooking && <VenueBookingNotice booking={requestedBooking} />}
    {searched && !error && <div className="venue-availability__results" aria-live="polite"><p className="venue-availability__summary">Results for <strong>{appliedSummary}</strong> · <strong>{attendanceValue} guests</strong>{layout.trim() ? <> · <strong>{layoutLabel(layout.trim())}</strong></> : null}</p>
      {venues?.length === 0 ? <div className="organisation-events__empty" role="status"><strong>No venues are available for this search.</strong><span>Keep the date and slots, then adjust them to explore another option.</span></div> : <div className="venue-availability__marketplace venue-marketplace" aria-label="Available venue results">
        {venues?.map((venue, index) => <m.button type="button" key={venue.id} className={`venue-card venue-availability__card palette-${index % 3}${selectedVenueId === venue.id ? ' selected' : ''}`} style={{ order: index * 2 }} onClick={() => setSelectedVenueId(current => current === venue.id ? null : venue.id)} aria-expanded={selectedVenueId === venue.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .16, ease: 'easeOut', delay: Math.min(index * .04, .16) }} whileHover={{ y: -2 }} whileTap={{ y: 0 }}>
          <span className="venue-card-art" aria-hidden="true"><span className="venue-card-index">{String(index + 1).padStart(2, '0')}</span><Building2 size={32} /><span className="venue-card-grid" /></span>
          <span className="venue-card-body"><span className="venue-card-label">Available venue</span><strong>{venue.name}</strong><span className="venue-card-location"><MapPin size={15} />{venue.location || 'Location to be confirmed'}</span><span className="venue-availability__capacity">Fits {attendanceValue} guests</span>{venue.timing && <span><span>Advertised: {formatInterval(venue.timing.event)}</span><br /><span>Occupied: {formatInterval(venue.timing.occupied)}</span><br /><span>Setup {venue.timing.setup_minutes} min · Turnaround {venue.timing.turnaround_minutes} min</span></span>}{venue.suitability && <SuitabilityBadge suitability={venue.suitability} />}<span className="venue-card-action"><BadgeCheck size={16} />{exactTiming ? 'Available for selected times' : 'Available for selected slots'} <ArrowUpRight size={16} /></span></span>
        </m.button>)}
        <AnimatePresence initial={false}>{selectedVenue && <m.div className="venue-card-details venue-availability__detail" key={selectedVenue.id} style={{ order: detailOrder }} layout initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: .2, ease: 'easeOut' }}>
          <section aria-labelledby={`availability-detail-${selectedVenue.id}`}><p className="eyebrow">{selectedVenue.suitability?.suitable ? <BadgeCheck size={14} /> : <CircleAlert size={14} />}{selectedVenue.suitability?.suitable ? ' Suitable for this event' : ' Event requirements to resolve'}</p><h3 id={`availability-detail-${selectedVenue.id}`}>{selectedVenue.name} {selectedVenue.suitability?.suitable ? 'is suitable' : 'does not meet every event requirement'}</h3><p className="venue-availability__detail-copy">Search filters are exploratory. This assessment uses the saved, current event requirements and creates neither a booking nor a hold.</p>{selectedVenue.suitability && <div className="venue-suitability__checks" aria-label={`Suitability checks for ${selectedVenue.name}`}>{selectedVenue.suitability.checks.map(check => <div className={`venue-suitability__check ${check.passed ? 'venue-suitability__check--pass' : 'venue-suitability__check--fail'}`} key={check.key}><span aria-hidden="true">{check.passed ? <CircleCheck size={18} /> : <CircleAlert size={18} />}</span><div><strong>{check.label}</strong><p>{check.detail}</p></div></div>)}</div>}{selectedVenue.suitability?.timing && <p>Saved event advertised: {formatInterval(selectedVenue.suitability.timing.event)}<br />Saved event occupied: {formatInterval(selectedVenue.suitability.timing.occupied)}</p>}<dl className="venue-availability__detail-facts"><div><dt>Applied search</dt><dd>{appliedSummary}</dd></div><div><dt>Search attendance</dt><dd>{attendanceValue} guests</dd></div><div><dt>Matching layout{selectedVenue.matching_layouts.length === 1 ? '' : 's'}</dt><dd>{selectedVenue.matching_layouts.map(layout => `${layoutLabel(layout.layout)} (${layout.capacity})`).join(', ')}</dd></div><div><dt>Search filters</dt><dd>{requirementSummary(facilities, accessibilityNeeds, location)}</dd></div></dl>{!exactTiming && selectedVenue.suitability?.suitable && <VenueBookingRequest api={api} eventId={eventId} venueId={selectedVenue.id} venueName={selectedVenue.name} expectedAttendance={expectedAttendance} preferredRoomLayout={preferredRoomLayout} onRequested={booking => { setRequestedBooking(booking); setBookingVersion(version => version + 1); void search(); }} />}</section>
        </m.div>}</AnimatePresence>
      </div>}
    </div>}
  </section>;
}

function SuitabilityBadge({ suitability }: { suitability: Suitability }) {
  return <span className={`venue-suitability__badge ${suitability.suitable ? 'venue-suitability__badge--pass' : 'venue-suitability__badge--fail'}`}>
    {suitability.suitable ? <BadgeCheck size={15} /> : <CircleAlert size={15} />}
    {suitability.suitable ? 'Suitable for this event' : 'Does not meet current event requirements'}
  </span>;
}

function initialAttendance(value: number | null) {
  return value && value > 0 ? String(value) : '';
}

function normaliseLayoutChoice(value: string | null) {
  if (!value) return '';
  return ROOM_LAYOUT_OPTIONS.find(option => option.toLowerCase() === value.trim().toLowerCase()) || value;
}

function normaliseRequirementValues(values: string[]) {
  const unique = new Map<string, string>();
  values.forEach(value => { const cleaned = value.trim(); if (cleaned) unique.set(cleaned.toLowerCase(), cleaned); });
  return [...unique.values()];
}
function mergeOptions(...groups: string[][]) { return normaliseRequirementValues(groups.flat()); }
function appendRequirementFilters(parameters: URLSearchParams, name: string, values: string[]) {
  if (values.length) values.forEach(item => parameters.append(name, item)); else parameters.append(name, '');
}
function requirementSummary(facilities: string[], accessibility: string[], location: string) {
  const parts = [facilities.join(', '), accessibility.join(', '), location.trim()].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'No extra requirements';
}

function RequirementPicker({ icon, label, options, selected, onChange }: { icon: ReactNode; label: string; options: string[]; selected: string[]; onChange: (values: string[]) => void }) {
  const available = options.filter(option => !selected.some(value => value.toLowerCase() === option.toLowerCase()));
  function addOption(value: string) {
    if (value) onChange(normaliseRequirementValues([...selected, value]));
  }
  return <fieldset className="venue-availability__requirements requirement-picker" aria-label={label}>
    <legend>{icon} {label} <em>Optional</em></legend>
    {selected.length > 0 && <div className="requirement-picker__chips" aria-label={`Selected ${label}`}>{selected.map(value => <span key={value} className="requirement-picker__chip">{value}<button aria-label={`Remove ${value}`} onClick={() => onChange(selected.filter(item => item !== value))} type="button"><X size={13} /></button></span>)}</div>}
    <label className="requirement-picker__select"><span>Choose from catalogue</span><select aria-label={`Add ${label}`} onChange={event => { addOption(event.target.value); event.currentTarget.value = ''; }} defaultValue=""><option value="">Select an option</option>{available.map(option => <option key={option} value={option}>{option}</option>)}</select></label>
    {available.length > 0 && <div className="requirement-picker__suggestions" aria-label={`Suggested ${label}`}>{available.slice(0, 4).map(option => <button key={option} onClick={() => addOption(option)} type="button">+ {option}</button>)}</div>}
  </fieldset>;
}

function validExactTimes(start: string, end: string) {
  const valid = /^(?:[01]\d|2[0-3]):(?:00|15|30|45)$/;
  return valid.test(start) && (valid.test(end) || end === '24:00') && end > start;
}
function formatInterval(interval: { start: string; end: string }) {
  const format = (value: string) => new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Singapore', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value));
  return `${format(interval.start)} – ${format(interval.end)} SGT`;
}

function initialTime(value?: string | null) {
  return value?.length === 8 && value.endsWith(':00') ? value.slice(0, 5) : value || '';
}
