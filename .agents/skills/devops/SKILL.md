---
name: devops
description: Do the DevOps step for one Jira ticket in ConnectSphere (the stage after QA passes). Use when the user invokes $devops or /devops with a ticket key such as SPL-103, and again after the user says the PR is merged. Commits, opens the PR, watches CI and fills the DEVOPS-<KEY> Confluence report from the DevOps master template with append-only conflict and failure logs.
---

# DevOps step for a ticket

The ticket key (`<KEY>`) is the argument given with the skill, for example `$devops SPL-103`.
If none was given, ask for it before doing anything else. If the user says the PR is merged,
go straight to "After merge".

Stage order: build → qa → **devops**.

Template: https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/20086804
Report title: DEVOPS-<KEY>, created in the QA space from that template.

## Before you change anything
1. Read AGENTS.md, .github/pull_request_template.md and the DevOps template,
   including its rules and hand-over checklist. Tell the user anything in them that
   conflicts with these instructions. Do not copy structure from older reports.
2. Confirm QA-<KEY> exists and passes. If not, stop and tell the user.

## Commit and PR
3. Work on the ticket's feature branch. Commit only files that belong to this ticket,
   as "<KEY>: <summary>". Never commit secrets, .env files or generated
   artifacts. Show the user the file list if anything looks unrelated.
4. Update the branch from main. If anything conflicts, stop. That includes a git
   conflict, two Alembic heads, a test that pins a shape this change extends, or
   a stacked PR whose parent merged first. Log it in the report's merge conflict
   log (exact output, files, cause, evidence) and tell the user. The user resolves it
   or approves your proposed resolution. Then add a resolution row, never edit the
   conflict row, re-run all checks and record the new CI run.
5. Run the local checks and report exact counts: lint, format, backend and
   frontend tests, typecheck, build, single Alembic head, and
   `npm run integration` on an empty disposable PostgreSQL. If anything fails,
   stop and tell the user. Never skip or weaken a check. Log each failure and its fix
   as a new row; never edit the failure row.
6. Push and open a PR against main using the PR template. State only what you
   verified.
7. Watch the PR's CI to completion. Record every run, passed, failed or
   cancelled, with run link, job links, commit and exact failing output. Fix
   failures caused by our code. Do not rerun while the Actions budget is
   UNKNOWN or critical; ask the user first.

## Jira and Confluence
8. Fill the report with real data only. Mark anything unknown until merge
   "Pending merge: <field name>". Leave no other placeholders.
9. Attach it to the ticket as a Web link, not a comment. List the existing Web
   links first so it is added exactly once. The report links back to the ticket.
10. Move the ticket to the Dev Ops column only after the PR exists and CI is green (earlier
    only if the user asks, and say so in the report).

## After merge (the user will say when)
11. Update the report. Strike through each Pending field and add the new value
    with its time, so the pre-merge text stays readable. Add the merge commit,
    main run and deploy job links and results, migration outcome, the health
    check, and confirmation the merge reached main. Add new rows to the
    append-only logs; never edit old ones. Do not run deploy.py or hosted
    migrations; deploy comes from GitHub Actions on passing main pushes.
12. Record review, merge, deployment and Jira status as four separate facts.
    Never mark the ticket Done; ask the user.

## Always
- Ask before any outward-facing action the user hasn't named: merging, force-pushing,
  changing billing or CI settings, or editing another ticket.
- End with open decisions and what is still pending, with a recommendation for
  each.
