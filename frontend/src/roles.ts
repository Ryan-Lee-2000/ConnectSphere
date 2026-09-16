export const ACCOUNT_ROLES = [
  'event_organiser',
  'event_operations_manager',
  'event_coordinator',
  'venue_staff',
  'technical_support_staff',
  'attendee',
] as const;

export type AccountRole = (typeof ACCOUNT_ROLES)[number];

export const ROLE_LABELS: Record<AccountRole, string> = {
  event_organiser: 'Event Organiser',
  event_operations_manager: 'Event Operations Manager',
  event_coordinator: 'Event Coordinator',
  venue_staff: 'Venue Staff',
  technical_support_staff: 'Technical Support Staff',
  attendee: 'Attendee',
};

export const ROLE_DESCRIPTIONS: Record<AccountRole, string> = {
  event_organiser: 'Plan and follow your client organisation’s events.',
  event_operations_manager: 'Coordinate operational ownership and event delivery.',
  event_coordinator: 'Review venue information for the events you coordinate.',
  venue_staff: 'Maintain venue profiles, room layouts, and operating details.',
  technical_support_staff: 'Coordinate equipment and technical support responsibilities.',
  attendee: 'Access attendee services as they become available.',
};

export function isAccountRole(value: unknown): value is AccountRole {
  return typeof value === 'string' && ACCOUNT_ROLES.includes(value as AccountRole);
}

export function normaliseRoles(values: unknown): AccountRole[] {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.filter(isAccountRole))];
}

export function activeRoleStorageKey(userId: string) {
  return `connectsphere.active-role:${userId}`;
}

export function readActiveRole(userId: string, assignedRoles: AccountRole[]) {
  try {
    const stored = window.sessionStorage.getItem(activeRoleStorageKey(userId));
    return isAccountRole(stored) && assignedRoles.includes(stored) ? stored : null;
  } catch {
    return null;
  }
}

export function writeActiveRole(userId: string, role: AccountRole) {
  try {
    window.sessionStorage.setItem(activeRoleStorageKey(userId), role);
  } catch {
    // The in-memory role remains usable when browser storage is unavailable.
  }
}

export function clearActiveRole(userId: string) {
  try {
    window.sessionStorage.removeItem(activeRoleStorageKey(userId));
  } catch {
    // A blocked storage API must not prevent sign-out.
  }
}
