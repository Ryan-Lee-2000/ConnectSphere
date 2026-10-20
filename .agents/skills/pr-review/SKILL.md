---
name: pr-review
description: Handle review feedback on an open ConnectSphere pull request for one Jira ticket. Use when the user invokes $pr-review or /pr-review with a ticket key and PR number, such as SPL-103 91. Lists every review comment, reproduces and fixes bugs with regression tests as new commits, updates the QA and DevOps reports append-only, and drafts replies for approval before posting.
---

# Handle PR review feedback

Arguments: the ticket key (`<KEY>`) and the pull request number (`<PR#>`), for example
`$pr-review SPL-103 91`. If either is missing, ask for it before doing anything else.

Stage order: build → qa → devops → **pr-review** (repeat for each review round) → devops
after merge.

## Before you change anything
1. Read every review, inline comment and PR comment on the PR (`gh pr view`, `gh api .../pulls/<PR#>/comments`).
   List each pointer as a numbered checklist: who said it, file and line, severity, what exactly is asked.
   Mark which ones are bugs, which are requests, and which are questions or opinions.
2. Check state and tell the user what you find: current branch and worktree, uncommitted files, whether the
   PR head is behind main, CI status on the current head, and whether anything in a comment conflicts with
   the ticket's acceptance criteria or AGENTS.md. Don't redo what already exists.
3. If a comment is ambiguous, or fixing it would change scope, behaviour or an acceptance criterion,
   stop and ask the user. Don't guess. If you disagree with a comment, say why and let the user decide.

## Fix the code
4. Work on the ticket's own branch or worktree only. Never touch another ticket's files.
5. Reproduce first. For each bug, write a regression test that fails on the current code, show the failure,
   then fix and show it pass. If the reviewer gave a reproduction, say whether you ran theirs verbatim or
   wrote an equivalent.
6. Fix only what the comments ask. No unrelated refactors. Don't weaken, skip or delete an existing test.
7. Commit as a plain new commit, message "<KEY>: <summary of the review fix>". Do not amend, squash, rebase
   or force-push without asking the user first, because that rewrites what the reviewer already saw.
   If main moved and a merge or rebase is needed, tell the user which and why, and wait for approval.
8. Run the full local checks and report exact results: lint, format, backend and frontend tests,
   typecheck, build, and the PostgreSQL integration suite on a disposable empty database
   (remove it afterwards). If anything fails, stop and tell the user. Don't skip a check.
9. Push, then watch CI to completion and report each job with its link. Don't rerun repeatedly while the
   Actions budget is UNKNOWN or critical. If a job fails and the cause is ours, fix it as a new commit.

## Merge conflicts or CI failures during this round
10. Keep the history. Do not delete the earlier problem from any report. Add a new line stating:
    what failed, the cause, what was changed, the commit that fixed it, and the new CI run link.

## Reports (Confluence QA and DevOps)
11. The QA report and the DevOps report may be updated, but the rule is append and mark, never remove:
    - Keep every earlier result, case, defect, run link and commit hash as it was.
    - Mark what is new in this round: label it "Review round <n> (<date>)" or "Added after review". Mark
      changed rows as "Changed after review" and show the earlier value beside the new one, not instead of it.
    - New test cases get new IDs. Don't renumber old ones. If an earlier statement is no longer true
      (for example "no open defects"), don't delete it. Add a dated line under it saying what changed.
    - Update the commit hash, test counts and run links as new rows or new lines, keeping the old ones
      labelled "Superseded by <new>".
    - Fill only real data. Unknown fields stay "Pending merge" with the field's name.
    - Keep the ticket-to-report and report-to-ticket links.
12. Update the PR body the same way: keep the original sections, add a "Review changes" section, and update
    the commit, test counts and CI links. Don't add anything you didn't verify.

## Replying (ask the user before each of these)
13. Draft a reply for each inline thread (what changed, commit hash, the test that covers it) and one
    summary PR comment that mentions the reviewer and lists what was not run. Show the user the drafts and
    post only after they say so. Never resolve a thread, re-request review or merge without their say.
14. Don't move or close the Jira ticket. Don't mark it Done.

## Always
- Ask before anything outward-facing the user hasn't named: posting, requesting review, merging,
  force-pushing, editing another ticket, or changing CI or billing settings.
- At the end give the user a table: each comment pointer, fixed or not, the commit and test that covers it,
  plus caveats (anything not run, anything you only partly addressed).
- Then list the open decisions and what is still pending, with a recommendation for each.
