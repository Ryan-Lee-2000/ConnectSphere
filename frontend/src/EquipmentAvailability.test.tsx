import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { EquipmentAvailability } from './EquipmentAvailability';

function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }); }

const assessment = {
  requirement_id: 1, event: { id: 3, name: 'Community Leadership Forum', date: '2026-10-15' },
  equipment_type: { id: 1, name: 'Wireless Microphone', location: 'Technical Store' }, requirement_status: 'requested',
  required_quantity: 6, required_start_date: '2026-10-15', required_end_date: '2026-10-15',
  commitment_start: '2026-10-14', commitment_end: '2026-10-15', busiest_day: '2026-10-14', total_stock: 10,
  unavailable_units: 0, active_reservations: 0, reserved_quantity: 0, available_to_reserve: 10, shortfall: 0, overcommitted_units: 0,
};

// TC-SPL-95-08 — the user sees decision values, not internal calculation diagnostics.
it('[TC-SPL-95-08] presents the commitment period and decision quantities without internal calculation fields', async () => {
  render(<EquipmentAvailability accessToken="token" request={async () => response({ assessments: [assessment], input_notice: 'Stock baseline only.' })} />);
  expect(await screen.findByRole('heading', { name: 'Wireless Microphone' })).toBeTruthy();
  expect(screen.getByText('Available to reserve')).toBeTruthy();
  expect(screen.getByText('Stock baseline only.')).toBeTruthy();
  expect(screen.queryByText('Busiest day')).toBeNull();
  expect(screen.queryByText('Stock basis')).toBeNull();
});

// TC-SPL-97-06 — feasible requested work presents a bounded, deliberate reserve action.
it('[TC-SPL-97-06] offers Technical Support an inline reserve control bounded by current availability', async () => {
  render(<EquipmentAvailability accessToken="token" request={async () => response({ assessments: [assessment], input_notice: 'Reservations included.' })} />);

  const input = await screen.findByLabelText('Units to reserve');
  expect(input.getAttribute('max')).toBe('6');
  fireEvent.change(input, { target: { value: '7' } });
  fireEvent.click(screen.getByRole('button', { name: 'Reserve units' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Enter a whole number from 1 to 6.');
});

// TC-SPL-95-09 — a stock deficit is understandable and never rendered as a negative availability value.
it('[TC-SPL-95-09] makes an actual shortfall visible instead of displaying negative availability', async () => {
  render(<EquipmentAvailability accessToken="token" request={async () => response({ assessments: [{ ...assessment, available_to_reserve: 0, shortfall: 6, overcommitted_units: 2 }], input_notice: 'Stock baseline only.' })} />);
  expect(await screen.findByText('Stock is short by 6')).toBeTruthy();
  expect(screen.getAllByText('Shortfall')).toHaveLength(2);
  expect(screen.queryByText('-2')).toBeNull();
});
