import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { EquipmentReviewQueue } from './EquipmentReviewQueue';

// SPL-92 TC-SPL-92-09. The repo has no @testing-library/user-event, so interaction uses
// fireEvent, as App.test.tsx does.

afterEach(cleanup);

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const mappedLine = {
  id: 11,
  event: { id: 3, name: 'Community Leadership Forum', date: '2026-11-20', status: 'confirmed', status_label: 'Confirmed' },
  coordinator: { id: 'c-1', display_name: 'Casey Coordinator' },
  organiser_equipment_text: 'Wireless microphones',
  equipment_type: { id: 1, name: 'Wireless Microphone', location: 'Technical Store A' },
  needs_mapping: false,
  quantity: 4,
  required_start_date: '2026-11-20',
  required_end_date: '2026-11-21',
  status: 'requested',
  review_reason: null,
  review_flagged_at: null,
};

const legacyLine = {
  ...mappedLine,
  id: 12,
  equipment_type: null,
  needs_mapping: true,
  organiser_equipment_text: 'Wireless microphone',
  status: 'review_required',
};

// TC-SPL-92-09
it('[TC-SPL-92-09] lists each line with its event, coordinator, type, quantity, dates and status', async () => {
  const request = async () => response({ requirements: [mappedLine, legacyLine] });
  render(<EquipmentReviewQueue accessToken="token" request={request} />);

  expect(await screen.findByRole('heading', { name: 'Wireless Microphone' })).toBeTruthy();
  // Both fixture lines sit on the same event, so the event and coordinator appear once per line.
  expect(screen.getAllByText(/Community Leadership Forum/)).toHaveLength(2);
  expect(screen.getAllByText('Casey Coordinator')).toHaveLength(2);
  expect(screen.getAllByText('Quantity')).toHaveLength(2);
  expect(screen.getByText('Requested')).toBeTruthy();
  expect(screen.getByText('Review Required')).toBeTruthy();

  // AC2: the unmapped line keeps the organiser's wording and is marked as needing mapping.
  expect(screen.getByRole('heading', { name: 'Wireless microphone' })).toBeTruthy();
  expect(screen.getByText('Needs mapping to the catalogue')).toBeTruthy();

  // AC4: this page offers no way to reserve anything.
  expect(screen.queryByRole('button', { name: /reserve/i })).toBeNull();
});

// TC-SPL-92-09
it('[TC-SPL-92-09] opening a line shows its notes and a note form, and saves a note', async () => {
  const calls: { path: string; body?: unknown }[] = [];
  const request = async (path: string, init?: RequestInit) => {
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (path === '/api/equipment-review-queue') return response({ requirements: [mappedLine] });
    if (init?.method === 'POST') {
      return response({
        note: { id: 5, note: 'Can this move to the Tuesday?', author: { id: 't-1', display_name: 'Taylor Goh' }, created_at: '2026-10-11T09:00:00+08:00' },
      }, 201);
    }
    return response({
      requirement: {
        ...mappedLine,
        notes: 'Needs a spare battery pack.',
        review_notes: [{ id: 4, note: 'Earlier question.', author: { id: 't-1', display_name: 'Taylor Goh' }, created_at: '2026-10-10T09:00:00+08:00' }],
      },
    });
  };

  render(<EquipmentReviewQueue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Open Wireless Microphone' }));

  // AC2: opening the line is what fetches its technical notes and review notes.
  expect(await screen.findByText('Needs a spare battery pack.')).toBeTruthy();
  expect(screen.getByText('Earlier question.')).toBeTruthy();
  expect(calls.map(call => call.path)).toContain('/api/equipment-review-queue/11');

  fireEvent.change(screen.getByLabelText('Add a note or question'), {
    target: { value: 'Can this move to the Tuesday?' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));

  await waitFor(() => expect(calls.at(-1)).toEqual({
    path: '/api/equipment-review-queue/11/notes',
    body: { note: 'Can this move to the Tuesday?' },
  }));
  // The saved note joins the list, and the form is cleared so it cannot be sent twice.
  await waitFor(() => expect(screen.getByText('Can this move to the Tuesday?')).toBeTruthy());
  expect((screen.getByLabelText('Add a note or question') as HTMLTextAreaElement).value).toBe('');
  expect(screen.getByRole('status').textContent).toContain('coordinator can read it');
});

// TC-SPL-92-09
it('[TC-SPL-92-09] shows a refused note beside the field and keeps what was typed', async () => {
  const request = async (path: string, init?: RequestInit) => {
    if (path === '/api/equipment-review-queue') return response({ requirements: [mappedLine] });
    if (init?.method === 'POST') return response({ error: 'A note is required.' }, 400);
    return response({ requirement: { ...mappedLine, notes: null, review_notes: [] } });
  };

  render(<EquipmentReviewQueue accessToken="token" request={request} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Open Wireless Microphone' }));
  expect(await screen.findByText('No review notes yet.')).toBeTruthy();

  fireEvent.change(screen.getByLabelText('Add a note or question'), { target: { value: '   ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));

  const refusal = await screen.findByRole('alert');
  expect(refusal.textContent).toContain('A note is required.');
  // What was typed is kept so it can be corrected rather than retyped, and nothing was confirmed.
  expect((screen.getByLabelText('Add a note or question') as HTMLTextAreaElement).value).toBe('   ');
  expect(screen.queryByRole('status')).toBeNull();
});

// TC-SPL-92-09
it('[TC-SPL-92-09] says plainly when nothing is awaiting review', async () => {
  const request = async () => response({ requirements: [] });
  render(<EquipmentReviewQueue accessToken="token" request={request} />);

  expect(await screen.findByRole('heading', { name: 'Nothing is awaiting review' })).toBeTruthy();
  // The page still explains itself rather than showing a bare empty list.
  expect(screen.getByRole('heading', { name: 'Equipment awaiting review' })).toBeTruthy();
});

// TC-SPL-96-03 — SPL-96 AC4 is displayed here, in SPL-92's queue.
it('[TC-SPL-96-03] shows the Review Required reason on a flagged line, and nothing on an unflagged one', async () => {
  const flagged = {
    ...mappedLine,
    id: 21,
    status: 'review_required',
    review_reason: 'Two units water damaged.',
    review_flagged_at: '2026-10-10T09:30:00+08:00',
  };
  const request = async () => response({ requirements: [flagged, mappedLine] });
  render(<EquipmentReviewQueue accessToken="token" request={request} />);

  expect(await screen.findByText('Review required: Two units water damaged.')).toBeTruthy();
  expect(screen.getByText('Review Required')).toBeTruthy();
  // The unflagged line in the same list carries no reason, so the message is not boilerplate.
  expect(screen.getAllByText(/Review required:/)).toHaveLength(1);
});
