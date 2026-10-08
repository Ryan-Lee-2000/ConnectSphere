import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { VenueTimingSettings } from './VenueTimingSettings';

it('[TC-SPL-129-01] saves explicit minute settings and actual daily hours', async () => {
  const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ venue: {} }) });
  const onSaved = vi.fn();
  render(<VenueTimingSettings venue={{ id: 1, setup_minutes: null, turnaround_minutes: null, operating_intervals: null }} api={request} onSaved={onSaved} />);
  fireEvent.change(screen.getByLabelText('Setup minutes'), { target: { value: '30' } });
  fireEvent.change(screen.getByLabelText('Turnaround minutes'), { target: { value: '45' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add opening interval' }));
  fireEvent.change(screen.getByLabelText('Opening time 1'), { target: { value: '09:00' } });
  fireEvent.change(screen.getByLabelText('Closing time 1'), { target: { value: '18:00' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save timing' }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({ setup_minutes: 30, turnaround_minutes: 45, operating_intervals: [[540,1080]] });
});

it('[TC-SPL-129-03] retains entered settings on a refused save', async () => {
  const request = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'Operating intervals must not overlap.' }) });
  render(<VenueTimingSettings venue={{ id: 1, setup_minutes: 30, turnaround_minutes: 45, operating_intervals: [[540,1080]] }} api={request} onSaved={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Save timing' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Operating intervals must not overlap.');
  expect((screen.getByLabelText('Setup minutes') as HTMLInputElement).value).toBe('30');
});
