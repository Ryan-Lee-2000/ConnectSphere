# SPL-51 — Shared event-request backend contract

Owner: Ranveer. Implementation support: Ryan while the owner is blocked.

## User outcome

As an Event Organiser, I want to create an event request with the event's core details so that
ConnectSphere knows what I need.

## Approved acceptance criteria

- Accept event name, purpose, description, proposed date, start time, end time and expected
  attendance.
- Require name, purpose, proposed date, start time, end time and expected attendance.
- Refuse a past proposed date and a start time that is not before the end time.
- Store expected attendance once at event level as a positive whole number.
- Return the venue slots intersected by the chosen times: AM (07:00–12:00), PM
  (13:00–18:00) and Night (19:00–24:00).
- Link the request to the organiser's client organisation automatically.

## Shared schema/API contract supplied by the story owner

The additive migration creates `event_requests` and child `equipment_requirements`. It includes
nullable preference fields needed by the adjacent venue, equipment and registration stories so
those teammates can build on one table rather than create competing migrations.

`POST /api/event-requests` is restricted to Event Organisers. The server derives
`organiser_account_id` from the verified caller and creates equipment lines in the same
transaction. `GET /api/event-requests` and `GET /api/event-requests/<id>` permit Event Organisers
and Event Coordinators. Organisers see only their own requests; Coordinators see all. An Organiser
opening another Organiser's identifier receives 404.

React continues to use Supabase only for authentication. Both new tables enable RLS and revoke
all table and sequence privileges from PUBLIC, `anon` and `authenticated`; Flask owns business
access through the existing trusted-role boundary.

## Explicit limitations and follow-up

- At the time SPL-51 was delivered, the account model had no client-organisation relationship and
  `organisation_id` remained `NULL`. SPL-45 now supersedes that temporary boundary by deriving a
  required organisation from trusted account membership; request input is still never trusted.
- The only current state is `submitted`. Adding draft or workflow states requires an additive
  migration to extend the database check; this migration must never be rewritten after merge.
- The slot calculation is display-only and does not create or imply a venue booking.
- Multi-day/multi-session events, PATCH, DELETE, drafts, bookings, assignments and status
  transitions are outside this batch.
- Preference columns do not complete the later venue, equipment or registration stories; those
  stories still own their interfaces and acceptance behaviour.

Sources: SPL-51; Week 4 core #2; Q50, Q72, Q107 and Q119; schema/API handoff supplied by Ranveer.
