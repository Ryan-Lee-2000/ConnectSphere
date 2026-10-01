import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react';
import { defaultRequest, type ApiRequest } from './api';
import { ClarificationHistory, type Clarification } from './ClarificationHistory';
import { VenueAvailabilitySearch } from './VenueAvailabilitySearch';
import { VenueBookingPanel } from './VenueBookingWithdrawal';

const VENUE_BOOKING_STAGES = new Set(['planning', 'confirmed', 'completed', 'cancelled', 'postponed']);
import { slotLabel } from './slots';

type AssignedEvent = {
  id: number;
  name: string;
  status: string;
  status_label: string;
  proposed_date: string | null;
  mapped_slots: string[];
  expected_attendance?: number | null;
  preferred_room_layout?: string | null;
  required_facilities?: string[];
  accessibility_needs?: string[];
  location_preference?: string | null;
};

type EquipmentLine = { equipment_type: string; quantity: number; notes: string | null };

// Begin review answers with the summary shape only, so the full detail fields are optional here.
type AssignedEventDetail = AssignedEvent & Partial<{
  purpose: string | null;
  description: string | null;
  start_time: string | null;
  end_time: string | null;
  expected_attendance: number | null;
  venue_name: string | null;
  preferred_room_layout: string | null;
  required_facilities: string[];
  facilities_notes: string | null;
  accessibility_needs: string[];
  location_preference: string | null;
  venue_notes: string | null;
  equipment_requirements: EquipmentLine[];
  registration_required: boolean;
  registration_notes: string | null;
  client_organisation: string;
  responsible_organiser: string;
  submitted_at: string | null;
  clarifications: Clarification[];
  approved_by: { id: string; name: string } | null;
  approved_at: string | null;
  rejected_by: { id: string; name: string } | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  withdrawn_by: { id: string; name: string } | null;
  withdrawn_at: string | null;
  withdrawal_note: string | null;
}>;

const NOT_PROVIDED = 'Not provided';

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`))
    : NOT_PROVIDED;
}

function formatText(value: string | number | null | undefined) {
  return value === null || value === undefined || value === '' ? NOT_PROVIDED : String(value);
}

function formatList(values: string[] | undefined) {
  return values && values.length > 0 ? values.join(', ') : NOT_PROVIDED;
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) return NOT_PROVIDED;
  return new Intl.DateTimeFormat('en-SG', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Singapore' }).format(new Date(value));
}

function formatEquipment(lines: EquipmentLine[] | undefined) {
  if (!lines || lines.length === 0) return NOT_PROVIDED;
  return <ul className="organisation-events__list">{lines.map((line, index) => <li key={index}>
    {line.equipment_type} × {line.quantity}{line.notes ? ` (${line.notes})` : ''}
  </li>)}</ul>;
}

function detailRows(event: AssignedEventDetail): [string, string, [string, ReactNode][]][] {
  const time = event.start_time && event.end_time ? `${event.start_time}–${event.end_time}` : NOT_PROVIDED;
  return [
    ['core', 'Core details', [
      ['Status', event.status_label],
      ...(event.rejected_by ? [
        ['Rejected by', `${event.rejected_by.name}, ${formatTimestamp(event.rejected_at)}`] as [string, ReactNode],
        ['Rejection reason', formatText(event.rejection_reason)] as [string, ReactNode],
      ] : []),
      ...(event.approved_by ? [['Approved by', `${event.approved_by.name}, ${formatTimestamp(event.approved_at)}`] as [string, ReactNode]] : []),
      ...(event.withdrawn_by ? [
        ['Withdrawal recorded by', `${event.withdrawn_by.name}, ${formatTimestamp(event.withdrawn_at)}`] as [string, ReactNode],
        ['Withdrawal note', formatText(event.withdrawal_note)] as [string, ReactNode],
      ] : []),
      ['Purpose', formatText(event.purpose)],
      ['Description', formatText(event.description)],
      ['Proposed date', formatDate(event.proposed_date)],
      ['Time', time],
      ['Expected attendance', formatText(event.expected_attendance)],
    ]],
    ['venue', 'Venue requirements', [
      ['Venue', formatText(event.venue_name)],
      ['Preferred room layout', formatText(event.preferred_room_layout)],
      ['Required facilities', formatList(event.required_facilities)],
      ['Facilities notes', formatText(event.facilities_notes)],
      ['Accessibility needs', formatList(event.accessibility_needs)],
      ['Location preference', formatText(event.location_preference)],
      ['Venue notes', formatText(event.venue_notes)],
    ]],
    ['equipment', 'Equipment requirements', [
      ['Equipment', formatEquipment(event.equipment_requirements)],
    ]],
    ['registration', 'Registration needs', [
      ['Registration required', event.registration_required === undefined ? NOT_PROVIDED : event.registration_required ? 'Yes' : 'No'],
      ['Registration notes', formatText(event.registration_notes)],
    ]],
    ['organisation', 'Organisation and submission', [
      ['Client organisation', formatText(event.client_organisation)],
      ['Responsible Event Organiser', formatText(event.responsible_organiser)],
      ['Submission date and time', formatTimestamp(event.submitted_at)],
    ]],
  ];
}

function labelLayout(value: string | null | undefined) {
  return value ? value.replace(/\b\w/g, character => character.toUpperCase()) : 'No preference recorded';
}

function listValue(values: string[] | undefined) {
  return values?.length ? values.join(', ') : 'No preference recorded';
}

function EventBrief({ event }: { event: AssignedEvent }) {
  const slots = event.mapped_slots.length
    ? event.mapped_slots.map(slot => slotLabel(slot).split(' · ')[0]).join(', ')
    : 'No slots recorded';
  return <section className="event-brief" aria-labelledby="event-brief-title">
    <header className="event-brief__header"><div><p className="eyebrow">Assigned event</p><h2 id="event-brief-title">Requirements to consider</h2></div><span className="event-brief__status">{event.status_label}</span></header>
    <dl className="event-brief__overview">
      <div><dt>Event date</dt><dd>{formatDate(event.proposed_date)}</dd></div>
      <div><dt>Required slots</dt><dd>{slots}</dd></div>
      <div><dt>Expected attendance</dt><dd>{event.expected_attendance ?? 'Not recorded'}</dd></div>
    </dl>
    <dl className="event-brief__requirements">
      <div><dt>Room layout</dt><dd>{labelLayout(event.preferred_room_layout)}</dd></div>
      <div><dt>Required facilities</dt><dd>{listValue(event.required_facilities)}</dd></div>
      <div><dt>Accessibility needs</dt><dd>{listValue(event.accessibility_needs)}</dd></div>
      <div><dt>Location preference</dt><dd>{event.location_preference || 'No preference recorded'}</dd></div>
    </dl>
  </section>;
}

export function AssignedEvents({ accessToken, eventId, onNavigate, request, view = 'detail' }: {
  accessToken: string;
  eventId?: number;
  onNavigate: (path: string) => void;
  request?: ApiRequest;
  view?: 'detail' | 'venue-search';
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [events, setEvents] = useState<AssignedEvent[] | null>(null);
  const [event, setEvent] = useState<AssignedEventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);
  const [clarification, setClarification] = useState('');
  const [rejecting, setRejecting] = useState<'closed' | 'reason' | 'confirm'>('closed');
  const [rejectionReason, setRejectionReason] = useState('');
  const [withdrawing, setWithdrawing] = useState(false);
  const [withdrawalNote, setWithdrawalNote] = useState('');
  // SPL-79: whether the event, as loaded, was already at a stage that can hold a venue booking.
  const [bookingStageOnLoad, setBookingStageOnLoad] = useState(false);

  // Refresh recorded requirements on navigation, including entry into search without a remount.
  useEffect(() => {
    let active = true;
    setEvents(null);
    setEvent(null);
    setError(null);
    setNotice(null);
    setClarification('');
    setRejecting('closed');
    setRejectionReason('');
    setWithdrawing(false);
    setWithdrawalNote('');
    setBookingStageOnLoad(false);
    void (async () => {
      try {
        const response = await api(eventId === undefined
          ? '/api/event-requests/assigned'
          : `/api/event-requests/assigned/${eventId}`);
        const body = await response.json().catch(() => null);
        if (!active) return;
        if (!response.ok) {
          setError(eventId === undefined ? 'Could not load your assigned events. Try again.' : 'This assigned event is unavailable.');
        } else if (eventId === undefined && Array.isArray(body?.events)) {
          setEvents(body.events);
        } else if (eventId !== undefined && body?.event) {
          setEvent(body.event);
          setBookingStageOnLoad(VENUE_BOOKING_STAGES.has(body.event.status));
        } else {
          setError('Could not load your assigned events. Try again.');
        }
      } catch {
        if (active) setError('Could not load your assigned events. Try again.');
      }
    })();
    return () => { active = false; };
  }, [api, eventId, view]);

  function follow(click: MouseEvent<HTMLAnchorElement>, path: string) {
    click.preventDefault();
    onNavigate(path);
  }

  async function beginReview() {
    if (!event || event.status !== 'submitted' || transitioning) return;
    setTransitioning(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/begin-review`, { method: 'POST' });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setError(body?.error || 'Could not begin review. Try again.');
      } else if (body?.event) {
        setEvent(current => ({ ...current, ...body.event }));
        setNotice('Review started.');
      } else {
        setError('Could not begin review. Try again.');
      }
    } catch {
      setError('Could not begin review. Try again.');
    } finally {
      setTransitioning(false);
    }
  }

  async function approve() {
    if (!event || event.status !== 'under_review' || transitioning) return;
    setTransitioning(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/approve`, { method: 'POST' });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setError(body?.error || 'Could not approve the request. Try again.');
      } else if (body?.event) {
        setEvent(current => ({ ...current, ...body.event }));
        setNotice(body.message || 'Request approved. Event planning can begin.');
      } else {
        setError('Could not approve the request. Try again.');
      }
    } catch {
      setError('Could not approve the request. Try again.');
    } finally {
      setTransitioning(false);
    }
  }

  function reviewRejection() {
    if (!rejectionReason.trim()) {
      setError('Enter a reason for rejecting the request.');
      return;
    }
    setError(null);
    setRejecting('confirm');
  }

  async function reject() {
    if (!event || event.status !== 'under_review' || transitioning) return;
    if (!rejectionReason.trim()) {
      setError('Enter a reason for rejecting the request.');
      return;
    }
    setTransitioning(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/reject`, {
        method: 'POST',
        body: JSON.stringify({ reason: rejectionReason }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setError(body?.error || 'Could not reject the request. Try again.');
      } else if (body?.event) {
        setEvent(current => ({ ...current, ...body.event }));
        setRejecting('closed');
        setRejectionReason('');
        setNotice(body.message || 'Request rejected. The Event Organiser can see your reason.');
      } else {
        setError('Could not reject the request. Try again.');
      }
    } catch {
      setError('Could not reject the request. Try again.');
    } finally {
      setTransitioning(false);
    }
  }

  async function requestClarification() {
    if (!event || event.status !== 'under_review' || transitioning) return;
    if (!clarification.trim()) {
      setError('Enter a clarification message.');
      return;
    }
    setTransitioning(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/request-clarification`, {
        method: 'POST',
        body: JSON.stringify({ message: clarification }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setError(body?.error || 'Could not request clarification. Try again.');
      } else if (body?.event) {
        setEvent(current => ({ ...current, ...body.event, clarifications: body.clarifications ?? current?.clarifications }));
        setClarification('');
        setNotice('Clarification requested. The event is returned to the Event Organiser.');
      } else {
        setError('Could not request clarification. Try again.');
      }
    } catch {
      setError('Could not request clarification. Try again.');
    } finally {
      setTransitioning(false);
    }
  }

  async function withdraw() {
    if (!event || !['submitted', 'under_review', 'returned_for_clarification'].includes(event.status) || transitioning) return;
    setTransitioning(true);
    setError(null);
    setNotice(null);
    try {
      const response = await api(`/api/event-requests/${event.id}/withdraw`, {
        method: 'POST',
        body: JSON.stringify({ note: withdrawalNote }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setError(body?.error || 'Could not record the withdrawal. Try again.');
      } else if (body?.event) {
        setEvent(current => ({ ...current, ...body.event }));
        setWithdrawing(false);
        setWithdrawalNote('');
        setNotice(body.message || 'Withdrawal recorded. This request will not be reviewed further.');
      } else {
        setError('Could not record the withdrawal. Try again.');
      }
    } catch {
      setError('Could not record the withdrawal. Try again.');
    } finally {
      setTransitioning(false);
    }
  }

  const back = <a className="organisation-events__back" href="/workspace/assigned-events"
    onClick={click => follow(click, '/workspace/assigned-events')}>Back to my assigned events</a>;

  if (view === 'venue-search') {
    return <section className="organisation-events venue-search-page" aria-labelledby="venue-search-title">
      {back}
      <p className="eyebrow">Event Coordinator · Venue planning</p>
      <h1 id="venue-search-title">Find available venues</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {!error && !event && <p role="status">Loading the assigned event…</p>}
      {event && event.status !== 'planning' && <p className="error" role="alert">Venue search is available after this request is approved and moves to Planning.</p>}
      {event?.status === 'planning' && <>
        <p className="venue-search-page__event-name">Explore venue options for <strong>{event.name}</strong>. The filters start with this request’s details, but do not change it.</p>
        <div className="venue-search-page__layout">
          <VenueAvailabilitySearch accessToken={accessToken} eventId={event.id}
            initialDate={event.proposed_date} initialSlots={event.mapped_slots}
            expectedAttendance={event.expected_attendance ?? null} preferredRoomLayout={event.preferred_room_layout ?? null}
            requiredFacilities={event.required_facilities ?? []} accessibilityNeeds={event.accessibility_needs ?? []}
            locationPreference={event.location_preference ?? null} request={api} />
          <aside className="venue-search-page__brief" aria-label="Assigned event requirements"><EventBrief event={event} /></aside>
        </div>
      </>}
    </section>;
  }

  return <section className={`organisation-events${eventId !== undefined ? ' organisation-events--detail' : ''}`} aria-labelledby="assigned-events-title">
    {eventId !== undefined && back}
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {!error && events === null && event === null && <p role="status">Loading assigned events…</p>}
    {!event && <><p className="eyebrow">Event Coordinator</p><h1 id="assigned-events-title">My assigned events</h1></>}
    {event && <article className="organisation-events__detail-shell">
      <header className="organisation-events__detail-header">
        <p className="eyebrow">Event Coordinator</p>
        <h1 id="assigned-events-title">{event.name}</h1>
      </header>
      <EventBrief event={event} />
      {/* SPL-79: the event's venue-booking request, its status and history. A request can only be
          made once the event is in Planning (SPL-77), so earlier stages have nothing to show. The
          panel follows the event as loaded, so approving on this page performs no booking read. */}
      {bookingStageOnLoad && <VenueBookingPanel api={api} eventId={event.id} emptyMessage />}
      <div className="organisation-events__table-wrap">
        <table className="organisation-events__table organisation-events__detail-table">
          <caption className="visually-hidden">Submitted request details for {event.name}</caption>
          {detailRows(event).map(([key, heading, rows]) => <tbody key={key}>
            <tr><th scope="colgroup" colSpan={2}>{heading}</th></tr>
            {rows.map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td>{value}</td></tr>)}
          </tbody>)}
        </table>
      </div>
      {event.status === 'submitted' && <div className="organisation-events__actions">
        <button type="button" className="button button--primary" disabled={transitioning}
          onClick={() => { void beginReview(); }}>
          {transitioning ? 'Beginning review…' : 'Begin review'}
        </button>
      </div>}
      {event.status === 'under_review' && <div className="organisation-events__actions">
        <button type="button" className="button button--primary" disabled={transitioning}
          onClick={() => { void approve(); }}>
          {transitioning ? 'Working…' : 'Approve request'}
        </button>
      </div>}
      {event.status === 'under_review' && <form className="request-form clarification-form"
        onSubmit={submit => { submit.preventDefault(); void requestClarification(); }}>
        <div className="field">
          <label htmlFor="clarification-message">Clarification for the Event Organiser</label>
          <textarea id="clarification-message" rows={4} maxLength={2000} value={clarification}
            onChange={change => setClarification(change.target.value)} />
        </div>
        <div className="organisation-events__actions">
          <button type="submit" className="button button--primary" disabled={transitioning}>
            {transitioning ? 'Requesting clarification…' : 'Request clarification'}
          </button>
        </div>
      </form>}
      {event.status === 'under_review' && rejecting === 'closed' && <div className="organisation-events__actions">
        <button type="button" className="button button--secondary" disabled={transitioning}
          onClick={() => setRejecting('reason')}>Reject request</button>
      </div>}
      {event.status === 'under_review' && rejecting === 'reason' && <form className="request-form rejection-form"
        onSubmit={submit => { submit.preventDefault(); reviewRejection(); }}>
        <div className="field">
          <label htmlFor="rejection-reason">Reason for rejecting this request</label>
          <textarea id="rejection-reason" rows={4} maxLength={2000} value={rejectionReason}
            onChange={change => setRejectionReason(change.target.value)} />
        </div>
        <div className="organisation-events__actions">
          <button type="button" className="button button--secondary"
            onClick={() => { setRejecting('closed'); setRejectionReason(''); setError(null); }}>Cancel</button>
          <button type="submit" className="button button--primary">Continue</button>
        </div>
      </form>}
      {event.status === 'under_review' && rejecting === 'confirm' && <div className="rejection-form" role="group" aria-label="Confirm rejection">
        <p><strong>Reject this request?</strong> Rejection is final. The Event Organiser will see your reason and must submit a new event request to proceed.</p>
        <p>{rejectionReason.trim()}</p>
        <div className="organisation-events__actions">
          <button type="button" className="button button--secondary" disabled={transitioning}
            onClick={() => setRejecting('reason')}>Back</button>
          <button type="button" className="button button--primary" disabled={transitioning}
            onClick={() => { void reject(); }}>
            {transitioning ? 'Rejecting…' : 'Confirm rejection'}
          </button>
        </div>
      </div>}
      {['submitted', 'under_review', 'returned_for_clarification'].includes(event.status) && !withdrawing && <div className="organisation-events__actions">
        <button type="button" className="button button--secondary" disabled={transitioning}
          onClick={() => setWithdrawing(true)}>Record withdrawal</button>
      </div>}
      {['submitted', 'under_review', 'returned_for_clarification'].includes(event.status) && withdrawing && <form className="request-form rejection-form"
        onSubmit={submit => { submit.preventDefault(); void withdraw(); }}>
        <p><strong>Record this request as withdrawn?</strong> It will remain available for reference and cannot continue through review or planning.</p>
        <div className="field">
          <label htmlFor="withdrawal-note">Withdrawal note (optional)</label>
          <textarea id="withdrawal-note" rows={3} maxLength={2000} value={withdrawalNote}
            onChange={change => setWithdrawalNote(change.target.value)} />
        </div>
        <div className="organisation-events__actions">
          <button type="button" className="button button--secondary" disabled={transitioning}
            onClick={() => { setWithdrawing(false); setWithdrawalNote(''); setError(null); }}>Keep reviewing</button>
          <button type="submit" className="button button--primary" disabled={transitioning}>
            {transitioning ? 'Recording withdrawal…' : 'Confirm withdrawal'}
          </button>
        </div>
      </form>}
      {event.clarifications && <ClarificationHistory clarifications={event.clarifications} heading="Clarification history" />}
      {event.status === 'planning' && <div className="organisation-events__actions organisation-events__actions--planning">
        <div><span className="organisation-events__planning-label">Next step</span><strong>Find a venue</strong><span>Search availability without changing this event or creating a booking.</span></div>
        <button type="button" className="button button--primary"
          onClick={() => onNavigate(`/workspace/assigned-events/${event.id}/venue-search`)}>
          Find venues
        </button>
      </div>}
    </article>}
    {events?.length === 0 && <div className="organisation-events__empty" role="status">
      <strong>No events assigned to you yet.</strong>
      <span>Events appear here when an Event Operations Manager assigns them to you.</span>
    </div>}
    {events && events.length > 0 && <div className="organisation-events__table-wrap">
      <table className="organisation-events__table">
        <caption className="visually-hidden">Events currently assigned to you</caption>
        <thead><tr><th scope="col">Event</th><th scope="col">Status</th><th scope="col">Proposed date</th></tr></thead>
        <tbody>{events.map(item => <tr key={item.id}>
          <td><a href={`/workspace/assigned-events/${item.id}`}
            onClick={click => follow(click, `/workspace/assigned-events/${item.id}`)}>{item.name}</a></td>
          <td>{item.status_label}</td>
          <td>{formatDate(item.proposed_date)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
  </section>;
}
