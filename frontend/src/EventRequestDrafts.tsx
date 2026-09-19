import { useEffect, useState } from 'react';
import type { ApiRequest } from './api';
import { EventRequestForm } from './EventRequestForm';

const LOAD_FAILURE_MESSAGE =
  "We couldn't load your requests. Refresh the page or try again shortly.";
const DELETE_FAILURE_MESSAGE = 'Could not delete the draft. Please try again.';

// CS-E07-S1 shows the status of a submitted request; SPL-56/57/58 add the draft lifecycle
// (save, reopen/resave/submit, delete). Both live on this one "my requests" screen since a
// draft is just an event_requests row with status='draft', not a separate concept.
type RequestSummary = {
  id: number;
  name: string;
  status: string;
  status_label: string;
  status_explanation: string;
  status_changed_at: string | null;
  last_saved_at: string | null;
};

function mostRecentFirst(rows: RequestSummary[]) {
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

export function EventRequestDrafts({ accessToken, request, onUnsavedChanges }: {
  accessToken: string;
  request?: ApiRequest;
  onUnsavedChanges?: (hasUnsavedChanges: boolean) => void;
}) {
  const [items, setItems] = useState<RequestSummary[] | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const api: ApiRequest = request || ((path, init = {}) => fetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json', ...init.headers },
  }));

  async function refresh() {
    setError(null);
    try {
      const response = await api('/api/event-requests');
      const payload = await response.json().catch(() => null);
      if (!response.ok || !Array.isArray(payload?.event_requests)) {
        setError(LOAD_FAILURE_MESSAGE);
        return;
      }
      setItems(payload.event_requests);
    } catch {
      setError(LOAD_FAILURE_MESSAGE);
    }
  }

  useEffect(() => { void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  async function deleteDraft(id: number) {
    setError(null);
    try {
      const response = await api(`/api/event-requests/drafts/${id}`, { method: 'DELETE' });
      if (!response.ok) { setError(DELETE_FAILURE_MESSAGE); return; }
      setItems(current => (current ?? []).filter(item => item.id !== id));
      setConfirming(null);
    } catch {
      setError(DELETE_FAILURE_MESSAGE);
    }
  }

  if (editing !== null) return <EventRequestForm
    accessToken={accessToken}
    request={request}
    draftId={editing}
    onUnsavedChanges={onUnsavedChanges}
    onCancel={() => { setEditing(null); onUnsavedChanges?.(false); void refresh(); }}
    onSubmitted={() => { setEditing(null); onUnsavedChanges?.(false); void refresh(); }}
  />;

  const drafts = items ? items.filter(item => item.status === 'draft') : [];
  const submitted = items ? mostRecentFirst(items.filter(item => item.status !== 'draft')) : [];

  return <div className="event-request-status">
    <p className="eyebrow">My requests</p>
    <h1 id="my-requests-title">The status of my events</h1>
    <p>Your saved drafts, and each request you have submitted with what is happening to it now.</p>

    {error && <div className="form-message form-message--error" role="alert"><span>{error}</span></div>}
    {!error && items === null && <p className="event-request-status__loading">Loading your requests…</p>}

    {!error && items !== null && <>
      <h2>Drafts</h2>
      {drafts.length === 0 && (
        <div className="form-message form-message--info" role="status">
          <strong>No saved drafts.</strong>
        </div>
      )}
      {drafts.length > 0 && <ul className="request-list">
        {drafts.map(item => <li key={item.id}>
          <div>
            <strong>{item.name}</strong>{' '}
            <span className="event-request-status__label">Draft</span>
            <p>Last saved: {item.last_saved_at ? new Date(item.last_saved_at).toLocaleString() : 'Unknown'}</p>
          </div>
          <div className="request-list__actions">
            <button className="button button--secondary" type="button" onClick={() => setEditing(item.id)}>Reopen draft</button>
            {confirming === item.id ? <>
              <span>Delete this draft?</span>
              <button className="button button--secondary" type="button" onClick={() => setConfirming(null)}>Cancel</button>
              <button className="button button--primary" type="button" onClick={() => void deleteDraft(item.id)}>Confirm delete</button>
            </> : <button className="button button--secondary" type="button" onClick={() => setConfirming(item.id)}>Delete draft</button>}
          </div>
        </li>)}
      </ul>}

      <h2>Submitted requests</h2>
      {submitted.length === 0 && (
        <div className="form-message form-message--info" role="status">
          <strong>You have not submitted any event requests yet.</strong>
          <span> Once you submit one, its status will appear here.</span>
        </div>
      )}
      {submitted.length > 0 && <table className="event-request-status__table">
        <caption className="visually-hidden">Your submitted event requests, most recently updated first</caption>
        <thead>
          <tr><th scope="col">Event</th><th scope="col">Status</th><th scope="col">As of</th></tr>
        </thead>
        <tbody>
          {submitted.map(item => <tr key={item.id}>
            <td><strong>{item.name}</strong><span className="event-request-status__reference">EVT-{item.id}</span></td>
            <td>
              <span className="event-request-status__label">{item.status_label}</span>
              <span className="event-request-status__explanation">{item.status_explanation}</span>
            </td>
            <td>{item.status_changed_at ? new Date(item.status_changed_at).toLocaleString() : 'Not recorded'}</td>
          </tr>)}
        </tbody>
      </table>}
    </>}
  </div>;
}
