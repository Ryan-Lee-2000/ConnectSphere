import { useEffect, useState } from 'react';
import { EventRequestCreate, type EventRequestApi } from './EventRequestCreate';

type RequestSummary = {
  id: number;
  name: string;
  status: string;
  proposed_date: string | null;
  last_saved_at: string | null;
};

export function EventRequestDrafts({ accessToken, onUnsavedChanges, request }: {
  accessToken: string;
  onUnsavedChanges?: (dirty: boolean) => void;
  request?: EventRequestApi;
}) {
  const [items, setItems] = useState<RequestSummary[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const api: EventRequestApi = request || ((path, init = {}) => fetch(path, {
    ...init,
    headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json', ...init.headers },
  }));

  async function refresh() {
    setLoading(true); setError(null);
    try {
      const response = await api('/api/event-requests');
      if (!response.ok) throw new Error('Could not load event requests.');
      const body = await response.json() as { event_requests: RequestSummary[] };
      setItems(body.event_requests);
    } catch {
      setError('Could not load event requests. Please try again.');
    } finally { setLoading(false); }
  }

  useEffect(() => { void refresh(); /* Load once for this workspace view. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function deleteDraft(id: number) {
    setError(null);
    try {
      const response = await api(`/api/event-requests/drafts/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Could not delete the draft.');
      setItems(current => current.filter(item => item.id !== id));
      setConfirming(null);
    } catch { setError('Could not delete the draft. Please try again.'); }
  }

  if (editing !== null) return <EventRequestCreate
    accessToken={accessToken} draftId={editing} onUnsavedChanges={onUnsavedChanges}
    onReturn={() => { setEditing(null); onUnsavedChanges?.(false); void refresh(); }} request={request}
  />;

  const drafts = items.filter(item => item.status === 'draft');
  const submitted = items.filter(item => item.status !== 'draft');
  return <section className="request-workspace" aria-labelledby="requests-heading">
    <p className="eyebrow">Event Organiser</p>
    <h2 id="requests-heading">My event requests</h2>
    {error && <p role="alert" className="error">{error}</p>}
    {loading && <p>Loading requests…</p>}
    {!loading && <>
      <h3>Drafts</h3>
      {drafts.length === 0 && <p>No saved drafts.</p>}
      <ul className="request-list">{drafts.map(item => <li key={item.id}>
        <div><strong>{item.name}</strong> <span className="request-status">Draft</span>
          <p>Last saved: {item.last_saved_at ? new Date(item.last_saved_at).toLocaleString() : 'Unknown'}</p></div>
        <div className="request-list__actions">
          <button className="button button--secondary" type="button" onClick={() => setEditing(item.id)}>Reopen draft</button>
          {confirming === item.id ? <>
            <span>Delete this draft?</span>
            <button className="button button--secondary" type="button" onClick={() => setConfirming(null)}>Cancel</button>
            <button className="button button--primary" type="button" onClick={() => void deleteDraft(item.id)}>Confirm delete</button>
          </> : <button className="button button--secondary" type="button" onClick={() => setConfirming(item.id)}>Delete draft</button>}
        </div>
      </li>)}</ul>
      <h3>Submitted requests</h3>
      {submitted.length === 0 && <p>No submitted requests.</p>}
      <ul className="request-list">{submitted.map(item => <li key={item.id}>
        <div><strong>{item.name}</strong> <span className="request-status">{item.status}</span>
          <p>Proposed date: {item.proposed_date || 'Not set'}</p></div>
      </li>)}</ul>
    </>}
  </section>;
}
