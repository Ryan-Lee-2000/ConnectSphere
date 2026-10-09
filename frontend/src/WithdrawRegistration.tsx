import { useState } from 'react';
import type { ApiRequest } from './api';

// SPL-118 (CS-E19-S5): an attendee withdraws their own registration. The server owns every rule
// (their own registration, still Registered, before the event starts) and sets the status and time.
// This control only decides whether to *offer* the action, asks for confirmation (withdrawing gives
// the place away, so it should never happen from one stray click), and shows the server's answer.
// SPL-117's My registrations page is where it is shown, next to each registration.

export type WithdrawalResult = {
  registration: { id: number; status: string; withdrawn_at: string | null };
  event: { id: number; name: string; places_remaining: number };
};

// The event's start as an instant: its date and start time in Singapore time (UTC+8, no daylight
// saving), the same cut-off the server applies (AC1).
const eventStart = (event: { date: string; start_time: string }) =>
  new Date(`${event.date}T${event.start_time}:00+08:00`);

export function WithdrawRegistration({ api, registration, event, now = () => new Date(), onWithdrawn }: {
  api: ApiRequest;
  registration: { id: number; status: string };
  event: { name: string; date: string; start_time: string };
  now?: () => Date;   // injectable clock, so tests can stand just before or at the start
  onWithdrawn?: (result: WithdrawalResult) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [withdrawn, setWithdrawn] = useState(false);

  if (withdrawn) return <p className="notice" role="status">You have withdrawn from {event.name}.</p>;
  // AC3 in the interface: not offered for a Withdrawn registration or once the event has started.
  // The server refuses both anyway; hiding the button just avoids offering an action that would fail.
  if (registration.status !== 'registered' || now() >= eventStart(event)) return null;

  async function withdraw() {
    if (saving) return;
    setSaving(true); setError(null);
    try {
      // No body: the status and the withdrawal time are decided by the server.
      const response = await api(`/api/registrations/${registration.id}/withdraw`, { method: 'POST' });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) { setError(body.error || 'Could not withdraw. Try again.'); return; }
      setWithdrawn(true);
      onWithdrawn?.(body as WithdrawalResult);
    } catch { setError('Could not withdraw. Try again.'); }
    finally { setSaving(false); setConfirming(false); }
  }

  return <div className="withdraw-registration">
    {!confirming && <button type="button" className="button button--secondary"
      aria-label={`Withdraw from ${event.name}`} onClick={() => { setError(null); setConfirming(true); }}>Withdraw</button>}
    {confirming && <div className="withdraw-registration__confirm" role="group" aria-label="Confirm withdrawal">
      <p>Withdraw your registration for {event.name}? Your place will be released for someone else.</p>
      <button type="button" className="button button--primary" disabled={saving} onClick={() => { void withdraw(); }}>
        {saving ? 'Withdrawing…' : 'Yes, withdraw'}
      </button>
      <button type="button" className="button button--secondary" disabled={saving} onClick={() => setConfirming(false)}>
        Keep my registration
      </button>
    </div>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
