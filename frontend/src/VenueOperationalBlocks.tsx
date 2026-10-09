import { FormEvent, useEffect, useRef, useState } from 'react';
import { CalendarOff, Trash2 } from 'lucide-react';
import type { ApiRequest, Venue } from './VenueCatalogue';
import { SLOTS, slotLabel } from './slots';

type OperationalBlock = {
  id: number;
  venue_id: number;
  start_date: string;
  end_date: string;
  slots: string[];
  reason: string;
  timing?: { start: string; end: string } | null;
  created_by_account_id: string;
  created_at: string;
  removed_by_account_id: string | null;
  removed_at: string | null;
};

async function responseError(response: Response) {
  const body = await response.json().catch(() => ({})) as { error?: string };
  return body.error || 'The operational-unavailability request could not be completed.';
}

function displayDate(value: string) {
  return new Intl.DateTimeFormat('en-SG', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Singapore',
  }).format(new Date(`${value}T00:00:00+08:00`));
}

export function VenueOperationalBlocks({ venue, api }: { venue: Venue; api: ApiRequest }) {
  const generation = useRef(0);
  const [exact, setExact] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [reload, setReload] = useState(0);
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [blocks, setBlocks] = useState<OperationalBlock[]>([]);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [slots, setSlots] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const current = ++generation.current;
    setLoaded(false); setBlocks([]); setError(null); setSaving(false);
    void (async () => {
      try {
        const response = await api(`/api/venues/${venue.id}/operational-blocks`);
        if (!response.ok) throw new Error(await responseError(response));
        const body = await response.json() as { operational_blocks?: OperationalBlock[]; capabilities?: { exact_venue_timing?: boolean } };
        if (generation.current !== current) return;
        setBlocks(body.operational_blocks ?? []);
        setExact(body.capabilities?.exact_venue_timing === true);
        setLoaded(true);
      } catch (failure) {
        if (generation.current === current) setError(failure instanceof Error ? failure.message : 'Could not load closures. Try again.');
      }
    })();
    return () => { generation.current++; };
  }, [api, venue.id, reload]);

  const toggleSlot = (slot: string) => {
    setSlots(current => current.includes(slot)
      ? current.filter(value => value !== slot)
      : [...current, slot]);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    const current = generation.current;
    try {
      const response = await api(`/api/venues/${venue.id}/operational-blocks`, {
        method: 'POST',
        body: JSON.stringify(exact ? { date: startDate, start_time: startTime, end_time: endTime, reason } : { start_date: startDate, end_date: endDate, slots, reason }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const body = await response.json() as {
        operational_block: OperationalBlock;
        affected_booking_count?: number;
      };
      if (generation.current !== current) return;
      setBlocks(current => [...current, body.operational_block]);
      setStartDate('');
      setEndDate('');
      setSlots([]);
      setReason('');
      const affected = body.affected_booking_count ?? 0;
      setStartTime(''); setEndTime('');
      setNotice(affected > 0
        ? `Operational unavailability recorded. ${affected} active ${affected === 1 ? 'booking requires' : 'bookings require'} review.`
        : 'Operational unavailability recorded.');
    } catch (failure) {
      if (generation.current === current) setError(failure instanceof Error ? failure.message : 'Could not record closure. Try again.');
    } finally {
      if (generation.current === current) setSaving(false);
    }
  };

  const remove = async (block: OperationalBlock) => {
    setError(null);
    setNotice(null);
    setSaving(true);
    const current = generation.current;
    try {
      const response = await api(`/api/venues/${venue.id}/operational-blocks/${block.id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(await responseError(response));
      if (generation.current !== current) return;
      setBlocks(current => current.filter(candidate => candidate.id !== block.id));
      setNotice('Operational unavailability removed.');
    } catch (failure) {
      if (generation.current === current) setError(failure instanceof Error ? failure.message : 'Could not remove closure. Try again.');
    } finally {
      if (generation.current === current) setSaving(false);
    }
  };

  const canSubmit = Boolean(loaded && startDate && reason.trim() && (exact ? startTime && endTime && endTime > startTime : endDate && slots.length));
  const supportedSlots = SLOTS.filter(({ key }) => venue.operating_slots.includes(key));

  return <section className="operational-blocks" aria-labelledby="operational-blocks-heading">
    <div className="operational-blocks__heading">
      <div>
        <p className="eyebrow"><CalendarOff size={14} /> Availability control</p>
        <h4 id="operational-blocks-heading">Operational unavailability</h4>
        <p>{exact ? 'Record a closure in Singapore time. Bookings that overlap it will require review.' : 'Block complete operating slots when this venue cannot be used.'}</p>
      </div>
    </div>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {!loaded && !error && <p role="status">Loading closures…</p>}
    {error && !loaded && <button type="button" onClick={() => setReload(value => value + 1)}>Retry loading closures</button>}
    <form className="operational-block-form" onSubmit={submit}>
      <div className="operational-block-form__dates">
        <label>Unavailable from<input type="date" value={startDate} onChange={event => setStartDate(event.target.value)} required /></label>
        {!exact && <label>Unavailable through<input type="date" min={startDate || undefined} value={endDate} onChange={event => setEndDate(event.target.value)} required /></label>}
      </div>
      {exact ? <div className="operational-block-form__dates">
        <label>Start time (SGT)<input type="time" step="900" value={startTime} onChange={event => setStartTime(event.target.value)} required /></label>
        <label>End time (SGT)<select value={endTime} onChange={event => setEndTime(event.target.value)} required><option value="">Choose end time</option>{Array.from({ length: 96 }, (_, index) => {
          const minutes = (index + 1) * 15;
          const value = `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
          return <option key={value} value={value}>{value === '24:00' ? '24:00 (end of day)' : value}</option>;
        })}</select></label>
      </div> : <fieldset>
        <legend>Unavailable operating slots</legend>
        <div className="slot-options">
          {supportedSlots.map(({ key, label }) => <label key={key}>
            <input type="checkbox" checked={slots.includes(key)} onChange={() => toggleSlot(key)} />
            {label} unavailable
          </label>)}
        </div>
      </fieldset>}
      <label>Reason for unavailability<textarea value={reason} onChange={event => setReason(event.target.value)} rows={2} required /></label>
      <div className="form-actions"><button className="primary" disabled={saving || !canSubmit}>{saving ? 'Recording…' : 'Record unavailability'}</button></div>
    </form>
    <div className="operational-block-list" aria-live="polite">
      <h5>Active blocks</h5>
      {!loaded ? <p>Closure information is not available yet.</p> : blocks.length === 0 ? <p>No operational unavailability recorded.</p> : <ul>
        {blocks.map(block => <li key={block.id}>
          <div><strong>{block.reason}</strong><span>{displayDate(block.start_date)} – {displayDate(block.end_date)}</span><span>{block.timing ? `${formatTime(block.timing.start)} – ${formatTime(block.timing.end)} SGT` : block.slots.map(slotLabel).join(', ')}</span></div>
          <button type="button" className="icon-button danger" disabled={saving} aria-label={`Remove ${block.reason}`} onClick={() => void remove(block)}><Trash2 size={16} />Remove</button>
        </li>)}
      </ul>}
    </div>
  </section>;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Singapore' }).format(new Date(value));
}
