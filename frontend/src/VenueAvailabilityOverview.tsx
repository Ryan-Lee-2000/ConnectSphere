import { useEffect, useMemo, useState } from 'react';
import { defaultRequest, responseError, type ApiRequest } from './api';
import type { AccountRole } from './roles';
import './venue-overview.css';

type Period = { start: string; end: string };
type Reason = { key: string; label: string; detail: string; event_name?: string; period?: Period; links?: { label: string; href: string; role: AccountRole }[] };
type Entry = Period & { status: string; requires_review: boolean; reasons: Reason[] };
type Venue = { id: number; name: string; intervals: Entry[] };
export type Overview = { date: string; timezone: string; venues: Venue[] };
const names: Record<string, string> = { available: 'Available', requested: 'Requested / held', booked: 'Approved', preparation: 'Preparation', blocked: 'Closure', not_operated: 'Closed hours', review_required: 'Timing unconfirmed' };
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Singapore', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const clock = (value: string) => new Intl.DateTimeFormat('en-SG', { timeZone: 'Asia/Singapore', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value));
const fullTime = (value: string) => new Intl.DateTimeFormat('en-SG', { timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value));
function label(entry: Entry) {
  return entry.status === 'preparation' ? entry.reasons.filter(r => r.key === 'setup' || r.key === 'turnaround').map(r => r.label).filter((v, i, all) => all.indexOf(v) === i).join(' / ') || 'Preparation' : names[entry.status] || entry.status;
}
function range(entry: Period, day: string) {
  return `${clock(entry.start)}–${entry.end.slice(0, 10) !== day ? '24:00' : clock(entry.end)}`;
}
function tone(entry: Entry) {
  return entry.status === 'preparation' && entry.reasons.some(r => r.key === 'turnaround') ? 'turnaround' : entry.status;
}

export function VenueAvailabilityOverview({ accessToken, activeRole, request }: {
  accessToken: string; activeRole: AccountRole; request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [date, setDate] = useState(today);
  const [refresh, setRefresh] = useState(0);
  const [loaded, setLoaded] = useState<{ body: Overview; role: AccountRole; api: ApiRequest; refresh: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ venue: number; start?: string } | null>(null);
  const data = loaded?.body.date === date && loaded.role === activeRole && loaded.api === api && loaded.refresh === refresh ? loaded.body : null;
  const venue = data?.venues.find(row => row.id === selected?.venue);
  const entry = venue?.intervals.find(row => row.start === selected?.start);

  useEffect(() => {
    let active = true;
    setLoaded(null); setSelected(null); setError(null);
    if (!date) return;
    void api(`/api/venues/occupancy-overview?date=${encodeURIComponent(date)}`).then(async response => {
      if (!response.ok) {
        const message = await responseError(response, 'Could not load venue availability. Please retry.');
        if (active) setError(message);
        return;
      }
      const body = await response.json() as Overview;
      if (active) setLoaded({ body, role: activeRole, api, refresh });
    }).catch(() => { if (active) setError('Could not load venue availability. Please retry.'); });
    return () => { active = false; };
  }, [api, date, refresh, activeRole]);

  return <section className="venue-overview" aria-labelledby="venue-overview-heading">
    <header className="catalogue-header"><div>
      <p className="eyebrow">Venue occupancy</p>
      <h1 id="venue-overview-heading">All venues</h1>
      <p className="catalogue-subtitle">Compare one day in Singapore time (SGT). Select a venue or period for details.</p>
    </div></header>
    <div className="occupancy-calendar__controls">
      <label className="field">Date (Singapore time)<input type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
      <button className="button button--secondary" type="button" disabled={!date} onClick={() => setRefresh(n => n + 1)}>Refresh availability</button>
    </div>
    <p className="venue-overview__hint">Available means unoccupied operating time. Booking checks also include your event’s preparation and requirements.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {!date && <p role="status">Choose a date to view availability.</p>}
    {date && !data && !error && <p role="status">Loading venue availability…</p>}
    {data?.venues.length === 0 && <p role="status">No venues have been added yet.</p>}
    {data && data.venues.length > 0 && <>
      <ul className="venue-overview__legend" aria-label="Timeline key">
        {(['available', 'requested', 'booked', 'preparation', 'turnaround', 'blocked', 'not_operated', 'review_required'] as const).map(state => <li key={state}><span aria-hidden="true" className={`venue-overview__swatch venue-overview__tone--${state}`} />{state === 'preparation' ? 'Setup' : state === 'turnaround' ? 'Turnaround' : names[state]}</li>)}
        <li>! Review required</li>
      </ul>
      <div className="venue-overview__scroll" role="region" aria-label="All venues timeline, scroll horizontally for the full day" tabIndex={0}>
        <div className="venue-overview__grid">
          <div className="venue-overview__row venue-overview__axis" aria-hidden="true"><span>Venue</span><div>{['00:00', '06:00', '12:00', '18:00', '24:00'].map((hour, index) => <span key={hour} style={{ left: `${index * 25}%` }}>{hour}</span>)}</div></div>
          {data.venues.map(row => <div className="venue-overview__row" key={row.id}>
            <button className="venue-overview__name" aria-label={`Inspect ${row.name}`} aria-pressed={venue?.id === row.id} onClick={() => setSelected({ venue: row.id })}>{row.name}</button>
            <div className="venue-overview__track">
              {row.intervals.map(period => <button type="button" key={period.start}
                className={`venue-overview__segment venue-overview__tone--${tone(period)}`}
                style={{ flex: `${new Date(period.end).getTime() - new Date(period.start).getTime()} 1 0` }}
                aria-label={`${row.name}, ${range(period, date)} ${label(period)}${period.requires_review ? ', review required' : ''}`}
                title={`${range(period, date)} ${label(period)}${period.requires_review ? ' · Review required' : ''}`}
                onClick={() => setSelected({ venue: row.id, start: period.start })}>
                <span aria-hidden="true">{period.requires_review ? '! ' : ''}{label(period)}</span>
              </button>)}
            </div>
          </div>)}
        </div>
      </div>
      <p className="venue-overview__hint">Quarter-hour guides; setup and turnaround retain their exact minute boundaries. Select a venue name for a readable list of periods.</p>
      {venue && <section className="venue-overview__periods" aria-label={`${venue.name} periods`}>
        <h2>{venue.name}</h2>
        <p>{date} · Singapore time</p>
        <ul>{venue.intervals.map(period => <li key={period.start}>
          <button type="button" aria-pressed={entry?.start === period.start} aria-label={`Inspect ${range(period, date)} ${label(period)}`} onClick={() => setSelected({ venue: venue.id, start: period.start })}>
            <span>{range(period, date)}</span><strong>{label(period)}</strong>{period.requires_review && <span>! Review required</span>}
          </button>
        </li>)}</ul>
      </section>}
      {entry && <section className="venue-overview__detail" aria-label="Selected period">
        <h2>{label(entry)}</h2>
        <p>{fullTime(entry.start)} to {fullTime(entry.end)} SGT</p>
        {entry.requires_review && <p className="venue-overview__review"><strong>Review required</strong><br />{entry.status === 'review_required' ? 'Availability cannot be confirmed until timing is reviewed.' : 'Recorded occupancy remains in place while review is outstanding.'}</p>}
        <ul>{entry.reasons.map((reason, index) => <li key={`${reason.key}-${index}`}>
          <strong>{reason.label}</strong>
          {reason.period && <p>{fullTime(reason.period.start)} to {fullTime(reason.period.end)} SGT</p>}
          {reason.detail !== reason.label && <p>{reason.detail}</p>}
          {reason.event_name && <p>{reason.event_name}</p>}
          {reason.links?.filter(link => link.role === activeRole).map(link => <a key={link.href} href={link.href}>{link.label}</a>)}
        </li>)}</ul>
        {entry.status === 'available' && <p>No recorded occupancy in this operating period. Use venue search to check a proposed booking.</p>}
      </section>}
    </>}
  </section>;
}
