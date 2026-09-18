# SPL-58 — Delete a draft

Owner: Daniel Seow. Source: Jira acceptance criteria supplied by the assignee.

## Acceptance criteria

- Only the creator can delete, after a confirmation prompt.
- Only Draft requests can be deleted; submitted requests cannot.
- A deleted draft no longer appears anywhere.

## Interfaces and scope

- `DELETE /api/event-requests/drafts/<id>` returns 204 for a creator-owned draft and 404 for
  missing, other-owned or submitted requests. Cascading child equipment lines are deleted.
- The organiser request list asks for confirmation before calling DELETE and removes the deleted row.
- No automatic draft retention or purge policy is introduced.

## Verification

- API tests cover creator-only deletion, submitted guard and absence after deletion.
- Frontend test covers confirmation before delete and immediate removal from the list.
- `npm run verify` passed: 99 backend tests (one PostgreSQL skip in the quick suite),
  43 frontend tests, lint, format, typecheck and build.
- `npm run integration` passed: one test against an empty disposable PostgreSQL database.
- Browser deletion and ownership checks remain to be completed and recorded.
