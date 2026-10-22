import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EquipmentRequirements } from './EquipmentRequirements';
import { Notifications } from './Notifications';

// SPL-122 QA cases (QA-SPL-122-NNN, see the QA-SPL-122 page). The API is stubbed: the server picks
// the link (backend/tests/test_qa_spl122.py); these prove the inbox follows it and nothing similar.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const NOTICE = {
  id: 3,
  message: 'Equipment requirement added to Founders Day: Wireless Microphone × 4.',
  event: { id: 7, name: 'Founders Day' },
  link: '/workspace/equipment-review-queue',
  created_at: '2026-10-22T09:05:00+08:00',
  read: false,
};

function inbox(notifications: unknown[]) {
  return vi.fn(async () => new Response(JSON.stringify({ notifications, unread_count: 1 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }));
}

describe('AC5 - each notice opens the Equipment review queue', () => {
  // QA-SPL-122-053 | AC5 | BB
  it('[QA-SPL-122-053] opens a Technical Support notice on the Equipment review queue', async () => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([NOTICE])} />);

    const link = await screen.findByRole('link', { name: 'Founders Day' });
    expect(link.getAttribute('href')).toBe('/workspace/equipment-review-queue');
    fireEvent.click(link);

    expect(onNavigate).toHaveBeenCalledWith('/workspace/equipment-review-queue');
    expect(screen.getByText(NOTICE.message)).toBeTruthy();
  });

  // QA-SPL-122-054 | AC5 | BB security
  it.each([
    '/workspace/equipment-review-queue/7',
    '/workspace/equipment-review-queuex',
    '/workspace/equipment-review-queue?line=7',
    '//evil.test/workspace/equipment-review-queue',
    '/workspace/equipment-review-queue/../admin',
  ])('[QA-SPL-122-054] does not follow a lookalike link %s', async link => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([{ ...NOTICE, link }])} />);

    fireEvent.click(await screen.findByRole('link', { name: 'Founders Day' }));

    expect(onNavigate).toHaveBeenCalledWith('/workspace/assigned-events/7');
  });
});

// Review round 1 (2026-10-22, Ryan on PR #96): a retried addition must not notify twice.
describe('AC4 - a retried addition reuses its request id', () => {
  const microphone = { id: 1, name: 'Wireless Microphone', description: '', location: 'Store A', total_stock: 12 };
  const page = {
    event: { id: 2, name: 'Founders Day', proposed_date: '2026-10-14', status: 'planning' },
    requirements: [], removed_requirements: [], equipment_types: [microphone],
    technical_support_staff: [],
  };

  // QA-SPL-122-055 | AC4 | BB
  it('[QA-SPL-122-055] resends the same request id after a failed save, and a new form gets a new one', async () => {
    const sent: string[] = [];
    let attempts = 0;
    const request = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        sent.push(JSON.parse(String(init.body)).request_id);
        attempts += 1;
        if (attempts === 1) throw new TypeError('Failed to fetch');
        return new Response(JSON.stringify({ requirement: {} }), { status: 201, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify(page), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    render(<EquipmentRequirements accessToken="token" eventId={2} onNavigate={vi.fn()} request={request} />);

    const addForm = async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'Add requirement' }));
      fireEvent.change(screen.getByLabelText('Catalogue equipment Required'), { target: { value: '1' } });
      fireEvent.change(screen.getByLabelText('Quantity Required'), { target: { value: '4' } });
    };
    await addForm();
    fireEvent.click(screen.getByRole('button', { name: 'Add requirement' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Try again');
    fireEvent.click(screen.getByRole('button', { name: 'Add requirement' }));
    expect(await screen.findByText('Equipment requirement added.')).toBeTruthy();

    await addForm();
    fireEvent.click(screen.getByRole('button', { name: 'Add requirement' }));
    await waitFor(() => expect(sent).toHaveLength(3));

    expect(sent[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(sent[1]).toBe(sent[0]);
    expect(sent[2]).not.toBe(sent[0]);
  });
});
