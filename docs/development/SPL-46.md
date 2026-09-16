# SPL-46: Switch between my roles without signing in again

## User outcome

As a ConnectSphere user with more than one role, I want to switch the role context presented by
the system without signing in again so that I can move between my different responsibilities using
one account.

## Acceptance criteria

- When an authenticated account has multiple assigned roles and no role is active for the current
  session, the user selects one of those roles before entering the authenticated interface.
- The interface shows which role is currently active.
- The user can switch from the active role to another role assigned to the same account without
  signing out or entering their credentials again.
- After switching, navigation entries for functions delivered by completed stories are presented
  according to the selected role's permissions.
- If the current page is unavailable to the newly selected role, the user is taken to an
  authenticated page available to that role and information from the previous role-specific page
  is no longer displayed.
- The selected role remains active during page navigation and refreshes within the current
  authenticated browser session.
- Only roles assigned to the authenticated account are available for selection.
- Attempting to select an unassigned role is refused and does not change the active role.
- Directly opening a page that is unavailable to the active role does not silently change the
  active role or display the unavailable page.
- Switching the active role does not add, remove, or otherwise change the roles assigned to the
  account.
- Switching roles does not end or replace the authenticated session.
- An account with only one assigned role enters the authenticated interface under that role and is
  not required to select or switch roles.
- If the current page contains unsaved changes, the user is warned before the role switch proceeds;
  cancelling leaves the active role, current page, and unsaved information unchanged; confirming
  completes the role switch without saving the unsaved changes.

## Security boundary

The active role is presentation context only. Assigned roles come from trusted application data,
and Flask continues to authorize business requests using the complete trusted role set established
by SPL-44. The frontend never sends the selected role as authorization evidence.

## Dependencies and exclusions

- Depends on SPL-43 authentication and SPL-44 trusted roles and reusable authorization.
- Uses the completed venue catalogue as the currently available role-specific destination.
- Does not assign, remove, or configure roles.
- Does not implement any new role-specific business function.
- Does not remember an active role across separate sign-in sessions or devices.

Source: Jira SPL-46, Q56, and the team's approved active-role presentation proposal.
