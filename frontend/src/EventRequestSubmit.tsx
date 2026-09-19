import { FormEvent, useId, useState } from 'react';

const SUBMIT_FAILURE_MESSAGE = "We couldn't submit your request. Please try again.";

// The six fields CS-E03-S5 requires before a request can be reviewed. The full request form,
// including venue, equipment and registration detail, belongs to CS-E03-S1 to S4.
const MANDATORY_FIELDS = [
  { name: 'name', label: 'Event name', type: 'text' },
  { name: 'purpose', label: 'Purpose', type: 'text' },
  { name: 'proposed_date', label: 'Proposed date', type: 'date' },
  { name: 'start_time', label: 'Start time', type: 'time' },
  { name: 'end_time', label: 'End time', type: 'time' },
  { name: 'expected_attendance', label: 'Expected attendance', type: 'number' },
] as const;

type FieldName = (typeof MANDATORY_FIELDS)[number]['name'];
type FormState = Record<FieldName, string>;

type Submitted = { id: number; name: string; status: string; submitted_at: string | null };

function emptyForm(): FormState {
  return {
    name: '',
    purpose: '',
    proposed_date: '',
    start_time: '',
    end_time: '',
    expected_attendance: '',
  };
}

// CS-E07-S1 takes the organiser to their requests once a submission succeeds. The callback is
// optional so the form can still be rendered and tested on its own.
export function EventRequestSubmit({
  accessToken,
  onSubmitted,
}: {
  accessToken: string;
  onSubmitted?: () => void;
}) {
  const [form, setForm] = useState<FormState>(emptyForm);
  const [submitted, setSubmitted] = useState<Submitted | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const errorId = useId();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // A new attempt always clears the previous outcome, so a confirmation and a stale error
    // are never shown together.
    setError(null);
    setMissing([]);
    setSubmitted(null);
    setSubmitting(true);

    const attendance = form.expected_attendance.trim();
    const body = {
      name: form.name,
      purpose: form.purpose,
      proposed_date: form.proposed_date,
      start_time: form.start_time,
      end_time: form.end_time,
      expected_attendance: attendance === '' ? null : Number(attendance),
    };

    try {
      const response = await fetch('/api/event-requests', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => null);

      if (response.status === 201 && payload?.event_request) {
        setSubmitted(payload.event_request);
        setForm(emptyForm());
        // Only a successful submission moves the organiser on (CS-E07-S1 AC7). A refusal
        // leaves them here with their entries and the reason.
        onSubmitted?.();
        return;
      }
      if (Array.isArray(payload?.missing_field_labels)) {
        setMissing(payload.missing_field_labels);
      }
      setError(payload?.error ?? SUBMIT_FAILURE_MESSAGE);
    } catch {
      setError(SUBMIT_FAILURE_MESSAGE);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="event-request-submit">
      <p className="eyebrow">Event requests</p>
      <h1 id="event-request-title">Submit an event request</h1>
      <p>ConnectSphere begins reviewing your request once you submit it.</p>

      {submitted && (
        <div className="form-message form-message--success" role="status">
          <strong>Request submitted.</strong>
          <span>
            {' '}
            {submitted.name} was received with reference EVT-{submitted.id} and its status is{' '}
            {submitted.status}
            {submitted.submitted_at
              ? ` as of ${new Date(submitted.submitted_at).toLocaleString()}`
              : ''}
            . You cannot change the request yourself once submitted — ask your Event
            Coordinator for any change.
          </span>
        </div>
      )}

      {error && (
        <div className="form-message form-message--error" id={errorId} role="alert">
          <span>{error}</span>
          {missing.length > 0 && (
            <ul className="event-request-submit__missing">
              {missing.map(label => (
                <li key={label}>{label}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <form className="event-request-submit__form" onSubmit={handleSubmit} noValidate>
        {MANDATORY_FIELDS.map(field => (
          <div className="field" key={field.name}>
            <label htmlFor={`event-${field.name}`}>{field.label}</label>
            <input
              aria-describedby={error ? errorId : undefined}
              id={`event-${field.name}`}
              onChange={event =>
                setForm(current => ({ ...current, [field.name]: event.target.value }))
              }
              type={field.type}
              value={form[field.name]}
            />
          </div>
        ))}
        <button className="button button--primary" disabled={submitting} type="submit">
          {submitting ? 'Submitting…' : 'Submit request'}
        </button>
      </form>
    </div>
  );
}
