# Wednesday onboarding check — 9 September 2026

Purpose: confirm each teammate can run the Sprint 0 foundation independently. Product stories
and estimates are agreed separately. Record failures as failures, with the command and error.

## Before the session

Follow README prerequisites: Git, Node 24, uv and a running Docker Desktop with Linux containers.
Choose the Docker installer matching your Mac's processor. Windows users can run all project
commands in PowerShell; the Docker backend still needs to be supported by that Windows machine.
WSL is not a required project shell. Hyper-V availability depends on the Windows edition and setup;
consult [Docker's requirements](https://docs.docker.com/desktop/setup/install/windows-install/).
If the machine cannot run a supported Docker backend, record a blocker for the team to resolve.

Keep existing projects' Node versions: README includes an isolated Node 24 command.
Download dependencies on a reliable connection before the session if possible. First setup takes
longer than daily startup. No separate Python, pnpm, Make or Supabase CLI installation is needed.

Use your own fresh clone of the team repository in a new folder. Start with the
[project orientation](start-here.md). Do not copy anyone's .env, .venv, node_modules or database files. Stop any other local
Supabase stack using the same ports through its own project; never reset it.

## Run and record

Use `npm.cmd` in PowerShell if `npm` is blocked by execution policy. If preserving Node 22,
prefix commands as described in README. Run the following from the project folder.

| Step | Command or action | Expected result |
| --- | --- | --- |
| 1 | `npm run doctor` | Prerequisites ready; Docker reachable |
| 2 | `npm run setup` | Locked installs, local services, migration and Auth fixture succeed |
| 3 | `npm run setup` again | Succeeds without resetting data or duplicating fixture |
| 4 | `npm run verify` | Lint, formatting, Python/frontend tests, typecheck and build pass; one PostgreSQL test skipped by design |
| 5 | `npm run browser:install` | Chromium installed |
| 6 | `npm start` | Open http://127.0.0.1:5173; ConnectSphere reports API and database connected |
| 7 | In a second terminal: `npm run check:e2e` | One browser/API/database/Auth smoke test passes |
| 8 | Ctrl+C in the first terminal | Both development servers stop; answer Y if Windows prompts |
| 9 | `npm start` again, then Ctrl+C | Both ports are reusable and the shell reconnects |
| 10 | `npm run stop` | Only this local Supabase project stops, with data retained |

For port conflicts, see README troubleshooting, including macOS AirPlay Receiver on port 5000.
The separate PostgreSQL migration gate needs an empty disposable database; follow README exactly.
It has already passed on Ryan's machine but is not covered by the quick suite's skipped test.
Production Docker evidence is in docs/infrastructure/verification.md; teammates need not repeat it as a first-run step.

## Result to record in docs/infrastructure/verification.md

- Developer, date, OS version and CPU (Apple Silicon/Intel or Windows architecture)
- Git commit when available, otherwise archive identity/date
- Node version, Docker version/backend, and whether this was a fresh clone or archive
- Each step: passed / failed / not run; include elapsed first-setup time
- Exact failing command and relevant error text, with credentials removed
- Recovery attempted and rerun result; any remaining blocker

Do not share .env contents, Auth tokens or entire Supabase status output.
Keep real macOS/teammate results pending until performed. The shared demo and automated deployment are verified separately; they do not
prove a teammate can set up a fresh clone and do not make INF-01 Done.
