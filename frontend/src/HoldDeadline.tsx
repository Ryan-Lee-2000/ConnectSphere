import { useState } from 'react';
import { Clock } from 'lucide-react';
import { responseError, type ApiRequest } from './api';

// SPL-133 (Week 7 change 4): a Requested booking is a tentative hold with a deadline. Venue Staff
// can move it here; the server enforces the limits (future, at most 14 days, not after the booking
// starts) and records the change, so the form only collects a date and time.

export const holdTime = (instant: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Singapore',
}).format(new Date(instant));

// The deadline as a datetime-local value in Singapore time, which the server reads as SGT.
const sgtInput = (instant: string) => {
  const local = new Date(new Date(instant).getTime() + 8 * 60 * 60 * 1000);
  return local.toISOString().slice(0, 16);
};

export function HoldDeadline({ api, bookingId, expiresAt, onChanged }: {
  api: ApiRequest; bookingId: number; expiresAt: string; onChanged: (booking: unknown) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(() => sgtInput(expiresAt));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (saving || !value) return;
    setSaving(true); setError(null);
    try {
      const response = await api(`/api/venue-bookings/${bookingId}/hold-deadline`, {
        method: 'PUT', body: JSON.stringify({ expires_at: value }),
      });
      if (!response.ok) { setError(await responseError(response, 'Could not change the hold deadline. Try again.')); return; }
      const next = await response.json() as { booking?: unknown };
      if (!next.booking) throw new Error('Invalid response');
      setEditing(false);
      onChanged(next.booking);
    } catch { setError('Could not change the hold deadline. Try again.'); }
    finally { setSaving(false); }
  }

  return <section className="hold-deadline" aria-label="Hold deadline">
    <p className="hold-deadline__summary">
      <Clock size={16} aria-hidden="true" />
      <span>This hold expires on <strong>{holdTime(expiresAt)}</strong> SGT unless it is approved before then.</span>
    </p>
    {!editing && <button className="button button--secondary" type="button" onClick={() => { setEditing(true); setError(null); setValue(sgtInput(expiresAt)); }}>Change deadline</button>}
    {editing && <form className="venue-booking-panel__confirm" aria-label="Change hold deadline" onSubmit={submit => { submit.preventDefault(); void save(); }}>
      <div className="field">
        <label htmlFor={`hold-deadline-${bookingId}`}>New deadline (SGT)</label>
        <input id={`hold-deadline-${bookingId}`} type="datetime-local" required value={value} onChange={change => setValue(change.target.value)} />
        <p className="hint">At most 14 days from now, and not after the booking starts.</p>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="button button--primary" disabled={saving || !value} type="submit">{saving ? 'Saving…' : 'Save deadline'}</button>
      <button className="button" disabled={saving} type="button" onClick={() => { setEditing(false); setError(null); }}>Keep deadline</button>
    </form>}
    {error && !editing && <p className="error" role="alert">{error}</p>}
  </section>;
}
