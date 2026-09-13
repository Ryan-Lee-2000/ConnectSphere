import { useEffect, useId, useState, type FormEvent } from 'react';
import { createAuthGateway, type AuthGateway, type AuthSession } from './auth';

const INVALID_CREDENTIALS_MESSAGE =
  "We couldn't sign you in with those credentials. Check your details and try again.";
const SERVICE_UNAVAILABLE_MESSAGE =
  "We couldn't reach the sign-in service. Check your connection and try again.";
const SIGN_OUT_FAILURE_MESSAGE = "We couldn't sign you out. Please try again.";

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
  onAuthenticated: () => void;
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
      onAuthenticated();
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
  onSignedOut,
}: {
  authGateway: AuthGateway;
  onSignedOut: () => void;
}) {
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSignOut() {
    setError(null);
    setSigningOut(true);

    try {
      const result = await authGateway.signOut();
      if (result.error) {
        setError(SIGN_OUT_FAILURE_MESSAGE);
        return;
      }
      window.history.replaceState({}, '', '/');
      onSignedOut();
    } catch {
      setError(SIGN_OUT_FAILURE_MESSAGE);
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <main className="workspace">
      <header className="workspace__header">
        <Brand />
        <button
          className="button button--secondary"
          disabled={signingOut}
          onClick={() => void handleSignOut()}
          type="button"
        >
          {signingOut ? 'Signing out…' : 'Sign out'}
        </button>
      </header>
      <section className="workspace__content" aria-labelledby="workspace-title">
        <p className="eyebrow">Secure session</p>
        <h1 id="workspace-title">Workspace access confirmed</h1>
        <p>Your session has been verified. Role-specific tools will appear here as they are delivered.</p>
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

  useEffect(() => {
    document.title = view === 'workspace' ? 'Workspace | ConnectSphere' : 'Sign in | ConnectSphere';
  }, [view]);

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      try {
        const { session } = await authGateway.getSession();
        const verified = session ? await verifySession(session) : false;
        if (active) setView(verified ? 'workspace' : 'sign-in');
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
  if (view === 'workspace') {
    return <Workspace authGateway={authGateway} onSignedOut={() => setView('sign-in')} />;
  }
  return <SignIn authGateway={authGateway} onAuthenticated={() => setView('workspace')} />;
}
