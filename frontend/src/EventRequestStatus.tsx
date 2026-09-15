import { useEffect, useState } from 'react';

const LOAD_FAILURE_MESSAGE =
  "We couldn't load your requests. Refresh the page or try again shortly.";

// CS-E07-S1 shows the status of a request and when it last moved. Everything else about the
// request — venue, equipment, registration — belongs to CS-E03-S1 to S4.
type EventRequestStatusRow = {
  id: number;
  name: string;
  status_label: string;
  status_explanation: string;
  status_changed_at: string | null;
  // CS-E05-S2 AC6 and CS-E05-S3 AC6: who is responsible, once a coordinator has been assigned.
  coordinator: { id: string; name: string } | null;
};

function formatChangedAt(value: string | null) {
  if (value === null) return 'Not recorded';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Not recorded';
  return parsed.toLocaleString();
}

// Most recent first, so the request an organiser has just submitted is at the top. Requests
// with no recorded time sort last rather than disappearing among the newest.
function mostRecentFirst(rows: EventRequestStatusRow[]) {
  return [...rows].sort((left, right) => {
    const leftTime = left.status_changed_at ? Date.parse(left.status_changed_at) : NaN;
    const rightTime = right.status_changed_at ? Date.parse(right.status_changed_at) : NaN;
    if (Number.isNaN(leftTime) && Number.isNaN(rightTime)) return right.id - left.id;
    if (Number.isNaN(leftTime)) return 1;
    if (Number.isNaN(rightTime)) return -1;
    if (leftTime === rightTime) return right.id - left.id;
    return rightTime - leftTime;
  });
}

export function EventRequestStatus({ accessToken }: { accessToken: string }) {
  const [requests, setRequests] = useState<EventRequestStatusRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const response = await fetch('/api/event-requests', {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        const payload = await response.json().catch(() => null);
        if (!active) return;
        if (!response.ok || !Array.isArray(payload?.event_requests)) {
          setError(LOAD_FAILURE_MESSAGE);
          return;
        }
        setRequests(mostRecentFirst(payload.event_requests));
      } catch {
        if (active) setError(LOAD_FAILURE_MESSAGE);
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [accessToken]);

  return (
    <div className="event-request-status">
      <p className="eyebrow">My requests</p>
      <h1 id="my-requests-title">The status of my events</h1>
      <p>Each request you have submitted, and what is happening to it now.</p>

      {error && (
        <div className="form-message form-message--error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {!error && requests === null && <p className="event-request-status__loading">Loading your requests…</p>}

      {!error && requests !== null && requests.length === 0 && (
        <div className="form-message form-message--info" role="status">
          <strong>You have not submitted any event requests yet.</strong>
          <span> Once you submit one, its status will appear here.</span>
        </div>
      )}

      {!error && requests !== null && requests.length > 0 && (
        <table className="event-request-status__table">
          <caption className="visually-hidden">
            Your event requests, most recently updated first
          </caption>
          <thead>
            <tr>
              <th scope="col">Event</th>
              <th scope="col">Status</th>
              <th scope="col">Event Coordinator</th>
              <th scope="col">As of</th>
            </tr>
          </thead>
          <tbody>
            {requests.map(request => (
              <tr key={request.id}>
                <td>
                  <strong>{request.name}</strong>
                  <span className="event-request-status__reference">EVT-{request.id}</span>
                </td>
                <td>
                  {/* The status is carried by text. Any styling only reinforces it. */}
                  <span className="event-request-status__label">{request.status_label}</span>
                  <span className="event-request-status__explanation">
                    {request.status_explanation}
                  </span>
                </td>
                <td>{request.coordinator ? request.coordinator.name : 'Not assigned yet'}</td>
                <td>{formatChangedAt(request.status_changed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
