# ConnectSphere project foundation

Sprint 0 infrastructure for Team T3. This skeleton provides a common local environment,
automated checks and contribution conventions for native Windows and macOS.
No Release 1 product story is implemented or estimated by this foundation.

## Included

- React/TypeScript/Vite shell with an API/database connectivity check
- Flask application factory, health endpoint and fail-closed Supabase token validation
- SQLAlchemy metadata and an empty Alembic baseline, ready for approved domain migrations
- Local Supabase PostgreSQL/Auth and one role-free Auth fixture for infrastructure tests
- Backend, frontend, PostgreSQL migration and browser/Auth smoke tests
- Common agent instructions, PR guidance, CI configuration and disabled deployment tooling

There are no event screens, event endpoints, product-domain tables, business-role fixtures or
sample stories to copy into the backlog. Role/organisation authorisation must be implemented
and tested with the approved product stories; a valid token alone grants no business permissions.

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
local environment files, applies Alembic migrations and creates one local Auth test fixture. First startup
needs internet access and time to download Python, packages and container images.
Rerunning setup is supported and preserves existing local data.

Open http://127.0.0.1:5173. The foundation screen should report API/database connectivity.
There is no product login screen yet. The browser smoke test uses `developer@example.test` /
`LocalDemo123!` to verify real Auth and server-side token validation. This local-only fixture
has no application profile, organisation or role.

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

## Repository map

- `frontend/`: React UI and component tests
- `backend/app/`: Flask API and SQLAlchemy models
- `backend/migrations/`: forward-reviewed Alembic migrations
- `scripts/`: setup, seed, deployment and budget utilities
- `docs/`: architecture, requirements, CI budget and deployment handoff
- `docs/onboarding/`: teammate setup checklist
- `docs/development/`: contribution and review workflow
- `docs/infrastructure/`: repository, hosting, budget, verification and infrastructure tasks
- `AGENTS.md`: binding shared instructions for all coding agents
- `CLAUDE.md`: forwards Claude to the shared instructions

## Handoff and remaining work

Read `docs/development/workflow.md` for the team/agent contribution process. The first product
story and any 1-point estimation reference are decisions for the team, not part of this skeleton.
Use [the Wednesday onboarding checklist](docs/onboarding/checklist.md) to record each teammate's setup.

- Native Windows and macOS clean-clone acceptance must be recorded in `docs/infrastructure/verification.md`.
- The full authoritative requirements baseline and team backlog must be supplied before product work.
- Hosted accounts, billing controls and deployment are not activated. Budget remains UNKNOWN.
- CI and Dependabot configuration are prepared; follow [repository setup](docs/infrastructure/repository-setup.md)
  for the personal GitHub Free account. GitHub execution remains unverified.

The local Supabase project ID is `connectsphere-foundation`. It has an empty product schema;
only Alembic's revision table is created. Old local databases are not migrated or reset by this
skeleton. Stop any other stack using the same ports before setup. Do not point this baseline at
an existing application database. Once the baseline is merged, evolve it with new migrations.

Share source through the team repository, not a copy of your working directory. Do not include
`.env`, `.venv`, `node_modules`, build output, test reports or database volumes. See `.gitignore`.
For an archive handoff before Git exists, use `npm run package:source`; it creates an explicit
source-only ZIP under ignored `artifacts/` and includes no local credentials or generated output.

See `docs/infrastructure/tasks/INF-01.md` for infrastructure acceptance and `docs/infrastructure/deployment.md` before enabling
any shared deployment.
