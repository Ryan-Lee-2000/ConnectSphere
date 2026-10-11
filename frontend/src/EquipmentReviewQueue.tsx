import { useEffect, useMemo, useState } from 'react';
import { defaultRequest, responseError, type ApiRequest } from './api';

// SPL-92 (CS-E14-S3): the queue of equipment requirement lines awaiting Technical Support.
//
// This page is a work view. AC4 says opening it or adding a note must not reserve stock, change a
// line or message the organiser, so it only ever reads, plus one POST that writes a note. There is
// deliberately no reserve control here — reserving is SPL-97's workspace.
//
// Which lines appear, and in what order, is decided entirely by the server (AC1). This page does
// no filtering and no sorting of its own, so the two cannot drift apart.

type Account = { id: string; display_name: string | null };

type EquipmentType = { id: number; name: string; location: string | null };

type ReviewNote = {
  id: number;
  note: string;
  author: Account | null;
  created_at: string | null;
};

type QueueLine = {
  id: number;
  event: { id: number; name: string; date: string | null; status: string; status_label: string };
  coordinator: Account | null;
  organiser_equipment_text: string;
  equipment_type: EquipmentType | null;
  needs_mapping: boolean;
  quantity: number;
  required_start_date: string | null;
  required_end_date: string | null;
  status: string;
  notes?: string | null;
  review_notes?: ReviewNote[];
};

const formatDate = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('en-SG', {
        day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
      }).format(new Date(`${value}T00:00:00Z`))
    : 'Not recorded';

const formatMoment = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('en-SG', {
        day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
      }).format(new Date(value))
    : 'Not recorded';

const statusLabel = (value: string) =>
  value.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());

export function EquipmentReviewQueue({ accessToken, request }: {
  accessToken: string;
  request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [lines, setLines] = useState<QueueLine[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [openLine, setOpenLine] = useState<QueueLine | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await api('/api/equipment-review-queue');
        if (!response.ok) throw new Error(await responseError(response, 'Could not load the review queue.'));
        const body = await response.json() as { requirements: QueueLine[] };
        if (active) setLines(body.requirements);
      } catch (reason) {
        if (active) setLoadError(reason instanceof Error ? reason.message : 'Could not load the review queue.');
      }
    })();
    return () => { active = false; };
  }, [api]);

  async function open(line: QueueLine) {
    setNoteError(null); setConfirmation(null); setDraft('');
    // The detail comes from the server rather than from the list row, because opening a line is
    // what adds its technical notes and review notes (AC2).
    try {
      const response = await api(`/api/equipment-review-queue/${line.id}`);
      if (!response.ok) throw new Error(await responseError(response, 'Could not open that line.'));
      const body = await response.json() as { requirement: QueueLine };
      setOpenLine(body.requirement);
    } catch (reason) {
      setNoteError(reason instanceof Error ? reason.message : 'Could not open that line.');
    }
  }

  async function saveNote() {
    if (!openLine || saving) return;
    setSaving(true); setNoteError(null); setConfirmation(null);
    try {
      const response = await api(`/api/equipment-review-queue/${openLine.id}/notes`, {
        method: 'POST',
        // Sent as typed. The server decides what is acceptable, so its refusal is what the
        // reviewer reads (AC3).
        body: JSON.stringify({ note: draft }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) { setNoteError(body.error || 'Could not save that note. Try again.'); return; }
      setOpenLine({ ...openLine, review_notes: [...(openLine.review_notes || []), body.note] });
      setDraft('');
      setConfirmation('Note saved. The assigned coordinator can read it.');
    } catch { setNoteError('Could not save that note. Try again.'); }
    finally { setSaving(false); }
  }

  if (loadError) return <section className="equipment-review-queue"><p className="error" role="alert">{loadError}</p></section>;
  if (!lines) return <p role="status">Loading the equipment review queue…</p>;

  return <section className="equipment-review-queue" aria-labelledby="equipment-review-queue-title">
    <header>
      <p className="eyebrow">Technical support · review queue</p>
      <h1 id="equipment-review-queue-title">Equipment awaiting review</h1>
      <p>Lines waiting for Technical Support, soonest required first. Viewing a line or leaving a
        note does not reserve any stock.</p>
    </header>

    {lines.length === 0
      ? <section className="equipment-review-queue__empty">
          <h2>Nothing is awaiting review</h2>
          <p>Requirement lines appear here once a coordinator requests equipment for an active event.</p>
        </section>
      : <ul className="equipment-review-queue__list">
          {lines.map(line => <li key={line.id} className="equipment-review-queue__item">
            <div>
              <p className="equipment-review-queue__event">
                {line.event.name} · {formatDate(line.event.date)} · {line.event.status_label}
              </p>
              <h2>{line.equipment_type ? line.equipment_type.name : line.organiser_equipment_text}</h2>
              {/* AC2: a line never mapped to the catalogue is work in itself, so it says so. */}
              {line.needs_mapping && <p className="equipment-review-queue__flag">Needs mapping to the catalogue</p>}
              <dl className="equipment-review-queue__facts">
                <div><dt>Quantity</dt><dd>{line.quantity}</dd></div>
                <div><dt>Required</dt><dd>{formatDate(line.required_start_date)} – {formatDate(line.required_end_date)}</dd></div>
                <div><dt>Line status</dt><dd>{statusLabel(line.status)}</dd></div>
                <div><dt>Coordinator</dt><dd>{line.coordinator?.display_name || 'Not assigned'}</dd></div>
              </dl>
            </div>
            <button type="button" className="button button--secondary"
              aria-label={`Open ${line.equipment_type ? line.equipment_type.name : line.organiser_equipment_text}`}
              onClick={() => { void open(line); }}>Open</button>
          </li>)}
        </ul>}

    {openLine && <section className="equipment-review-queue__detail" aria-label="Line detail">
      <h2>{openLine.equipment_type ? openLine.equipment_type.name : openLine.organiser_equipment_text}</h2>
      <p>Event status: {openLine.event.status_label}</p>
      <h3>Technical notes</h3>
      <p>{openLine.notes || 'No technical notes recorded.'}</p>

      <h3>Review notes</h3>
      {(openLine.review_notes || []).length === 0
        ? <p>No review notes yet.</p>
        : <ul className="equipment-review-queue__notes">
            {(openLine.review_notes || []).map(note => <li key={note.id}>
              <span>{note.note}</span>
              <span>{note.author?.display_name || 'Unknown'} · {formatMoment(note.created_at)}</span>
            </li>)}
          </ul>}

      <form onSubmit={event => event.preventDefault()}>
        <label htmlFor="review-note">Add a note or question</label>
        <textarea id="review-note" name="note" value={draft}
          onChange={event => setDraft(event.target.value)} />
        {/* The server's refusal is shown beside the field it is about (TC-SPL-92-09). */}
        {noteError && <p className="error" role="alert">{noteError}</p>}
        {confirmation && <p className="notice" role="status">{confirmation}</p>}
        <button type="button" className="button button--primary" disabled={saving}
          onClick={() => { void saveNote(); }}>{saving ? 'Saving…' : 'Save note'}</button>
      </form>
    </section>}
  </section>;
}
