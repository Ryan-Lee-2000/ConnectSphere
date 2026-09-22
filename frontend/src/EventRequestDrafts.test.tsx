import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EventRequestDrafts } from './EventRequestDrafts';

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('EventRequestDrafts', () => {
  it('separates drafts and submitted requests and confirms deletion', async () => {
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') return new Response(null, { status: 204 });
      if (path === '/api/event-requests') return response({ event_requests: [
        { id: 1, name: 'Early idea', status: 'draft', last_saved_at: '2026-09-18T10:00:00+00:00', proposed_date: null },
        { id: 2, name: 'Ready event', status: 'submitted', last_saved_at: null, proposed_date: '2026-12-10' },
      ] });
      throw new Error('Unexpected request');
    });
    render(<EventRequestDrafts accessToken="token" request={request} />);
    expect(await screen.findByText('Early idea')).toBeTruthy();
    expect(screen.getByText('Ready event')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Delete draft' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Delete draft' }));
    expect(request).not.toHaveBeenCalledWith('/api/event-requests/drafts/1', expect.anything());
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/drafts/1', expect.objectContaining({ method: 'DELETE' })));
    expect(screen.queryByText('Early idea')).toBeNull();
    expect(screen.getByText('Ready event')).toBeTruthy();
  });

  // CS-E05-S2 AC6 and CS-E05-S3 AC6
  it('names the Event Coordinator once one is responsible, and says so when none is', async () => {
    const request = vi.fn(async () => response({ event_requests: [
      { id: 1, name: 'Assigned', status: 'under_review', status_label: 'Under review', status_explanation: 'A coordinator is reviewing it.', status_changed_at: null, last_saved_at: null, proposed_date: null, coordinator: { id: 'alice', name: 'Alice Tan' } },
      { id: 2, name: 'Waiting', status: 'submitted', status_label: 'Submitted', status_explanation: 'Waiting to be picked up.', status_changed_at: null, last_saved_at: null, proposed_date: null, coordinator: null },
    ] }));
    render(<EventRequestDrafts accessToken="token" request={request} />);
    expect(await screen.findByText('Alice Tan')).toBeTruthy();
    expect(screen.getByText('Not assigned yet')).toBeTruthy();
  });
});
