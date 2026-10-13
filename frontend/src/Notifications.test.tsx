import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import type { AuthGateway, AuthSession } from './auth';
import { Notifications } from './Notifications';

// SPL-101 QA cases (QA-SPL-101-NNN, see the QA report). The API is stubbed, so these prove what the
// inbox shows and does with a given payload; whose notices the server returns, and the assignment
// trigger, are proved in backend/tests/test_notifications.py.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, '', '/');
});

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

const NEWER = {
  id: 2,
  message: 'You have been assigned to Harbour Summit.',
  event: { id: 7, name: 'Harbour Summit' },
  created_at: '2026-10-07T09:05:00+08:00',
  read: false,
};
const OLDER = {
  id: 1,
  message: 'You have been assigned to Coastal Forum.',
  event: { id: 8, name: 'Coastal Forum' },
  created_at: '2026-10-07T09:00:00+08:00',
  read: true,
};

function inbox(notifications: unknown[], unread: number) {
  return vi.fn(async (_path: string, init?: RequestInit) => {
    if (init?.method === 'POST') return response({ unread_count: 0 });
    return response({ notifications, unread_count: unread });
  });
}

function status() {
  return screen.getByRole('status').textContent;
}

describe('AC1 - the inbox shows the signed-in account\'s notifications', () => {
  // QA-SPL-101-008 | AC1 | happy path
  it('[QA-SPL-101-008] lists notices in the order given with event, time and unread state', async () => {
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={inbox([NEWER, OLDER], 1)} />);

    expect(screen.getByText('Loading notifications')).toBeTruthy();
    const items = await screen.findAllByRole('listitem');
    expect(items[0].textContent).toContain('Harbour Summit');
    expect(items[0].textContent).toContain('Unread');
    expect(items[0].textContent).toContain('You have been assigned to Harbour Summit.');
    expect(items[1].textContent).toContain('Coastal Forum');
    expect(items[1].textContent).not.toContain('Unread');
    expect(status()).toBe('1 unread');
  });

  // QA-SPL-101-009 | AC1 | boundary: nothing to show
  it('[QA-SPL-101-009] shows an empty state and no actions when there are no notices', async () => {
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={inbox([], 0)} />);

    expect(await screen.findByText('No notifications yet.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Mark all as read' })).toBeNull();
    expect(screen.queryByRole('listitem')).toBeNull();
  });

  // QA-SPL-101-010 | AC1 | negative: the server refuses
  it('[QA-SPL-101-010] reports a server failure without showing notices', async () => {
    const request = vi.fn(async () => response({ error: 'down' }, 503));
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={request} />);

    expect((await screen.findByRole('alert')).textContent).toContain("couldn't load your notifications");
    expect(screen.queryByRole('listitem')).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
  });

  // QA-SPL-101-011 | AC1 | negative: the network fails or the reply is not an inbox
  it.each([
    ['the request rejects', () => vi.fn(async () => { throw new TypeError('offline'); })],
    ['the reply has no notification list', () => vi.fn(async () => response({ notifications: 'x' }))],
  ])('[QA-SPL-101-011] reports a failure when %s', async (_name, build) => {
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={build()} />);

    expect((await screen.findByRole('alert')).textContent).toContain("couldn't load your notifications");
  });

  // QA-SPL-101-012 | AC1 | boundary: an unreadable time is shown rather than hidden
  it('[QA-SPL-101-012] shows the raw time when it cannot be formatted', async () => {
    const odd = { ...NEWER, created_at: 'not-a-date' };
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={inbox([odd], 1)} />);

    expect((await screen.findByRole('listitem')).textContent).toContain('not-a-date');
  });

  // QA-SPL-101-042 | AC1 | cross-cut: the view never sends an account identifier
  it('[QA-SPL-101-042] asks only for the signed-in session\'s inbox', async () => {
    const request = inbox([NEWER], 1);
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={request} />);
    await screen.findByRole('listitem');

    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0][0]).toBe('/api/notifications');
  });
});

describe('AC2 - marking notifications read', () => {
  // QA-SPL-101-021 | AC2 | happy path
  it('[QA-SPL-101-021] marking one read updates that notice and the unread count', async () => {
    const request = vi.fn(async (_path: string, init?: RequestInit) => (
      init?.method === 'POST'
        ? response({ unread_count: 0 })
        : response({ notifications: [NEWER], unread_count: 1 })
    ));
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: /Mark as read/ }));

    await waitFor(() => expect(status()).toBe('0 unread'));
    expect(request).toHaveBeenCalledWith('/api/notifications/2/read', { method: 'POST' });
    expect(screen.queryByRole('button', { name: /Mark as read/ })).toBeNull();
  });

  // QA-SPL-101-022 | AC2 | happy path and boundary
  it('[QA-SPL-101-022] marking all read clears every unread notice, then the action is disabled', async () => {
    const request = inbox([NEWER, { ...OLDER, id: 3, read: false }], 2);
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={request} />);

    const markAll = await screen.findByRole('button', { name: 'Mark all as read' }) as HTMLButtonElement;
    expect(markAll.disabled).toBe(false);
    fireEvent.click(markAll);

    await waitFor(() => expect(status()).toBe('0 unread'));
    expect(request).toHaveBeenCalledWith('/api/notifications/read-all', { method: 'POST' });
    expect(screen.queryByText('Unread:', { exact: false })).toBeNull();
    expect((screen.getByRole('button', { name: 'Mark all as read' }) as HTMLButtonElement).disabled).toBe(true);
  });

  // QA-SPL-101-023 | AC2 | negative: the server refuses; nothing changes on screen
  it('[QA-SPL-101-023] a refused mark-read keeps the notice unread and says so', async () => {
    const request = vi.fn(async (_path: string, init?: RequestInit) => (
      init?.method === 'POST'
        ? response({ error: 'Notification not found.' }, 404)
        : response({ notifications: [NEWER], unread_count: 1 })
    ));
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: /Mark as read/ }));

    expect((await screen.findByRole('alert')).textContent).toBe('Notification not found.');
    expect(status()).toBe('1 unread');
    expect(screen.getByRole('button', { name: /Mark as read/ })).toBeTruthy();
  });

  // QA-SPL-101-024 | AC2 | negative: the network fails while marking all read
  it('[QA-SPL-101-024] a network failure while marking all read leaves the count unchanged', async () => {
    const request = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === 'POST') throw new TypeError('offline');
      return response({ notifications: [NEWER], unread_count: 1 });
    });
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={request} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Mark all as read' }));

    expect((await screen.findByRole('alert')).textContent).toContain("couldn't update your notifications");
    expect(status()).toBe('1 unread');
  });

  // QA-SPL-101-043 | AC2 | boundary: only the chosen notice changes
  it('[QA-SPL-101-043] marking one of two unread notices leaves the other unread', async () => {
    const second = { ...OLDER, id: 5, read: false };
    const request = vi.fn(async (_path: string, init?: RequestInit) => (
      init?.method === 'POST'
        ? response({ unread_count: 1 })
        : response({ notifications: [NEWER, second], unread_count: 2 })
    ));
    render(<Notifications accessToken="token" onNavigate={vi.fn()} request={request} />);

    const buttons = await screen.findAllByRole('button', { name: /Mark as read/ });
    fireEvent.click(buttons[0]);

    await waitFor(() => expect(status()).toBe('1 unread'));
    expect(screen.getAllByRole('button', { name: /Mark as read/ })).toHaveLength(1);
    expect(screen.getAllByRole('listitem')[1].textContent).toContain('Unread');
  });
});

describe('AC4 - opening a related record', () => {
  // QA-SPL-101-037 | AC4 | the link goes through the protected event page
  it('[QA-SPL-101-037] opens the related event through the protected event page', async () => {
    const onNavigate = vi.fn();
    render(<Notifications accessToken="token" onNavigate={onNavigate} request={inbox([NEWER], 1)} />);

    fireEvent.click(await screen.findByRole('link', { name: 'Harbour Summit' }));

    expect(onNavigate).toHaveBeenCalledWith('/workspace/assigned-events/7');
  });
});

describe('every role can reach its inbox from the workspace', () => {
  const session = {
    access_token: 'verified-token',
    user: { id: 'user-1', app_metadata: {}, user_metadata: {}, aud: 'authenticated', created_at: '' },
  } as AuthSession;
  const gateway: AuthGateway = {
    getSession: vi.fn().mockResolvedValue({ session }),
    signInWithPassword: vi.fn(),
    signOut: vi.fn(),
  };

  // QA-SPL-101-038 | AC1 | every supported role
  it.each([
    'event_organiser',
    'event_operations_manager',
    'event_coordinator',
    'venue_staff',
    'technical_support_staff',
    'attendee',
  ])('[QA-SPL-101-038] the %s workspace links to a working inbox', async role => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === '/api/session') return Promise.resolve({ ok: true });
      if (path === '/api/account/roles') return Promise.resolve(response({ roles: [role] }));
      if (path === '/api/notifications') {
        return Promise.resolve(response({ notifications: [NEWER], unread_count: 1 }));
      }
      return Promise.resolve(response({ error: 'Not found.' }, 404));
    }));
    render(<App authGateway={gateway} />);

    fireEvent.click(await screen.findByRole('link', { name: 'Notifications' }));

    expect(window.location.pathname).toBe('/workspace/notifications');
    expect(await screen.findByRole('heading', { name: 'Notifications' })).toBeTruthy();
    expect(await screen.findByText('You have been assigned to Harbour Summit.')).toBeTruthy();
  });
});

describe('AC4 - an inbox never outlives the account it was loaded for', () => {
  function sessionFor(id: string): AuthSession {
    return {
      access_token: `token-${id}`,
      user: { id, app_metadata: {}, user_metadata: {}, aud: 'authenticated', created_at: '' },
    } as AuthSession;
  }

  // QA-SPL-101-044 | AC4 | a different account with the same role is restored while the inbox is open
  it('[QA-SPL-101-044] shows the new account\'s inbox, never the previous account\'s, after a same-role account change', async () => {
    const getSession = vi.fn().mockResolvedValue({ session: sessionFor('account-a') });
    const gateway: AuthGateway = { getSession, signInWithPassword: vi.fn(), signOut: vi.fn() };
    const requested: string[] = [];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const token = String((init?.headers as Record<string, string> | undefined)?.Authorization ?? '');
      if (path === '/api/session') return Promise.resolve({ ok: true });
      if (path === '/api/account/roles') return Promise.resolve(response({ roles: ['event_coordinator'] }));
      if (path === '/api/notifications') {
        requested.push(token);
        const mine = token.includes('account-b')
          ? { ...NEWER, id: 9, message: 'You have been assigned to B Private Gala.', event: { id: 9, name: 'B Private Gala' } }
          : { ...NEWER, id: 3, message: 'You have been assigned to A Secret Summit.', event: { id: 3, name: 'A Secret Summit' } };
        return Promise.resolve(response({ notifications: [mine], unread_count: 1 }));
      }
      return Promise.resolve(response({ error: 'Not found.' }, 404));
    }));
    render(<App authGateway={gateway} />);
    fireEvent.click(await screen.findByRole('link', { name: 'Notifications' }));
    expect(await screen.findByText('You have been assigned to A Secret Summit.')).toBeTruthy();

    // Another tab signs in as account B (same role); this tab sees it on the next navigation event.
    getSession.mockResolvedValue({ session: sessionFor('account-b') });
    window.dispatchEvent(new PopStateEvent('popstate'));

    expect(await screen.findByText('You have been assigned to B Private Gala.')).toBeTruthy();
    expect(screen.queryByText('You have been assigned to A Secret Summit.')).toBeNull();
    expect(requested.length).toBe(2);
  });
});
