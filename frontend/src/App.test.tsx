import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import type { AuthGateway, AuthSession } from './auth';
import { activeRoleStorageKey } from './roles';

const session = {
  access_token: 'verified-token',
  user: { id: 'user-1', app_metadata: {}, user_metadata: {}, aud: 'authenticated', created_at: '' },
} as AuthSession;

function gateway(overrides: Partial<AuthGateway> = {}): AuthGateway {
  return {
    getSession: vi.fn().mockResolvedValue({ session: null }),
    signInWithPassword: vi.fn().mockResolvedValue({ session, error: null }),
    signOut: vi.fn().mockResolvedValue({ error: null }),
    ...overrides,
  };
}

function verifiedSessionFetch(input: RequestInfo | URL) {
  if (String(input) === '/api/session') return Promise.resolve({ ok: true });
  if (String(input) === '/api/account/roles') return Promise.resolve({
    ok: true,
    json: async () => ({ roles: ['event_organiser'] }),
  });
  return Promise.resolve({
    ok: false,
    json: async () => ({ error: 'The venue catalogue is unavailable for this account.' }),
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, '', '/');
});

describe('sign in', () => {
  it('shows the credential form when there is no session', async () => {
    render(<App authGateway={gateway()} />);
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeTruthy();
    expect(screen.getByLabelText('Email address')).toBeTruthy();
    expect(screen.getByLabelText('Password')).toBeTruthy();
  });

  it('establishes and verifies a session before entering the workspace', async () => {
    const auth = gateway();
    vi.stubGlobal('fetch', vi.fn(verifiedSessionFetch));
    render(<App authGateway={auth} />);
    fireEvent.change(await screen.findByLabelText('Email address'), {
      target: { value: 'organiser@example.test' },
    });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'fixture-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    expect(auth.signInWithPassword).toHaveBeenCalledWith({
      email: 'organiser@example.test',
      password: 'fixture-password',
    });
    expect(fetch).toHaveBeenCalledWith('/api/session', {
      headers: { Authorization: 'Bearer verified-token' },
    });
  });

  it('uses one generic message for invalid credentials', async () => {
    const auth = gateway({
      signInWithPassword: vi.fn().mockResolvedValue({
        session: null,
        error: new Error('email not found'),
      }),
    });
    render(<App authGateway={auth} />);
    fireEvent.change(await screen.findByLabelText('Email address'), {
      target: { value: 'missing@example.test' },
    });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      "We couldn't sign you in with those credentials. Check your details and try again.",
    );
    expect(alert.textContent).not.toContain('missing@example.test');
    expect(alert.textContent).not.toContain('wrong-password');
    expect(alert.textContent).not.toContain('email not found');
  });

  it.each([
    'Event Organiser',
    'Event Operations Manager',
    'Event Coordinator',
    'Venue Staff',
    'Technical Support Staff',
    'Attendee',
  ])('uses the shared sign-in mechanism for the %s role', async role => {
    const roleSession = {
      ...session,
      user: { ...session.user, user_metadata: { role } },
    } as AuthSession;
    const auth = gateway({
      signInWithPassword: vi.fn().mockResolvedValue({ session: roleSession, error: null }),
    });
    vi.stubGlobal('fetch', vi.fn(verifiedSessionFetch));
    render(<App authGateway={auth} />);
    fireEvent.change(await screen.findByLabelText('Email address'), {
      target: { value: 'account@example.test' },
    });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'fixture-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    expect(auth.signInWithPassword).toHaveBeenCalledTimes(1);
  });
});

describe('protected access', () => {
  it('opens the Event Coordinator assigned-events route', async () => {
    vi.stubGlobal('fetch', vi.fn(input => {
      if (String(input) === '/api/session') return Promise.resolve({ ok: true });
      if (String(input) === '/api/account/roles') return Promise.resolve({
        ok: true, json: async () => ({ roles: ['event_coordinator'] }),
      });
      if (String(input) === '/api/event-requests/assigned') return Promise.resolve({
        ok: true, json: async () => ({ events: [] }),
      });
      return Promise.resolve({ ok: false, json: async () => ({}) });
    }));
    render(<App authGateway={gateway({ getSession: vi.fn().mockResolvedValue({ session }) })} />);
    fireEvent.click(await screen.findByRole('link', { name: 'My assigned events' }));
    expect(window.location.pathname).toBe('/workspace/assigned-events');
    expect(await screen.findByText('No events assigned to you yet.')).toBeTruthy();
  });

  it('opens the permanent request form from the Event Organiser workspace', async () => {
    vi.stubGlobal('fetch', vi.fn(verifiedSessionFetch));
    render(<App authGateway={gateway({ getSession: vi.fn().mockResolvedValue({ session }) })} />);

    const link = await screen.findByRole('link', { name: 'Event requests' });
    fireEvent.click(link);

    expect(window.location.pathname).toBe('/workspace/event-requests');
    expect(screen.getByRole('heading', { name: 'Request an event' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Submit event request' })).toBeTruthy();
  });

  it('does not open the organiser form for an account without that role', async () => {
    window.history.replaceState({}, '', '/workspace/event-requests');
    vi.stubGlobal('fetch', vi.fn(input => {
      if (String(input) === '/api/session') return Promise.resolve({ ok: true });
      return Promise.resolve({ ok: true, json: async () => ({ roles: ['attendee'] }) });
    }));
    render(<App authGateway={gateway({ getSession: vi.fn().mockResolvedValue({ session }) })} />);

    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    expect(window.location.pathname).toBe('/workspace');
    expect(screen.queryByRole('heading', { name: 'Request an event' })).toBeNull();
  });

  it('restores a stored session only after the server verifies it', async () => {
    vi.stubGlobal('fetch', vi.fn(verifiedSessionFetch));
    render(<App authGateway={gateway({ getSession: vi.fn().mockResolvedValue({ session }) })} />);
    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
  });

  it('does not reveal the workspace without a session', async () => {
    window.history.replaceState({}, '', '/workspace');
    render(<App authGateway={gateway()} />);
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeTruthy();
    expect(screen.queryByText('Workspace access confirmed')).toBeNull();
  });

  it('does not reveal the workspace when the server rejects a stored session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
    render(<App authGateway={gateway({ getSession: vi.fn().mockResolvedValue({ session }) })} />);
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeTruthy();
    expect(screen.queryByText('Workspace access confirmed')).toBeNull();
  });

  it('shows a service message when server verification cannot complete after sign-in', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    render(<App authGateway={gateway()} />);
    fireEvent.change(await screen.findByLabelText('Email address'), {
      target: { value: 'account@example.test' },
    });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'fixture-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain("couldn't reach the sign-in service");
    });
  });
});

describe('sign out', () => {
  it('ends the browser session and returns to sign in', async () => {
    const auth = gateway({
      getSession: vi
        .fn()
        .mockResolvedValueOnce({ session })
        .mockResolvedValue({ session: null }),
    });
    window.sessionStorage.setItem(activeRoleStorageKey(session.user.id), 'event_organiser');
    vi.stubGlobal('fetch', vi.fn(verifiedSessionFetch));
    render(<App authGateway={auth} />);

    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeTruthy();
    expect(auth.signOut).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.getItem(activeRoleStorageKey(session.user.id))).toBeNull();
    expect(window.location.pathname).toBe('/');
    expect(screen.queryByText('Workspace access confirmed')).toBeNull();

    window.history.pushState({}, '', '/workspace');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(auth.getSession).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeTruthy();
    expect(screen.queryByText('Workspace access confirmed')).toBeNull();
  });

  it('keeps the protected view and reports a failed sign-out attempt', async () => {
    const auth = gateway({
      getSession: vi.fn().mockResolvedValue({ session }),
      signOut: vi.fn().mockResolvedValue({ error: new Error('provider unavailable') }),
    });
    vi.stubGlobal('fetch', vi.fn(verifiedSessionFetch));
    render(<App authGateway={auth} />);

    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    expect(await screen.findByText("We couldn't sign you out. Please try again.")).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Sign out' }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });
});

describe('coordinator assignment', () => {
  function managerFetch(input: RequestInfo | URL) {
    const path = String(input);
    if (path === '/api/session') return Promise.resolve({ ok: true });
    if (path === '/api/account/roles') return Promise.resolve({
      ok: true,
      json: async () => ({ roles: ['event_operations_manager'] }),
    });
    if (path === '/api/event-requests/awaiting-assignment') return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ events: [], count: 0 }),
    });
    return Promise.resolve({ ok: false, status: 404, json: async () => ({ error: 'Not found.' }) });
  }

  it('gives an Event Operations Manager a way into the assignment queue', async () => {
    vi.stubGlobal('fetch', vi.fn(managerFetch));
    render(<App authGateway={gateway({ getSession: vi.fn().mockResolvedValue({ session }) })} />);

    fireEvent.click(await screen.findByRole('link', { name: 'Coordinator assignment' }));

    expect(await screen.findByRole('heading', { name: 'Events awaiting a coordinator' })).toBeTruthy();
    expect(window.location.pathname).toBe('/workspace/assignments');
  });

  it('keeps the assignment queue out of other roles’ workspaces', async () => {
    vi.stubGlobal('fetch', vi.fn(verifiedSessionFetch));
    render(<App authGateway={gateway({ getSession: vi.fn().mockResolvedValue({ session }) })} />);

    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Coordinator assignment' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Events awaiting a coordinator' })).toBeNull();
  });
});
