import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EquipmentRequirements } from './EquipmentRequirements';

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const microphone = {
  id: 1, name: 'Wireless Microphone', description: 'Handheld microphone with receiver.',
  location: 'Technical Store A', total_stock: 12,
};
const unmappedRequirement = {
  id: 7, organiser_equipment_text: 'Wireless microphone', equipment_type: null,
  quantity: 4, notes: 'For panel discussion.', required_start_date: '2026-10-14',
  required_end_date: '2026-10-14', collection_date: '2026-10-13',
  planned_return_date: '2026-10-14', status: 'unmapped', essentiality: 'undecided' as const,
  consulted_technical_support: null, essentiality_decision_note: null,
  essentiality_decided_at: null, essentiality_decided_by: null,
  review_reason: null, review_flagged_at: null,
};

function payload(requirements: unknown[] = [unmappedRequirement], removed_requirements: unknown[] = []) {
  return {
    event: { id: 2, name: 'Northstar Innovation Forum', proposed_date: '2026-10-14', status: 'planning' },
    requirements, removed_requirements, equipment_types: [microphone],
    technical_support_staff: [{ id: 'technical-1', name: 'Taylor Technical' }],
  };
}

describe('EquipmentRequirements', () => {
  // SPL-90 AC-1 / TC-SPL-90-009: the page preserves organiser wording until the coordinator maps it.
  it('maps a retained organiser request to a catalogue item without changing its original wording', async () => {
    let mapped = false;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/event-requests/2/equipment-requirements' && !init) {
        return response(mapped ? payload([{ ...unmappedRequirement, equipment_type: microphone, status: 'requested' }]) : payload());
      }
      if (path === '/api/event-requests/2/equipment-requirements/7' && init?.method === 'PATCH') {
        expect(JSON.parse(String(init.body))).toEqual({
          equipment_type_id: 1, quantity: 4, notes: 'For panel discussion.',
          required_start_date: '2026-10-14', required_end_date: '2026-10-14', essentiality: 'undecided',
        });
        mapped = true;
        return response({ requirement: { ...unmappedRequirement, equipment_type: microphone, status: 'requested' } });
      }
      return response({});
    });

    render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    await screen.findByRole('button', { name: 'Map to catalogue' });
    fireEvent.click(screen.getByRole('button', { name: 'Map to catalogue' }));
    fireEvent.change(screen.getByLabelText('Catalogue equipment Required'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Map requirement' }));

    expect(await screen.findByText('Equipment requirement saved.')).toBeTruthy();
    expect(await screen.findByText('Organiser wording: Wireless microphone')).toBeTruthy();
    expect(await screen.findByText('requested')).toBeTruthy();
  });

  // SPL-90 AC-3 / TC-SPL-90-010: a criticality choice visibly requires consultation evidence.
  it('requires a Technical Support consultant and decision note when marking an item essential', async () => {
    const request = vi.fn(async () => response(payload()));
    render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    await screen.findByRole('button', { name: 'Map to catalogue' });
    fireEvent.click(screen.getByRole('button', { name: 'Map to catalogue' }));
    fireEvent.click(screen.getByLabelText('Essential'));

    const consultant = screen.getByLabelText('Consulted Technical Support Staff Required');
    const note = screen.getByLabelText('Decision note Required');
    expect((consultant as HTMLSelectElement).required).toBe(true);
    expect((note as HTMLTextAreaElement).required).toBe(true);
    expect(screen.getByText('Keep this Undecided until you have consulted Technical Support. Essential requirements later contribute to event readiness.')).toBeTruthy();
  });

  // SPL-90 AC-4 / TC-SPL-90-011: removal refreshes active planning and exposes retained history.
  it('removes a requirement from active planning while retaining it in the history panel', async () => {
    let removed = false;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/event-requests/2/equipment-requirements' && !init) {
        return response(removed ? payload([], [unmappedRequirement]) : payload());
      }
      if (path === '/api/event-requests/2/equipment-requirements/7' && init?.method === 'DELETE') {
        removed = true;
        return response({ message: 'Equipment requirement removed.' });
      }
      return response({});
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    await screen.findByRole('button', { name: 'Map to catalogue' });
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(await screen.findByText('Equipment requirement removed from active planning.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show removed requirements (1)' }));
    expect(await screen.findByText('Removed from active planning')).toBeTruthy();
  });
});
