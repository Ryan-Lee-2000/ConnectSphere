import { useEffect, useId, useState, type FormEvent } from 'react';
import { createAuthGateway, type AuthGateway, type AuthSession } from './auth';
import { CoordinatorAssignmentQueue } from './CoordinatorAssignmentQueue';
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
import { OrganisationEvents } from './OrganisationEvents';
import { MyRegistrations } from './MyRegistrations';
import { AssignedEvents } from './AssignedEvents';
import { PendingBookingRequests } from './PendingBookingRequests';
import { VenueBookingReview } from './VenueBookingReview';
import { VenueOccupancyCalendarPage } from './VenueOccupancyCalendarPage';
import { EquipmentCatalogue } from './EquipmentCatalogue';
import { EquipmentRequirements } from './EquipmentRequirements';
import { EquipmentAvailability } from './EquipmentAvailability';
import { EquipmentReviewQueue } from './EquipmentReviewQueue';
import { EquipmentUnavailability } from './EquipmentUnavailability';
import { OpenEvents } from './OpenEvents';

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
  if (requestedPath === '/workspace/assignments') return role === 'event_operations_manager';
  // SPL-117. An attendee's own registrations (AC5); the server enforces ownership and role too.
  if (requestedPath === '/workspace/my-registrations') return role === 'attendee';
  if (/^\/workspace\/assigned-events\/\d+\/venue-search$/.test(requestedPath)) {
    return role === 'event_coordinator';
  }
  if (/^\/workspace\/assigned-events\/\d+\/equipment-requirements$/.test(requestedPath)) {
    return role === 'event_coordinator';
  }
  if (/^\/workspace\/assigned-events(?:\/\d+)?$/.test(requestedPath)) {
    return role === 'event_coordinator';
  }
  if (/^\/workspace\/organisation-events(?:\/\d+)?$/.test(requestedPath)) {
    return role === 'event_organiser';
  }
  // SPL-80. Venue Staff's queue of booking requests awaiting review.
  if (requestedPath === '/workspace/booking-requests') return role === 'venue_staff';
  // SPL-81. Venue Staff review and approve one venue-booking request.
  if (/^\/workspace\/venue-bookings\/\d+$/.test(requestedPath)) return role === 'venue_staff';
  // SPL-88. The operational calendar, for the three roles that schedule venues.
  if (requestedPath === '/workspace/venue-calendar') {
    return role === 'venue_staff' || role === 'event_coordinator'
      || role === 'event_operations_manager';
  }
  if (requestedPath === '/workspace/equipment-catalogue') return role === 'technical_support_staff';
  if (requestedPath === '/workspace/equipment-availability') return role === 'technical_support_staff';
  // SPL-92 AC5. The review queue is Technical Support's; the server enforces it too, so this only
  // avoids offering a page that would refuse the request.
  if (requestedPath === '/workspace/equipment-review-queue') return role === 'technical_support_staff';
  // SPL-96 AC6. Recording and restoring unavailable units is Technical Support only; the server
  // enforces it too, so this only avoids offering a page that would refuse the request.
  if (/^\/workspace\/equipment-types\/\d+\/unavailability$/.test(requestedPath)) {
    return role === 'technical_support_staff';
  }
  // SPL-115. Events open for registration, for attendees only (AC5); the server enforces it too.
  if (requestedPath === '/workspace/open-events') return role === 'attendee';
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
  const managerRole = activeRole === 'event_operations_manager';
  const technicalSupportRole = activeRole === 'technical_support_staff';
  const attendeeRole = activeRole === 'attendee';
  const organisationEventMatch = safePath.match(/^\/workspace\/organisation-events\/(\d+)$/);
  const organisationEventId = organisationEventMatch
    ? Number(organisationEventMatch[1])
    : undefined;
  const assignedEventMatch = safePath.match(/^\/workspace\/assigned-events\/(\d+)$/);
  const assignedEventId = assignedEventMatch ? Number(assignedEventMatch[1]) : undefined;
  const venueSearchMatch = safePath.match(/^\/workspace\/assigned-events\/(\d+)\/venue-search$/);
  const venueSearchEventId = venueSearchMatch ? Number(venueSearchMatch[1]) : undefined;
  const equipmentRequirementsMatch = safePath.match(/^\/workspace\/assigned-events\/(\d+)\/equipment-requirements$/);
  const equipmentRequirementsEventId = equipmentRequirementsMatch ? Number(equipmentRequirementsMatch[1]) : undefined;
  const venueBookingMatch = safePath.match(/^\/workspace\/venue-bookings\/(\d+)$/);
  const venueBookingId = venueBookingMatch ? Number(venueBookingMatch[1]) : undefined;
  // SPL-96. One equipment type's unavailable units, reached from the catalogue.
  const unavailabilityMatch = safePath.match(/^\/workspace\/equipment-types\/(\d+)\/unavailability$/);
  const unavailabilityTypeId = unavailabilityMatch ? Number(unavailabilityMatch[1]) : undefined;
  const contentLabel = safePath === '/workspace/venues'
    ? 'Venue catalogue workspace'
    : safePath === '/workspace/venue-calendar'
      ? 'Venue occupancy calendar workspace'
    : safePath === '/workspace/booking-requests'
      ? 'Booking requests workspace'
    : safePath === '/workspace/my-registrations'
      ? 'My registrations workspace'
    : safePath === '/workspace/assignments'
      ? 'Coordinator assignment workspace'
      : safePath === '/workspace/equipment-catalogue'
        ? 'Equipment catalogue workspace'
      : safePath === '/workspace/equipment-availability'
        ? 'Equipment availability workspace'
      : safePath === '/workspace/equipment-review-queue'
        ? 'Equipment review queue workspace'
      : unavailabilityTypeId !== undefined
        ? 'Equipment unavailable units workspace'
    : safePath === '/workspace/open-events'
      ? 'Open events workspace'
    : venueSearchEventId !== undefined
      ? 'Venue availability search workspace'
    : equipmentRequirementsEventId !== undefined
      ? 'Equipment requirements workspace'
    : venueBookingId !== undefined
      ? 'Venue booking review workspace'
      : safePath.startsWith('/workspace/assigned-events')
      ? 'Assigned events workspace'
      : safePath.startsWith('/workspace/organisation-events')
        ? 'Organisation event workspace'
        : safePath === '/workspace/event-requests' || safePath === '/workspace/my-requests'
          ? 'Event request workspace'
          : undefined;

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
        {managerRole && <a
          aria-current={safePath === '/workspace/assignments' ? 'page' : undefined}
          href="/workspace/assignments"
          onClick={event => { event.preventDefault(); navigate('/workspace/assignments'); }}
        >Coordinator assignment</a>}
        {activeRole === 'event_coordinator' && <a
          aria-current={safePath.startsWith('/workspace/assigned-events') ? 'page' : undefined}
          href="/workspace/assigned-events"
          onClick={event => { event.preventDefault(); navigate('/workspace/assigned-events'); }}
        >My assigned events</a>}
        {activeRole === 'venue_staff' && <a
          aria-current={safePath === '/workspace/booking-requests' ? 'page' : undefined}
          href="/workspace/booking-requests"
          onClick={event => { event.preventDefault(); navigate('/workspace/booking-requests'); }}
        >Booking requests</a>}
        {venueRole && <a
          aria-current={safePath === '/workspace/venues' ? 'page' : undefined}
          href="/workspace/venues"
          onClick={event => { event.preventDefault(); navigate('/workspace/venues'); }}
        >Venue catalogue</a>}
        {/* SPL-88: the operational calendar, for the three roles that schedule venues. */}
        {(venueRole || managerRole) && <a
          aria-current={safePath === '/workspace/venue-calendar' ? 'page' : undefined}
          href="/workspace/venue-calendar"
          onClick={event => { event.preventDefault(); navigate('/workspace/venue-calendar'); }}
        >Venue calendar</a>}
        {technicalSupportRole && <a
          aria-current={safePath === '/workspace/equipment-catalogue' ? 'page' : undefined}
          href="/workspace/equipment-catalogue"
          onClick={event => { event.preventDefault(); navigate('/workspace/equipment-catalogue'); }}
        >Equipment catalogue</a>}
        {technicalSupportRole && <a
          aria-current={safePath === '/workspace/equipment-availability' ? 'page' : undefined}
          href="/workspace/equipment-availability"
          onClick={event => { event.preventDefault(); navigate('/workspace/equipment-availability'); }}
        >Equipment availability</a>}
        {/* SPL-92: Technical Support's own queue of lines awaiting review. */}
        {technicalSupportRole && <a
          aria-current={safePath === '/workspace/equipment-review-queue' ? 'page' : undefined}
          href="/workspace/equipment-review-queue"
          onClick={event => { event.preventDefault(); navigate('/workspace/equipment-review-queue'); }}
        >Equipment review queue</a>}
        {/* SPL-115: an attendee's way into registration. */}
        {attendeeRole && <a
          aria-current={safePath === '/workspace/open-events' ? 'page' : undefined}
          href="/workspace/open-events"
          onClick={event => { event.preventDefault(); navigate('/workspace/open-events'); }}
        >Events open for registration</a>}
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
        {organiserRole && <a
          aria-current={safePath.startsWith('/workspace/organisation-events') ? 'page' : undefined}
          href="/workspace/organisation-events"
          onClick={event => { event.preventDefault(); navigate('/workspace/organisation-events'); }}
        >Organisation events</a>}
        {/* SPL-117: an attendee's own registrations, where SPL-118's withdraw control lives. */}
        {activeRole === 'attendee' && <a
          aria-current={safePath === '/workspace/my-registrations' ? 'page' : undefined}
          href="/workspace/my-registrations"
          onClick={event => { event.preventDefault(); navigate('/workspace/my-registrations'); }}
        >My registrations</a>}
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
        aria-label={contentLabel}
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
        ) : safePath.startsWith('/workspace/organisation-events') ? (
          <OrganisationEvents
            accessToken={session.access_token}
            eventId={organisationEventId}
            key={`${activeRole}:organisation-events:${organisationEventId ?? 'list'}`}
            onNavigate={navigate}
          />
        ) : safePath === '/workspace/my-registrations' ? (
          <MyRegistrations accessToken={session.access_token} key={`${activeRole}:my-registrations`} />
        ) : venueBookingId !== undefined ? (
          <VenueBookingReview
            accessToken={session.access_token}
            bookingId={venueBookingId}
            key={`${activeRole}:venue-booking:${venueBookingId}`}
          />
        ) : safePath === '/workspace/booking-requests' ? (
          // SPL-80: the queue is read-only; deciding happens on SPL-81's review page, which each
          // row opens by booking id.
          <PendingBookingRequests
            accessToken={session.access_token}
            key={`${activeRole}:booking-requests`}
            onOpen={bookingId => navigate(`/workspace/venue-bookings/${bookingId}`)}
          />
        ) : venueSearchEventId !== undefined ? (
          <AssignedEvents
            accessToken={session.access_token}
            eventId={venueSearchEventId}
            key={`${activeRole}:venue-search:${venueSearchEventId}`}
            onNavigate={navigate}
            view="venue-search"
          />
        ) : equipmentRequirementsEventId !== undefined ? (
          <EquipmentRequirements
            accessToken={session.access_token}
            eventId={equipmentRequirementsEventId}
            key={`${activeRole}:equipment-requirements:${equipmentRequirementsEventId}`}
            onNavigate={navigate}
          />
        ) : safePath.startsWith('/workspace/assigned-events') ? (
          <AssignedEvents
            accessToken={session.access_token}
            eventId={assignedEventId}
            key={`${activeRole}:assigned-events:${assignedEventId ?? 'list'}`}
            onNavigate={navigate}
          />
        ) : safePath === '/workspace/venue-calendar' ? (
          <VenueOccupancyCalendarPage
            accessToken={session.access_token}
            activeRole={activeRole}
            key={`${activeRole}:venue-calendar`}
          />
        ) : safePath === '/workspace/venues' ? (
          <VenueCatalogue
            accessToken={session.access_token}
            activeRole={activeRole}
            key={`${activeRole}:venues`}
            onUnsavedChanges={setHasUnsavedChanges}
          />
        ) : safePath === '/workspace/assignments' ? (
          <CoordinatorAssignmentQueue
            accessToken={session.access_token}
            key={`${activeRole}:assignments`}
          />
        ) : safePath === '/workspace/equipment-catalogue' ? (
          <EquipmentCatalogue accessToken={session.access_token} key={`${activeRole}:equipment-catalogue`} />
        ) : safePath === '/workspace/equipment-availability' ? (
          <EquipmentAvailability accessToken={session.access_token} key={`${activeRole}:equipment-availability`} />
        ) : safePath === '/workspace/equipment-review-queue' ? (
          <EquipmentReviewQueue accessToken={session.access_token} key={`${activeRole}:equipment-review-queue`} />
        ) : unavailabilityTypeId !== undefined ? (
          <EquipmentUnavailability
            accessToken={session.access_token}
            equipmentTypeId={unavailabilityTypeId}
            key={`${activeRole}:equipment-unavailability:${unavailabilityTypeId}`}
          />
        ) : safePath === '/workspace/open-events' ? (
          <OpenEvents accessToken={session.access_token} key={`${activeRole}:open-events`} />
        ) : (
          <>
            <p className="eyebrow">{ROLE_LABELS[activeRole]}</p>
            <h1 id="workspace-title">Workspace access confirmed</h1>
            <p>{ROLE_DESCRIPTIONS[activeRole]}</p>
            {venueRole && <p className="workspace__next-step">Use the venue catalogue to {activeRole === 'venue_staff' ? 'maintain venue information' : 'review available spaces'}.</p>}
            {managerRole && <p className="workspace__next-step">Use coordinator assignment to give submitted events an Event Coordinator.</p>}
            {attendeeRole && <p className="workspace__next-step">Use Events open for registration to find an event and register.</p>}
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
          if (verified && !window.location.pathname.startsWith('/workspace')) {
            window.history.replaceState({}, '', '/workspace');
          }
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
