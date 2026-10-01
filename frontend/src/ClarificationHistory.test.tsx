import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ClarificationHistory } from './ClarificationHistory';

describe('ClarificationHistory', () => {
  // TC-SPL-66-02
  // SPL-66 AC-2
  it('[TC-SPL-66-02] shows the retained response with its respondent and time', () => {
    render(<ClarificationHistory heading="Clarification history" clarifications={[{
      id: 12,
      message: 'Please confirm the attendance.',
      author: { id: 'alice', name: 'Alice Tan' },
      created_at: '2026-09-28T10:00:00+08:00',
      response: 'Attendance remains 120 people.',
      respondent: { id: 'olivia', name: 'Olivia Organiser' },
      responded_at: '2026-09-29T11:30:00+08:00',
    }]} />);

    expect(screen.getByText('Please confirm the attendance.')).toBeTruthy();
    expect(screen.getByText('Attendance remains 120 people.')).toBeTruthy();
    // AC2 requires a visible saved date and time as well as the respondent.
    const responseMetadata = screen.getByText(/Response from Olivia Organiser/);
    expect(responseMetadata.textContent).toMatch(/29 Sep(?:t)? 2026/);
    expect(responseMetadata.textContent).toMatch(/11:30\s*am/i);
  });
});
