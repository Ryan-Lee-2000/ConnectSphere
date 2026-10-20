---
name: build
description: Implement one Jira ticket in ConnectSphere (the build stage, before QA). Asks every open question before writing code, then implements, runs npm run verify and hands the branch to QA without committing.
argument-hint: <ticket key, e.g. SPL-103>
disable-model-invocation: true
---

Ticket key: $ARGUMENTS

Read `.agents/skills/build/SKILL.md` in full and follow it exactly. It is the single source of
these instructions, shared with Codex. Do not work from memory of an earlier version.
