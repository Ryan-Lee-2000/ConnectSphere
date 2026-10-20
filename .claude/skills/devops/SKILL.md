---
name: devops
description: Do the DevOps step for one Jira ticket in ConnectSphere (after QA passes, and again after the PR is merged). Commits, opens the PR, watches CI and fills the DEVOPS-<KEY> Confluence report from the DevOps master template.
argument-hint: <ticket key, e.g. SPL-103> [merged]
disable-model-invocation: true
---

Ticket key and any note (for example "merged"): $ARGUMENTS

Read `.agents/skills/devops/SKILL.md` in full and follow it exactly. It is the single source of
these instructions, shared with Codex. Do not work from memory of an earlier version.
