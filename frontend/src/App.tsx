import { useEffect, useId, useState, type FormEvent } from 'react';
import { createAuthGateway, type AuthGateway, type AuthSession } from './auth';
import {
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  clearActiveRole,
  isAccountRole,
  normaliseRoles,
  readActiveRole,
  writeActiveRole,
  type AccountRole,
} from './roles';
import { EventRequestForm } from './EventRequestForm';
import { VenueCatalogue } from './VenueCatalogue';
import { EventRequestDrafts } from './EventRequestDrafts';

const INVALID_CREDENTIALS_MESSAGE =
  "We couldn't sign you in with those credentials. Check your details and try again.";
const SERVICE_UNAVAILABLE_MESSAGE =
  "We couldn't reach the sign-in service. Check your connection and try again.";
const SIGN_OUT_FAILURE_MESSAGE = "We couldn't sign you out. Please try again.";
const ROLE_LOAD_FAILURE_MESSAGE =
  "We couldn't load your assigned roles. Refresh the page or try signing in again.";
const INVALID_ROLE_MESSAGE = 'That role is not assigned to this account.';

type View = 'checking' | 'sign-in' | 'workspace';

interface AppProps {
  authGateway?: AuthGateway;
}

const defaultAuthGateway = createAuthGateway();

async function verifySession(session: AuthSession): Promise<boolean> {
  const response = await fetch('/api/session', {
    headers: { Authorization: `Bearer ${session.access_token}` },
  });
  return response.ok;
}

function roleCanAccessPath(role: AccountRole, requestedPath: string) {
  if (requestedPath === '/workspace') return true;
  if (requestedPath === '/workspace/event-requests') return role === 'event_organiser';
  // CS-E07-S1. An organiser's own requests; every other role is refused here, including the
  // coordinator, who reads requests through their own story rather than this view.
  if (requestedPath === '/workspace/my-requests') return role === 'event_organiser';
  return requestedPath === '/workspace/venues'
    && (role === 'venue_staff' || role === 'event_coordinator');
}

function Brand() {
  return (
    <div className="brand" aria-label="ConnectSphere">
      <svg className="brand__mark" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M7 8.5 16 3l9 5.5v10L16 24l-9-5.5z" />
        <path d="m7 18.5 9 5.5 9-5.5V24l-9 5-9-5z" />
        <circle cx="16" cy="13.5" r="2.25" />
      </svg>
      <span>ConnectSphere</span>
    </div>
  );
}

function AtlasPanel() {
  return (
    <section className="atlas" aria-labelledby="atlas-title">
      <Brand />
      <div className="atlas__copy">
        <p className="eyebrow">Secure event operations</p>
        <h2 id="atlas-title">One clear route from request to event.</h2>
        <p>Coordinate people, places, and resources from a shared operational view.</p>
      </div>
      <ol className="atlas__legend" aria-label="Event delivery stages">
        <li><span>01</span> Plan</li>
        <li><span>02</span> Coordinate</li>
        <li><span>03</span> Deliver</li>
      </ol>
    </section>
  );
}

function SessionCheck() {
  return (
    <main className="auth-layout">
      <AtlasPanel />
      <section className="session-check" aria-live="polite" aria-busy="true">
        <div className="session-check__line session-check__line--short" />
        <div className="session-check__line" />
        <div className="session-check__field" />
        <div className="session-check__field" />
        <p>Checking your secure session…</p>
      </section>
    </main>
  );
}

function SignIn({
  authGateway,
  onAuthenticated,
}: {
  authGateway: AuthGateway;
  onAuthenticated: (session: AuthSession) => void;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const errorId = useId();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const result = await authGateway.signInWithPassword({ email: email.trim(), password });
      if (result.error || !result.session) {
        setError(INVALID_CREDENTIALS_MESSAGE);
        return;
      }
      if (!(await verifySession(result.session))) {
        setError(SERVICE_UNAVAILABLE_MESSAGE);
        return;
      }
      window.history.replaceState({}, '', '/workspace');
      onAuthenticated(result.session);
    } catch {
      setError(SERVICE_UNAVAILABLE_MESSAGE);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-layout">
      <AtlasPanel />
      <section className="sign-in" aria-labelledby="sign-in-title">
        <div className="sign-in__content">
          <p className="eyebrow">Protected workspace</p>
          <h1 id="sign-in-title">Welcome back</h1>
          <p className="sign-in__intro">Sign in to continue to your workspace.</p>

          <form className="sign-in__form" onSubmit={handleSubmit}>
            {error && (
              <div className="form-message form-message--error" id={errorId} role="alert">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 7v6M12 17h.01" />
                </svg>
                <span>{error}</span>
              </div>
            )}

            <div className="field">
              <label htmlFor="email">Email address</label>
              <input
                autoComplete="email"
                id="email"
                inputMode="email"
                name="email"
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
                aria-describedby={error ? errorId : undefined}
              />
            </div>

            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                autoComplete="current-password"
                id="password"
                name="password"
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
                aria-describedby={error ? errorId : undefined}
              />
            </div>

            <button className="button button--primary" disabled={submitting} type="submit">
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}

function Workspace({
  authGateway,
  session,
  onSignedOut,
}: {
  authGateway: AuthGateway;
  session: AuthSession;
  onSignedOut: () => void;
}) {
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [roles, setRoles] = useState<AccountRole[] | null>(null);
  const [activeRole, setActiveRole] = useState<AccountRole | null>(null);
  const [roleError, setRoleError] = useState<string | null>(null);
  const [pendingRole, setPendingRole] = useState<AccountRole | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    let active = true;

    async function loadRoles() {
      try {
        const response = await fetch('/api/account/roles', {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!response.ok) throw new Error('role lookup failed');
        const body = await response.json() as { roles?: unknown };
        const assignedRoles = normaliseRoles(body.roles);
        if (assignedRoles.length === 0) throw new Error('no supported roles');
        if (!active) return;
        setRoles(assignedRoles);
        setActiveRole(
          assignedRoles.length === 1
            ? assignedRoles[0]
            : readActiveRole(session.user.id, assignedRoles),
        );
      } catch {
        if (active) setRoleError(ROLE_LOAD_FAILURE_MESSAGE);
      }
    }

    function handleNavigation() {
      setPath(window.location.pathname);
    }

    void loadRoles();
    window.addEventListener('popstate', handleNavigation);
    return () => {
      active = false;
      window.removeEventListener('popstate', handleNavigation);
    };
  }, [session.access_token, session.user.id]);

  const navigate = (nextPath: string, replace = false) => {
    window.history[replace ? 'replaceState' : 'pushState']({}, '', nextPath);
    setPath(nextPath);
    setHasUnsavedChanges(false);
    setPendingRole(null);
  };

  useEffect(() => {
    if (activeRole && !roleCanAccessPath(activeRole, path)) {
      window.history.replaceState({}, '', '/workspace');
      setPath('/workspace');
    }
  }, [activeRole, path]);

  const commitRole = (role: AccountRole) => {
    writeActiveRole(session.user.id, role);
    setActiveRole(role);
    setPendingRole(null);
    setHasUnsavedChanges(false);
    setRoleError(null);
    if (!roleCanAccessPath(role, path)) navigate('/workspace', true);
  };

  const requestRoleSwitch = (value: string) => {
    if (!isAccountRole(value) || !roles?.includes(value)) {
      setRoleError(INVALID_ROLE_MESSAGE);
      return;
    }
    if (value === activeRole) return;
    setRoleError(null);
    if (hasUnsavedChanges) {
      setPendingRole(value);
      return;
    }
    commitRole(value);
  };

  async function handleSignOut() {
    setError(null);
    setSigningOut(true);

    try {
      const result = await authGateway.signOut();
      if (result.error) {
        setError(SIGN_OUT_FAILURE_MESSAGE);
        return;
      }
      clearActiveRole(session.user.id);
      window.history.replaceState({}, '', '/');
      onSignedOut();
    } catch {
      setError(SIGN_OUT_FAILURE_MESSAGE);
    } finally {
      setSigningOut(false);
    }
  }

  if (!roles) {
    return (
      <main className="workspace">
        <header className="workspace__header">
          <Brand />
          <button className="button button--secondary" onClick={() => void handleSignOut()} type="button">
            Sign out
          </button>
        </header>
        <section className="workspace__content role-loading" aria-busy={!roleError} aria-live="polite">
          <p className="eyebrow">Account roles</p>
          <h1>{roleError ? 'Your workspace is unavailable' : 'Preparing your workspace'}</h1>
          {roleError ? (
            <div className="form-message form-message--error workspace__message" role="alert">
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v6M12 17h.01" /></svg>
              <span>{roleError}</span>
            </div>
          ) : <p>Loading the roles assigned to your account…</p>}
        </section>
      </main>
    );
  }

  if (!activeRole) {
    return (
      <main className="workspace">
        <header className="workspace__header">
          <Brand />
          <button className="button button--secondary" onClick={() => void handleSignOut()} type="button">
            Sign out
          </button>
        </header>
        <section className="role-choice" aria-labelledby="role-choice-title">
          <p className="eyebrow">Choose your workspace</p>
          <h1 id="role-choice-title">Which role are you working in?</h1>
          <p>Select one of your assigned roles. You can switch roles later without signing in again.</p>
          <div className="role-choice__options">
            {roles.map(role => (
              <button className="role-choice__option" key={role} onClick={() => commitRole(role)} type="button">
                <strong>{ROLE_LABELS[role]}</strong>
                <span>{ROLE_DESCRIPTIONS[role]}</span>
              </button>
            ))}
          </div>
        </section>
      </main>
    );
  }

  const safePath = roleCanAccessPath(activeRole, path) ? path : '/workspace';
  const venueRole = activeRole === 'venue_staff' || activeRole === 'event_coordinator';
  const organiserRole = activeRole === 'event_organiser';

  return (
    <main className="workspace">
      <header className="workspace__header">
        <Brand />
        <div className="workspace__account">
          {roles.length > 1 ? (
            <label className="role-switcher">
              <span>Active role</span>
              <select
                aria-describedby={roleError ? 'role-switch-error' : undefined}
                onChange={event => requestRoleSwitch(event.target.value)}
                value={activeRole}
              >
                {roles.map(role => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
              </select>
            </label>
          ) : (
            <div className="active-role" aria-label={`Active role: ${ROLE_LABELS[activeRole]}`}>
              <span>Active role</span>
              <strong>{ROLE_LABELS[activeRole]}</strong>
            </div>
          )}
          <button
            className="button button--secondary"
            disabled={signingOut}
            onClick={() => void handleSignOut()}
            type="button"
          >
            {signingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      </header>
      <nav className="workspace__nav" aria-label="Workspace">
        <a
          aria-current={safePath === '/workspace' ? 'page' : undefined}
          href="/workspace"
          onClick={event => { event.preventDefault(); navigate('/workspace'); }}
        >Overview</a>
        {venueRole && <a
          aria-current={safePath === '/workspace/venues' ? 'page' : undefined}
          href="/workspace/venues"
          onClick={event => { event.preventDefault(); navigate('/workspace/venues'); }}
        >Venue catalogue</a>}
        {organiserRole && <a
          aria-current={safePath === '/workspace/event-requests' ? 'page' : undefined}
          href="/workspace/event-requests"
          onClick={event => { event.preventDefault(); navigate('/workspace/event-requests'); }}
        >Event requests</a>}
        {organiserRole && <a
          aria-current={safePath === '/workspace/my-requests' ? 'page' : undefined}
          href="/workspace/my-requests"
          onClick={event => { event.preventDefault(); navigate('/workspace/my-requests'); }}
        >My requests</a>}
      </nav>
      {pendingRole && (
        <section className="role-switch-warning" aria-labelledby="role-switch-warning-title" role="alert">
          <div>
            <h2 id="role-switch-warning-title">Discard unsaved changes?</h2>
            <p>Switching to {ROLE_LABELS[pendingRole]} will leave this page without saving your changes.</p>
          </div>
          <div className="role-switch-warning__actions">
            <button className="button button--secondary" onClick={() => setPendingRole(null)} type="button">Stay here</button>
            <button className="button button--primary" onClick={() => commitRole(pendingRole)} type="button">Discard and switch</button>
          </div>
        </section>
      )}
      {roleError && roleError !== ROLE_LOAD_FAILURE_MESSAGE && (
        <p className="role-error" id="role-switch-error" role="alert">{roleError}</p>
      )}
      <section
        className="workspace__content"
        aria-label={safePath === '/workspace/venues' ? 'Venue catalogue workspace' : safePath === '/workspace/event-requests' || safePath === '/workspace/my-requests' ? 'Event request workspace' : undefined}
        aria-labelledby={safePath === '/workspace' ? 'workspace-title' : undefined}
      >
        {safePath === '/workspace/event-requests' ? (
          <EventRequestForm
            accessToken={session.access_token}
            key={`${activeRole}:event-requests`}
            onUnsavedChanges={setHasUnsavedChanges}
            onSubmitted={() => navigate('/workspace/my-requests')}
          />
        ) : safePath === '/workspace/my-requests' ? (
          <EventRequestDrafts
            accessToken={session.access_token}
            key={`${activeRole}:my-requests`}
            onUnsavedChanges={setHasUnsavedChanges}
          />
        ) : safePath === '/workspace/venues' ? (
          <VenueCatalogue
            accessToken={session.access_token}
            activeRole={activeRole}
            key={`${activeRole}:venues`}
            onUnsavedChanges={setHasUnsavedChanges}
          />
        ) : (
          <>
            <p className="eyebrow">{ROLE_LABELS[activeRole]}</p>
            <h1 id="workspace-title">Workspace access confirmed</h1>
            <p>{ROLE_DESCRIPTIONS[activeRole]}</p>
            {venueRole && <p className="workspace__next-step">Use the venue catalogue to {activeRole === 'venue_staff' ? 'maintain venue information' : 'review available spaces'}.</p>}
          </>
        )}
        {error && (
          <div className="form-message form-message--error workspace__message" role="alert">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v6M12 17h.01" />
            </svg>
            <span>{error}</span>
          </div>
        )}
      </section>
    </main>
  );
}

export function App({ authGateway = defaultAuthGateway }: AppProps) {
  const [view, setView] = useState<View>('checking');
  const [session, setSession] = useState<AuthSession | null>(null);

  useEffect(() => {
    document.title = view === 'workspace' ? 'Workspace | ConnectSphere' : 'Sign in | ConnectSphere';
  }, [view]);

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      try {
        const { session } = await authGateway.getSession();
        const verified = session ? await verifySession(session) : false;
        if (active) {
          setSession(verified ? session : null);
          setView(verified ? 'workspace' : 'sign-in');
        }
      } catch {
        if (active) setView('sign-in');
      }
    }

    function handleNavigation() {
      void restoreSession();
    }

    void restoreSession();
    window.addEventListener('popstate', handleNavigation);
    return () => {
      active = false;
      window.removeEventListener('popstate', handleNavigation);
    };
  }, [authGateway]);

  if (view === 'checking') return <SessionCheck />;
  if (view === 'workspace' && session) {
    return <Workspace authGateway={authGateway} session={session} onSignedOut={() => {
      setSession(null);
      setView('sign-in');
    }} />;
  }
  return <SignIn authGateway={authGateway} onAuthenticated={nextSession => {
    setSession(nextSession);
    setView('workspace');
  }} />;
}
