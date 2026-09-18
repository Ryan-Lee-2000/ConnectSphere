# SPL-57 — Reopen a saved draft

Owner: Daniel Seow. Source: Jira acceptance criteria supplied by the assignee.

## Acceptance criteria

- Drafts are listed separately and labelled to distinguish them from submitted requests.
- All fields remain editable and the draft can be saved again.
- The draft can be submitted directly, applying the normal complete-request rules.
- The last-saved time is shown.

## Interfaces and scope

- Uses SPL-56's draft entity and creator-only read scope.
- `PATCH /api/event-requests/drafts/<id>` resaves a creator-owned draft.
- `POST /api/event-requests/drafts/<id>/submit` validates the complete submitted-request shape and
  changes status on the same request ID. Incomplete drafts remain drafts on validation failure.
- `last_saved_at` is set by the server and returned in reads. The organiser UI has separate draft
  and submitted sections, and one form for new and reopened requests.
- No coordinator assignment or notification flow is added here.

## Verification

- API tests cover resave, last-saved timestamp, failed incomplete submission and successful submission.
- Frontend tests cover draft reopen, resave and submission.
- `npm run verify` passed: 99 backend tests (one PostgreSQL skip in the quick suite),
  43 frontend tests, lint, format, typecheck and build.
- `npm run integration` passed: one test against an empty disposable PostgreSQL database.
- Browser draft-submission checks remain to be completed and recorded.
