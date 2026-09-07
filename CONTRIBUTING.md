# Contributing

Select one agreed story/task and read `AGENTS.md`. Create a branch named with its issue/story ID.
Keep the change small enough for a teammate to understand. Update from main before opening a PR.

Run focused tests while developing and `npm run verify` before review. Report any unrun PostgreSQL or
browser check. Use `.github/pull_request_template.md`; link acceptance criteria to test evidence.

Migrations require two named maintainers once CODEOWNERS is activated. Never rewrite a merged
migration. Use additive schema changes when the old application may still be live.

The human assignee owns the outcome of agent-assisted changes. They must be able to explain the
behaviour and review the diff. PR merged, story Done and demo deployed are distinct states.
