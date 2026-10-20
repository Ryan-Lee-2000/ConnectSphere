---
name: qa
description: Do QA for one Jira ticket in ConnectSphere (after build, before devops). Designs and runs the tests, records the UAT video and fills the QA-<KEY> Confluence report from the QA master template.
argument-hint: <ticket key, e.g. SPL-103>
disable-model-invocation: true
---

Ticket key: $ARGUMENTS

Read `.agents/skills/qa/SKILL.md` in full and follow it exactly. It is the single source of
these instructions, shared with Codex. Do not work from memory of an earlier version.
