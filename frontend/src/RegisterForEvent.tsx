import { useState, type FormEvent } from 'react';
import type { ApiRequest } from './api';

// SPL-116 (CS-E19-S3): an attendee registers for an open event. The server owns every rule
// (registration open, a place left, not already registered, the details valid); this form only
// collects the details, sends them, and shows the server's answer. On success it shows the
// confirmation AC7 asks for: the event's name, date, times and venues, and what was submitted.
// SPL-115's open-events list is where an attendee picks the event and opens this form.

type Field = 'name' | 'email' | 'contact_number' | 'special_requirements';
export type RegistrationConfirmation = {
  registration: {
    id: number; status: string; name: string; email: string; contact_number: string;
    special_requirements: string | null; registered_at: string;
  };
  event: {
    id: number; name: string; description: string | null; date: string; start_time: string; end_time: string;
    venues: string[]; places_remaining: number;
  };
};

// The event date is a calendar date, so it is formatted in UTC to avoid shifting a day by time zone.
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  .format(new Date(`${day}T00:00:00Z`));

export function RegisterForEvent({ api, event, onRegistered }: {
  api: ApiRequest;
  event: { id: number; name: string };
  onRegistered?: (confirmation: RegistrationConfirmation) => void;
}) {
  const [values, setValues] = useState<Record<Field, string>>({ name: '', email: '', contact_number: '', special_requirements: '' });
  const [saving, setSaving] = useState(false);
  // A refusal the server tied to one field is shown beside that field; any other one, above the button.
  const [fieldError, setFieldError] = useState<{ field: Field; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<RegistrationConfirmation | null>(null);

  const update = (field: Field) => (change: { target: { value: string } }) =>
    setValues(current => ({ ...current, [field]: change.target.value }));

  async function register(submit: FormEvent) {
    submit.preventDefault();
    if (saving) return;
    setSaving(true); setFieldError(null); setError(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/registrations`, {
        method: 'POST',
        // Special requirements are optional: an empty box is sent as null rather than "".
        body: JSON.stringify({ ...values, special_requirements: values.special_requirements || null }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (body.field && body.error) setFieldError({ field: body.field, message: body.error });
        else setError(body.error || 'Could not register for this event. Try again.');
        return;   // what was typed stays in the form, so the attendee only fixes the one field
      }
      setConfirmation(body as RegistrationConfirmation);
      onRegistered?.(body as RegistrationConfirmation);
    } catch { setError('Could not register for this event. Try again.'); }
    finally { setSaving(false); }
  }

  if (confirmation) {
    const { event: booked, registration } = confirmation;
    return <section className="venue-booking-panel" aria-labelledby="registration-confirmed-title">
      <p className="eyebrow" id="registration-confirmed-title">You are registered</p>
      <div className="venue-booking-panel__summary">
        <strong>{booked.name}</strong>
        <span>{dateName(booked.date)} · {booked.start_time}–{booked.end_time} · {booked.venues.join(', ')}</span>
        <span>Registered as {registration.name} · {registration.email} · {registration.contact_number}</span>
        {registration.special_requirements && <span>Special requirements: {registration.special_requirements}</span>}
      </div>
    </section>;
  }

  // Accessible wiring for a field-level refusal: the input is marked invalid and points at the message.
  const describedBy = (field: Field) => (fieldError?.field === field ? `register-${field}-error` : undefined);
  const message = (field: Field) => fieldError?.field === field
    ? <p className="error" id={`register-${field}-error`}>{fieldError.message}</p> : null;
  const input = (field: Exclude<Field, 'special_requirements'>, label: string, type: string) => <div className="field">
    <label htmlFor={`register-${field}`} data-required>{label}</label>
    <input id={`register-${field}`} type={type} required value={values[field]} onChange={update(field)}
      aria-invalid={fieldError?.field === field || undefined} aria-describedby={describedBy(field)} />
    {message(field)}
  </div>;

  return <form className="request-form registration-settings__form" aria-label={`Register for ${event.name}`}
    onSubmit={submit => { void register(submit); }}>
    {input('name', 'Name', 'text')}
    {input('email', 'Email address', 'email')}
    {input('contact_number', 'Contact number', 'tel')}
    <div className="field">
      <label htmlFor="register-special_requirements">Special requirements (optional)</label>
      <textarea id="register-special_requirements" rows={3} value={values.special_requirements}
        onChange={update('special_requirements')}
        aria-invalid={fieldError?.field === 'special_requirements' || undefined}
        aria-describedby={describedBy('special_requirements')} />
      {message('special_requirements')}
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    <button type="submit" className="button button--primary" disabled={saving}>{saving ? 'Registering…' : 'Register'}</button>
  </form>;
}
