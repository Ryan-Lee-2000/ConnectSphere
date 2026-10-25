import { useEffect, useMemo, useState } from 'react';
import { defaultRequest, responseError, type ApiRequest } from './api';

type PlanItem = { value: string; not_applicable_reason: string };
type Plan = Record<string, PlanItem>;
type Review = { id: number; status: string; plan: Plan; reason: string | null; submitted_at: string; decided_at: string | null; decided_by: { id: string; name: string } | null; current: boolean };
type SafetyContext = {
  id: number; name: string; status: string; expected_attendance: number | null; accessibility_needs: string[];
  venues: { name: string; layout: string | null; capacity: number | null; attendance: number | null; restrictions: string | null }[];
  equipment: { name: string; required: number; reserved: number; essentiality: string | null; status: string }[];
};
type QueueItem = { id: number; event: SafetyContext; plan: Plan; submitted_at: string };

const fields: [keyof Plan, string, string][] = [
  ['emergency_access', 'Emergency access', 'Explain emergency routes and access arrangements.'],
  ['equipment_placement', 'Equipment placement', 'Explain where equipment will be placed safely.'],
  ['crowd_movement', 'Crowd movement', 'Explain entry, exit and movement arrangements.'],
  ['venue_restrictions', 'Venue restrictions', 'Record venue rules or why none apply.'],
];
const emptyPlan = (): Plan => Object.fromEntries(fields.map(([key]) => [key, { value: '', not_applicable_reason: '' }])) as Plan;
const label = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase());

function ArrangementEvidence({ context }: { context: SafetyContext }) {
  // The read contract is additive. Defaults keep a transient older API response from blanking the
  // operational screen while the server is being restarted during a local upgrade.
  const venues = context.venues ?? [];
  const equipment = context.equipment ?? [];
  const accessibilityNeeds = context.accessibility_needs ?? [];
  return <div className="safety-review__evidence" aria-label="Confirmed arrangement evidence">
    <dl className="safety-review__facts"><div><dt>Expected attendance</dt><dd>{context.expected_attendance ?? 'Not recorded'}</dd></div><div><dt>Accessibility needs</dt><dd>{accessibilityNeeds.length ? accessibilityNeeds.join(', ') : 'None recorded'}</dd></div></dl>
    <section><h3>Approved venue arrangements</h3>{venues.length === 0 ? <p>No approved venue arrangement is recorded.</p> : <ul>{venues.map(venue => <li key={`${venue.name}-${venue.layout}`}><strong>{venue.name}</strong><span>{venue.layout ? `${label(venue.layout)} layout` : 'Layout not recorded'} · {venue.capacity ?? 'Capacity not recorded'} capacity · {venue.attendance ?? 'Attendance not recorded'} attending</span><small>{venue.restrictions || 'No venue restrictions recorded; address this in the safety plan.'}</small></li>)}</ul>}</section>
    <section><h3>Technical arrangements</h3>{equipment.length === 0 ? <p>No equipment requirements are recorded.</p> : <ul>{equipment.map(item => <li key={`${item.name}-${item.status}`}><strong>{item.name}</strong><span>{item.reserved}/{item.required} reserved · {label(item.essentiality || 'undecided')} · {label(item.status)}</span></li>)}</ul>}</section>
  </div>;
}

// SPL-135: the coordinator submits a safety plan. The server remains the authority for
// arrangement readiness and status, so this panel only collects and displays the evidence.
export function SafetyReviewPanel({ accessToken, eventId, onStatusChange }: { accessToken: string; eventId: number; onStatusChange: (status: string) => void }) {
  const api = useMemo(() => defaultRequest(accessToken), [accessToken]);
  const [context, setContext] = useState<SafetyContext | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [plan, setPlan] = useState<Plan>(emptyPlan);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function load() {
    setError(null);
    const response = await api(`/api/event-requests/${eventId}/safety-review`);
    if (!response.ok) throw new Error(await responseError(response, 'Could not load the safety review.'));
    const body = await response.json() as { event: SafetyContext; review: Review | null };
    setContext(body.event); setReview(body.review); setPlan(body.review?.plan ?? emptyPlan());
  }
  useEffect(() => { void load().catch(reason => setError(reason instanceof Error ? reason.message : 'Could not load the safety review.')); }, [api, eventId]);

  async function submit() {
    setSaving(true); setError(null); setNotice(null);
    try {
      const response = await api(`/api/event-requests/${eventId}/safety-review`, { method: 'POST', body: JSON.stringify({ plan }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || 'Could not submit the safety review.');
      setReview(body.review); setNotice(body.message || 'Safety review submitted.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not submit the safety review.'); }
    finally { setSaving(false); }
  }
  async function beginPreparation() {
    setSaving(true); setError(null); setNotice(null);
    try {
      const response = await api(`/api/event-requests/${eventId}/begin-preparation`, { method: 'POST' });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || 'Could not begin preparation.');
      onStatusChange('preparing'); setNotice(body.message || 'Preparation has begun.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not begin preparation.'); }
    finally { setSaving(false); }
  }

  if (error && !context) return <p className="error" role="alert">{error}</p>;
  if (!context) return <p role="status">Loading safety review…</p>;
  // A current approval closes this review cycle. SPL-136 returns a corrected event to Confirmed;
  // at that point the same submission action starts a fresh safety-review cycle. A current
  // pending review is deliberately not duplicated while Safety is deciding it.
  const canSubmit = context.status === 'confirmed'
    && (!review || (review.status !== 'submitted' && (review.status !== 'approved' || !review.current)));
  const canBegin = context.status === 'confirmed' && review?.status === 'approved' && review.current;
  return <section className="safety-review" aria-labelledby="safety-review-title">
    <header className="safety-review__header"><div><p className="eyebrow">Safety gate</p><h2 id="safety-review-title">Safety review</h2><p>Preparation can begin only after the current confirmed arrangements are approved by Safety.</p></div><strong className={`safety-review__status safety-review__status--${review?.status ?? 'not-submitted'}`}>{review ? label(review.status) : 'Not submitted'}</strong></header>
    <ArrangementEvidence context={context} />
    {review && <div className="safety-review__decision"><strong>{review.current ? 'Current arrangement' : 'Arrangement changed'}</strong><span>{review.reason || (review.status === 'approved' ? 'Safety approved this submitted arrangement.' : 'Awaiting the Safety Officer’s decision.')}</span>{review.decided_by && <small>Recorded by {review.decided_by.name} on {new Date(review.decided_at || '').toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })}</small>}</div>}
    {canSubmit && <fieldset className="safety-review__plan" disabled={saving}><legend>Safety plan</legend>{fields.map(([key, title, hint]) => {
      const notApplicable = Boolean(plan[key]?.not_applicable_reason);
      return <div className="field" key={key}>
        <label htmlFor={`safety-${key}`}>{title}</label><small>{hint}</small>
        <label className="safety-review__na" htmlFor={`safety-na-${key}`}>
          <input id={`safety-na-${key}`} type="checkbox" checked={notApplicable}
            onChange={event => setPlan(current => ({ ...current, [key]: { value: '', not_applicable_reason: event.target.checked ? ' ' : '' } }))} />
          <span>Not applicable</span>
        </label>
        <textarea id={`safety-${key}`} rows={3}
          aria-label={notApplicable ? `Why ${title.toLowerCase()} is not applicable` : title}
          placeholder={notApplicable ? 'Explain why this does not apply' : 'Describe the planned arrangement'}
          value={notApplicable ? plan[key]?.not_applicable_reason.trimStart() ?? '' : plan[key]?.value ?? ''}
          onChange={event => setPlan(current => ({ ...current, [key]: notApplicable
            ? { value: '', not_applicable_reason: event.target.value }
            : { value: event.target.value, not_applicable_reason: '' } }))} />
      </div>;
    })}</fieldset>}
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div className="organisation-events__actions">{canSubmit && <button className="button button--primary" type="button" disabled={saving} onClick={() => void submit()}>{saving ? 'Submitting…' : 'Submit safety review'}</button>}{canBegin && <button className="button button--primary" type="button" disabled={saving} onClick={() => void beginPreparation()}>{saving ? 'Starting…' : 'Begin preparation'}</button>}</div>
  </section>;
}

// SPL-135 AC3: the Coordinator Lead can inspect the recorded decision and its supporting
// evidence without gaining any decision or arrangement-editing controls.
export function SafetyReviewEvidence({ accessToken, eventId, request }: { accessToken: string; eventId: number; request?: ApiRequest }) {
  const api = useMemo(() => request || defaultRequest(accessToken), [accessToken, request]);
  const [data, setData] = useState<{ event: SafetyContext; review: Review | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void (async () => {
    try {
      const response = await api(`/api/event-requests/${eventId}/safety-review`);
      if (!response.ok) throw new Error(await responseError(response, 'Could not load safety evidence.'));
      setData(await response.json() as { event: SafetyContext; review: Review | null });
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load safety evidence.'); }
  })(); }, [api, eventId]);
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!data) return <p role="status">Loading safety evidence…</p>;
  if (!data.review) return <section className="safety-review__decision"><h3>Safety decision evidence</h3><p>No safety review has been submitted for this event.</p></section>;
  const review = data.review;
  return <section className="safety-review__decision" aria-label={`Safety evidence for ${data.event.name}`}><h3>Safety decision evidence</h3><p><strong>{label(review.status)}</strong>{review.current ? ' for the current arrangement.' : ' for an earlier arrangement.'}</p><dl className="safety-queue__plan">{fields.map(([key, title]) => <div key={key}><dt>{title}</dt><dd>{review.plan[key]?.value || `Not applicable: ${review.plan[key]?.not_applicable_reason || 'No reason recorded'}`}</dd></div>)}</dl>{review.decided_by && <p>Recorded by {review.decided_by.name} on {new Date(review.decided_at || '').toLocaleString('en-SG', { timeZone: 'Asia/Singapore' })}.</p>}{review.reason && <p>Decision reason: {review.reason}</p>}<ArrangementEvidence context={data.event} /></section>;
}

// Safety Officers use a compact work queue: open the submitted item, make one accountable
// decision, and leave a reason for changes or rejection. The server writes actor and timestamp.
export function SafetyReviewQueue({ accessToken }: { accessToken: string }) {
  const api = useMemo(() => defaultRequest(accessToken), [accessToken]);
  const [rows, setRows] = useState<QueueItem[] | null>(null); const [open, setOpen] = useState<QueueItem | null>(null);
  const [reason, setReason] = useState(''); const [error, setError] = useState<string | null>(null); const [saving, setSaving] = useState(false);
  async function load() { const response = await api('/api/safety-reviews'); if (!response.ok) throw new Error(await responseError(response, 'Could not load safety reviews.')); const body = await response.json() as { reviews: QueueItem[] }; setRows(body.reviews); }
  useEffect(() => { void load().catch(reason => setError(reason instanceof Error ? reason.message : 'Could not load safety reviews.')); }, [api]);
  async function decide(decision: string) { if (!open) return; setSaving(true); setError(null); try { const response = await api(`/api/safety-reviews/${open.id}/decision`, { method: 'POST', body: JSON.stringify({ decision, reason }) }); if (!response.ok) throw new Error(await responseError(response, 'Could not record this decision.')); setOpen(null); setReason(''); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not record this decision.'); } finally { setSaving(false); } }
  if (error && !rows) return <p className="error" role="alert">{error}</p>; if (!rows) return <p role="status">Loading safety review queue…</p>;
  return <section className="safety-queue" aria-labelledby="safety-queue-title"><header><p className="eyebrow">Safety Officer · review queue</p><h1 id="safety-queue-title">Safety reviews awaiting decision</h1><p>Review the confirmed arrangement and record one decision. A rejected or changed arrangement returns to planning; it is not cancelled.</p></header>{rows.length === 0 ? <p className="safety-queue__empty">Nothing is awaiting safety review.</p> : <ul className="safety-queue__list">{rows.map(row => <li key={row.id}><div><strong>{row.event.name}</strong><span>Expected attendance: {row.event.expected_attendance ?? 'Not recorded'}</span></div><button className="button button--secondary" type="button" onClick={() => { setOpen(row); setReason(''); }}>Review</button></li>)}</ul>}{open && <section className="safety-queue__decision" aria-label={`Decide ${open.event.name}`}><h2>{open.event.name}</h2><ArrangementEvidence context={open.event} /><dl className="safety-queue__plan">{fields.map(([key, title]) => <div key={key}><dt>{title}</dt><dd>{open.plan[key]?.value || `Not applicable: ${open.plan[key]?.not_applicable_reason || 'No reason recorded'}`}</dd></div>)}</dl><div className="field"><label htmlFor="safety-decision-reason">Decision reason</label><textarea id="safety-decision-reason" value={reason} onChange={event => setReason(event.target.value)} placeholder="Required for changes or rejection" rows={3} /></div>{error && <p className="error" role="alert">{error}</p>}<div className="organisation-events__actions"><button className="button button--secondary" type="button" disabled={saving} onClick={() => void decide('approved')}>Approve</button><button className="button button--secondary" type="button" disabled={saving} onClick={() => void decide('changes_requested')}>Request changes</button><button className="button button--primary" type="button" disabled={saving} onClick={() => void decide('rejected')}>Reject</button></div></section>}</section>;
}
