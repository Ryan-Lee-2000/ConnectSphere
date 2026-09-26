import { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, BadgeCheck, Building2, MapPin } from 'lucide-react';
import { AnimatePresence, m } from 'motion/react';
import { defaultRequest, responseError, type ApiRequest } from './api';
import { SLOTS, type SlotKey } from './slots';

type AvailableVenue = { id: number; name: string; location: string | null; maximum_layout_capacity: number | null };

export function VenueAvailabilitySearch({ accessToken, eventId, initialDate, initialSlots, request }: {
  accessToken: string; eventId: number; initialDate: string | null; initialSlots?: string[]; request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [accessToken, request]);
  const selectableSlots = (slots: string[]) => slots.filter((slot): slot is SlotKey => SLOTS.some(candidate => candidate.key === slot));
  const [searchDate, setSearchDate] = useState(initialDate || '');
  const [selectedSlots, setSelectedSlots] = useState<SlotKey[]>(selectableSlots(initialSlots || []));
  const [venues, setVenues] = useState<AvailableVenue[] | null>(null);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedVenueId, setSelectedVenueId] = useState<number | null>(null);

  useEffect(() => {
    setSearchDate(initialDate || ''); setSelectedSlots(selectableSlots(initialSlots || []));
    setVenues(null); setSearched(false); setError(null); setSelectedVenueId(null);
  }, [eventId, initialDate, initialSlots]);

  function toggleSlot(slot: SlotKey) {
    setSelectedSlots(current => current.includes(slot)
      ? current.filter(candidate => candidate !== slot)
      : SLOTS.filter(candidate => [...current, slot].includes(candidate.key)).map(candidate => candidate.key));
  }
  async function search() {
    if (!searchDate || selectedSlots.length === 0 || loading) return;
    setLoading(true); setError(null);
    const parameters = new URLSearchParams({ date: searchDate });
    selectedSlots.forEach(slot => parameters.append('slot', slot));
    try {
      const response = await api(`/api/event-requests/${eventId}/available-venues?${parameters.toString()}`);
      if (!response.ok) { setError(await responseError(response, 'Could not search venue availability. Try again.')); return; }
      const body = await response.json() as { venues?: unknown };
      if (!Array.isArray(body.venues)) throw new Error('Invalid response');
      setVenues(body.venues as AvailableVenue[]); setSearched(true); setSelectedVenueId(null);
    } catch { setError('Could not search venue availability. Try again.'); }
    finally { setLoading(false); }
  }
  const canSearch = Boolean(searchDate && selectedSlots.length);
  const summary = `${searchDate || 'No date'} · ${selectedSlots.map(slot => SLOTS.find(item => item.key === slot)?.label.split(' · ')[0] || slot).join(', ') || 'No slots'}`;
  const selectedVenue = venues?.find(venue => venue.id === selectedVenueId) || null;
  const selectedIndex = selectedVenue ? venues?.findIndex(venue => venue.id === selectedVenue.id) ?? -1 : -1;
  const detailOrder = selectedIndex < 0 ? 0 : (selectedIndex % 2 === 0 && selectedIndex < (venues?.length || 0) - 1 ? selectedIndex + 1 : selectedIndex) * 2 + 1;
  return <section className="venue-availability" aria-labelledby="venue-availability-title">
    <div className="venue-availability__heading"><div><p className="eyebrow">Venue availability</p><h2 id="venue-availability-title">Find available venues</h2></div><p>Searches are read-only. A result is not a booking or a hold.</p></div>
    <div className="venue-availability__controls"><label className="field"><span>Singapore date</span><input aria-label="Singapore date" onChange={event => setSearchDate(event.target.value)} type="date" value={searchDate} /></label>
      <fieldset className="venue-availability__slots"><legend>Required slots</legend><div>{SLOTS.map(slot => <label key={slot.key}><input checked={selectedSlots.includes(slot.key)} onChange={() => toggleSlot(slot.key)} type="checkbox" /><span>{slot.label}</span></label>)}</div></fieldset>
      <button className="button button--primary" disabled={!canSearch || loading} onClick={() => void search()} type="button">{loading ? 'Checking availability…' : 'Find venues'}</button></div>
    {!canSearch && <p className="venue-availability__hint" role="status">Choose a Singapore date and at least one slot to search.</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {searched && !error && <div className="venue-availability__results" aria-live="polite"><p className="venue-availability__summary">Availability for <strong>{summary}</strong></p>
      {venues?.length === 0 ? <div className="organisation-events__empty" role="status"><strong>No venues are available for this search.</strong><span>Keep the date and slots, then adjust them to explore another option.</span></div> : <div className="venue-availability__marketplace venue-marketplace" aria-label="Available venue results">
        {venues?.map((venue, index) => <m.button type="button" key={venue.id} className={`venue-card venue-availability__card palette-${index % 3}${selectedVenueId === venue.id ? ' selected' : ''}`} style={{ order: index * 2 }} onClick={() => setSelectedVenueId(current => current === venue.id ? null : venue.id)} aria-expanded={selectedVenueId === venue.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .16, ease: 'easeOut', delay: Math.min(index * .04, .16) }} whileHover={{ y: -2 }} whileTap={{ y: 0 }}>
          <span className="venue-card-art" aria-hidden="true"><span className="venue-card-index">{String(index + 1).padStart(2, '0')}</span><Building2 size={32} /><span className="venue-card-grid" /></span>
          <span className="venue-card-body"><span className="venue-card-label">Available venue</span><strong>{venue.name}</strong><span className="venue-card-location"><MapPin size={15} />{venue.location || 'Location to be confirmed'}</span><span className="venue-availability__capacity">Up to {venue.maximum_layout_capacity ?? '—'} guests</span><span className="venue-card-action"><BadgeCheck size={16} />Available for selected slots <ArrowUpRight size={16} /></span></span>
        </m.button>)}
        <AnimatePresence initial={false}>{selectedVenue && <m.div className="venue-card-details venue-availability__detail" key={selectedVenue.id} style={{ order: detailOrder }} layout initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: .2, ease: 'easeOut' }}>
          <section aria-labelledby={`availability-detail-${selectedVenue.id}`}><p className="eyebrow"><BadgeCheck size={14} /> Timing confirmed</p><h3 id={`availability-detail-${selectedVenue.id}`}>{selectedVenue.name} is available</h3><p className="venue-availability__detail-copy">This venue can accommodate the selected date and every required slot, including any recorded preparation time.</p><dl className="venue-availability__detail-facts"><div><dt>Applied search</dt><dd>{summary}</dd></div><div><dt>Location</dt><dd>{selectedVenue.location || 'Not recorded'}</dd></div><div><dt>Maximum layout capacity</dt><dd>{selectedVenue.maximum_layout_capacity ?? 'Not recorded'}{selectedVenue.maximum_layout_capacity !== null ? ' guests' : ''}</dd></div></dl></section>
        </m.div>}</AnimatePresence>
      </div>}
    </div>}
  </section>;
}
