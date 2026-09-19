# SPL-45: View events in my client organisation

## Story

As an Event Organiser, I want to view submitted events belonging to my client organisation so
that I can stay informed about my organisation's events without accessing another client's
information.

## Implemented acceptance boundary

- Event Organisers can open **Organisation events** to see submitted events owned by their client
  organisation, including events managed by a colleague in the same organisation.
- The list shows the event name, proposed date and responsible Event Organiser.
- The read-only detail shows the approved fields: name, purpose, description, proposed date,
  start and end time, expected attendance and responsible Event Organiser.
- Drafts are excluded, regardless of who created them. The existing **My requests** view remains
  responsible for the signed-in organiser's private drafts.
- Cross-organisation and draft detail requests return the same generic `404` response and no
  protected event information.
- Account, organiser and organisation selectors supplied in query parameters or headers do not
  affect access. Flask derives membership from the verified account record.
- An organisation with no submitted events receives an empty list, not an error.

## Data and migration notes

The additive `s1_client_organisations` Alembic migration creates `organisations`, adds trusted
organisation membership and a display name to `accounts`, and converts
`event_requests.organisation_id` into a required foreign key. Existing event data is retained under
an explicit migration organisation before the constraint becomes required. The new table follows
the existing security boundary: PostgreSQL RLS is enabled and browser-role grants are revoked.

New event requests and drafts copy the organisation from the authenticated organiser's account.
The API never accepts an account, organiser or organisation identifier from the request body as
authorization evidence.

## API

- `GET /api/organisation/events` returns the approved list fields for the caller's organisation.
- `GET /api/organisation/events/<id>` returns the approved read-only detail fields when the event
  belongs to the caller's organisation and is not a draft.

The existing `/api/event-requests` routes retain their own-request and private-draft contract so
SPL-45 does not broaden the **My requests** view.

## Verification

Automated coverage is split by responsibility:

- `backend/tests/test_organisation_events.py`: organisation scope, draft exclusion, list/detail
  fields, forged selectors, empty results and access refusal.
- `frontend/src/OrganisationEvents.test.tsx`: list, direct detail, navigation, empty and refused
  states.
- `backend/tests/test_postgres.py`: migration head, RLS and browser-grant denial.

Before review, run `npm run verify`, `npm run integration` against a fresh disposable PostgreSQL
database, and the relevant authenticated browser walkthrough when the local stack is available.
