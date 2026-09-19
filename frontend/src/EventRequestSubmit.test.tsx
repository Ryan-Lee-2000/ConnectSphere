import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EventRequestSubmit } from './EventRequestSubmit';

afterEach(() => {
  vi.restoreAllMocks();
});

const submittedRequest = {
  id: 7,
  name: 'Regional Partner Conference',
  status: 'submitted',
  submitted_at: '2026-09-18T09:30:00+08:00',
};

function response(body: unknown, status = 200) {
  return Promise.resolve({ status, json: () => Promise.resolve(body) } as Response);
}

function enterMandatoryFields() {
  const values: [string, string][] = [
    ['Event name', 'Regional Partner Conference'],
    ['Purpose', 'Brief partners on the roadmap'],
    ['Proposed date', '2026-12-01'],
    ['Start time', '09:00'],
    ['End time', '11:30'],
    ['Expected attendance', '120'],
  ];
  for (const [label, value] of values) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
}

function submitForm() {
  fireEvent.click(screen.getByRole('button', { name: 'Submit request' }));
}

// TC-CS-E03-S5-10
it('sends the request to the server and confirms the submission', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockReturnValue(response({ event_request: submittedRequest }, 201));

  render(<EventRequestSubmit accessToken="token-123" />);
  enterMandatoryFields();
  submitForm();

  const confirmation = await screen.findByRole('status');
  expect(confirmation.textContent).toContain('Request submitted.');
  expect(confirmation.textContent).toContain('EVT-7');
  expect(confirmation.textContent).toContain('submitted');
  expect(screen.queryByRole('alert')).toBeNull();

  const [path, init] = fetchMock.mock.calls[0];
  expect(path).toBe('/api/event-requests');
  expect(init?.method).toBe('POST');
  expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer token-123');
  expect(JSON.parse(init?.body as string)).toMatchObject({
    name: 'Regional Partner Conference',
    purpose: 'Brief partners on the roadmap',
    proposed_date: '2026-12-01',
    start_time: '09:00',
    end_time: '11:30',
    expected_attendance: 120,
  });
});

// TC-CS-E03-S5-12
it('names every missing mandatory field when the submission is refused', async () => {
  vi.spyOn(globalThis, 'fetch').mockReturnValue(
    response(
      {
        error: 'Complete the required fields before submitting.',
        missing_fields: ['name', 'purpose'],
        missing_field_labels: ['Event name', 'Purpose'],
      },
      400,
    ),
  );

  render(<EventRequestSubmit accessToken="token-123" />);
  submitForm();

  const message = await screen.findByRole('alert');
  expect(message.textContent).toContain('Complete the required fields before submitting.');
  expect(message.textContent).toContain('Event name');
  expect(message.textContent).toContain('Purpose');
  expect(screen.queryByRole('status')).toBeNull();
});

// TC-CS-E03-S5-13
it('clears the earlier error once a corrected submission succeeds', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockReturnValueOnce(
      response(
        {
          error: 'Complete the required fields before submitting.',
          missing_field_labels: ['Event name'],
        },
        400,
      ),
    )
    .mockReturnValueOnce(response({ event_request: submittedRequest }, 201));

  render(<EventRequestSubmit accessToken="token-123" />);
  submitForm();
  expect(await screen.findByRole('alert')).toBeTruthy();

  enterMandatoryFields();
  submitForm();

  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  const confirmation = await screen.findByRole('status');
  expect(confirmation.textContent).toContain('Request submitted.');
});

it('reports a service failure without claiming the request was submitted', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network down'));

  render(<EventRequestSubmit accessToken="token-123" />);
  enterMandatoryFields();
  submitForm();

  const message = await screen.findByRole('alert');
  expect(message.textContent).toContain("We couldn't submit your request. Please try again.");
  expect(screen.queryByRole('status')).toBeNull();
});
