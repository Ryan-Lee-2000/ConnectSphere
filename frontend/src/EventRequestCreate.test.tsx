import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EventRequestCreate } from './EventRequestCreate';

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('EventRequestCreate', () => {
  it('saves a name-only draft without requiring submission fields', async () => {
    const request = vi.fn(async (_path: string, _init?: RequestInit) => response({ event_request: {
      id: 10, name: 'Idea', status: 'draft', mapped_slots: [], last_saved_at: '2026-09-18T10:00:00+00:00',
    } }, 201));
    render(<EventRequestCreate accessToken="token" request={request} />);
    fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Idea' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/drafts', expect.objectContaining({ method: 'POST' })));
    expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toMatchObject({ name: 'Idea', purpose: '', proposed_date: null });
    expect(await screen.findByText(/Draft saved. Last saved:/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save draft again' })).toBeTruthy();
  });

  it('loads a draft, resaves changes, then submits the same request', async () => {
    const draft = { id: 12, name: 'Idea', purpose: null, description: null,
      proposed_date: null, start_time: null, end_time: null, expected_attendance: null,
      status: 'draft', mapped_slots: [], last_saved_at: '2026-09-18T10:00:00+00:00' };
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (!init) return response({ event_request: draft });
      if (path.endsWith('/submit')) return response({ event_request: { ...draft, status: 'submitted', mapped_slots: ['AM'] } });
      return response({ event_request: { ...draft, name: 'Updated idea', last_saved_at: '2026-09-18T11:00:00+00:00' } });
    });
    const onReturn = vi.fn();
    render(<EventRequestCreate accessToken="token" draftId={12} request={request} onReturn={onReturn} />);
    fireEvent.change(await screen.findByLabelText('Event name'), { target: { value: 'Updated idea' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save draft again' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/drafts/12', expect.objectContaining({ method: 'PATCH' })));
    fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Community' } });
    fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2026-12-10' } });
    fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '10:00' } });
    fireEvent.change(screen.getByLabelText('End time'), { target: { value: '11:00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit request' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests/drafts/12/submit', expect.objectContaining({ method: 'POST' })));
    expect(await screen.findByText(/has been submitted as request #12/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Back to requests' }));
    expect(onReturn).toHaveBeenCalledOnce();
  });
  it('submits the core request fields through Flask and displays the returned slots', async () => {
    const request = vi.fn(async (_path: string, _init?: RequestInit) => response({
      event_request: { id: 7, name: 'Community Forum', status: 'submitted', mapped_slots: ['AM', 'PM'] },
    }, 201));
    const onUnsavedChanges = vi.fn();
    render(<EventRequestCreate accessToken="token" request={request} onUnsavedChanges={onUnsavedChanges} />);

    fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Community Forum' } });
    fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Bring neighbours together' } });
    fireEvent.change(screen.getByLabelText(/Description/), { target: { value: 'A half-day gathering' } });
    fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2026-12-10' } });
    fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '80' } });
    fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '11:00' } });
    fireEvent.change(screen.getByLabelText('End time'), { target: { value: '14:00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit request' }));

    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/event-requests', expect.objectContaining({ method: 'POST' })));
    const init = request.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      name: 'Community Forum',
      purpose: 'Bring neighbours together',
      description: 'A half-day gathering',
      proposed_date: '2026-12-10',
      start_time: '11:00',
      end_time: '14:00',
      expected_attendance: 80,
    });
    expect(await screen.findByText(/has been submitted as request #7/)).toBeTruthy();
    expect(screen.getByText(/Mapped venue slots: AM, PM/)).toBeTruthy();
    expect(onUnsavedChanges).toHaveBeenLastCalledWith(false);
  });

  it('shows server validation errors without claiming the request was saved', async () => {
    const request = vi.fn(async (_path: string, _init?: RequestInit) => response({ error: 'Proposed date cannot be in the past.' }, 400));
    render(<EventRequestCreate accessToken="token" request={request} />);

    fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Community Forum' } });
    fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Bring neighbours together' } });
    fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '80' } });
    fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '11:00' } });
    fireEvent.change(screen.getByLabelText('End time'), { target: { value: '14:00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit request' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Proposed date cannot be in the past.');
    expect(screen.queryByText('Request submitted')).toBeNull();
  });

  it('sends the verified session token to Flask for a submission', async () => {
    const fetchRequest = vi.fn(async () => response({
      event_request: { id: 8, name: 'Test Event', status: 'submitted', mapped_slots: [] },
    }, 201));
    vi.stubGlobal('fetch', fetchRequest);
    render(<EventRequestCreate accessToken="verified-token" />);

    fireEvent.change(screen.getByLabelText('Event name'), { target: { value: 'Test Event' } });
    fireEvent.change(screen.getByLabelText('Purpose'), { target: { value: 'Community' } });
    fireEvent.change(screen.getByLabelText('Proposed date'), { target: { value: '2026-12-10' } });
    fireEvent.change(screen.getByLabelText('Expected attendance'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('Start time'), { target: { value: '10:00' } });
    fireEvent.change(screen.getByLabelText('End time'), { target: { value: '11:00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit request' }));

    await waitFor(() => expect(fetchRequest).toHaveBeenCalledWith('/api/event-requests', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer verified-token' }),
    })));
  });
});
