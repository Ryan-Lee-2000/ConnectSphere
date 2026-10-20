---
name: qa
description: Do QA for one Jira ticket in ConnectSphere (the stage after build, before devops). Use when the user invokes $qa or /qa with a ticket key such as SPL-103. Designs and runs the tests, records the recorded UAT, and fills the QA-<KEY> Confluence report from the QA master template with append-only failure records.
---
# QA a ticket

The ticket key (`<KEY>`) is the argument given with the skill, for example `$qa SPL-103`.
If none was given, ask for it before doing anything else.

Stage order: build → **qa** → devops. Read and follow AGENTS.md first (it defines the
commands: `npm run verify`, `integration`, `check:e2e`, `e2e:record`).

Template: copy the master page
https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/pages/20086786
(QA space) to a new page QA-<KEY>. Use its sections in order and fill every one. Do not use
the old "QA-[Jira Ticket Key]" space template.

## Rules

- Report only what you measured: passed, failed, skipped, could not run, failed->fixed. Never
  present a guess as a cause; write "cause not established".
- Failure records are append-only (mandatory). Never edit, reword or delete a failure row,
  failed result, run line or original failure count. A fix is a NEW row "RE-TEST of <row ID>":
  PASS, the rectification reason, what changed (file, before/after, commit SHA), the tests
  re-run and everything sharing the changed code. Anything learned later (reviewer finding,
  re-run after a merge, new case) goes in as a dated entry, never by rewriting earlier text.
- Never weaken, skip, delete or edit an existing test without the user's approval; log every
  approved change in the Failure and change log.
- No commit, push, PR, deploy or other Jira status change until the user says so. The only
  status change this skill makes is moving the ticket from In Progress to QA in step 1; the
  ticket then stays in QA.
- Don't delete data, reset a database, or kill/restart services without asking. Use a
  disposable empty PostgreSQL database. Clean up only what you created. If another session
  holds the shared checkout, database or ports, use an isolated worktree/QA database and leave
  theirs alone.
- No secrets, passwords, tokens or personal data in the report, video, logs or screenshots.
- If an action is blocked, don't work around it: finish the rest, then stop and explain.

## 1. Setup

1. Move the ticket from In Progress to QA. If it is already in QA, leave it; if it is in any
   other status, don't move it and tell the user. Read the story, every acceptance criterion (AC), linked
   requirements, dependencies and docs/tasks. Copy each AC verbatim into the page. Flag any
   AC wording that is a team proposal or unconfirmed, and any dependency not merged.
2. Create QA-<KEY> from the master and link it to the ticket as a Web link to the Confluence
   page (a remote link, not an issue-to-issue link), never as a comment. List the existing Web
   links first so it is added exactly once. Confirm the link shows on the ticket.
3. Bring the branch level with main, then re-run migrations and setup. Re-measure every number
   after any later merge or rebase and say when it was measured.
4. Before running anything, check and tell the user what is missing: Docker and PostgreSQL,
   Supabase (all containers healthy incl. Auth), migrations applied, frontend and API running,
   the test accounts and fixtures the ticket needs, Playwright MCP connected (say up front if
   not). Fix what you can; list what you can't. Record any fixture you add.
5. Run the existing full suites once on main (this ticket's changes stashed) as the baseline.

## 2. Test design

6. Write labelled black-box (BB) and white-box (WB) cases: at least 5 per AC (happy path,
   negative, boundary, security), plus cross-cutting and PostgreSQL cases where relevant.
   Target 100% line and branch coverage of the lines this ticket added; report the figure,
   explain any gap, and say plainly if frontend coverage can't be measured. Do a red/mutation
   check: remove or break the feature and report which tests fail.
7. Fill the BB/WB count table and the traceability table (AC -> case IDs -> automated test
   name). Before executing, review the cases against each AC's exact wording ("exactly once",
   "never", "after reload", "after reassignment") and record the risk and the case added for
   each gap.

## 3. Execution

8. Run everything: unit, API, UI, the whole browser suite (not only this ticket's spec), lint,
   format, typecheck, build, and the PostgreSQL suite on a disposable empty database. Add each
   run to the Run history (date, commit SHA, scope, passed, failed, skipped/could not run).
   Never replace a failing check with a skip.

## 4. Failures

9. Tell the user about every failure. Compare with the baseline and classify:

   | Class | Meaning                                         | Action                                                                                                                                                                                                          |
   | ----- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | A     | Defect in this ticket's code                    | Fix the code, re-run, record defect and fix                                                                                                                                                                     |
   | B     | Wrong expectation in a test written for this QA | Fix it, record the correction                                                                                                                                                                                   |
   | C     | Existing test broken by another ticket's change | Find the ticket/commit; use its AC to decide if intended. Intended: the test is stale, don't edit, ask the user whether to update it here or separately. Not intended: report it as a regression in that ticket |
   | D     | Depends on an unfinished ticket                 | Mark failed: "depends on SPL-xx being completed"                                                                                                                                                                |
   | E     | Unclear cause or product decision               | Ask the user, with a recommendation                                                                                                                                                                             |

   Also fails on main without this ticket = pre-existing; don't count it against the ticket.
   Flaky tests: note them in the log with the evidence; don't re-run; fix afterwards.
10. Flag any spec that depends on exact wording, labels or layout rather than behaviour and
    suggest a sturdier locator. After the user approves a change to an existing test, make the
    smallest change that keeps its intent and re-run it plus anything sharing the code.

## 5. Recorded UAT

11. One case is the recorded manual flow on the real UI: Playwright MCP if connected, otherwise
    the repo's Playwright with video. State which in the report.
12. The video must prove each AC visibly: one scripted step per AC in the same order as the
    written steps, on-screen captions naming the AC (e.g. "AC2: mark one as read"), negative
    and access behaviour on screen (refused action, reassignment, another account's empty
    inbox). Extract frames to confirm every caption shows and nothing sensitive is visible.
    Fill the "ACs shown" table: Fully / Partly / Not, and where each unshown step is verified.

## 6. Report

13. Fill the page completely. At the top, the Executive status lists each QA run in one line,
    oldest first (e.g. "Run 1: FAIL, 1 test failed. Run 2: PASS, all pass."). No placeholders
    once a case has run. Per-case results keep a failed run and add the passing run beneath it.
    Record every defect (D1..) and observation (O1..) on the page, not as Jira bugs; also record
    assumptions, what is not covered, and anything not re-run after a later merge. Attach
    whatever evidence a result needs (error text, traces, screenshots).
14. Failure and change log: one row per failing or changed test, in the master's columns. No
    test may be changed, skipped or left failing without a row.
15. Embed or attach the video in the UAT section via Confluence attachment upload. If you can't,
    pause and ask the user to upload it. Give them three things: the QA-<KEY> page link, the
    section to put it in (Recorded UAT), and the full local path to the video file. Wait until
    they confirm it is uploaded. Do not write "video not attached" (the master template says the
    same). Then re-read the page, confirm the video is in the UAT section, update
    any text that still describes it as missing, and carry on to finish the page and the task.
16. Before finishing, re-read the page and confirm every original failure row is unchanged and
    the page is linked on the ticket.

## Exit

Don't finish while the video is still waiting to be uploaded.
Pass = every test case passes. Finish with: did everything pass (initial vs final result), and
if not why; open decisions with a recommendation each; and what is left running or created
locally (servers, databases, containers, fixtures, test data). If QA passed, the next stage is
`$devops <KEY>`.
