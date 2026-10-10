import { useEffect, useMemo, useState } from 'react';
import { defaultRequest, type ApiRequest } from './api';
import { VenueOccupancyCalendar, type CalendarVenue } from './VenueOccupancyCalendar';
import { VenueAvailabilityOverview } from './VenueAvailabilityOverview';
import type { AccountRole } from './roles';

// SPL-88: loads the venue list the calendar's picker chooses from, so the calendar itself stays a
// pure renderer of one venue's occupancy and can be tested without a second stubbed request.

function OneVenueCalendar({ accessToken, request }: {
  accessToken: string;
  request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [venues, setVenues] = useState<CalendarVenue[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api('/api/venues').then(async response => {
      if (!response.ok) {
        if (active) setError('Could not load the venue list.');
        return;
      }
      const body = await response.json() as { venues: CalendarVenue[] };
      if (active) setVenues(body.venues);
    }).catch(() => { if (active) setError('Could not load the venue list.'); });
    return () => { active = false; };
  }, [api]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!venues) return <p role="status">Loading venues…</p>;
  if (venues.length === 0) {
    return <p className="catalogue-empty">No venues have been added yet.</p>;
  }
  return <VenueOccupancyCalendar accessToken={accessToken} request={request} venues={venues} />;
}


export function VenueOccupancyCalendarPage({ accessToken, activeRole, request }: {
  accessToken: string; activeRole: AccountRole; request?: ApiRequest;
}) {
  const [view, setView] = useState<'one' | 'all'>('one');
  return <>
    <div className="calendar-view-switch" role="group" aria-label="Calendar view">
      <button className="button button--secondary" type="button" aria-pressed={view === 'one'} onClick={() => setView('one')}>One venue</button>
      <button className="button button--secondary" type="button" aria-pressed={view === 'all'} onClick={() => setView('all')}>All venues</button>
    </div>
    {view === 'one' ? <OneVenueCalendar accessToken={accessToken} request={request} />
      : <VenueAvailabilityOverview accessToken={accessToken} activeRole={activeRole} request={request} />}
  </>;
}
