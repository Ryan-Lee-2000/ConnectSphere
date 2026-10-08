import { useState } from 'react';
import type { ApiRequest } from './api';

type TimingVenue = { id: number; setup_minutes?: number | null; turnaround_minutes?: number | null; operating_intervals?: number[][] | null };
const clock = (minutes: number) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
const minutes = (value: string) => { const [h, m] = value.split(':').map(Number); return h * 60 + m; };

export function VenueTimingSettings({ venue, api, onSaved }: { venue: TimingVenue; api: ApiRequest; onSaved: () => void }) {
  const [setup, setSetup] = useState(venue.setup_minutes == null ? '' : String(venue.setup_minutes));
  const [turnaround, setTurnaround] = useState(venue.turnaround_minutes == null ? '' : String(venue.turnaround_minutes));
  const [hours, setHours] = useState<string[][]>((venue.operating_intervals || []).map(pair => pair.map(clock)));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const valid = setup !== '' && turnaround !== '' && [setup, turnaround].every(value => Number.isInteger(Number(value)) && Number(value) >= 0)
    && hours.every(([a, b]) => /^([01]\d|2[0-3]):[0-5]\d$/.test(a) && (/^([01]\d|2[0-3]):[0-5]\d$/.test(b) || b === '24:00') && minutes(b) > minutes(a));
  async function save() {
    if (!valid || saving) return;
    setSaving(true); setError(null); setSaved(false);
    try {
      const response = await api(`/api/venues/${venue.id}`, { method: 'PATCH', body: JSON.stringify({ setup_minutes: Number(setup), turnaround_minutes: Number(turnaround), operating_intervals: hours.map(pair => pair.map(minutes)) }) });
      const body = await response.json();
      if (!response.ok) { setError(body.error || 'Could not save timing.'); return; }
      setSaved(true); onSaved();
    } catch { setError('Could not save timing. Your entries are retained; try again.'); }
    finally { setSaving(false); }
  }
  return <form className="venue-form" aria-label="Venue timing" onSubmit={event => { event.preventDefault(); void save(); }}>
    <h4>Operating hours and preparation</h4>
    <p>Singapore time. These hours repeat every day. Enter actual hours; meal times have no automatic closure.</p>
    {venue.operating_intervals == null && <p role="status">Timing needs confirmation before this venue can appear in exact-time searches. Previous slot settings remain recorded.</p>}
    <label>Setup minutes<input type="number" min="0" step="1" required value={setup} onChange={event => setSetup(event.target.value)} /></label>
    <label>Turnaround minutes<input type="number" min="0" step="1" required value={turnaround} onChange={event => setTurnaround(event.target.value)} /></label>
    <fieldset><legend>Daily opening intervals</legend><p>Use HH:MM and 24:00 for midnight at the end of the day. Split overnight opening into two intervals. No intervals means closed all day.</p>
      {hours.map(([a, b], index) => <div className="detail-grid" key={index}>
        <label>Opening time {index + 1}<input value={a} placeholder="09:00" onChange={event => setHours(current => current.map((pair, n) => n === index ? [event.target.value, pair[1]] : pair))} required /></label>
        <label>Closing time {index + 1}<input value={b} placeholder="18:00" onChange={event => setHours(current => current.map((pair, n) => n === index ? [pair[0], event.target.value] : pair))} required /></label>
        <button className="button button--secondary" type="button" aria-label={`Remove opening interval ${index + 1}`} onClick={() => setHours(current => current.filter((_, n) => n !== index))}>Remove interval</button>
      </div>)}
      <button className="button button--secondary" type="button" onClick={() => setHours(current => [...current, ['', '']])}>Add opening interval</button>
    </fieldset>
    {error && <p className="error" role="alert">{error}</p>}
    {saved && <p role="status">Timing saved.</p>}
    <button className="button button--primary" disabled={!valid || saving}>{saving ? 'Saving…' : 'Save timing'}</button>
  </form>;
}
