import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import type { AuthGateway, AuthSession } from './auth';
import { activeRoleStorageKey } from './roles';

const session = {
  access_token: 'verified-token',
  user: { id: 'multi-role-user', app_metadata: {}, user_metadata: {}, aud: 'authenticated', created_at: '' },
} as AuthSession;

function gateway(): AuthGateway {
  return {
    getSession: vi.fn().mockResolvedValue({ session }),
    signInWithPassword: vi.fn(),
    signOut: vi.fn().mockResolvedValue({ error: null }),
  };
}

function response(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response;
}

function appFetch(roles: string[], venueCanManage = true) {
  return vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === '/api/session') return Promise.resolve(response({}));
    if (path === '/api/account/roles') return Promise.resolve(response({ roles }));
    if (path === '/api/venues') {
      return Promise.resolve(response({ venues: [], capabilities: { can_manage: venueCanManage } }));
    }
    return Promise.resolve(response({ error: 'Not found' }, false));
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, '', '/');
});

describe('SPL-46 role context', () => {
  it('requires a multi-role account to select an assigned role before entering the workspace', async () => {
    const request = appFetch(['event_organiser', 'attendee']);
    vi.stubGlobal('fetch', request);
    render(<App authGateway={gateway()} />);

    expect(await screen.findByRole('heading', { name: 'Which role are you working in?' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Event Organiser/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Attendee/ })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Workspace' })).toBeNull();
    expect(request).toHaveBeenCalledWith('/api/account/roles', {
      headers: { Authorization: 'Bearer verified-token' },
    });
  });

  it('switches only between assigned roles without replacing the authenticated session', async () => {
    const auth = gateway();
    vi.stubGlobal('fetch', appFetch(['venue_staff', 'attendee']));
    render(<App authGateway={auth} />);

    fireEvent.click(await screen.findByRole('button', { name: /Venue Staff/ }));
    expect((await screen.findByRole('combobox', { name: 'Active role' }) as HTMLSelectElement).value).toBe('venue_staff');
    expect(screen.getByRole('link', { name: 'Venue catalogue' })).toBeTruthy();

    fireEvent.change(screen.getByRole('combobox', { name: 'Active role' }), {
      target: { value: 'attendee' },
    });

    expect((screen.getByRole('combobox', { name: 'Active role' }) as HTMLSelectElement).value).toBe('attendee');
    expect(screen.queryByRole('link', { name: 'Venue catalogue' })).toBeNull();
    expect(auth.signInWithPassword).not.toHaveBeenCalled();
    expect(auth.signOut).not.toHaveBeenCalled();
  });

  it('persists the active role across a refresh in the same browser session', async () => {
    window.sessionStorage.setItem(activeRoleStorageKey(session.user.id), 'attendee');
    vi.stubGlobal('fetch', appFetch(['event_organiser', 'attendee']));

    render(<App authGateway={gateway()} />);

    expect((await screen.findByRole('combobox', { name: 'Active role' }) as HTMLSelectElement).value).toBe('attendee');
    expect(screen.queryByRole('heading', { name: 'Which role are you working in?' })).toBeNull();
  });

  it('enters a single-role workspace without showing a switch control', async () => {
    vi.stubGlobal('fetch', appFetch(['technical_support_staff']));
    render(<App authGateway={gateway()} />);

    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    expect(screen.getByLabelText('Active role: Technical Support Staff')).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: 'Active role' })).toBeNull();
  });

  it('refuses an unassigned role without changing the active role', async () => {
    window.sessionStorage.setItem(activeRoleStorageKey(session.user.id), 'attendee');
    vi.stubGlobal('fetch', appFetch(['event_organiser', 'attendee']));
    render(<App authGateway={gateway()} />);

    const switcher = await screen.findByRole('combobox', { name: 'Active role' });
    fireEvent.change(switcher, { target: { value: 'venue_staff' } });

    expect((await screen.findByRole('alert')).textContent).toContain('That role is not assigned');
    expect(window.sessionStorage.getItem(activeRoleStorageKey(session.user.id))).toBe('attendee');
    expect(screen.getByText('Attendee', { selector: '.eyebrow' })).toBeTruthy();
  });

  it('redirects an unavailable direct page without changing the active role', async () => {
    window.history.replaceState({}, '', '/workspace/venues');
    window.sessionStorage.setItem(activeRoleStorageKey(session.user.id), 'attendee');
    const request = appFetch(['event_organiser', 'attendee']);
    vi.stubGlobal('fetch', request);
    render(<App authGateway={gateway()} />);

    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    await waitFor(() => expect(window.location.pathname).toBe('/workspace'));
    expect((screen.getByRole('combobox', { name: 'Active role' }) as HTMLSelectElement).value).toBe('attendee');
    expect(request).not.toHaveBeenCalledWith('/api/venues');
  });

  it('protects unsaved information until the user confirms a role switch', async () => {
    window.history.replaceState({}, '', '/workspace/venues');
    window.sessionStorage.setItem(activeRoleStorageKey(session.user.id), 'venue_staff');
    vi.stubGlobal('fetch', appFetch(['venue_staff', 'attendee']));
    render(<App authGateway={gateway()} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Create first venue' }));
    fireEvent.change(screen.getByLabelText('Venue name'), { target: { value: 'Atlas Hall' } });
    const switcher = screen.getByRole('combobox', { name: 'Active role' });
    fireEvent.change(switcher, { target: { value: 'attendee' } });

    expect(screen.getByRole('heading', { name: 'Discard unsaved venue changes?' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Stay here' }));
    expect(screen.getByDisplayValue('Atlas Hall')).toBeTruthy();
    expect((screen.getByRole('combobox', { name: 'Active role' }) as HTMLSelectElement).value).toBe('venue_staff');

    fireEvent.change(switcher, { target: { value: 'attendee' } });
    fireEvent.click(screen.getByRole('button', { name: 'Discard and switch' }));
    expect(await screen.findByRole('heading', { name: 'Workspace access confirmed' })).toBeTruthy();
    expect(screen.queryByDisplayValue('Atlas Hall')).toBeNull();
    expect(window.location.pathname).toBe('/workspace');
  });

  it('uses active-role context to hide management actions without weakening server authorization', async () => {
    window.history.replaceState({}, '', '/workspace/venues');
    window.sessionStorage.setItem(activeRoleStorageKey(session.user.id), 'event_coordinator');
    vi.stubGlobal('fetch', appFetch(['venue_staff', 'event_coordinator'], true));
    render(<App authGateway={gateway()} />);

    expect(await screen.findByRole('heading', { name: 'No venues to browse yet' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create first venue' })).toBeNull();

    fireEvent.change(screen.getByRole('combobox', { name: 'Active role' }), {
      target: { value: 'venue_staff' },
    });
    expect(await screen.findByRole('button', { name: 'Create first venue' })).toBeTruthy();
  });

  it('fails closed when trusted roles cannot be loaded', async () => {
    const request = appFetch(['attendee']);
    request.mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === '/api/session') return Promise.resolve(response({}));
      return Promise.resolve(response({ error: 'Unavailable' }, false));
    });
    vi.stubGlobal('fetch', request);
    render(<App authGateway={gateway()} />);

    expect(await screen.findByRole('heading', { name: 'Your workspace is unavailable' })).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: 'Workspace' })).toBeNull();
  });
});
