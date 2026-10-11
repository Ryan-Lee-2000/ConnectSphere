import { useState } from 'react';
import type { ApiRequest } from './api';

// SPL-100 (CS-E16-S4): Technical Support records when reserved equipment is planned back.
//
// The server owns every rule — the floor (the requirement's required end date), whether an
// extension would overcommit any added day, and who changed it — so this control only collects a
// date and shows the server's answer. It deliberately does no feasibility arithmetic of its own:
// the page and the server must never disagree about whether a date is allowed.
//
// AC4 is enforced by the server. This control is only rendered inside the Technical Support
// workspace, so `canEdit` exists to keep it out of any read-only context that reuses the card.

export type Reservation = {
  id: number;
  quantity: number;
  planned_return_date: string;
  return_date_changed_by: { id: string; display_name: string | null } | null;
  return_date_changed_at: string | null;
};

const formatMoment = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('en-SG', {
        day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
      }).format(new Date(value))
    : null;

export function PlannedReturnDate({ api, reservation, canEdit = true, onSaved }: {
  api: ApiRequest;
  reservation: Reservation;
  canEdit?: boolean;
  onSaved?: (saved: Reservation) => void;
}) {
  const [current, setCurrent] = useState(reservation);
  const [draft, setDraft] = useState(reservation.planned_return_date);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  const changedAt = formatMoment(current.return_date_changed_at);

  async function save() {
    if (saving) return;
    setSaving(true); setError(null); setConfirmation(null);
    try {
      const response = await api(`/api/equipment-reservations/${current.id}/planned-return-date`, {
        method: 'PATCH',
        // Sent as typed. The server decides what is allowed, so its refusal is what is shown.
        body: JSON.stringify({ planned_return_date: draft }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) { setError(body.error || 'Could not save that date. Try again.'); return; }
      setCurrent(body.reservation as Reservation);
      setConfirmation(`Planned return date saved as ${body.reservation.planned_return_date}.`);
      onSaved?.(body.reservation as Reservation);
    } catch { setError('Could not save that date. Try again.'); }
    finally { setSaving(false); }
  }

  return <div className="planned-return-date">
    <dl>
      <dt>Planned return date</dt>
      <dd data-testid="planned-return-date">{current.planned_return_date}</dd>
    </dl>
    {/* AC1's assumption: this is a planned date and never records a physical return. */}
    <p className="planned-return-date__note">
      A planned date only — it does not record that the equipment has come back.
    </p>
    {changedAt && <p className="planned-return-date__history">
      Last changed by {current.return_date_changed_by?.display_name || 'Unknown'} on {changedAt}
    </p>}

    {canEdit && <>
      <label htmlFor={`planned-return-${current.id}`}>Change planned return date</label>
      <input id={`planned-return-${current.id}`} name="planned_return_date" type="date"
        value={draft} onChange={event => setDraft(event.target.value)} />
      {/* The server's refusal is shown beside the field it is about (TC-SPL-100-08). */}
      {error && <p className="error" role="alert">{error}</p>}
      {confirmation && <p className="notice" role="status">{confirmation}</p>}
      <button type="button" className="button button--primary" disabled={saving}
        onClick={() => { void save(); }}>{saving ? 'Saving…' : 'Save planned return date'}</button>
    </>}
  </div>;
}
