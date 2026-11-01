import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import type { AuthGateway, AuthSession } from './auth';
import { NotificationSettings } from './NotificationSettings';
import { Notifications } from './Notifications';

// SPL-126 QA cases (QA-SPL-126-NNN, see the QA report). The API is stubbed, so these prove what the
// settings screen shows and sends for a given payload; whose settings the server returns and how
// they stop emails are proved in backend/tests/test_qa_spl126.py.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, '', '/');
});

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function setting(type: string, label: string, role: string, roleLabel: string, email = true) {
  return { type, label, description: `${label} description.`, role, role_label: roleLabel, email };
}

const COORDINATOR = [
  setting('coordinator_assignment', 'Assignment changes', 'event_coordinator', 'Event Coordinator'),
  setting('coordinator_safety', 'Safety decisions', 'event_coordinator', 'Event Coordinator'),
];
const ATTENDEE = [
  setting('attendee_registration', 'Registration receipts', 'attendee', 'Attendee'),
];

function api(types: unknown[], put: (path: string, init: RequestInit) => Promise<Response> | Response = (
  path, init,
) => {
  const type = decodeURIComponent(path.split('/').pop()!);
  const found = (types as { type: string }[]).find(item => item.type === type);
  return response({ ...found, email: JSON.parse(String(init.body)).email });
}) {
  return vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === 'PUT') return put(path, init);
    return response({ types });
  });
}

function view(request: ReturnType<typeof api>, onNavigate = vi.fn()) {
  render(<NotificationSettings accessToken="token" onNavigate={onNavigate} request={request} />);
  return onNavigate;
}

describe('AC2 - the screen lists each notification type with an email switch', () => {
  // QA-SPL-126-016 | AC2 | BB happy path
  it('[QA-SPL-126-016] shows one labelled switch per type, grouped by role', async () => {
    view(api([...COORDINATOR, ...ATTENDEE]));

    const assignment = await screen.findByRole('switch', { name: 'Assignment changes' });
    expect(screen.getAllByRole('switch')).toHaveLength(3);
    expect(assignment.getAttribute('aria-describedby')).toBeTruthy();
    expect(document.getElementById(assignment.getAttribute('aria-describedby')!)?.textContent)
      .toBe('Assignment changes description.');
    const groups = screen.getAllByRole('group');
    expect(groups.map(group => within(group).getAllByRole('switch').length)).toEqual([2, 1]);
    expect(within(groups[0]).getByText('Event Coordinator')).toBeTruthy();
    expect(within(groups[1]).getByText('Attendee')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Email settings' })).toBeTruthy();
  });

  // QA-SPL-126-017 | AC2 | BB loading state
  it('[QA-SPL-126-017] says it is loading until the settings arrive', async () => {
    let release: (value: Response) => void = () => {};
    const request = vi.fn(() => new Promise<Response>(resolve => { release = resolve; }));
    render(<NotificationSettings accessToken="token" onNavigate={vi.fn()} request={request} />);

    expect(screen.getByText('Loading email settings')).toBeTruthy();
    expect(screen.queryByRole('switch')).toBeNull();
    release(response({ types: COORDINATOR }));
    expect(await screen.findAllByRole('switch')).toHaveLength(2);
  });

  // QA-SPL-126-018 | AC2 | BB negative (the settings cannot be loaded)
  it.each([
    ['a server error', () => Promise.resolve(response({ error: 'Down.' }, 500))],
    ['an unexpected payload', () => Promise.resolve(response({ settings: [] }))],
    ['a network failure', () => Promise.reject(new Error('offline'))],
  ])('[QA-SPL-126-018] reports %s without showing any switch', async (_name, reply) => {
    render(<NotificationSettings accessToken="token" onNavigate={vi.fn()} request={vi.fn(reply)} />);

    expect((await screen.findByRole('alert')).textContent)
      .toBe("We couldn't load your email settings. Try again shortly.");
    expect(screen.queryByRole('switch')).toBeNull();
  });

  // QA-SPL-126-019 | AC2 | BB boundary (a role with no notification types)
  it('[QA-SPL-126-019] explains when the account has no types to choose', async () => {
    view(api([]));

    expect((await screen.findByRole('status')).textContent).toContain('No email notifications for your role yet.');
    expect(screen.queryByRole('switch')).toBeNull();
  });

  // QA-SPL-126-054 | AC2 | BB the screen is reached from the inbox and leads back to it
  it('[QA-SPL-126-054] links from Notifications to Email settings and back', async () => {
    const fromInbox = vi.fn();
    render(<Notifications
      accessToken="token"
      onNavigate={fromInbox}
      request={vi.fn(async () => response({ notifications: [], unread_count: 0 }))}
    />);
    fireEvent.click(await screen.findByRole('link', { name: 'Email settings' }));
    expect(fromInbox).toHaveBeenCalledWith('/workspace/notification-settings');
    cleanup();

    const fromSettings = view(api(COORDINATOR));
    fireEvent.click(await screen.findByRole('link', { name: 'in-app inbox' }));
    expect(fromSettings).toHaveBeenCalledWith('/workspace/notifications');
  });
});

describe('AC3 - every switch starts on', () => {
  // QA-SPL-126-026 | AC3 | BB happy path
  it('[QA-SPL-126-026] shows each type the server reports as on, switched on', async () => {
    view(api([...COORDINATOR, setting('coordinator_requests', 'Requests', 'event_coordinator', 'Event Coordinator', false)]));

    const switches = await screen.findAllByRole('switch');
    expect(switches.map(item => (item as HTMLInputElement).checked)).toEqual([true, true, false]);
    expect(screen.getAllByText('Email on')).toHaveLength(2);
    expect(screen.getAllByText('Email off')).toHaveLength(1);
  });
});

describe('AC4 - a switch changes email only', () => {
  // QA-SPL-126-037 | AC4 | BB in-app notices cannot be turned off here
  it('[QA-SPL-126-037] offers email switches only and says the inbox still gets everything', async () => {
    view(api(COORDINATOR));

    await screen.findAllByRole('switch');
    expect(screen.getByText(/Every notification still appears in your/).textContent).toContain('in-app inbox');
    expect(screen.queryByRole('switch', { name: /in-app/i })).toBeNull();
    expect(screen.getAllByRole('switch')).toHaveLength(COORDINATOR.length);
  });

  // QA-SPL-126-038 | AC2, AC4 | BB happy path (turn one type off, then on)
  it('[QA-SPL-126-038] saves each switch at once and says so', async () => {
    let finish: (value: Response) => void = () => {};
    const request = api(COORDINATOR, () => new Promise<Response>(resolve => { finish = resolve; }));
    view(request);
    const assignment = await screen.findByRole('switch', { name: 'Assignment changes' }) as HTMLInputElement;

    fireEvent.click(assignment);

    expect(assignment.checked).toBe(false);
    expect(assignment.disabled).toBe(true);
    expect(screen.getByText('Saving…')).toBeTruthy();
    const [path, init] = request.mock.calls.find(([, call]) => call?.method === 'PUT')!;
    expect(path).toBe('/api/notification-settings/coordinator_assignment');
    expect(JSON.parse(String(init!.body))).toEqual({ email: false });
    finish(response({ ...COORDINATOR[0], email: false }));
    await waitFor(() => expect(assignment.disabled).toBe(false));
    expect(assignment.checked).toBe(false);
    expect((screen.getByRole('switch', { name: 'Safety decisions' }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getAllByText('Email off')).toHaveLength(1);
  });

  // QA-SPL-126-039 | AC2 | BB negative (a failed save puts the switch back)
  it.each([
    ['the server refuses it', () => response({ error: 'Notification type not found.' }, 404), 'Notification type not found.'],
    ['the server fails without a message', () => response({}, 500), "We couldn't save that setting. Try again."],
    ['the network fails', () => Promise.reject(new Error('offline')), "We couldn't save that setting. Try again."],
  ])('[QA-SPL-126-039] restores the switch when %s', async (_name, put, message) => {
    view(api(COORDINATOR, put as never));
    const assignment = await screen.findByRole('switch', { name: 'Assignment changes' }) as HTMLInputElement;

    fireEvent.click(assignment);

    expect(await screen.findByText(message)).toBeTruthy();
    expect(assignment.checked).toBe(true);
    expect(assignment.disabled).toBe(false);
    expect(screen.getByText(message).closest('.notification-settings__status--error')).toBeTruthy();
  });
});

describe('AC5 - only the signed-in account, every role', () => {
  // QA-SPL-126-052 | AC5 | BB security (the view never names an account)
  it('[QA-SPL-126-052] never sends an account, role or user identifier', async () => {
    const request = api(COORDINATOR);
    view(request);
    fireEvent.click(await screen.findByRole('switch', { name: 'Safety decisions' }));
    await waitFor(() => expect(request.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(true));

    for (const [path, init] of request.mock.calls) {
      expect(path).not.toMatch(/account|user|role/i);
      if (init?.body) expect(Object.keys(JSON.parse(String(init.body)))).toEqual(['email']);
    }
  });

  const session = {
    access_token: 'verified-token',
    user: { id: 'user-1', app_metadata: {}, user_metadata: {}, aud: 'authenticated', created_at: '' },
  } as AuthSession;
  const gateway: AuthGateway = {
    getSession: vi.fn().mockResolvedValue({ session }),
    signInWithPassword: vi.fn(),
    signOut: vi.fn(),
  };

  // QA-SPL-126-053 | AC5 | BB every role reaches its own settings in the workspace
  it.each([
    'event_organiser',
    'event_operations_manager',
    'event_coordinator',
    'venue_staff',
    'technical_support_staff',
    'safety_officer',
    'attendee',
  ])('[QA-SPL-126-053] the %s workspace opens Email settings from the inbox', async role => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === '/api/session') return Promise.resolve({ ok: true });
      if (path === '/api/account/roles') return Promise.resolve(response({ roles: [role] }));
      if (path === '/api/notifications') return Promise.resolve(response({ notifications: [], unread_count: 0 }));
      if (path === '/api/notification-settings') return Promise.resolve(response({ types: ATTENDEE }));
      return Promise.resolve(response({ error: 'Not found.' }, 404));
    }));
    render(<App authGateway={gateway} />);

    fireEvent.click(await screen.findByRole('link', { name: 'Notifications' }));
    fireEvent.click(await screen.findByRole('link', { name: 'Email settings' }));

    expect(window.location.pathname).toBe('/workspace/notification-settings');
    expect(await screen.findByRole('switch', { name: 'Registration receipts' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Notifications' }).getAttribute('aria-current')).toBe('page');
  });
});
