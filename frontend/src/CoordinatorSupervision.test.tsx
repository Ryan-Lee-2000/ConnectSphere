import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CoordinatorAssignmentQueue } from './CoordinatorAssignmentQueue';
import {
  CoordinatorLeadWorkspace,
  CoordinatorSupervision,
  type SupervisedEvent,
} from './CoordinatorSupervision';

// SPL-134 QA cases (QA-SPL-134-NNN, see the QA report). The API is stubbed, so these prove what the
// Lead's screen shows and sends for a given payload; who is allowed, which events are active and who
// is notified are proved in backend/tests/test_qa_spl134.py.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const harbour: SupervisedEvent = {
  id: 7,
  name: 'Harbour Summit',
  purpose: 'Client showcase',
  organisation_name: 'Northstar Community Partners',
  proposed_date: '2026-10-12',
  start_time: '09:00',
  end_time: '12:00',
  expected_attendance: 120,
  status: 'under_review',
  status_label: 'Under review',
  coordinator: { id: 'alice', name: 'Alice Tan' },
  reassignable: true,
};
const gala: SupervisedEvent = {
  ...harbour,
  id: 8,
  name: 'Gala Night',
  purpose: null,
  proposed_date: null,
  start_time: null,
  end_time: null,
  expected_attendance: null,
  status: 'submitted',
  status_label: 'Submitted',
  coordinator: null,
  reassignable: false,
};
const closed: SupervisedEvent = {
  ...harbour,
  id: 9,
  name: 'Old Expo',
  status: 'completed',
  status_label: 'Completed',
  reassignable: false,
};
const choices = [{ id: 'bob', name: 'Bob Lim' }, { id: 'carol', name: 'Carol Ng' }];

type Handler = (init?: RequestInit) => Response | Promise<Response>;
function api(routes: Record<string, Handler>) {
  return vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? 'GET'} ${path}`];
    return handler ? handler(init) : response({ error: 'Unexpected request.' }, 500);
  });
}

// QA-SPL-134-101 | AC2 | BB happy path
describe('supervision list', () => {
  it('QA-SPL-134-101 lists each event with the agreed basic information and its coordinator', async () => {
    const request = api({
      'GET /api/event-requests/supervision': () => response({ events: [harbour, gala] }),
    });
    render(<CoordinatorSupervision accessToken="t" request={request} />);

    const rows = (await screen.findAllByRole('row')).slice(1);
    const first = within(rows[0]);
    expect(first.getByRole('rowheader').textContent).toBe('Harbour Summit');
    for (const text of ['Client showcase', 'Northstar Community Partners', 'Under review', 'Alice Tan', '120']) {
      expect(first.getByText(text)).toBeTruthy();
    }
    expect(first.getByText(/12 Oct 2026, 09:00–12:00/)).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'Coordinator' })).toBeTruthy();
  });

  // QA-SPL-134-102 | AC2 | BB boundary
  it('QA-SPL-134-102 says what is missing instead of showing blanks', async () => {
    const request = api({
      'GET /api/event-requests/supervision': () => response({ events: [gala] }),
    });
    render(<CoordinatorSupervision accessToken="t" request={request} />);

    const row = within((await screen.findAllByRole('row'))[1]);
    expect(row.getAllByText('Not provided')).toHaveLength(3);
    expect(row.getByText('Awaiting assignment')).toBeTruthy();
  });

  // QA-SPL-134-103 | AC2/AC3 | BB: reassign is offered only where it can succeed
  it('QA-SPL-134-103 offers Reassign only on events that can be reassigned', async () => {
    const request = api({
      'GET /api/event-requests/supervision': () => response({ events: [harbour, gala, closed] }),
    });
    render(<CoordinatorSupervision accessToken="t" request={request} />);

    await screen.findByText('Harbour Summit');
    expect(screen.getAllByRole('button', { name: /^Reassign coordinator for/ })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Reassign coordinator for Harbour Summit' })).toBeTruthy();
  });

  // QA-SPL-134-104 | AC2 | BB boundary
  it('QA-SPL-134-104 shows an empty state when there are no active events', async () => {
    const request = api({ 'GET /api/event-requests/supervision': () => response({ events: [] }) });
    render(<CoordinatorSupervision accessToken="t" request={request} />);

    expect(await screen.findByRole('heading', { name: 'No active events' })).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
  });

  // QA-SPL-134-105 | AC4 | BB security: a non-Lead never sees the section
  it('QA-SPL-134-105 renders nothing for an account the server refuses', async () => {
    const request = api({
      'GET /api/event-requests/supervision': () => response({ error: 'Access denied.' }, 403),
    });
    const { container } = render(<CoordinatorSupervision accessToken="t" request={request} />);

    await waitFor(() => expect(container.innerHTML).toBe(''));
  });

  // QA-SPL-134-106 | AC2 | BB negative: server error is explained, not blank
  it('QA-SPL-134-106 shows the server message when loading fails', async () => {
    const request = api({
      'GET /api/event-requests/supervision': () => response({ error: 'Service unavailable.' }, 503),
    });
    render(<CoordinatorSupervision accessToken="t" request={request} />);

    expect((await screen.findByRole('alert')).textContent).toBe('Service unavailable.');
    expect(screen.queryByRole('table')).toBeNull();
  });

  // QA-SPL-134-107 | AC2 | BB negative: network failure and an unreadable reply
  it.each([
    ['network failure', () => Promise.reject(new Error('offline'))],
    ['a non-JSON error body', () => new Response('<html>', { status: 502 })],
  ])('QA-SPL-134-107 survives %s', async (_label, handler) => {
    const request = api({ 'GET /api/event-requests/supervision': handler as Handler });
    render(<CoordinatorSupervision accessToken="t" request={request} />);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent?.length).toBeGreaterThan(10);
  });

  // QA-SPL-134-108 | AC2 | BB: the session token is what authorises the request
  it('QA-SPL-134-108 sends the bearer token and never an account id', async () => {
    const fetchMock = vi.fn(async () => response({ events: [] }));
    vi.stubGlobal('fetch', fetchMock);
    render(<CoordinatorSupervision accessToken="session-token" />);

    await screen.findByRole('heading', { name: 'No active events' });
    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe('/api/event-requests/supervision');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer session-token');
    expect(init.body).toBeUndefined();
    vi.unstubAllGlobals();
  });
});

describe('reassignment panel', () => {
  function reassignRoutes(overrides: Record<string, Handler> = {}) {
    let reassigned = false;
    return api({
      'GET /api/event-requests/supervision': () =>
        response({
          events: [reassigned ? { ...harbour, coordinator: choices[0] } : harbour],
        }),
      'GET /api/event-requests/7/coordinator-options': () =>
        response({ coordinators: choices, current_coordinator: harbour.coordinator, unavailable_reason: null }),
      'PUT /api/event-requests/7/coordinator': () => {
        reassigned = true;
        return response({ assignment: { event_request_id: 7, status: 'under_review', coordinator: choices[0] } });
      },
      ...overrides,
    });
  }

  async function open(request: ReturnType<typeof api>) {
    render(<CoordinatorSupervision accessToken="t" request={request} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Reassign coordinator for Harbour Summit' }));
  }

  // QA-SPL-134-109 | AC3/AC5 | BB happy path
  it('QA-SPL-134-109 reassigns with only the chosen coordinator id and refreshes the list', async () => {
    const request = reassignRoutes();
    await open(request);

    const confirm = screen.getByRole('button', { name: 'Confirm reassignment' });
    expect(confirm).toHaveProperty('disabled', true);
    fireEvent.change(await screen.findByLabelText('New Event Coordinator'), { target: { value: 'bob' } });
    fireEvent.click(confirm);

    expect((await screen.findByRole('status')).textContent).toBe('Bob Lim is now responsible for Harbour Summit.');
    const put = request.mock.calls.find(([, init]) => init?.method === 'PUT')!;
    expect(put[0]).toBe('/api/event-requests/7/coordinator');
    expect(JSON.parse(put[1]!.body as string)).toEqual({ coordinator_account_id: 'bob' });
    await waitFor(() => expect(screen.getByText('Bob Lim', { selector: 'td' })).toBeTruthy());
    expect(screen.queryByRole('form')).toBeNull();
  });

  // QA-SPL-134-110 | AC3 | BB: the Lead is told what will happen before confirming
  it('QA-SPL-134-110 names the former coordinator and who will be told', async () => {
    await open(reassignRoutes());

    const hint = await screen.findByText(/Alice Tan stops being responsible immediately/);
    expect(hint.textContent).toMatch(/keeps its status and arrangements/);
    expect(hint.textContent).toMatch(/former coordinator, new coordinator and organiser are notified/);
  });

  // QA-SPL-134-111 | AC3 | BB negative: a refusal is shown and nothing is closed or refreshed
  it('QA-SPL-134-111 shows the server refusal and keeps the panel open', async () => {
    const request = reassignRoutes({
      'PUT /api/event-requests/7/coordinator': () =>
        response({ error: 'The Event Coordinator changed while you were reassigning. Try again.' }, 409),
    });
    await open(request);
    fireEvent.change(await screen.findByLabelText('New Event Coordinator'), { target: { value: 'carol' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reassignment' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/changed while you were reassigning/);
    expect(screen.getByRole('button', { name: 'Confirm reassignment' })).toBeTruthy();
    expect(screen.queryByText(/is now responsible/)).toBeNull();
  });

  // QA-SPL-134-112 | AC3 | BB negative: no other coordinator is explained and cannot be confirmed
  it('QA-SPL-134-112 explains when no other coordinator is available', async () => {
    const request = reassignRoutes({
      'GET /api/event-requests/7/coordinator-options': () =>
        response({
          coordinators: [],
          current_coordinator: harbour.coordinator,
          unavailable_reason: 'No other active Event Coordinator is available, so this event cannot be reassigned yet.',
        }),
    });
    await open(request);

    expect((await screen.findByRole('alert')).textContent).toMatch(/No other active Event Coordinator/);
    expect(screen.queryByLabelText('New Event Coordinator')).toBeNull();
    expect(screen.getByRole('button', { name: 'Confirm reassignment' })).toHaveProperty('disabled', true);
  });

  // QA-SPL-134-113 | AC3 | BB negative: options cannot be loaded
  it.each([
    ['a refused load', () => response({ error: 'Event request not found.' }, 404), /not found/],
    ['a network failure', () => Promise.reject(new Error('offline')), /could not be loaded/],
  ])('QA-SPL-134-113 reports %s while loading coordinators', async (_label, handler, expected) => {
    await open(reassignRoutes({ 'GET /api/event-requests/7/coordinator-options': handler as Handler }));

    expect((await screen.findByRole('alert')).textContent).toMatch(expected);
  });

  // QA-SPL-134-114 | AC3 | BB negative: network failure on save
  it('QA-SPL-134-114 survives a network failure while saving and can be retried', async () => {
    let attempts = 0;
    const request = reassignRoutes({
      'PUT /api/event-requests/7/coordinator': () => {
        attempts += 1;
        if (attempts === 1) return Promise.reject(new Error('offline'));
        return response({ assignment: { event_request_id: 7, status: 'under_review', coordinator: choices[1] } });
      },
    });
    await open(request);
    fireEvent.change(await screen.findByLabelText('New Event Coordinator'), { target: { value: 'carol' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reassignment' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/could not be saved/);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reassignment' }));
    expect((await screen.findByRole('status')).textContent).toBe('Carol Ng is now responsible for Harbour Summit.');
  });

  // QA-SPL-134-115 | AC3 | BB: cancel changes nothing
  it('QA-SPL-134-115 sends nothing when the Lead cancels', async () => {
    const request = reassignRoutes();
    await open(request);
    await screen.findByLabelText('New Event Coordinator');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByLabelText('New Event Coordinator')).toBeNull();
    expect(request.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false);
  });

  // QA-SPL-134-116 | AC3 | BB: a stale selection after switching events is not reused
  it('QA-SPL-134-116 starts a fresh choice for each event', async () => {
    const second = { ...harbour, id: 11, name: 'Tech Forum', coordinator: { id: 'carol', name: 'Carol Ng' } };
    const request = api({
      'GET /api/event-requests/supervision': () => response({ events: [harbour, second] }),
      'GET /api/event-requests/7/coordinator-options': () =>
        response({ coordinators: choices, current_coordinator: harbour.coordinator, unavailable_reason: null }),
      'GET /api/event-requests/11/coordinator-options': () =>
        response({ coordinators: [choices[0]], current_coordinator: second.coordinator, unavailable_reason: null }),
    });
    render(<CoordinatorSupervision accessToken="t" request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Reassign coordinator for Harbour Summit' }));
    fireEvent.change(await screen.findByLabelText('New Event Coordinator'), { target: { value: 'carol' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reassign coordinator for Tech Forum' }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tech Forum', level: 3 })).toBeTruthy());
    const select = (await screen.findByLabelText('New Event Coordinator')) as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(within(select).queryByText('Carol Ng')).toBeNull();
  });
});

describe('Lead workspace', () => {
  // QA-SPL-134-117 | AC1/AC2 | BB: assigning from the queue updates supervision without a reload
  it('QA-SPL-134-117 shows the new assignment in supervision straight after the queue assigns', async () => {
    let assigned = false;
    const unassigned = { id: 8, name: 'Gala Night', organisation_id: 3, organisation_name: 'Northstar', proposed_date: null, submitted_at: null };
    const request = api({
      'GET /api/event-requests/awaiting-assignment': () =>
        response(assigned ? { events: [], count: 0 } : { events: [unassigned], count: 1 }),
      'GET /api/event-requests/supervision': () =>
        response({ events: [assigned ? { ...gala, coordinator: choices[0], reassignable: true } : gala] }),
      'GET /api/event-requests/8/basic-information': () =>
        response({ event: { ...gala, purpose: 'Annual dinner', start_time: '18:00', end_time: '22:00', expected_attendance: 90 } }),
      'GET /api/event-requests/8/coordinator-options': () =>
        response({ coordinators: choices, current_coordinator: null, unavailable_reason: null }),
      'POST /api/event-requests/8/coordinator': () => {
        assigned = true;
        return response({ assignment: { event_request_id: 8, status: 'submitted', coordinator: choices[0] } }, 201);
      },
    });
    render(<CoordinatorLeadWorkspace accessToken="t" request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Assign coordinator to Gala Night' }));
    fireEvent.change(await screen.findByLabelText('Event Coordinator'), { target: { value: 'bob' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm assignment' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Reassign coordinator for Gala Night' })).toBeTruthy());
    expect(screen.getByText('Bob Lim', { selector: 'td' })).toBeTruthy();
  });

  // QA-SPL-134-118 | AC1 | BB: basic information appears in the assignment panel
  it('QA-SPL-134-118 shows the basic information before the Lead assigns', async () => {
    const unassigned = { id: 8, name: 'Gala Night', organisation_id: 3, organisation_name: 'Northstar', proposed_date: '2026-11-03', submitted_at: null };
    const request = api({
      'GET /api/event-requests/awaiting-assignment': () => response({ events: [unassigned], count: 1 }),
      'GET /api/event-requests/8/basic-information': () =>
        response({ event: { purpose: 'Annual dinner', start_time: '18:00', end_time: '22:00', expected_attendance: 90, status_label: 'Submitted' } }),
      'GET /api/event-requests/8/coordinator-options': () =>
        response({ coordinators: choices, current_coordinator: null, unavailable_reason: null }),
    });
    render(<CoordinatorAssignmentQueue accessToken="t" request={request} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Assign coordinator to Gala Night' }));

    expect(await screen.findByText('Annual dinner')).toBeTruthy();
    expect(screen.getByText('3 Nov 2026, 18:00–22:00')).toBeTruthy();
    expect(screen.getByText('90')).toBeTruthy();
    expect(screen.getByText('Submitted', { selector: 'dd' })).toBeTruthy();
  });

  // QA-SPL-134-119 | AC1 | BB negative: missing basic information never blocks assigning
  it.each([
    ['a refusal', () => response({ error: 'Event request not found.' }, 404)],
    ['a network failure', () => Promise.reject(new Error('offline'))],
    ['an unrecognised reply', () => response({ unexpected: true })],
  ])('QA-SPL-134-119 still lets the Lead assign after %s loading basic information', async (_label, handler) => {
    const unassigned = { id: 8, name: 'Gala Night', organisation_id: 3, organisation_name: 'Northstar', proposed_date: null, submitted_at: null };
    const request = api({
      'GET /api/event-requests/awaiting-assignment': () => response({ events: [unassigned], count: 1 }),
      'GET /api/event-requests/8/basic-information': handler as Handler,
      'GET /api/event-requests/8/coordinator-options': () =>
        response({ coordinators: choices, current_coordinator: null, unavailable_reason: null }),
    });
    render(<CoordinatorAssignmentQueue accessToken="t" request={request} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Assign coordinator to Gala Night' }));

    expect(await screen.findByLabelText('Event Coordinator')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText('Northstar', { selector: 'dd' })).toBeTruthy();
  });
});
