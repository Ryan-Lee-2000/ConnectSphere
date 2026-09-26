# SPL-53 — State equipment requirements on a request

Owner: Ranveer.

## User story

As an Event Organiser, I want to state my equipment requirements on an event request so that
Technical Support Staff know what to prepare.

## Acceptance criteria (current)

- Can add zero or more equipment lines, each with equipment type, quantity and technical notes.
- Quantity must be a positive whole number.
- Equipment type is entered as free text describing what's needed (a Technical Support Staff
  catalogue is not required at this stage — no concrete requirement for one exists yet).
- An event with no equipment lines is valid.

## What changed and why

Two things, both found during the QA pass:

1. **Genuine defect (fixed):** the live `EventRequestForm.tsx` submitted equipment lines under
   the key `equipment_lines`; the backend's `_REQUEST_FIELDS` only accepted
   `equipment_requirements`. Every real submission with equipment failed with a 400, even though
   the backend's own equipment validation was correct in isolation — nothing in the existing test
   suite exercised the real UI-to-API contract (the frontend unit test mocked the network call;
   the backend tests only ever posted hand-built payloads using the correct key). The frontend now
   sends `equipment_requirements`, matching the backend on both sides.
2. **AC correction, not a code change:** AC3 previously said equipment types "come from the types
   recorded by Technical Support Staff, plus an 'other' free-text option (proposed)". No
   Technical Support Staff catalogue exists anywhere in the system, and no concrete customer
   requirement for one does either — `Role.TECHNICAL_SUPPORT_STAFF` exists in the role enum but
   has zero routes. Rather than build a catalogue against an unconfirmed requirement, the AC was
   corrected on the Jira ticket to describe the actual, intended behaviour: equipment type is free
   text. The existing implementation already matched this; no code changed for it.

## QA

Redone end-to-end as `QA-SPL-53` (10 test cases across all 4 ACs plus one regression check, ≥2
tests per AC). All four ACs now pass — the previous QA pass recorded an overall FAIL because of
the field-name defect above; that's fixed and re-verified at `QA-SPL-53-008`. See the QA SPACE
report for the full breakdown.

**Save-draft integration, briefly:** equipment lines are replaced wholesale on every draft
save/patch and on submit (`event.equipment_requirements = [EquipmentRequirement(**line) for line
in equipment_lines]`), the same behaviour as the plain create route — there's no partial merge of
old and new lines. A draft with `equipment_requirements` omitted from a `PATCH` body keeps its
existing lines untouched (the key is only processed when present).
