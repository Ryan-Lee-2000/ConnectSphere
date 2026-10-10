import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { EquipmentUnavailability } from './EquipmentUnavailability';

// SPL-96 TC-SPL-96-08, the half that does not need SPL-97: the form records a quantity and a
// reason and shows the usable stock afterwards, and a refused value is shown beside its field.
// The flagged-line half (Review Required) arrives with SPL-97.

afterEach(cleanup);

// The repo has no @testing-library/user-event, so interaction uses fireEvent, as App.test.tsx does.
function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const stock = { id: 1, name: 'Wireless Microphone', total_stock: 6, unavailable_units: 0, usable_stock: 6 };

// TC-SPL-96-08
it('[TC-SPL-96-08] records a quantity and reason, then shows the usable stock the server returns', async () => {
  const calls: { path: string; body: unknown }[] = [];
  const request = async (path: string, init?: RequestInit) => {
    if (!init?.method) return response({ equipment_type: stock, history: [] });
    calls.push({ path, body: JSON.parse(String(init.body)) });
    return response({
      equipment_type: { ...stock, unavailable_units: 2, usable_stock: 4 },
      record: { id: 7, action: 'marked_unavailable', quantity: 2, reason: 'Two capsules cracked.', recorded_at: '2026-10-10T09:30:00+08:00' },
    }, 201);
  };

  render(<EquipmentUnavailability accessToken="token" equipmentTypeId={1} request={request} />);

  // It opens on the server's current figures, so the starting point is never guessed.
  expect(await screen.findByRole('heading', { name: 'Wireless Microphone' })).toBeTruthy();
  expect(screen.getByTestId('usable-stock').textContent).toBe('6');

  type('Number of units', '2');
  type('Reason', 'Two capsules cracked.');
  fireEvent.click(screen.getByRole('button', { name: 'Mark unavailable' }));

  // The quantity is sent as a number and the reason as typed, to the marking route.
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].path).toBe('/api/equipment-types/1/unavailable-units');
  expect(calls[0].body).toEqual({ quantity: 2, reason: 'Two capsules cracked.' });

  // Usable stock afterwards comes from the server's reply, not from arithmetic done here.
  await waitFor(() => expect(screen.getByTestId('usable-stock').textContent).toBe('4'));
  expect(screen.getByRole('status').textContent).toContain('4 still usable');
  // The history gains the entry, with its reason.
  expect(screen.getByText('Two capsules cracked.')).toBeTruthy();
  // And the form is cleared, so the same units cannot be recorded twice by a stray second click.
  expect((screen.getByLabelText('Number of units') as HTMLInputElement).value).toBe('');
});

// TC-SPL-96-08
it('[TC-SPL-96-08] shows the server refusal beside the fields and leaves the figures untouched', async () => {
  const request = async (path: string, init?: RequestInit) => {
    if (!init?.method) return response({ equipment_type: stock, history: [] });
    return response({ error: 'Only 6 of 6 unit(s) are still usable, so 7 cannot be marked unavailable.' }, 400);
  };

  render(<EquipmentUnavailability accessToken="token" equipmentTypeId={1} request={request} />);
  expect(await screen.findByRole('heading', { name: 'Wireless Microphone' })).toBeTruthy();

  type('Number of units', '7');
  type('Reason', 'Water damage in the store.');
  fireEvent.click(screen.getByRole('button', { name: 'Mark unavailable' }));

  const refusal = await screen.findByRole('alert');
  expect(refusal.textContent).toContain('still usable');
  // Nothing moved, and what was typed is kept so it can be corrected rather than retyped.
  expect(screen.getByTestId('usable-stock').textContent).toBe('6');
  expect((screen.getByLabelText('Number of units') as HTMLInputElement).value).toBe('7');

  // Positive control: the same panel does report success, so this test cannot pass against a
  // component that simply never updates anything.
  expect(screen.queryByRole('status')).toBeNull();
});

// TC-SPL-96-08
it('[TC-SPL-96-08] restores units through the restore route and reports the new usable stock', async () => {
  const calls: string[] = [];
  const request = async (path: string, init?: RequestInit) => {
    if (!init?.method) {
      return response({
        equipment_type: { ...stock, unavailable_units: 3, usable_stock: 3 },
        history: [{ id: 1, action: 'marked_unavailable', quantity: 3, reason: 'Three cracked.', recorded_at: '2026-10-10T09:30:00+08:00' }],
      });
    }
    calls.push(path);
    return response({
      equipment_type: { ...stock, unavailable_units: 1, usable_stock: 5 },
      record: { id: 2, action: 'restored', quantity: 2, reason: 'Two replaced.', recorded_at: '2026-10-10T09:31:00+08:00' },
    }, 201);
  };

  render(<EquipmentUnavailability accessToken="token" equipmentTypeId={1} request={request} />);
  expect(await screen.findByTestId('usable-stock')).toBeTruthy();
  expect(screen.getByTestId('usable-stock').textContent).toBe('3');

  type('Number of units', '2');
  type('Reason', 'Two replaced.');
  fireEvent.click(screen.getByRole('button', { name: 'Restore units' }));

  await waitFor(() => expect(calls).toEqual(['/api/equipment-types/1/restored-units']));
  await waitFor(() => expect(screen.getByTestId('usable-stock').textContent).toBe('5'));
  expect(screen.getByRole('status').textContent).toContain('now usable');
});

// TC-SPL-96-08
it('[TC-SPL-96-08] does not offer a Review Required flag, which SPL-97 owns', async () => {
  const request = async () => response({ equipment_type: stock, history: [] });
  render(<EquipmentUnavailability accessToken="token" equipmentTypeId={1} request={request} />);

  expect(await screen.findByRole('heading', { name: 'Wireless Microphone' })).toBeTruthy();
  // Guards the scope line in docs/tasks/SPL-96.md: AC3-AC5 are not half-built here.
  expect(screen.queryByText(/review required/i)).toBeNull();
});
