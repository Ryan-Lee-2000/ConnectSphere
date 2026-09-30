import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EventRequestDrafts } from './EventRequestDrafts';

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('EventRequestDrafts', () => {
  // SPL-56 AC-2 Test-002
  // SPL-57 AC-1 Test-001
  // SPL-58 AC-1 Test-001
  // SPL-58 AC-3 Test-003
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

  // SPL-57 AC-1 Test-001
  it('reopens a draft into the event request form and returns to the list afterwards', async () => {
    const draftDetail = {
      id: 1, name: 'Early idea', purpose: null, description: null, proposed_date: null,
      start_time: null, end_time: null, expected_attendance: null, preferred_room_layout: null,
      required_facilities: [], facilities_notes: null, accessibility_needs: [],
      location_preference: null, venue_notes: null, venue_id: null,
      registration_required: false, registration_notes: null,
      last_saved_at: '2026-09-18T10:00:00+00:00', equipment_requirements: [],
    };
    const request = vi.fn(async (path: string) => {
      if (path === '/api/event-requests') return response({ event_requests: [
        { id: 1, name: 'Early idea', status: 'draft', last_saved_at: '2026-09-18T10:00:00+00:00' },
      ] });
      if (path === '/api/event-requests/1') return response({ event_request: draftDetail });
      if (path === '/api/venues') return response({ venues: [] });
      return response({}, 404);
    });
    render(<EventRequestDrafts accessToken="token" request={request} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Reopen draft' }));

    expect(await screen.findByDisplayValue('Early idea')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Back to my requests' }));

    expect(await screen.findByRole('heading', { name: 'The status of my events' })).toBeTruthy();
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

  // CS-E06-S4 AC4
  // SPL-67 AC-4 Test-13
  it('[TC-SPL-67-13] shows the organiser who approved the request', async () => {
    const request = vi.fn(async () => response({ event_requests: [
      { id: 1, name: 'Forum', status: 'planning', status_label: 'In planning', status_explanation: 'Approved.', status_changed_at: null, last_saved_at: null, proposed_date: null, coordinator: { id: 'alice', name: 'Alice Tan' }, approved_by: { id: 'alice', name: 'Alice Tan' }, approved_at: '2026-09-27T10:00:00+08:00' },
    ] }));
    render(<EventRequestDrafts accessToken="token" request={request} />);
    expect(await screen.findByText(/Approved by Alice Tan on/)).toBeTruthy();
  });
  // CS-E06-S5 AC4
  it('[TC-SPL-68-15] shows the organiser who rejected the request and why', async () => {
    const request = vi.fn(async () => response({ event_requests: [
      { id: 1, name: 'Forum', status: 'rejected', status_label: 'Not approved', status_explanation: 'Not accepted.', status_changed_at: null, last_saved_at: null, proposed_date: null, coordinator: { id: 'alice', name: 'Alice Tan' }, rejected_by: { id: 'alice', name: 'Alice Tan' }, rejected_at: '2026-09-27T10:00:00+08:00', rejection_reason: 'Clashes with exams.' },
    ] }));
    render(<EventRequestDrafts accessToken="token" request={request} />);
    expect(await screen.findByText(/Rejected by Alice Tan on/)).toBeTruthy();
    expect(screen.getByText('Reason: Clashes with exams.')).toBeTruthy();
  });

  // TC-SPL-66-01
  // SPL-66 AC-1,2,3,4
  it('[TC-SPL-66-01] lets the responsible organiser answer the outstanding clarification', async () => {
    let responded = false;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/event-requests/8') return response({ event_request: {
        id: 8,
        name: 'Community Forum',
        clarifications: [{
          id: 12,
          message: 'Please confirm the attendance.',
          author: { id: 'alice', name: 'Alice Tan' },
          created_at: '2026-09-28T10:00:00+08:00',
          response: null,
          respondent: null,
          responded_at: null,
        }],
      } });
      if (path === '/api/event-requests/8/clarifications/12/respond' && init?.method === 'POST') {
        responded = true;
        expect(JSON.parse(String(init.body))).toEqual({ response: 'Attendance remains 120 people.' });
        return response({ event: { id: 8, status: 'under_review' } });
      }
      if (path === '/api/event-requests') return response({ event_requests: [{
        id: 8,
        name: 'Community Forum',
        status: responded ? 'under_review' : 'returned_for_clarification',
        status_label: responded ? 'Under review' : 'Returned for clarification',
        status_explanation: 'Response needed.',
        status_changed_at: '2026-09-28T10:00:00+08:00',
        last_saved_at: null,
        coordinator: { id: 'alice', name: 'Alice Tan' },
      }] });
      throw new Error(`Unexpected request: ${path}`);
    });
    render(<EventRequestDrafts accessToken="token" request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Respond to clarification' }));
    expect(await screen.findByText('Please confirm the attendance.')).toBeTruthy();
    const field = screen.getByRole('textbox', { name: 'Your response' });
    fireEvent.change(field, { target: { value: 'Attendance remains 120 people.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send response' }));

    await waitFor(() => expect(responded).toBe(true));
    expect(await screen.findByText('Under review')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Respond to clarification' })).toBeNull();
  });

});
