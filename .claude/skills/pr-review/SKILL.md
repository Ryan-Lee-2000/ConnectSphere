---
name: pr-review
description: Handle review feedback on an open ConnectSphere pull request for one Jira ticket. Fixes bugs with regression tests as new commits, updates the QA and DevOps reports append-only, and drafts replies for approval before posting.
argument-hint: <ticket key> <PR number>, e.g. SPL-103 91
disable-model-invocation: true
---

Ticket key and PR number: $ARGUMENTS

Read `.agents/skills/pr-review/SKILL.md` in full and follow it exactly. It is the single source of
these instructions, shared with Codex. Do not work from memory of an earlier version.
