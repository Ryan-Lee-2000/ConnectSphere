# Team and agent workflow

Sprint 0 supplies tools and conventions. It does not deliver or estimate product features.
The team chooses its smallest useful reference story and agrees its size after refinement.
Record infrastructure setup separately so first-time installation is visible in planning.

## Before implementation

Choose one assigned task. Read AGENTS.md, the authoritative requirement, current acceptance
criteria and dependencies. Record exclusions and unresolved questions. Agree any API/schema
contract with affected teammates. Do not infer a requirement from an earlier generated example.

Each developer uses their own clone, local database and ports. Start with one agent workspace
per developer. Any additional simultaneous workspace needs separate files, ports and database.
Different agent tools read the same AGENTS.md; CLAUDE.md forwards to it. Jira is deferred.

## Task handoff template

- Task ID and assigned developer
- User outcome (or infrastructure objective)
- Authoritative requirement/customer-answer links
- Acceptance criteria and illustrative test cases
- Dependencies and open questions
- In-scope changes and explicit exclusions
- Migration needs and affected interfaces
- Verification results, PR link, review and deployment status

## Delivery

1. Agree scope and estimation as a team. Keep unfinished setup and uncertainty visible.
2. Create a task branch; give the agent only the agreed work and repository instructions.
3. Implement and run focused tests, then npm run verify. Run PostgreSQL/browser checks as applicable.
4. Push a coherent change, with a PR explaining behaviour, requirements, tests and migration notes.
5. A teammate reviews the behaviour and code. Agents do not merge their own work.
6. Meet required CI checks and the team's Definition of Done. Track deployment separately.
7. Demonstrate the outcome and record review effort, rework and blockers for the retrospective.

CI and shared deployment are active: PRs run checks; passing main pushes run migrations,
deploy the selected commit and verify live health. Even a documentation merge triggers this
workflow. Review the deployment job after merging; a successful merge alone is not deployment evidence.
A local simulation must not be recorded as a passing hosted pipeline. Budget UNKNOWN means
unverified account usage; avoid optional repeated CI runs and never weaken required gates.

Repository activation follows docs/infrastructure/repository-setup.md: personal GitHub Free, private repository,
and collaborators. PR approval and passing checks are manual team rules, not enforced protections.

## Contributor responsibilities

Select one agreed story/task and read `AGENTS.md`. Create a branch named with its issue/story ID.
Keep the change small enough for a teammate to understand. Update from main before opening a PR.

Run focused tests while developing and `npm run verify` before review. Report any unrun PostgreSQL or
browser check. Use `.github/pull_request_template.md`; link acceptance criteria to test evidence.

Migrations require two named maintainers once CODEOWNERS is activated. Never rewrite a merged
migration. Use additive schema changes when the old application may still be live.

The human assignee owns the outcome of agent-assisted changes. They must be able to explain the
behaviour and review the diff. PR merged, story Done and demo deployed are distinct states.
