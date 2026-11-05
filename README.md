# ConnectSphere

ConnectSphere is Team T3's IS212 Software Project Management project for coordinating event
requests, venue bookings, equipment, safety reviews, attendee registration and notifications. The monorepo contains a React/TypeScript frontend,
a Flask API, and PostgreSQL data managed through SQLAlchemy and Alembic. Supabase provides
authentication; business operations go through the API.

- [Getting started](#getting-started)
- [Exploring the application](#exploring-the-application)
- [Development commands](#development-commands)
- [Project links and access](#project-links-and-access)
- [Submission guide](#submission-guide)
- [Team process](#team-process)
- [Repository structure](#repository-structure)

## Getting started

To run ConnectSphere locally, you need the source code, an internet connection for the first
setup, and the prerequisites below. Setup creates the local database and demo accounts; no hosted service credentials or manual database configuration
are required.

### 1. Install prerequisites

| Install | Required action |
| --- | --- |
| [Git](https://git-scm.com/downloads) | Required by the setup prerequisite check, including when using a source ZIP. |
| [Node.js 24](https://nodejs.org/en/download) | Choose version **24**; it includes npm. Node 22 will be rejected by the launcher. |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Install uv; setup uses it to obtain Python and the backend dependencies. |
| [Docker Desktop](https://docs.docker.com/desktop/) | Install for your operating system, open it and wait for the engine to be running. Use Linux containers on Windows. |

Reopen PowerShell (Windows) or Terminal (macOS) after installation. On Windows, Docker needs
[a supported Linux-container backend](https://docs.docker.com/desktop/setup/install/windows-install/);
project commands run directly in PowerShell. On macOS, choose the installer for your Mac's
Apple Silicon or Intel processor. WSL and Make are optional.

No separate Python, pnpm, Corepack or Supabase CLI installation is required: uv supplies Python
3.13, and npm obtains pnpm 10.15.1. See [Keeping Node 22](#keeping-node-22-for-another-project)
if another project needs that version.

### 2. Open the source folder

**From a source ZIP:** extract it first, then open a terminal in the extracted directory
containing `package.json`, `README.md`, `backend/` and `frontend/`. Do not run commands inside
the ZIP or from its parent directory.

**From GitHub:** accept the repository access invitation, then run:

```sh
git clone --branch main https://github.com/Ryan-Lee-2000/ConnectSphere.git
cd ConnectSphere
```

If GitHub reports “Repository not found”, ask the team to confirm access for your GitHub account,
or use a source ZIP provided by the team.

### 3. Set up and start

Run these commands **one at a time** from the source folder. Continue only after each command
succeeds. First setup downloads dependencies and Docker images, so allow it to finish.

**Windows — PowerShell:**

```powershell
npm.cmd run doctor
npm.cmd run setup
npm.cmd start
```

**macOS — Terminal:**

```sh
npm run doctor
npm run setup
npm start
```

`doctor` checks prerequisites. `setup` installs dependencies, starts local Supabase, creates the
local environment files, applies database migrations and seeds demo accounts and sample venues.
It should finish with **“Setup complete. Run npm start, then open http://127.0.0.1:5173.”**
`start` runs the API and frontend together. **Keep that terminal open while using the application.**

With the default local configuration, notification emails are captured in
[Mailpit](http://127.0.0.1:54324) and are not sent externally. Setup writes the required email
settings; no Gmail credentials are needed for a fresh local installation.

### 4. Open the application and sign in

Open **[http://127.0.0.1:5173](http://127.0.0.1:5173)** in your browser. You should see the
ConnectSphere sign-in screen. A fresh local setup creates eight accounts covering all seven
application roles:

| Role | Email | Password |
| --- | --- | --- |
| Event Coordinator | `event.coordinator@example.test` | `LocalDemo123!` |
| Venue Staff | `venue.staff@example.test` | `LocalDemo123!` |
| Event Organiser / Attendee | `developer@example.test` | `LocalDemo123!` |
| Event Coordinator Lead | `operations.manager@example.test` | `LocalDemo123!` |
| Technical Support Staff | `technical.support@example.test` | `LocalDemo123!` |
| Safety Officer | `safety.officer@example.test` | `LocalDemo123!` |
| Attendee only | `attendee@example.test` | `LocalDemo123!` |
| Event Coordinator — second account for reassignment | `qa.coordinator.b@example.test` | `LocalDemo123!` |

These are fake **local-only** fixtures from [scripts/seed.py](scripts/seed.py); they are not
credentials for the hosted demo. For the Organiser/Attendee account, select the Event Organiser
role to explore event requests.

Use the attendee-only account to test registration without organiser privileges. The second
coordinator account supports assignment and reassignment walkthroughs. The Lead account retains
its original `operations.manager@example.test` email but appears as **Event Coordinator Lead**.
Rerunning setup creates missing accounts; it does not reset passwords on existing accounts.

**Try the venue catalogue:** sign in as the Event Coordinator,
open **Venue catalogue**, and select **Harbour Hall**. On a fresh database, setup provides five
sample venues. Check the venue details and layouts; the coordinator's catalogue is read-only.
Sign out before signing in as Venue Staff to explore catalogue maintenance, or as the Event
Organiser to try [event requests and drafts](#exploring-the-application).

### 5. Stop, restart or troubleshoot

- **Stop:** press `Ctrl+C` in the running terminal, then run `npm.cmd run stop` on Windows or
  `npm run stop` on macOS. If Windows asks `Terminate batch job (Y/N)?`, enter `Y`.
- **Restart later:** open Docker Desktop, return to the source folder, run `setup`, then `start`
  using the same commands above. Setup preserves existing local data; it does not reset your work.
- **Setup fails or the page does not load:** check that Node is version 24 and Docker is running,
  then follow [Troubleshooting](#troubleshooting). Keep the failing command and error message for
  the team. Do not proceed past a failed setup.
- **Run automated checks:** use `npm.cmd run verify` on Windows or `npm run verify` on macOS.
  See [Development commands](#development-commands) and the [PostgreSQL integration gate](#postgresql-integration-gate)
  for browser and database checks with additional prerequisites.

The [hosted demo](https://connectsphere-mmay.onrender.com) is a separate option; role-specific
hosted access must be supplied by the team. The local instructions above are the reproducible
route for running your local copy of the source.

## Exploring the application

Use the local accounts above to explore different roles. Sign out before switching accounts.

| Role | Views and workflows |
| --- | --- |
| Event Organiser | **Event requests**, **My requests** and **Organisation events**: create and submit requests, manage drafts, view client events and request changes. |
| Event Coordinator Lead | **Coordinator assignment**: assign/reassign coordinators and oversee active events. |
| Event Coordinator | **My assigned events**, **Venue catalogue** and **Venue calendar**: review requests, plan venue/equipment arrangements and manage event progression. |
| Venue Staff | **Venue catalogue**, **Booking requests**, **Timing reviews** and **Venue calendar**: maintain venues, review bookings and manage availability. |
| Technical Support Staff | **Equipment catalogue**, **Equipment availability** and **Equipment review queue**: manage stock and review equipment requirements and reservations. |
| Safety Officer | **Safety reviews**: review operational plans and record approval or required changes before preparation. |
| Attendee | **Events open for registration** and **My registrations**: register for eligible events and manage your registrations. |
| All roles | **Notifications** and email settings: read personal notices and choose which notification types send email. |

Fresh setup seeds accounts and five sample venues, not a complete end-to-end event scenario.
Create an event as an organiser, assign it through the Lead account, then use the assigned
coordinator and relevant staff accounts to progress it. Registration and safety queues depend
on the event reaching the appropriate workflow state; an empty queue on first login is expected.

### Exact-time venue workflows

Exact-time venue configuration and booking use the `EXACT_VENUE_TIMING_ENABLED` flag, which is
off by default. To explore these workflows locally, start the application with the flag enabled
in the terminal running it:

**Windows — PowerShell:**

```powershell
$env:EXACT_VENUE_TIMING_ENABLED = 'true'
npm.cmd start
# After stopping the application:
Remove-Item Env:EXACT_VENUE_TIMING_ENABLED
```

**macOS — Terminal:**

```sh
EXACT_VENUE_TIMING_ENABLED=true npm start
```

Configure the venue's exact-time settings as Venue Staff before trying exact-time searches and
bookings. Existing slot-based sample data is not automatically a fully configured exact-time
scenario. This flag affects local execution; shared deployment follows the team's rollout process.

Story-specific behaviour and test evidence are documented in [docs/development](docs/development).
Jira holds the active backlog and acceptance criteria; [requirements](docs/requirements.md)
describes the Release 1 requirement boundary.

## Development commands

| Command | Purpose |
| --- | --- |
| `npm start` | Start Flask and React after setup, with automatic reload on code changes |
| `npm run doctor` | Check tools, supported Node/pnpm versions and Docker availability |
| `npm run setup` | First setup, refresh dependencies, or restart the local database after stopping it |
| `npm run verify` | Ruff lint/format, Python tests, TypeScript, frontend tests and production frontend build |
| `npm run browser:install` | Install Playwright Chromium once |
| `npm run check:e2e` | Run browser tests with local Supabase, fixtures and `npm start` already running |
| `npm run e2e:record -- e2e/<story>.spec.ts` | Record a selected browser test with video, traces and screenshots |
| `npm run e2e:report` | Open the browser evidence report |
| `npm run integration` | Run PostgreSQL checks against an empty disposable database |
| `npm run package:source` | Create a source ZIP in `artifacts/` |
| `npm run budget` | Report the CI budget snapshot; UNKNOWN means unverified |
| `npm run stop` | Stop local Supabase without deleting data |

The same commands work on both platforms. Existing `make` commands remain optional aliases
for environments already configured with Python 3.13, uv and pinned pnpm. Do not share a `.venv`
or `node_modules` folder between native Windows and WSL; use separate clones if using both.

### Keeping Node 22 for another project

On Windows, run this repository with an isolated Node 24 runtime:

```powershell
npm.cmd exec --yes --package=node@24 -- npm.cmd run setup
npm.cmd exec --yes --package=node@24 -- npm.cmd start
```

These commands do not replace your system Node. A version manager using this repository's
`.nvmrc` is another option. On macOS, use `npm` instead of `npm.cmd` in those commands.

### Troubleshooting

- If PowerShell blocks `npm.ps1`, use `npm.cmd run setup` / `npm.cmd start` (and the same
  substitution for other commands). No execution-policy change is required.
- If a tool is missing, follow the prerequisite link above and reopen the terminal.
- If Docker cannot be reached, start Docker Desktop and select Linux containers on Windows.
- On macOS, AirPlay Receiver may occupy port 5000. If Flask reports that port in use,
  search System Settings for AirPlay Receiver and temporarily turn it off if you do not need it.
  If you need to keep it running, report the conflict before changing ports: Flask and the Vite
  proxy must use the same API port. See [Flask's guidance](https://flask.palletsprojects.com/en/stable/server/).
- If ports 5000, 5173 or Supabase ports 54320–54325/54327/8083 are occupied, stop your own
  conflicting process or coordinate with its owner; do not reset another project's database.
- If setup stops, resolve the reported error and rerun `npm run setup`.
- If startup reports missing email settings, rerun setup. If Mailpit SMTP is unavailable, stop
  the application, run `npm run stop`, then `npm run setup` and `npm start` to restart the local stack.
- An existing non-local `.env` is refused. Keep hosted credentials separate from the local clone.

### PostgreSQL integration gate

PostgreSQL-specific tests require a separate integration run. Run the separate gate against an
**empty disposable PostgreSQL database**, never the seeded Supabase application database or hosted demo.

PowerShell:

```powershell
$env:INTEGRATION_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/EMPTY_DB'
npm.cmd run integration
Remove-Item Env:INTEGRATION_DATABASE_URL
```

macOS Terminal:

```sh
INTEGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/EMPTY_DB' npm run integration
```

The URL is a placeholder; provide a real disposable database. Do not start another database on
Supabase's port 54322. Browser tests may create dedicated local business fixtures; use the local test environment.

## Project links and access

| Resource | Location | Access |
| --- | --- | --- |
| Source, PRs and CI | [GitHub repository](https://github.com/Ryan-Lee-2000/ConnectSphere) | Private repository; a collaborator invitation is required. |
| Backlog and sprint tracking | [Jira SPL board](https://clivelim01-1787647390567.atlassian.net/jira/software/projects/SPL/boards/40/backlog) | Requires access to the team's Atlassian project. |
| Process records | [SPM Project G9 Team 3](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/SPGT3/overview) | Requires access to the Confluence space. |
| Test and deployment reports | [QA SPACE](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/QS/overview) | Requires access to the space and linked attachments. |
| Submission backup | [Final submission on Google Drive](https://drive.google.com/drive/folders/1R7pY7xSRm4LVEKprZErvY16Pk2EbTw-6) | Use the Google account granted access by the team. |
| Sprint 4 ceremony recordings | [Recording folder](https://drive.google.com/drive/folders/1cy6_Z-TQ91ROreeVbZu4r9DYMSpeW5Dv) | Requires access to the folder and its recordings. |
| Team working documents | [[IS212] SPM Team 3](https://drive.google.com/drive/folders/1bPFDcmjKqRuOZI0Ls2lfzP_047thJtY5) | Includes AI SKILLS, the preparation task list and supporting material. |
| Hosted application | [ConnectSphere demo](https://connectsphere-mmay.onrender.com) | Request role-specific hosted accounts from the team; local fixture credentials do not apply. |

If a resource is inaccessible, contact the team with the account that needs access. Use the same account when opening linked files and recordings.

## Submission guide

Start with the submission **Index** and the `G9T3_Final_Submission` folder in the submitted ZIP.
The same materials are linked through the [Google Drive backup](https://drive.google.com/drive/folders/1R7pY7xSRm4LVEKprZErvY16Pk2EbTw-6).
The paths below follow the Index; they are relative to the extracted submission folder, not this
source repository.

| Criterion | Folder / location | Contents |
| --- | --- | --- |
| 1 — Full product backlog | `G9T3_Final_Submission/1.Full Product Backlog` | Sprint 1–4 user stories with their QA documents, DevOps documents and UAT videos. The [Jira project](https://clivelim01-1787647390567.atlassian.net/jira/software/projects/SPL/summary) provides the linked story records. |
| 2 — System design | `G9T3_Final_Submission/2.System Design (C4)` | C4 system design diagrams. Repository references: [C4 model](docs/architecture/c4.md) and [architecture](docs/architecture.md). |
| 3 — Test cases | `G9T3_Final_Submission/3. Test Cases` and the QA/DevOps documents under `1.Full Product Backlog` | HTML test-case dashboard for navigation; QA documents hold test cases, coverage, UAT and results. DevOps documents hold PR history, CI, migration and deployment evidence. |
| 4 — Sprint documentation | `G9T3_Final_Submission/4. Sprint Documentation/Sprint X/Documentation Or Recording Folder` | Replace `Sprint X` with the sprint required. Includes sprint documentation, recordings/transcripts, velocity and burndown charts, sprint backlogs and retrospective boards. [Sprint 4 ceremony recordings](https://drive.google.com/drive/folders/1cy6_Z-TQ91ROreeVbZu4r9DYMSpeW5Dv). |
| 6 — Software release | `G9T3_Final_Submission/6.Software_Release` | Application source/release package. Extract the source and follow [Getting started](#getting-started). |
| 7 — README | `G9T3_Final_Submission/7.Read me` | Project setup, submission navigation and team process guide. |

The criterion numbering follows the supplied submission Index. For current source, reviews and
pipeline runs, use [GitHub](https://github.com/Ryan-Lee-2000/ConnectSphere). For shared agent
instructions and preparation tracking, use **AI SKILLS** and **Final Submission Task list** in
the [team working folder](https://drive.google.com/drive/folders/1bPFDcmjKqRuOZI0Ls2lfzP_047thJtY5).

To trace a story end to end, follow **Jira story and AC → QA cases → test source and results →
reviewed PR → DevOps report**.

### Packaging source

Run `npm run package:source` (`npm.cmd run package:source` on Windows) to create
`artifacts/connectsphere-foundation.zip`. This packages the application source, frontend assets, tests and project documentation.
Drive/Confluence evidence and recordings belong in their separate submission folders.
Do not distribute `.env`, `.venv`, `node_modules` or database volumes. See [.gitignore](.gitignore).

## Team process

Our delivery cycle is **refine → plan → implement and verify → peer review → sprint review →
retrospective → next sprint planning**. Sprint 0 establishes infrastructure; product work follows
team-approved stories and acceptance criteria.

### Planning, review and retrospectives

1. **Refine and plan:** clarify the user outcome, testable AC, dependencies and shared ownership.
   Two teammates review each story without AI and leave feedback in Jira before the sprint.
   Apply the Definition of Ready, estimate relative size and agree a goal against available capacity.
2. **Implement and track:** owners develop the agreed scope, maintain QA evidence and raise blockers
   at stand-up. Each impediment has an owner and a recorded resolution.
3. **Sprint review:** demonstrate user journeys against the AC, capture Product Owner feedback,
   and distinguish finished work from unmerged or incomplete work.
4. **Retrospective:** use the 4Ls—Liked, Learned, Lacked and Longed for—to identify improvements.
   Give each action an owner and due date.
5. **Next sprint planning:** begin with the previous retrospective's actions. Decide which to adopt,
   carry forward or close with evidence, and account for them in capacity and working agreements.

See the [ceremony run sheets](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/SPGT3/pages/5537862),
[decision log](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/SPGT3/pages/5505159) and
[Definition of Ready/Done](https://clivelim01-1787647390567.atlassian.net/wiki/spaces/SPGT3/pages/5374063).

#### Retrospective actions in subsequent sprints

| Transition | Retrospective action | Follow-through and outcome |
| --- | --- | --- |
| **Sprint 2 → Sprint 3: daily updates** | Each member should report their own stand-up status rather than wait to be asked. | Sprint 3 planning (6 October, 18:21–18:45) repeated daily updates, buddy tracking and escalation through the Scrum Master. The Sprint 3 retro acknowledged that self-checking had not solved missed updates; buddy accountability and individual Scrum Master check-ins were proposed for Sprint 4. |
| **Sprint 3 → Sprint 4 preparation: clearer AC** | Review story boundaries and remove overlapping or ambiguous AC before work starts. | Sprint 4 grooming (18 October, 19:10–19:31) asked developers to read and negotiate AC over the next one or two days, before Tuesday's assignment and estimation. Stories remained unassigned/unestimated during grooming, making clarification an explicit preparation step. |
| **Sprint 3 → Sprint 4 delivery: shared workflows** | Standardise development, QA and DevOps prompts and improve UAT-to-AC evidence. | On 20 October, [shared workflow skills were added](https://github.com/Ryan-Lee-2000/ConnectSphere/commit/ae2c18f302de4a19da47d0fc5c5f95df6b593d4f), followed by consistent QA video instructions and test-case/AC comments. These are concrete process changes matching the retro request. |
| **Sprint 2 → Sprint 3 review: stronger verification** | Use happy-path UAT evidence and take more initiative on PR reviews. | The Sprint 3 retro (06:46–07:03; 10:07–10:30) reported UAT video use and more responsive, detailed reviews. It then requested clearer video timestamp-to-AC mapping. This is reported progress, not a measured time saving. |

See the [retrospective follow-through evidence](docs/planning/retro-follow-through.md) for source
records, dates, recording timestamps and implementation commits. The Sprint 4 preparation example
comes from grooming, not final planning minutes. The shared-workflow and UAT examples show later
implementation or review outcomes; their adoption is not explicitly recorded in planning minutes.

### Estimation benchmark

The team's selected benchmark is **[SPL-50 — Browse Venue Catalogue](https://clivelim01-1787647390567.atlassian.net/browse/SPL-50),
3 story points**.

Its scope is a read-only Event Coordinator view: list venue names and locations, open recorded
venue details and layouts, and display an empty state when there are no venues. Search/filtering,
suitability, date/time availability and booking are outside the story.

Compare other stories with this reference by scope, complexity, uncertainty and testing effort,
using the team's Fibonacci scale **1, 2, 3, 5, 8**. Points express relative size, not fixed hours
or individual performance. Jira's structured story-point field holds the estimate. Infrastructure
setup is tracked separately from product-story estimation.

### Peer review and quality gates

**Every PR requires review by another person, including a review of the linked QA document.**
The reviewer checks both implementation correctness and whether the evidence demonstrates the AC.

| Gate | Requirements | Purpose |
| --- | --- | --- |
| Story readiness | Peer-reviewed, testable AC; clear scope and dependencies | Catch ambiguity before coding. |
| Author verification and QA | Applicable automated checks and user walkthroughs; AC-to-case mapping; expected/actual results; failures and retests recorded | Establish what was tested and what remains unresolved. |
| Independent PR review | Review behaviour, code, assertions, security, migrations and the QA report against the reviewed revision | Catch defects, missing coverage and unsupported completion claims. |
| Merge | Required checks pass, findings are resolved and a human approves the latest changes | Keep reviewed changes as the integration boundary. These are team rules, not assumed branch protections. |
| Deployment and Done | Record merge/pipeline/deployment evidence and satisfy the Definition of Done | Keep PR approval, merge, deployment and story completion distinct. |

QA review includes test rationale, reproducible commands, commit/run identity, screenshots where
relevant, and disclosed skips or defects. Preserve the merge-complete CI link and append later
runs separately. Use the [PR template](.github/pull_request_template.md),
[development workflow](docs/development/workflow.md) and [deployment procedure](docs/infrastructure/deployment.md).

The shared workflows live in the repository under `.agents/skills/`: **build → qa → devops**,
with **pr-review** handling review feedback and **devops** run again after merge. The QA and
DevOps reports use shared Confluence templates. See **AI SKILLS** in Drive and the repository's
[AGENTS.md](AGENTS.md) for the workflow entry points. The PR-review skill helps resolve review
comments; independent human approval remains required.

### Project value adds

**User story buddy system.** The team used a fixed review allocation throughout the project.
Each member checks two teammates' user stories, so every author has two assigned reviewers.

| Reviewer | Checks stories written by |
| --- | --- |
| Dan | Ryan and Lin |
| Lin | Xinghua (XH) and Ranveer |
| Xinghua (XH) | Lin and Clive |
| Ryan | Clive and Dan |
| Ranveer | Dan and Xinghua (XH) |
| Clive | Ryan and Ranveer |

After checking the assigned stories and giving comments, reviewers tick their own entry in the
team's **Buddy System User Story Check** poll. This makes review responsibility explicit and
provides a shared completion tracker. Two reviewers per author bring additional perspectives to
story clarity, acceptance criteria and dependencies. Story feedback is recorded in Jira;
independent PR review of the implementation and QA evidence remains a separate gate.

**RV test-case dashboard.** The submission Index lists an HTML dashboard under
`G9T3_Final_Submission/3. Test Cases` to help navigate the test cases. Use it alongside each
story's QA/DevOps documents for the underlying evidence.

## Repository structure

| Path | Contents |
| --- | --- |
| `frontend/` | React UI and component tests |
| `backend/app/` | Flask API and SQLAlchemy models |
| `backend/migrations/` | Alembic application migrations |
| `e2e/` | Browser checks |
| `scripts/` | Setup, local fixtures, verification, packaging and deployment utilities |
| `docs/` | [Documentation index](docs/README.md), architecture, requirements and story evidence |
| `docs/development/` | Contribution workflow and test conventions |
| `docs/infrastructure/` | Deployment, budget policy and verification records |
| `PRODUCT.md`, `DESIGN.md`, `DESIGN.json` | Product principles and shared visual system |
| `AGENTS.md`, `CLAUDE.md` | Shared coding-agent instructions |

Alembic owns application migrations; merged migrations are not rewritten. Shared deployment runs
through GitHub Actions after passing main-branch checks. See [deployment and recovery](docs/infrastructure/deployment.md)
and [CI budget policy](docs/infrastructure/ci-budget.md) for operational details.
