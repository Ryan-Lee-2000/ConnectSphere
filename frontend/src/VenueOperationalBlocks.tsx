import { FormEvent, useEffect, useState } from 'react';
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
  const [blocks, setBlocks] = useState<OperationalBlock[]>([]);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [slots, setSlots] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void api(`/api/venues/${venue.id}/operational-blocks`).then(async response => {
      if (!current) return;
      if (!response.ok) {
        setError(await responseError(response));
        return;
      }
      const body = await response.json() as { operational_blocks?: OperationalBlock[] };
      setBlocks(body.operational_blocks ?? []);
    });
    return () => { current = false; };
  }, [api, venue.id]);

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
    const response = await api(`/api/venues/${venue.id}/operational-blocks`, {
      method: 'POST',
      body: JSON.stringify({ start_date: startDate, end_date: endDate, slots, reason }),
    });
    if (!response.ok) {
      setError(await responseError(response));
      setSaving(false);
      return;
    }
    const body = await response.json() as {
      operational_block: OperationalBlock;
      affected_booking_count?: number;
    };
    setBlocks(current => [...current, body.operational_block]);
    setStartDate('');
    setEndDate('');
    setSlots([]);
    setReason('');
    const affected = body.affected_booking_count ?? 0;
    setNotice(affected > 0
      ? `Operational unavailability recorded. ${affected} active ${affected === 1 ? 'booking requires' : 'bookings require'} review.`
      : 'Operational unavailability recorded.');
    setSaving(false);
  };

  const remove = async (block: OperationalBlock) => {
    setError(null);
    setNotice(null);
    const response = await api(
      `/api/venues/${venue.id}/operational-blocks/${block.id}`,
      { method: 'DELETE' },
    );
    if (!response.ok) {
      setError(await responseError(response));
      return;
    }
    setBlocks(current => current.filter(candidate => candidate.id !== block.id));
    setNotice('Operational unavailability removed.');
  };

  const canSubmit = Boolean(startDate && endDate && slots.length && reason.trim());
  const supportedSlots = SLOTS.filter(({ key }) => venue.operating_slots.includes(key));

  return <section className="operational-blocks" aria-labelledby="operational-blocks-heading">
    <div className="operational-blocks__heading">
      <div>
        <p className="eyebrow"><CalendarOff size={14} /> Availability control</p>
        <h4 id="operational-blocks-heading">Operational unavailability</h4>
        <p>Block complete operating slots when this venue cannot be used.</p>
      </div>
    </div>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <form className="operational-block-form" onSubmit={submit}>
      <div className="operational-block-form__dates">
        <label>Unavailable from<input type="date" value={startDate} onChange={event => setStartDate(event.target.value)} required /></label>
        <label>Unavailable through<input type="date" min={startDate || undefined} value={endDate} onChange={event => setEndDate(event.target.value)} required /></label>
      </div>
      <fieldset>
        <legend>Unavailable operating slots</legend>
        <div className="slot-options">
          {supportedSlots.map(({ key, label }) => <label key={key}>
            <input type="checkbox" checked={slots.includes(key)} onChange={() => toggleSlot(key)} />
            {label} unavailable
          </label>)}
        </div>
      </fieldset>
      <label>Reason for unavailability<textarea value={reason} onChange={event => setReason(event.target.value)} rows={2} required /></label>
      <div className="form-actions"><button className="primary" disabled={saving || !canSubmit}>{saving ? 'Recording…' : 'Record unavailability'}</button></div>
    </form>
    <div className="operational-block-list" aria-live="polite">
      <h5>Active blocks</h5>
      {blocks.length === 0 ? <p>No operational unavailability recorded.</p> : <ul>
        {blocks.map(block => <li key={block.id}>
          <div><strong>{block.reason}</strong><span>{displayDate(block.start_date)} – {displayDate(block.end_date)}</span><span>{block.slots.map(slotLabel).join(', ')}</span></div>
          <button type="button" className="icon-button danger" aria-label={`Remove ${block.reason}`} onClick={() => void remove(block)}><Trash2 size={16} />Remove</button>
        </li>)}
      </ul>}
    </div>
  </section>;
}
