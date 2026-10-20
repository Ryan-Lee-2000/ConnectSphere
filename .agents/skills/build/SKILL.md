---
name: build
description: Implement one Jira ticket in ConnectSphere (the build stage, before QA). Use when the user invokes $build or /build with a ticket key such as SPL-103. Asks every open question before writing code, then implements, runs npm run verify and hands the branch to QA without committing.
---

# Build a ticket

The ticket key (`<KEY>`) is the argument given with the skill, for example `$build SPL-103`.
If none was given, ask for it before doing anything else.

Stage order: **build** → qa → devops. This skill ends when the branch is ready for QA.

## Orient first
1. Read the ticket in Jira: the story, every acceptance criterion (AC), comments and
   dependencies. Read AGENTS.md, README.md, docs/architecture.md, docs/requirements.md
   and the task file for this ticket. For frontend work, also read PRODUCT.md and
   DESIGN.md and use the DESIGN.md tokens.
2. Read the existing code closest to this change and match its structure, naming and
   style.
3. Check the working state: current branch, uncommitted changes, and whether a branch
   or PR for this ticket already exists. Don't overwrite unrelated work.
4. Create a separate feature branch for this ticket, named with its key
   (for example `feature/SPL-103-short-description`).

## Resolve all questions before building
5. Restate the ACs as a short checklist: what you will build for each, what is out of
   scope, and every ambiguity, assumption or decision that could change behaviour,
   data, permissions or the UI. For each question, give your recommendation.
6. Stop here and wait for the user's answers. Do not write any code until every question
   has been answered.
7. If answers raise new questions, ask them and wait again. Repeat until nothing is
   open. Then confirm in one line that there are no open questions and begin building.
8. Once building starts, don't raise new questions. If something unexpected comes up
   that genuinely needs the user's decision, stop and ask before continuing; otherwise
   follow the answers already given and the project's rules.

## Build
9. Move the ticket from To Do to In Progress on the Jira board. This is the only status change
   this skill makes. If the ticket is already In Progress, leave it; if it is in any other
   status, don't move it and tell the user.
10. Implement only this ticket. Don't change scope, ACs or estimates, and don't pick up
    other work.
11. Follow the project's rules:
    - React calls Supabase only for auth; business records go through Flask.
    - Never trust a submitted user, role or organisation id; the server decides
      identity and permissions from the session.
    - Deny by default until access is explicitly allowed.
    - Database changes go in a new Alembic migration. Never edit a merged one. New
      tables get row-level security and no browser grants.
    - Related writes share one transaction.
    - No secrets in Git, and never disable auth to make something work.
12. Handle edge cases as you build: empty, loading and error states, retries and
    duplicates, malformed or out-of-range input, and access after a state change.
13. Keep changes small and coherent. No unrelated refactors, new dependencies or paid
    services. Comment only where necessary, briefly: name the AC a non-obvious rule enforces
    (`# AC2: ...`) or explain a reason the code can't show. No other comments.

## Check and hand off
14. Run `npm run verify` and make sure the existing suites still pass.
15. Writing the new test suite is the QA step, so don't write one here. Don't change
    any existing test without consulting the user first to confirm the change is
    necessary.
16. Don't commit, push or open a PR.
17. Finish with a response that has no open questions. It should contain only:
    - Each AC that was tackled, and where it is implemented (file and function).
    - Anything intentionally left out of scope.
    - The files changed.
    - The verify result.
    - Migration notes.
    - The decisions that were made during the work, including the answers the user gave.

    The branch is then ready for QA (`$qa <KEY>`).
