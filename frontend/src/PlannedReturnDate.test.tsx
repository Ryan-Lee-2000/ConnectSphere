import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { PlannedReturnDate } from './PlannedReturnDate';

// SPL-100 TC-SPL-100-08. The repo has no @testing-library/user-event, so interaction uses
// fireEvent, as App.test.tsx does.

afterEach(cleanup);

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const reservation = {
  id: 7,
  quantity: 2,
  planned_return_date: '2026-10-14',
  return_date_changed_by: null,
  return_date_changed_at: null,
};

// TC-SPL-100-08
it('[TC-SPL-100-08] labels the field, shows the default, and saves a later date', async () => {
  const calls: { path: string; body: unknown }[] = [];
  const request = async (path: string, init?: RequestInit) => {
    calls.push({ path, body: JSON.parse(String(init?.body)) });
    return response({
      reservation: {
        ...reservation,
        planned_return_date: '2026-10-16',
        return_date_changed_by: { id: 't-1', display_name: 'Taylor Goh' },
        return_date_changed_at: '2026-10-11T10:00:00+08:00',
      },
    });
  };

  render(<PlannedReturnDate api={request} reservation={reservation} />);

  // AC1: the field is named "Planned return date" and shows the default it came with.
  expect(screen.getByText('Planned return date')).toBeTruthy();
  expect(screen.getByTestId('planned-return-date').textContent).toBe('2026-10-14');
  // The story's assumption is stated on screen, so nobody reads it as a physical return.
  expect(screen.getByText(/does not record that the equipment has come back/)).toBeTruthy();

  fireEvent.change(screen.getByLabelText('Change planned return date'), {
    target: { value: '2026-10-16' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save planned return date' }));

  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].path).toBe('/api/equipment-reservations/7/planned-return-date');
  expect(calls[0].body).toEqual({ planned_return_date: '2026-10-16' });

  // The saved date and the audit line both come from the server's reply.
  await waitFor(() => expect(screen.getByTestId('planned-return-date').textContent).toBe('2026-10-16'));
  expect(screen.getByText(/Last changed by Taylor Goh/)).toBeTruthy();
  expect(screen.getByRole('status').textContent).toContain('2026-10-16');
});

// TC-SPL-100-08
it('[TC-SPL-100-08] shows the refusal beside the field and leaves the date alone', async () => {
  const request = async () => response(
    { error: 'The planned return date cannot be before the requirement\'s required end date (2026-10-14).', field: 'planned_return_date' },
    400,
  );

  render(<PlannedReturnDate api={request} reservation={reservation} />);

  fireEvent.change(screen.getByLabelText('Change planned return date'), {
    target: { value: '2026-10-13' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save planned return date' }));

  const refusal = await screen.findByRole('alert');
  expect(refusal.textContent).toContain('cannot be before');
  // The shown date did not move, and what was typed is kept so it can be corrected.
  expect(screen.getByTestId('planned-return-date').textContent).toBe('2026-10-14');
  expect((screen.getByLabelText('Change planned return date') as HTMLInputElement).value).toBe('2026-10-13');
  expect(screen.queryByRole('status')).toBeNull();
});

// TC-SPL-100-08
it('[TC-SPL-100-08] shows the overcommit conflict the server reports', async () => {
  const request = async () => response(
    { error: 'Extending to 2026-10-16 would overcommit stock on 2026-10-15.' },
    409,
  );

  render(<PlannedReturnDate api={request} reservation={reservation} />);
  fireEvent.change(screen.getByLabelText('Change planned return date'), {
    target: { value: '2026-10-16' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save planned return date' }));

  const refusal = await screen.findByRole('alert');
  // The naming of the blocking day comes from the server; the page does no arithmetic of its own.
  expect(refusal.textContent).toContain('2026-10-15');
  expect(screen.getByTestId('planned-return-date').textContent).toBe('2026-10-14');
});

// TC-SPL-100-08
it('[TC-SPL-100-08] offers no edit control where editing is not allowed', () => {
  const request = async () => response({});
  render(<PlannedReturnDate api={request} reservation={reservation} canEdit={false} />);

  // AC4 is enforced by the server; this keeps the control out of a read-only context entirely.
  expect(screen.queryByLabelText('Change planned return date')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Save planned return date' })).toBeNull();
  // The date itself is still shown, so the card is not simply blank.
  expect(screen.getByTestId('planned-return-date').textContent).toBe('2026-10-14');
});
