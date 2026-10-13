import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
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
  // TC-SPL-93-009 — AC2/AC3: the coordinator receives and can read the immutable support history.
  it('[TC-SPL-93-009] shows an unavailable reason, suggestion and later restoration on its own line', async () => {
    const unavailable = {
      ...unmappedRequirement, equipment_type: microphone, status: 'requested',
      unavailability_history: [
        { id: 1, action: 'marked_unavailable', reason: 'Supplier recall', alternative_suggestion: 'Use wired microphones', recorded_at: '2026-10-12T10:15:00+08:00', recorded_by: { id: 'technical-1', name: 'Taylor Technical' } },
        { id: 2, action: 'restored_to_requested', reason: null, alternative_suggestion: null, recorded_at: '2026-10-12T11:15:00+08:00', recorded_by: { id: 'technical-1', name: 'Taylor Technical' } },
      ],
    };
    render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={async () => response(payload([unavailable]))} />);

    expect(await screen.findByText('Technical Support availability history')).toBeTruthy();
    expect(screen.getByText('Reason: Supplier recall')).toBeTruthy();
    expect(screen.getByText('Alternative suggestion: Use wired microphones')).toBeTruthy();
    expect(screen.getByText(/Restored to requested/)).toBeTruthy();
  });

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

// SPL-91 TC-SPL-91-10: revising a line Technical Support has already reserved stock for.
describe('EquipmentRequirements — changing a reserved line (SPL-91)', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  const reservedLine = {
    ...unmappedRequirement, id: 8, equipment_type: microphone, status: 'reserved',
    organiser_equipment_text: 'Wireless microphones',
  };
  const flaggedLine = {
    ...reservedLine, status: 'review_required', quantity: 5,
    review_reason: 'The assigned coordinator changed the quantity (4 → 5). The 4 reserved unit(s) were released for Technical Support to review.',
  };

  // TC-SPL-91-10
  it('[TC-SPL-91-10] warns before saving, reports the release, and shows the line back with Technical Support', async () => {
    let saved = false;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/event-requests/2/equipment-requirements' && !init) {
        return response(payload([saved ? flaggedLine : reservedLine]));
      }
      if (path === '/api/event-requests/2/equipment-requirements/8' && init?.method === 'PATCH') {
        saved = true;
        return response({ requirement: flaggedLine, released_quantity: 4 });
      }
      return response({});
    });
    render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Edit requirement' }));
    // AC2, said before the coordinator commits to it rather than discovered afterwards.
    const warning = screen.getByRole('note');
    expect(warning.textContent).toContain('releases any units reserved for it');
    expect(warning.textContent).toContain('back to Technical Support');

    fireEvent.change(screen.getByLabelText('Quantity Required'), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save requirement' }));

    // The cost of the save is stated from the server's own count, not inferred.
    // (The reason badge repeats the count, so the notice is matched by its own opening words.)
    expect(await screen.findByText(/^Equipment requirement saved\. 4 reserved unit\(s\) were released/)).toBeTruthy();
    // And the line now reads as back with Technical Support, with the reason why.
    expect(await screen.findByText('review required')).toBeTruthy();
    expect(screen.getByText(/Back with Technical Support for review:/).textContent).toContain('quantity (4 → 5)');
  });

  // TC-SPL-91-10
  it('[TC-SPL-91-10] asks before removing a reserved line, and says its units will be released', async () => {
    const calls: string[] = [];
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method) calls.push(`${init.method} ${path}`);
      return response(payload([reservedLine]));
    });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Remove' }));

    // The confirmation names the consequence for a line holding stock.
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0][0]).toContain('Any units reserved for it will be released.');
    // Declining sends nothing at all.
    expect(calls).toEqual([]);
  });

  // TC-SPL-91-10
  it('[TC-SPL-91-10] shows a refusal inside the form being edited and keeps what was typed', async () => {
    // A refusal only the server can make. A value the browser itself rejects (such as 0, below
    // the input's min of 1) never reaches the server at all, so it cannot test this path.
    const refusalText = 'This equipment requirement changed while its edit was being prepared.';
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'PATCH') return response({ error: refusalText }, 409);
      return response(payload([reservedLine]));
    });
    const { container } = render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Edit requirement' }));
    fireEvent.change(screen.getByLabelText('Quantity Required'), { target: { value: '6' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save requirement' }));

    // The refusal is inside the form, just above Save, not at the top of the page.
    const form = container.querySelector('form.equipment-requirements__editor') as HTMLElement;
    const refusal = await within(form).findByRole('alert');
    expect(refusal.textContent).toContain(refusalText);
    // The form stays open with the coordinator's input, so it can be corrected, not retyped.
    expect((within(form).getByLabelText('Quantity Required') as HTMLInputElement).value).toBe('6');
  });

  // TC-SPL-91-10
  it('[TC-SPL-91-10] gives no release warning on a line that holds no stock', async () => {
    const requested = { ...reservedLine, status: 'requested' };
    const request = vi.fn(async () => response(payload([requested])));
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Edit requirement' }));
    // The editor is open (so this is not vacuous), but the warning is reserved for held stock.
    expect(screen.getByRole('button', { name: 'Save requirement' })).toBeTruthy();
    expect(screen.queryByRole('note')).toBeNull();
  });

  // TC-SPL-91-10
  it('[TC-SPL-91-10] never shows one line\'s refused removal inside another line\'s open form', async () => {
    const otherLine = { ...reservedLine, id: 9, organiser_equipment_text: 'Portable speakers' };
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') return response({ error: 'This equipment requirement can no longer be changed or removed.' }, 409);
      return response(payload([reservedLine, otherLine]));
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { container } = render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    // Open line 8's form, then remove line 9 from its card.
    const editButtons = await screen.findAllByRole('button', { name: 'Edit requirement' });
    fireEvent.click(editButtons[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));

    // The removal's refusal belongs to the page, not to the unrelated form that happens to be open.
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('can no longer be changed or removed');
    const form = container.querySelector('form.equipment-requirements__editor') as HTMLElement;
    expect(within(form).queryByRole('alert')).toBeNull();
  });

  // TC-SPL-91-16 (added from review on PR #78)
  it('[TC-SPL-91-16] shows the review warning only while a line is Review Required', async () => {
    // Re-reserving a line now clears its explanation on the server. The page must not rely on
    // that alone: a reason arriving with any other status is history, not an active warning.
    const reservedAgain = {
      ...reservedLine, id: 10, organiser_equipment_text: 'Portable speakers',
      review_reason: 'Stale reason on a line that is Reserved again.',
      review_flagged_at: '2026-10-13T10:00:00+08:00',
    };
    const partlyReservedAgain = {
      ...reservedLine, id: 11, organiser_equipment_text: 'Lectern microphones', status: 'partially_reserved',
      review_reason: 'Stale reason on a line that is Partially Reserved again.',
      review_flagged_at: '2026-10-13T10:00:00+08:00',
    };
    const request = vi.fn(async () => response(payload([reservedAgain, partlyReservedAgain, flaggedLine])));
    render(<EquipmentRequirements accessToken="fixture" eventId={2} onNavigate={vi.fn()} request={request} />);

    // The Review Required line still shows its warning, so the badge is genuinely rendered...
    const warnings = await screen.findAllByText(/Back with Technical Support for review:/);
    // ...but only for that line. Neither stale reason reaches the page.
    expect(warnings).toHaveLength(1);
    expect(warnings[0].textContent).toContain('quantity (4 → 5)');
    expect(screen.queryByText(/Stale reason/)).toBeNull();
  });
});
