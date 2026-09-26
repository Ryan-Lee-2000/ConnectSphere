# SPL-54 — Indicate registration needs on a request

Owner: Ranveer.

## User story

As an Event Organiser, I want to indicate whether my event needs attendee registration so that
registration can be set up if required.

## Acceptance criteria (current, unchanged this pass)

- Can indicate registration required: yes or no; default no.
- If yes, can enter free-text registration notes (e.g. information to collect).
- The indication is visible to the Event Coordinator so registration can be enabled later.

## What changed and why

No code or AC changes were needed here — this story's implementation already matched its ACs.
This pass was a QA redo only: confirmed `registration_required` defaults to `false` when omitted,
confirmed notes are stored verbatim only when required is `true` and are not force-cleared when
it's `false`, and confirmed an Event Coordinator sees identical `registration_required`/
`registration_notes` values to the organiser who created the request.

## QA

Redone end-to-end as `QA-SPL-54` (7 test cases across all 3 ACs, ≥2 per AC). All three ACs pass
with no defects. See the QA SPACE report for the full breakdown and cited automated tests
(`backend/tests/test_event_requests.py`, `backend/tests/test_qa_spl51_54.py`,
`frontend/src/EventRequestForm.test.tsx`).

**Save-draft integration, briefly:** `registration_required`/`registration_notes` pass through
`_draft_attributes()` the same as on the plain create route — a draft can be saved with
registration left unset (defaults to `false`, notes `null`) and both fields survive a
reopen/resave/submit cycle unchanged unless the organiser edits them.
