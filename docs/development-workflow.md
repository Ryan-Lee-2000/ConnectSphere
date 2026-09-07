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

CI and shared deployment need repository/account activation before they can be rehearsed.
A local simulation must not be recorded as a passing hosted pipeline. Budget UNKNOWN means
unverified account usage; avoid optional repeated CI runs and never weaken required gates.

Repository activation follows docs/repository-setup.md: personal GitHub Free, private repository,
and collaborators. PR approval and passing checks are manual team rules, not enforced protections.
