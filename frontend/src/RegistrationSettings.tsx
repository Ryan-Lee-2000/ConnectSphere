import { useEffect, useState, type FormEvent } from 'react';
import { responseError, type ApiRequest } from './api';

// SPL-114 (CS-E19-S1): the assigned coordinator turns attendee registration on for a Confirmed event
// and can change its settings later. The server owns every rule (open before close, close before
// the event starts, capacity within the booked layout); this panel only collects the three values,
// sends them, and shows whatever the server decides, including which field a refusal is about.

type SettingsValues = { opens_at: string | null; closes_at: string | null; capacity: number | null };
type SettingsChange = {
  previous: SettingsValues | null;
  current: SettingsValues;
  changed_by: { id: string; name: string };
  changed_at: string;
};
type RegistrationSettings = SettingsValues & {
  enabled: boolean;
  state: 'off' | 'not_yet_open' | 'open' | 'closed';
  max_capacity: number | null;
  event_starts_at: string | null;
  history: SettingsChange[];
};
type Field = 'opens_at' | 'closes_at' | 'capacity';

// Every time in the story is Singapore time, whatever zone the coordinator's browser is in.
const timeName = (instant: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Singapore',
}).format(new Date(instant));

// The server always answers in Singapore time ("2026-10-10T09:00:00+08:00"), so the first 16
// characters are exactly the wall-clock value a datetime-local input expects ("2026-10-10T09:00").
const inputValue = (instant: string | null) => (instant ? instant.slice(0, 16) : '');

function stateLine(settings: RegistrationSettings) {
  if (settings.state === 'off') return 'Registration is off. Attendees cannot see or register for this event.';
  if (settings.state === 'not_yet_open') return `Not yet open. Registration opens ${timeName(settings.opens_at!)}.`;
  if (settings.state === 'open') return `Open. Registration closes ${timeName(settings.closes_at!)}.`;
  return `Closed on ${timeName(settings.closes_at!)}. Set a later closing time to reopen it.`;
}

const summary = (values: SettingsValues) =>
  `opens ${timeName(values.opens_at!)}, closes ${timeName(values.closes_at!)}, ${values.capacity} places`;

export function RegistrationSettingsPanel({ api, eventId }: { api: ApiRequest; eventId: number }) {
  const [settings, setSettings] = useState<RegistrationSettings | null>(null);
  const [opensAt, setOpensAt] = useState('');
  const [closesAt, setClosesAt] = useState('');
  const [capacity, setCapacity] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // A refusal the server tied to one field is shown beside that field; any other one, above the button.
  const [fieldError, setFieldError] = useState<{ field: Field; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load the saved settings, then fill the form with them so a change starts from what is saved.
  function show(loaded: RegistrationSettings) {
    setSettings(loaded);
    setOpensAt(inputValue(loaded.opens_at));
    setClosesAt(inputValue(loaded.closes_at));
    setCapacity(loaded.capacity === null ? '' : String(loaded.capacity));
  }

  useEffect(() => {
    let active = true;
    // Some page-level tests stub the API with a function that returns nothing for paths they do not
    // care about; treat that like "not loaded yet" instead of crashing (as VenueBookingPanel does).
    const pending = api(`/api/event-requests/${eventId}/registration`);
    if (!pending) return () => { active = false; };
    void pending.then(async response => {
      if (!response.ok) { if (active) setError('Could not load the registration settings. Try again.'); return; }
      const body = await response.json() as { registration?: RegistrationSettings };
      if (active && body.registration) show(body.registration);
    }).catch(() => { if (active) setError('Could not load the registration settings. Try again.'); });
    return () => { active = false; };
  }, [api, eventId]);

  async function save(submit: FormEvent) {
    submit.preventDefault();
    if (!settings || saving) return;
    const wasEnabled = settings.enabled;
    setSaving(true); setNotice(null); setFieldError(null); setError(null);
    try {
      // Times go as the wall-clock value typed; the server reads a time without an offset as Singapore
      // time. Capacity goes as a number so the server can refuse 2.5 or "ten" (AC3).
      const response = await api(`/api/event-requests/${eventId}/registration`, {
        method: 'PUT',
        body: JSON.stringify({ opens_at: opensAt, closes_at: closesAt, capacity: Number(capacity) }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { error?: string; field?: Field };
        if (body.field && body.error) setFieldError({ field: body.field, message: body.error });
        else setError(body.error || await responseError(response, 'Could not save the registration settings. Try again.'));
        return;
      }
      const body = await response.json() as { registration?: RegistrationSettings };
      if (!body.registration) throw new Error('Invalid response');
      show(body.registration);
      setNotice(wasEnabled ? 'Registration settings saved.' : 'Registration enabled.');
    } catch { setError('Could not save the registration settings. Try again.'); }
    finally { setSaving(false); }
  }

  if (!settings) return error ? <p className="error" role="alert">{error}</p> : null;

  // Accessible wiring for a field-level refusal: the input is marked invalid and points at the message.
  const errorFor = (field: Field) => (fieldError?.field === field ? `registration-${field}-error` : undefined);
  const fieldMessage = (field: Field) => fieldError?.field === field
    ? <p className="error" id={`registration-${field}-error`}>{fieldError.message}</p> : null;
  const noBooking = settings.max_capacity === null;

  return <section className="venue-booking-panel registration-settings" aria-labelledby="registration-settings-title">
    <p className="eyebrow" id="registration-settings-title">Attendee registration</p>
    <p className="venue-booking-panel__summary">{stateLine(settings)}</p>
    <form className="request-form registration-settings__form" onSubmit={submit => { void save(submit); }}>
      <div className="request-form__row">
        <div className="field">
          <label htmlFor="registration-opens_at">Registration opens</label>
          <input id="registration-opens_at" type="datetime-local" value={opensAt}
            aria-invalid={fieldError?.field === 'opens_at' || undefined} aria-describedby={errorFor('opens_at')}
            onChange={change => setOpensAt(change.target.value)} />
          {fieldMessage('opens_at')}
        </div>
        <div className="field">
          <label htmlFor="registration-closes_at">Registration closes</label>
          <input id="registration-closes_at" type="datetime-local" value={closesAt}
            aria-invalid={fieldError?.field === 'closes_at' || undefined} aria-describedby={errorFor('closes_at')}
            onChange={change => setClosesAt(change.target.value)} />
          {fieldMessage('closes_at')}
        </div>
      </div>
      <div className="field">
        <label htmlFor="registration-capacity">Capacity</label>
        <input id="registration-capacity" type="number" min={1} step={1} max={settings.max_capacity ?? undefined}
          value={capacity}
          aria-invalid={fieldError?.field === 'capacity' || undefined} aria-describedby={errorFor('capacity')}
          onChange={change => setCapacity(change.target.value)} />
        {noBooking
          ? <p className="hint">Registration needs an Approved venue booking to set its capacity against.</p>
          : <p className="hint">Up to {settings.max_capacity} places, the capacity of the booked layout.</p>}
        {fieldMessage('capacity')}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="venue-booking-panel__notice" role="status">{notice}</p>}
      <button type="submit" className="button button--primary" disabled={saving || noBooking}>
        {saving ? 'Saving…' : settings.enabled ? 'Save changes' : 'Enable registration'}
      </button>
    </form>
    {/* AC6: every save is listed, newest first, with who made it and when. */}
    {settings.history.length > 0 && <ul className="registration-settings__history" aria-label="Registration change history">
      {settings.history.map(change => <li key={change.changed_at + change.changed_by.id}>
        <strong>{change.changed_by.name}</strong> · {timeName(change.changed_at)} · {change.previous ? 'changed to' : 'enabled with'} {summary(change.current)}
      </li>)}
    </ul>}
  </section>;
}
