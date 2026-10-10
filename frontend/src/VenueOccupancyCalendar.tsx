import { useEffect, useMemo, useState } from 'react';
import { CalendarRange } from 'lucide-react';
import { defaultRequest, responseError, type ApiRequest } from './api';

// SPL-88 (CS-E11-S1): a venue's occupancy for a date range, one cell per operating slot. Read-only:
// changing the venue or the range only re-reads, it never writes (AC6). The server decides each
// slot's headline status and the reasons behind it; this screen only renders them, so the
// precedence rule lives in one place rather than being re-derived here.

type Reason = { key: string; label: string; detail: string };
type SlotEntry = { slot: string; status: string; reasons: Reason[] };
type TimedEntry = { requires_review?: boolean; start: string; end: string; status: string; reasons: Reason[] };
type DayEntry = { date: string; slots: SlotEntry[]; intervals?: TimedEntry[] };
type Calendar = { mode?: 'exact'; venue: { id: number; name: string }; start_date: string; end_date: string; days: DayEntry[] };
export type CalendarVenue = { id: number; name: string };

// AC2 and AC5: every state a slot can hold, each with its own visible label. "Not operated" is
// deliberately its own entry so it can never read as Available.
const STATUS_NAMES: Record<string, string> = {
  review_required: 'Timing review required',
  available: 'Available',
  requested: 'Requested',
  booked: 'Booked',
  preparation: 'Preparation',
  blocked: 'Blocked',
  not_operated: 'Not operated',
};
const SLOT_NAMES: Record<string, string> = { AM: 'AM', PM: 'PM', NIGHT: 'Night' };
const SLOTS = ['AM', 'PM', 'NIGHT'];
// Calendar dates must not shift with the viewer's time zone.
const dateName = (day: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
}).format(new Date(`${day}T00:00:00Z`));

function addDays(day: string, count: number) {
  if (!day) return '';
  const shifted = new Date(`${day}T00:00:00Z`);
  shifted.setUTCDate(shifted.getUTCDate() + count);
  return shifted.toISOString().slice(0, 10);
}

export function VenueOccupancyCalendar({ accessToken, venues, request }: {
  accessToken: string;
  venues: CalendarVenue[];
  request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [venueId, setVenueId] = useState(() => venues[0]?.id ?? 0);
  const [start, setStart] = useState(() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Singapore', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()));
  // The server refuses more than 31 days, so the default range stays well inside it.
  const [days, setDays] = useState(7);
  const [calendar, setCalendar] = useState<Calendar | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const end = addDays(start, days - 1);

  useEffect(() => {
    if (!venueId || !start) { setCalendar(null); setError(null); return; }
    let active = true;
    setError(null); setCalendar(null);
    void api(`/api/venues/${venueId}/occupancy?start_date=${start}&end_date=${end}`)
      .then(async response => {
        if (!response.ok) {
          const message = await responseError(response, 'Could not load this venue calendar.');
          if (active) { setError(message); setCalendar(null); }
          return;
        }
        const next = await response.json() as Calendar;
        if (active) setCalendar(next);
      })
      .catch(() => { if (active) setError('Could not load this venue calendar.'); });
    return () => { active = false; };
  }, [api, venueId, start, end, refresh]);

  return <section className="occupancy-calendar" aria-labelledby="occupancy-calendar-heading">
    <header className="catalogue-header">
      <div>
        <p className="eyebrow"><CalendarRange size={14} /> Venue occupancy</p>
        <h1 id="occupancy-calendar-heading">Venue calendar</h1>
        <p className="catalogue-subtitle">
          Occupancy for the chosen venue and dates. All times are Singapore time (SGT).
        </p>
      </div>
    </header>

    <div className="occupancy-calendar__controls">
      <label>Venue
        <select onChange={change => setVenueId(Number(change.target.value))} value={venueId}>
          {venues.map(venue => <option key={venue.id} value={venue.id}>{venue.name}</option>)}
        </select>
      </label>
      <label>From
        <input onChange={change => setStart(change.target.value)} type="date" value={start} />
      </label>
      <label>Days
        <select onChange={change => setDays(Number(change.target.value))} value={days}>
          {[7, 14, 31].map(option => <option key={option} value={option}>{option}</option>)}
        </select>
      </label>
    </div>

    <button type="button" onClick={() => setRefresh(value => value + 1)}>Refresh calendar</button>
    {error && <p className="error" role="alert">{error}</p>}
    {!start && <p role="status">Choose a start date to view occupancy.</p>}
    {!calendar && !error && start && venueId !== 0 && <p role="status">Loading the calendar…</p>}

    {calendar?.mode === 'exact' && <div className="occupancy-calendar__exact" aria-label="Exact venue occupancy">
      {calendar.days.map(day => <section key={day.date} aria-label={dateName(day.date)}>
        <h2>{dateName(day.date)}</h2>
        <ul>{day.intervals?.map(entry => <li className={`occupancy-cell occupancy-cell--${entry.status}`} key={entry.start}>
          <strong>{clockTime(entry.start)} – {entry.end.slice(0, 10) !== day.date ? '24:00' : clockTime(entry.end)} · {STATUS_NAMES[entry.status] || entry.status}</strong>
          {entry.reasons.map((reason, index) => <span className="occupancy-cell__reason" key={`${reason.key}-${index}`}>{reason.label}</span>)}
          {entry.requires_review && <strong>Review required</strong>}
        </li>)}</ul>
      </section>)}
    </div>}
    {calendar && calendar.mode !== 'exact' && <div className="occupancy-calendar__grid" role="grid" aria-label="Venue occupancy">
      <div className="occupancy-calendar__row occupancy-calendar__row--head" role="row">
        <span role="columnheader">Date</span>
        {SLOTS.map(slot => <span key={slot} role="columnheader">{SLOT_NAMES[slot]}</span>)}
      </div>
      {calendar.days.map(day => <div className="occupancy-calendar__row" key={day.date} role="row">
        <span className="occupancy-calendar__date" role="rowheader">{dateName(day.date)}</span>
        {day.slots.map(entry => (
          <div
            aria-label={`${dateName(day.date)}, ${entry.slot}: ${STATUS_NAMES[entry.status] || entry.status}`}
            className={`occupancy-cell occupancy-cell--${entry.status}`}
            key={entry.slot}
            role="gridcell"
          >
            <strong>{STATUS_NAMES[entry.status] || entry.status}</strong>
            {/* AC4: a slot can have more than one reason. The headline above is the most serious
                one; every reason is still listed here so nothing is lost behind that single word. */}
            {entry.reasons.map(reason => (
              <span className="occupancy-cell__reason" key={reason.key}>
                <span className="occupancy-cell__reason-label">{reason.label}</span>
                <span className="occupancy-cell__reason-detail">{reason.detail}</span>
              </span>
            ))}
          </div>
        ))}
      </div>)}
    </div>}
  </section>;
}

function clockTime(value: string) {
  return new Intl.DateTimeFormat('en-SG', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Singapore' }).format(new Date(value));
}
