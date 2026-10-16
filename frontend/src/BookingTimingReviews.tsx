import { useEffect, useMemo, useState } from 'react';
import { CircleAlert, ClipboardCheck } from 'lucide-react';
import { defaultRequest, responseError, type ApiRequest } from './api';
import { occupancyName, type BookingReviewFinding } from './BookingReviewFindings';

type AffectedBooking = {
  booking_id: number;
  status: string;
  event: { id: number; name: string; advertised_interval: { start: string; end: string } | null };
  venue: { id: number; name: string };
  coordinator: { id: string; name: string } | null;
  findings: BookingReviewFinding[];
};

export function BookingTimingReviews({ accessToken, onOpen, request }: {
  accessToken: string;
  onOpen: (bookingId: number) => void;
  request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [reviews, setReviews] = useState<AffectedBooking[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api('/api/venue-bookings/timing-reviews').then(async response => {
      if (!response.ok) {
        if (active) setError(await responseError(response, 'Could not load timing reviews.'));
        return;
      }
      const body = await response.json() as { reviews?: AffectedBooking[] };
      if (active) setReviews(body.reviews || []);
    }).catch(() => { if (active) setError('Could not load timing reviews.'); });
    return () => { active = false; };
  }, [api]);

  return <section className="assignment-queue" aria-labelledby="timing-reviews-heading">
    <header className="catalogue-header">
      <div>
        <p className="eyebrow"><ClipboardCheck size={14} /> Venue timing</p>
        <h1 id="timing-reviews-heading">Bookings needing timing review</h1>
        <p className="catalogue-subtitle">Requested and Approved commitments affected by revised venue rules.</p>
      </div>
    </header>
    {error && <p className="error" role="alert">{error}</p>}
    {reviews === null && !error && <p role="status">Loading timing reviews…</p>}
    {reviews?.length === 0 && <div className="catalogue-empty"><ClipboardCheck size={28} /><h2>No timing reviews</h2><p>No active booking has an outstanding timing finding.</p></div>}
    {reviews && reviews.length > 0 && <div className="assignment-table"><table>
      <caption className="visually-hidden">Active venue bookings with timing review findings</caption>
      <thead><tr><th scope="col">Event</th><th scope="col">Venue</th><th scope="col">Coordinator</th><th scope="col">Status</th><th scope="col">Reason and occupancy</th><th scope="col"><span className="visually-hidden">Action</span></th></tr></thead>
      <tbody>{reviews.map(item => <tr key={item.booking_id}>
        <th scope="row">{item.event.name}{item.event.advertised_interval && <span className="timing-review-event-time">Advertised: {occupancyName(item.event.advertised_interval)}</span>}<span className="request-flag"><CircleAlert size={14} /> Needs review</span></th>
        <td>{item.venue.name}</td>
        <td>{item.coordinator?.name || 'Not assigned'}</td>
        <td>{item.status === 'approved' ? 'Approved' : 'Requested'}</td>
        <td><ul className="timing-review-list">{item.findings.map(finding => <li key={finding.id}><strong>{finding.detail}</strong><span>Original: {occupancyName(finding.original_occupancy)}</span><span>Current: {occupancyName(finding.current_occupancy)}</span></li>)}</ul></td>
        <td><button className="button button--secondary" type="button" onClick={() => onOpen(item.booking_id)}>Review</button></td>
      </tr>)}</tbody>
    </table></div>}
  </section>;
}
