# ConnectSphere

Team T3's ConnectSphere monorepo provides the shared local environment, automated checks and
contribution conventions for native Windows and macOS, together with team-approved Release 1 work.

## Included

- React/TypeScript/Vite shell with an API/database connectivity check
- Flask application factory, health endpoint and fail-closed Supabase token validation
- SQLAlchemy/Alembic application data with the approved account-role authorization foundation
- Local Supabase PostgreSQL/Auth and role-specific Auth fixtures for authentication/authorization tests
- Event Organiser request creation, draft lifecycle, and equipment-line backend contract for approved Sprint 1 work
- Backend, frontend, PostgreSQL migration and browser/Auth smoke tests
- Common agent instructions, PR guidance, working CI and verified shared deployment

CS-E01-S2 adds the approved account-role authorization foundation; a valid token alone grants no
business permissions. Sprint 1 adds the venue catalogue and the approved event-request flow:
authorised Event Organisers can submit requests, save and reopen their own drafts, and delete drafts
after confirmation. Event Coordinators can read submitted requests, but drafts are visible only to
their creator. Event Organisers can also read submitted events within their own trusted client
organisation while other clients and colleagues' drafts remain hidden. Booking and availability
remain later, separately approved work.

## First setup (Windows and macOS)

Use PowerShell on Windows or Terminal on macOS. WSL2 and Make are optional.
Install these once, then reopen your terminal:

| Prerequisite | Installation |
| --- | --- |
| Git | [Git installer](https://git-scm.com/downloads) |
| Node.js 24 (includes npm) | [Node.js installer](https://nodejs.org/en/download) — choose version 24 |
| uv | [Windows/macOS instructions](https://docs.astral.sh/uv/getting-started/installation/) |
| Docker Desktop | [Docker Desktop installer](https://docs.docker.com/desktop/) — start it and wait until the engine is ready |

On Windows, Docker needs a supported Linux-container backend; Docker Desktop can use WSL2
or Hyper-V on supported Windows editions. You do not need to run repository commands inside WSL.
See [Docker's Windows requirements](https://docs.docker.com/desktop/setup/install/windows-install/).
On macOS, choose the installer for your Mac's Apple Silicon or Intel processor.

Clone the team repository and open a terminal in its folder. Run:

```sh
npm run setup
npm start
```

No separate Python, pnpm, Corepack, Make, or global Supabase installation is required.
uv supplies Python 3.13 when needed; npm fetches pnpm 10.15.1 into its cache.
Setup checks prerequisites, installs locked dependencies, starts local Supabase, writes ignored
local environment files, applies Alembic migrations and creates local Auth fixtures for Event
Organiser/Attendee, Venue Staff, and Event Coordinator roles. First startup
needs internet access and time to download Python, packages and container images.
Rerunning setup is supported and preserves existing local data.

Open http://127.0.0.1:5173 and sign in with a local fixture. The browser checks use
`venue.staff@example.test` / `LocalDemo123!` and `event.coordinator@example.test` /
`LocalDemo123!` to verify real Auth, server-side role lookup and catalogue permissions. Fixtures
are local-only and contain no production data.

Use Ctrl+C to stop Flask and React. Run `npm run stop` to stop this project's local Supabase
containers when finished; this preserves their data. Other Docker projects are left alone.
If Windows asks `Terminate batch job (Y/N)?`, enter `Y`.

## Daily commands

| Command | Purpose |
| --- | --- |
| `npm start` | Start Flask and React after setup, with automatic reload on code changes |
| `npm run doctor` | Check tools, supported Node/pnpm versions and Docker availability |
| `npm run setup` | First setup, refresh dependencies, or restart the local database after stopping it |
| `npm run verify` | Ruff lint/format, Python tests, TypeScript, frontend tests and production frontend build |
| `npm run browser:install` | Install Playwright Chromium once |
| `npm run check:e2e` | Infrastructure browser/API/database/Auth smoke test, with `npm start` running in another terminal |
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
- If ports 5000, 5173 or Supabase ports 54320–54324/54327/8083 are occupied, stop your own
  conflicting process or coordinate with its owner; do not reset another project's database.
- If setup stops, resolve the reported error and rerun `npm run setup`.
- An existing non-local `.env` is refused. Keep hosted credentials separate from the local clone.

### PostgreSQL integration gate

The quick Python suite skips one PostgreSQL test by design. Run the separate gate against an
**empty disposable PostgreSQL database**, never the seeded Supabase application database or hosted demo.

PowerShell:

```powershell
$env:INTEGRATION_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/EMPTY_DB'
npm run integration
Remove-Item Env:INTEGRATION_DATABASE_URL
```

macOS Terminal:

```sh
INTEGRATION_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/EMPTY_DB' npm run integration
```

The URL is a placeholder; provide a real disposable database. Do not start another database on
Supabase's port 54322. Infrastructure smoke tests create no business records.

### Event request and draft checks

After setup, run `npm start` and sign in with a local Event Organiser fixture. Open **New event
request** to submit a complete request or save a draft with only an event name. Open **My event
requests** to see drafts separately from submitted requests, reopen and resave a draft, submit it,
or delete it after confirmation. A submitted request cannot be deleted through the draft action.

Run `npm run verify` for lint, formatting, backend API tests, frontend tests, typecheck and build.
Run `npm run integration` using the empty disposable PostgreSQL database described above to check
the Alembic migration. With the local stack and browser fixture available, run `npm run check:e2e`;
the draft flow also needs a manual browser walkthrough until dedicated draft browser checks exist.
The story-specific behavior and test evidence are in `docs/development/SPL-56.md`,
`docs/development/SPL-57.md` and `docs/development/SPL-58.md`.

### Client-organisation event checks

Sign in with the local Event Organiser fixture and open **Organisation events**. The list contains
submitted events associated with that fixture's client organisation and exposes read-only event
details. Drafts remain under **My event requests** and never appear in the organisation list.

Run `npm run verify` for the API and interface scope tests. Run `npm run integration` against an
empty disposable PostgreSQL database to verify the organisation migration, RLS and browser-role
grant denial. The story boundary and evidence map are in `docs/development/SPL-45.md`.

## Repository map

- `frontend/`: React UI and component tests
- `backend/app/`: Flask API and SQLAlchemy models
- `backend/migrations/`: forward-reviewed Alembic migrations
- `PRODUCT.md`: product users, purpose, personality and design principles
- `DESIGN.md` / `DESIGN.json`: shared visual rules, tokens and component guidance
- `docs/design/moodboard/`: selected Operations Atlas direction and visual probes
- `scripts/`: setup, seed, deployment and budget utilities
- `docs/`: architecture, requirements, CI budget and deployment handoff
- `docs/onboarding/`: teammate setup checklist
- `docs/development/`: contribution and review workflow
- `docs/development/testing.md`: test-case IDs, code lookup, focused runs and CI evidence
- `docs/infrastructure/`: repository, hosting, budget, verification and infrastructure tasks
- `AGENTS.md`: binding shared instructions for all coding agents
- `CLAUDE.md`: forwards Claude to the shared instructions

## Handoff and ongoing work

Read `docs/development/workflow.md` for the team/agent contribution process. Implement only
team-approved Jira stories and use their current acceptance criteria rather than this README.
Use [the Wednesday onboarding checklist](docs/onboarding/checklist.md) to record each teammate's setup.

- Native Windows and macOS clean-clone acceptance must be recorded in `docs/infrastructure/verification.md`.
- The maintained requirement boundary is in `docs/requirements.md`; Jira holds the active backlog.
- Shared demo: https://connectsphere-mmay.onrender.com. Hosted Auth, baseline and automated deployment passed.
- GitHub Actions paid budget was verified at $0 with Stop usage enabled. Run `npm run budget`
  for the dated snapshot; it expires after 24 hours and does not retrieve live usage.
- CI and Dependabot configuration are prepared; follow [repository setup](docs/infrastructure/repository-setup.md)
  for the personal GitHub Free account. PR checks and the main deployment workflow have passed.

The local Supabase project ID is `connectsphere-foundation`. Alembic owns its application schema,
including the account-role authorization tables. Setup upgrades existing local databases without
resetting them. Stop any other stack using the same ports before setup, and never point local setup
at an existing hosted or unrelated application database.

Share source through the team repository, not a copy of your working directory. Do not include
`.env`, `.venv`, `node_modules`, build output, test reports or database volumes. See `.gitignore`.
For an archive handoff before Git exists, use `npm run package:source`; it creates an explicit
source-only ZIP under ignored `artifacts/` and includes no local credentials or generated output.

See `docs/infrastructure/tasks/INF-01.md` for infrastructure acceptance and `docs/infrastructure/deployment.md` for the active shared deployment and recovery procedure.
