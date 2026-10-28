"""Native Windows/macOS commands, also available through optional Make aliases."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def command_args(args):
    if args[0] == "pnpm" and os.getenv("CONNECTSPHERE_NPM"):
        return [
            os.environ["CONNECTSPHERE_NODE"],
            os.environ["CONNECTSPHERE_NPM"],
            "exec",
            "--yes",
            "--package=pnpm@10.15.1",
            "--",
            "pnpm",
            *args[1:],
        ]
    executable = shutil.which(args[0])
    if not executable:
        raise RuntimeError(f"Missing {args[0]}. See README prerequisites; reopen your terminal.")
    return [executable, *args[1:]]


def run(*args, capture=False, env=None):
    return subprocess.run(
        command_args(args),
        check=True,
        text=True,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE if capture else None,
    )


def doctor():
    missing = [tool for tool in ("git", "node", "uv", "docker") if not shutil.which(tool)]
    if missing:
        raise RuntimeError("Install " + ", ".join(missing) + "; see README prerequisites.")
    version = run("node", "--version", capture=True).stdout.strip()
    if version.split(".")[0] != "v24":
        raise RuntimeError(
            f"Node 24 required; found {version}. Install Node 24 and reopen terminal."
        )
    if run("pnpm", "--version", capture=True).stdout.strip() != "10.15.1":
        raise RuntimeError("pnpm 10.15.1 required. Use npm run setup for the pinned version.")
    try:
        run("docker", "info", "--format", "{{.ServerVersion}}")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Start Docker Desktop with Linux containers, then rerun npm run doctor."
        ) from exc
    print("Prerequisites ready (Node 24, pnpm 10.15.1, uv, Git and Docker).")


def stop_process(process):
    if os.name == "nt":
        # uv/npm spawn descendants; terminating only the wrapper leaves ports occupied.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def email_env(target):
    """SPL-125: local email goes to Supabase's Mailpit. Email settings already in .env are kept,
    so Gmail credentials added by hand survive a rerun of setup."""
    settings = {
        "EMAIL_BACKEND": "smtp",
        # The shared inbox; Mailpit captures local mail, so nothing reaches it from smtp.
        "NOTIFICATION_EMAIL_TO": "connectsphere.notices@gmail.com",
        "APP_BASE_URL": "http://127.0.0.1:5173",
    }
    keys = (*settings, "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
    if target.exists():
        for line in target.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() in keys and value.strip():
                settings[key.strip()] = value.strip()
    return "".join(f"{key}={value}\n" for key, value in settings.items())


def local_env():
    data = json.loads(run("pnpm", "exec", "supabase", "status", "-o", "json", capture=True).stdout)
    api = data["API_URL"]
    # Only accept loopback: setup must never seed or overwrite a hosted project.
    if urlparse(api).scheme != "http" or urlparse(api).hostname not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        raise RuntimeError("Refusing non-local Supabase setup")
    public = data.get("ANON_KEY") or data["PUBLISHABLE_KEY"]
    secret = data.get("SERVICE_ROLE_KEY") or data["SECRET_KEY"]
    db = data["DB_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    if urlparse(db).scheme != "postgresql+psycopg" or urlparse(db).hostname not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        raise RuntimeError("Refusing non-local database setup")
    target = ROOT / ".env"
    if target.exists() and "http://127.0.0.1:" not in target.read_text():
        raise RuntimeError("Existing .env is not known-local. Move it before local setup.")
    target.write_text(
        f"DATABASE_URL={db}\nSUPABASE_URL={api}\n"
        f"SUPABASE_PUBLISHABLE_KEY={public}\n"
        f"SUPABASE_SERVICE_ROLE_KEY={secret}\n" + email_env(target)
    )
    target.chmod(0o600)
    (ROOT / "frontend/.env.local").write_text(
        f"VITE_SUPABASE_URL={api}\nVITE_SUPABASE_PUBLISHABLE_KEY={public}\n"
        "VITE_LOCAL_DEMO_PASSWORD=LocalDemo123!\n"
        "VITE_LOCAL_DEMO_VENUE_STAFF_EMAIL=venue.staff@example.test\n"
        "VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL=event.coordinator@example.test\n"
    )
    return {
        **os.environ,
        "DATABASE_URL": db,
        "SUPABASE_URL": api,
        "SUPABASE_PUBLISHABLE_KEY": public,
        "SUPABASE_SERVICE_ROLE_KEY": secret,
    }


def main():
    os.chdir(ROOT)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "doctor":
        doctor()
    elif cmd == "setup":
        doctor()
        run("pnpm", "install", "--frozen-lockfile")
        run("uv", "sync", "--frozen")
        run("pnpm", "exec", "supabase", "start")
        environment = local_env()
        run("uv", "run", "--frozen", "alembic", "upgrade", "head", env=environment)
        run("uv", "run", "--frozen", "python", "scripts/seed.py", env=environment)
        print("Setup complete. Run npm start, then open http://127.0.0.1:5173.")
    elif cmd == "migrate":
        run("uv", "run", "--frozen", "alembic", "upgrade", "head")
    elif cmd == "verify":
        run("uv", "run", "--frozen", "ruff", "check", "backend", "scripts")
        run("uv", "run", "--frozen", "ruff", "format", "--check", "backend", "scripts")
        # Windows can deny access to the account-level pytest temp directory.
        # Keep disposable test files inside this ignored project-local directory instead.
        run("uv", "run", "--frozen", "pytest", "-q", "--basetemp", ".pytest-run")
        run("pnpm", "typecheck")
        run("pnpm", "test")
        run("pnpm", "build")
    elif cmd == "coverage-spl71":
        # Week 6 coverage is a diagnostic for this story's owned backend module.
        # It supplements requirement-based assertions; it is not a quality target.
        run("uv", "run", "--frozen", "coverage", "erase")
        run(
            "uv",
            "run",
            "--frozen",
            "coverage",
            "run",
            "-m",
            "pytest",
            "backend/tests/test_venue_availability_unit.py",
            "backend/tests/test_venue_availability.py",
            "-q",
            "--basetemp",
            ".pytest-run",
        )
        run("uv", "run", "--frozen", "coverage", "report", "--show-missing")
    elif cmd == "coverage-spl72":
        # Week 6 coverage diagnostic for the capacity-filter rules added to SPL-71's module.
        run("uv", "run", "--frozen", "coverage", "erase")
        run(
            "uv",
            "run",
            "--frozen",
            "coverage",
            "run",
            "-m",
            "pytest",
            "backend/tests/test_venue_availability_unit.py",
            "backend/tests/test_venue_availability.py",
            "-q",
            "--basetemp",
            ".pytest-run",
        )
        run("uv", "run", "--frozen", "coverage", "report", "--show-missing")
    elif cmd == "coverage-spl73":
        # Week 6 coverage diagnostic for requirement-filter rules in the shared availability module.
        run("uv", "run", "--frozen", "coverage", "erase")
        run(
            "uv",
            "run",
            "--frozen",
            "coverage",
            "run",
            "-m",
            "pytest",
            "backend/tests/test_venue_availability_unit.py",
            "backend/tests/test_venue_availability.py",
            "-q",
            "--basetemp",
            ".pytest-run",
        )
        run("uv", "run", "--frozen", "coverage", "report", "--show-missing")
    elif cmd == "coverage-spl75":
        # Week 6 coverage diagnostic for the reusable venue-suitability checks.
        run("uv", "run", "--frozen", "coverage", "erase")
        run(
            "uv",
            "run",
            "--frozen",
            "coverage",
            "run",
            "-m",
            "pytest",
            "backend/tests/test_venue_availability_unit.py",
            "backend/tests/test_venue_availability.py",
            "-q",
            "--basetemp",
            ".pytest-run",
        )
        run("uv", "run", "--frozen", "coverage", "report", "--show-missing")
    elif cmd == "coverage-spl85":
        # SPL-85 coverage report, also run in CI: branch coverage of the event-confirmation route
        # and gate from their own acceptance tests. The team aims for about 95%; it is a
        # diagnostic, not a hard floor, so a lower figure is reported rather than failing CI.
        run("uv", "run", "--frozen", "coverage", "erase")
        run(
            "uv",
            "run",
            "--frozen",
            "coverage",
            "run",
            "--branch",
            "--source=app.event_confirmation",
            "-m",
            "pytest",
            "backend/tests/test_event_confirmation.py",
            "-q",
            "--basetemp",
            ".pytest-run",
        )
        run("uv", "run", "--frozen", "coverage", "report", "--show-missing")
    elif cmd == "coverage-spl131":
        # SPL-131 coverage report, also run in CI: branch coverage of the several-venue rules and
        # cancellation route from their own acceptance tests. Reported, not a hard floor (~95%).
        run("uv", "run", "--frozen", "coverage", "erase")
        run(
            "uv",
            "run",
            "--frozen",
            "coverage",
            "run",
            "--branch",
            "--source=app.venue_arrangements",
            "-m",
            "pytest",
            "backend/tests/test_venue_arrangements.py",
            "-q",
            "--basetemp",
            ".pytest-run",
        )
        run("uv", "run", "--frozen", "coverage", "report", "--show-missing")
    elif cmd == "coverage-spl86":
        # SPL-86 coverage report, also run in CI: branch coverage of the whole-event cancellation
        # route from its own acceptance tests. Reported, not a hard floor (~95%).
        run("uv", "run", "--frozen", "coverage", "erase")
        run(
            "uv",
            "run",
            "--frozen",
            "coverage",
            "run",
            "--branch",
            "--source=app.event_cancellation",
            "-m",
            "pytest",
            "backend/tests/test_event_cancellation.py",
            "-q",
            "--basetemp",
            ".pytest-run",
        )
        run("uv", "run", "--frozen", "coverage", "report", "--show-missing")
    elif cmd == "integration":
        if not os.getenv("INTEGRATION_DATABASE_URL"):
            raise SystemExit("Set INTEGRATION_DATABASE_URL to a disposable PostgreSQL database.")
        # test_postgres.py requires an empty database, so it must migrate before the rest.
        run(
            "uv",
            "run",
            "--frozen",
            "pytest",
            "backend/tests/test_postgres.py",
            # SPL-90: verifies its data backfill and PostgreSQL-only state constraints.
            "backend/tests/test_equipment_requirements_postgres.py",
            # SPL-97: verifies requirement edits and reservations share a real PostgreSQL lock.
            "backend/tests/test_equipment_reservations_postgres.py",
            "backend/tests/test_exact_venue_bookings_postgres.py",
            "backend/tests/test_timed_venue_closures_postgres.py",
            "backend/tests/test_venue_booking_assessment_postgres.py",
            "backend/tests/test_coordinator_concurrency_postgres.py",
            "backend/tests/test_venue_conflicts_postgres.py",
            "backend/tests/test_qa_spl65_postgres.py",
            "backend/tests/test_qa_spl67_postgres.py",
            "backend/tests/test_qa_spl68_postgres.py",
            "backend/tests/test_respond_clarification_postgres.py",
            "backend/tests/test_venue_booking_requests_postgres.py",
            "backend/tests/test_venue_booking_withdrawals_postgres.py",
            "backend/tests/test_venue_booking_status_postgres.py",
            "backend/tests/test_venue_booking_approval_postgres.py",
            "backend/tests/test_venue_booking_queue_postgres.py",
            "backend/tests/test_venue_booking_rejection_postgres.py",
            "backend/tests/test_venue_occupancy_calendar_postgres.py",
            "backend/tests/test_registration_settings_postgres.py",
            "backend/tests/test_event_registrations_postgres.py",
            "backend/tests/test_equipment_unavailability_postgres.py",
            "backend/tests/test_equipment_return_dates_postgres.py",
            "backend/tests/test_equipment_requirement_changes_postgres.py",
            "backend/tests/test_equipment_requirement_unavailability_postgres.py",
            # SPL-111: simultaneous change-request submissions, the one-pending index and grants.
            "backend/tests/test_event_change_requests_postgres.py",
            # SPL-141: equipment proposals serialize and roll back atomically.
            "backend/tests/test_qa_spl141_postgres.py",
            # SPL-112: final decisions, PostgreSQL serialization and migration safety.
            "backend/tests/test_qa_spl112_postgres.py",
            # SPL-134: assignment/reassignment notices under real concurrent requests.
            "backend/tests/test_qa_spl134_postgres.py",
            # SPL-85: concurrent confirmation, confirmation racing a release, and the migration.
            "backend/tests/test_event_confirmation_postgres.py",
            # SPL-131: same-venue requests and cancellations racing, and the migration.
            "backend/tests/test_venue_arrangements_postgres.py",
            # SPL-86: simultaneous cancellations, cancellation racing confirmation and release.
            "backend/tests/test_event_cancellation_postgres.py",
            # SPL-122: racing removals, cancellations and changes notify Technical Support once.
            "backend/tests/test_qa_spl122_postgres.py",
            # SPL-121: racing decisions notify the assigned coordinator once.
            "backend/tests/test_qa_spl121_postgres.py",
            # SPL-104: racing withdrawals and requests notify Venue Staff once.
            "backend/tests/test_qa_spl104_postgres.py",
            # SPL-124: racing registrations, withdrawals and cancellations notify attendees once.
            "backend/tests/test_qa_spl124_postgres.py",
            # SPL-123: organiser notices commit once with their lifecycle action.
            "backend/tests/test_qa_spl123_postgres.py",
            # SPL-105: racing completions complete once; the completion migration round-trips.
            "backend/tests/test_qa_spl105_postgres.py",
            # SPL-133: expiry racing approval expires once; the hold-expiry migration and cutover.
            "backend/tests/test_qa_spl133_postgres.py",
            # SPL-125: email row locking, restart pick-up, role backfill, checks and grants.
            "backend/tests/test_qa_spl125_postgres.py",
            "-q",
        )
    elif cmd == "dev":
        if not (ROOT / ".env").exists() or not (ROOT / "frontend/.env.local").exists():
            raise RuntimeError("Local configuration missing. Run npm run setup first.")
        processes = []
        try:
            commands = [
                [
                    "uv",
                    "run",
                    "--frozen",
                    "flask",
                    "--app",
                    "backend.app:create_app",
                    "run",
                    "--debug",
                    "--port",
                    "5000",
                ],
                ["pnpm", "dev"],
            ]
            for args in commands:
                processes.append(
                    subprocess.Popen(
                        command_args(args),
                        env={**os.environ, "PYTHONPATH": "backend"},
                        start_new_session=os.name != "nt",
                        creationflags=(
                            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                        ),
                    )
                )
            while all(p.poll() is None for p in processes):
                time.sleep(0.5)
            raise RuntimeError("A development server exited. Check its output above.")
        except KeyboardInterrupt:
            pass
        finally:
            for p in processes:
                stop_process(p)
    elif cmd == "browser-install":
        run("pnpm", "exec", "playwright", "install", "chromium")
    elif cmd == "e2e":
        run("pnpm", "e2e")
    elif cmd == "budget":
        run(sys.executable, "scripts/budget.py")
    elif cmd == "package-source":
        run(sys.executable, "scripts/package_source.py")
    elif cmd == "stop":
        run("pnpm", "exec", "supabase", "stop")
    else:
        print(
            "Commands: doctor setup dev migrate verify coverage-spl71 coverage-spl72 "
            "coverage-spl73 coverage-spl75 coverage-spl85 coverage-spl131 coverage-spl86 "
            "integration "
            "stop browser-install e2e budget"
        )
        if cmd != "help":
            raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        sys.exit(1)
