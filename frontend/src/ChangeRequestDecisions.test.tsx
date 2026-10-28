import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ChangeRequestDecisions } from './ChangeRequestDecisions';
import type { ChangeRequest } from './ChangeRequests';
import type { ApiRequest } from './api';

afterEach(cleanup);
const pending: ChangeRequest = {
  id: 7, status: 'pending', submitted_at: '2026-10-24T10:00:00+08:00',
  items: [
    { id: 1, field: 'name', field_label: 'Event name', current_value: 'Gala', requested_value: 'New gala', reason: 'Rebrand' },
    { id: 2, field: 'description', field_label: 'Description', current_value: 'Old', requested_value: 'New', reason: 'Revised' },
  ],
};
function setup(request = pending, status = 'confirmed', replies = [
  { preview_token: 'snapshot', arrangements: [{ kind: 'venue', id: 1, name: 'Hall', reason: 'Attendance review' }], returns_to_planning: true },
  { event: { id: 10, status: 'planning' } },
]) {
  const api = vi.fn();
  replies.forEach(body => api.mockResolvedValueOnce({ ok: true, json: async () => body }));
  const saved = vi.fn(), reload = vi.fn();
  render(<ChangeRequestDecisions api={api as ApiRequest} eventId={10} eventStatus={status} request={request} onSaved={saved} onReload={reload} />);
  return { api, saved, reload };
}
const select = (value: string, label = 'Event name') => fireEvent.change(screen.getByLabelText(`Outcome for ${label}`), { target: { value } });

// QA-SPL-112-101 | AC1 | BB
it('[QA-SPL-112-101] requires a decline reason before calling the API', async () => {
  const { api } = setup();
  select('declined');
  fireEvent.click(screen.getByRole('button', { name: 'Review decisions' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Give a reason');
  expect(api).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Decline reason for Event name').getAttribute('maxlength')).toBe('1000');
});

// QA-SPL-112-102 | AC2 | BB
it('[QA-SPL-112-102] previews impacts and cancellation does not save', async () => {
  const { api, saved } = setup();
  select('accepted');
  fireEvent.click(screen.getByRole('button', { name: 'Review decisions' }));
  expect((await screen.findByRole('region', { name: 'Review decision impacts' })).textContent).toContain('Hall');
  expect(screen.getByText('This event will return to Planning.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel review' }));
  expect(api).toHaveBeenCalledTimes(1);
  expect(saved).not.toHaveBeenCalled();
  expect(screen.queryByRole('region', { name: 'Review decision impacts' })).toBeNull();
});

// QA-SPL-112-103 | AC3 | BB
it('[QA-SPL-112-103] saves only selected items with the reviewed token', async () => {
  const { api, saved } = setup();
  select('declined');
  fireEvent.change(screen.getByLabelText('Decline reason for Event name'), { target: { value: ' Keep name ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review decisions' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm decisions' }));
  await waitFor(() => expect(saved).toHaveBeenCalledWith({ id: 10, status: 'planning' }));
  expect(JSON.parse(api.mock.calls[1][1].body)).toEqual({ decisions: [{ item_id: 1, decision: 'declined', decline_reason: 'Keep name' }], preview_token: 'snapshot' });
  expect(screen.getByRole('status').textContent).toBe('Decisions saved.');
});

// QA-SPL-112-104 | AC4 | BB
it('[QA-SPL-112-104] shows durable actor time and reason without editable saved items', () => {
  setup({ ...pending, items: [{ ...pending.items[0], decision: 'declined', decline_reason: 'Keep name', decided_by: { id: 'coordinator', display_name: 'Casey Lim' }, decided_at: '2026-10-24T10:30:00+08:00' }, pending.items[1]] });
  expect(screen.getByText(/by Casey Lim/).textContent).toContain(new Date('2026-10-24T10:30:00+08:00').toLocaleString());
  expect(screen.getByText('Decline reason: Keep name')).toBeTruthy();
  expect(screen.queryByLabelText('Outcome for Event name')).toBeNull();
  expect(screen.getByLabelText('Outcome for Description')).toBeTruthy();
  expect(document.body.textContent).not.toContain('\uFFFD');
});

// QA-SPL-112-105 | AC5 | BB
it('[QA-SPL-112-105] Closed Cancelled and Completed offer no actions', () => {
  for (const [status, request] of [['confirmed', { ...pending, status: 'closed' }], ['cancelled', pending], ['completed', pending]] as const) {
    setup(request, status);
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Review decisions' })).toBeNull();
    cleanup();
  }
});

// QA-SPL-112-106 | AC2 | BB
it('[QA-SPL-112-106] Under Review equipment allows decline but not acceptance', () => {
  setup({ ...pending, items: [{ ...pending.items[0], field: 'equipment:add:1', field_label: 'Equipment', current_value: null, requested_value: { operation: 'add', equipment_type: 'Screen', quantity: 2, notes: '' } }] }, 'under_review');
  expect((screen.getByRole('option', { name: 'Accept' }) as HTMLOptionElement).disabled).toBe(true);
  expect((screen.getByRole('option', { name: 'Decline' }) as HTMLOptionElement).disabled).toBe(false);
});

// QA-SPL-112-107 | AC5 | BB
it('[QA-SPL-136] permits equipment decisions during Preparing and warns before saving', async () => {
  setup({ ...pending, items: [{ ...pending.items[0], field: 'equipment:add:1', field_label: 'Equipment', current_value: null, requested_value: { operation: 'add', equipment_type: 'Screen', quantity: 2, notes: '' } }] }, 'preparing');
  expect((screen.getByRole('option', { name: 'Accept' }) as HTMLOptionElement).disabled).toBe(false);
  select('accepted', 'Equipment');
  fireEvent.click(screen.getByRole('button', { name: 'Review decisions' }));
  expect(await screen.findByText('This event will return to Planning.')).toBeTruthy();
});

it('[QA-SPL-112-107] stale save refuses success and offers reload', async () => {
  const { api, saved, reload } = setup();
  api.mockReset().mockResolvedValueOnce({ ok: false, json: async () => ({ error: 'The original value changed.' }) });
  select('accepted');
  fireEvent.click(screen.getByRole('button', { name: 'Review decisions' }));
  expect((await screen.findByRole('alert')).textContent).toContain('The original value changed.');
  expect(saved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Reload change requests' }));
  expect(reload).toHaveBeenCalledOnce();
});

// QA-SPL-112-108 | AC3 | BB
it('[QA-SPL-112-108] transport failure keeps choices and reports no success', async () => {
  const { api, saved } = setup();
  api.mockReset().mockRejectedValueOnce(new Error('offline'));
  select('accepted');
  fireEvent.click(screen.getByRole('button', { name: 'Review decisions' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Could not save decisions.');
  expect(saved).not.toHaveBeenCalled();
  expect((screen.getByLabelText('Outcome for Event name') as HTMLSelectElement).value).toBe('accepted');
});
