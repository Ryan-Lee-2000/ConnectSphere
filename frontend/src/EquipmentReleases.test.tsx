import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { EquipmentAvailability } from './EquipmentAvailability';

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const heldAssessment = {
  requirement_id: 1, event: { id: 3, name: 'Community Leadership Forum', date: '2026-10-15' },
  equipment_type: { id: 1, name: 'Wireless Microphone', location: 'Technical Store' }, requirement_status: 'partially_reserved',
  required_quantity: 6, required_start_date: '2026-10-15', required_end_date: '2026-10-15',
  commitment_start: '2026-10-14', commitment_end: '2026-10-15', reserved_quantity: 3,
  available_to_reserve: 7, shortfall: 0, overcommitted_units: 0,
};

// TC-SPL-98-06 — staff cannot submit a browser-only release without a bounded quantity and reason.
it('[TC-SPL-98-06] validates the reason and held quantity before a release request', async () => {
  const request = vi.fn(async () => response({ assessments: [heldAssessment], input_notice: 'Reservations included.' }));
  render(<EquipmentAvailability accessToken="token" request={request} />);

  fireEvent.change(await screen.findByLabelText('Units to release'), { target: { value: '4' } });
  fireEvent.click(screen.getByRole('button', { name: 'Release units' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Enter a whole number from 1 to 3.');
  expect(request).toHaveBeenCalledTimes(1);

  fireEvent.change(screen.getByLabelText('Units to release'), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Release units' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Enter a reason for this release.');
  expect(request).toHaveBeenCalledTimes(1);
});

// TC-SPL-98-07 — a reasoned release calls the server once, then refreshes authoritative quantities.
it('[TC-SPL-98-07] submits a partial release and reloads the remaining reservation state', async () => {
  let availabilityCalls = 0;
  const request = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/api/equipment-availability') {
      availabilityCalls += 1;
      return response({
        assessments: [availabilityCalls === 1 ? heldAssessment : {
          ...heldAssessment, requirement_status: 'partially_reserved', reserved_quantity: 1, available_to_reserve: 9,
        }],
        input_notice: 'Reservations included.',
      });
    }
    return response({ releases: [{ quantity: 2 }], assessment: { reserved_quantity: 1 } }, 201);
  });
  render(<EquipmentAvailability accessToken="token" request={request} />);

  fireEvent.change(await screen.findByLabelText('Units to release'), { target: { value: '2' } });
  fireEvent.change(screen.getByLabelText('Release reason'), { target: { value: 'Programme format changed' } });
  fireEvent.click(screen.getByRole('button', { name: 'Release units' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith(
    '/api/equipment-requirements/1/releases',
    { method: 'POST', body: JSON.stringify({ quantity: 2, reason: 'Programme format changed' }) },
  ));
  expect(await screen.findByText('1 of 6 units held')).toBeTruthy();
  expect(screen.getByText('9')).toBeTruthy();
});

// TC-SPL-98-09 — the event-wide control sends only an audit reason and lets the server release each line.
it('[TC-SPL-98-09] confirms and submits release-all through the event equipment workflow', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  const request = vi.fn(async (path: string) => {
    if (path === '/api/equipment-availability') {
      return response({ assessments: [heldAssessment], input_notice: 'Reservations included.' });
    }
    return response({ event_id: 3, releases: [{ quantity: 3 }], assessments: [heldAssessment] }, 201);
  });
  render(<EquipmentAvailability accessToken="token" request={request} />);

  fireEvent.change(await screen.findByLabelText('Release reason'), { target: { value: 'Event plan changed' } });
  fireEvent.click(screen.getByRole('button', { name: 'Release all for event' }));

  await waitFor(() => expect(request).toHaveBeenCalledWith(
    '/api/event-requests/3/equipment-releases',
    { method: 'POST', body: JSON.stringify({ reason: 'Event plan changed' }) },
  ));
  expect(confirm).toHaveBeenCalledOnce();
  confirm.mockRestore();
});
