"""Prepare repeatable local-only equipment data for the SPL-90/95/97 browser journeys."""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Account, AccountRole, Role  # noqa: E402

from scripts.equipment_e2e_fixtures import (  # noqa: E402
    prepare_arrangement_fixture,
    prepare_cancellation_fixture,
    prepare_confirmation_fixture,
    prepare_equipment_fixtures,
)

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "frontend/.env.local")
database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("E2E fixture preparation is local-only and refuses a non-local database.")

engine = create_engine(database_url)


def fixture_account(session: Session, email: str, role: Role) -> Account:
    """Resolve the browser's exact local Auth fixture, then verify its trusted application role.

    This script uses the local migration connection, never exposes Auth data to a browser, and
    never chooses a different developer's account merely because it sorts first by UUID.
    """
    account_id = session.scalar(
        text("SELECT id FROM auth.users WHERE email = :email"), {"email": email}
    )
    account = session.get(Account, str(account_id)) if account_id is not None else None
    if (
        account is None
        or not account.is_active
        or session.scalar(
            select(AccountRole.account_id).where(
                AccountRole.account_id == account.id,
                AccountRole.role == role.value,
            )
        )
        is None
    ):
        raise SystemExit(
            f"Run npm run setup first: the local {role.value} Auth fixture is missing or inactive."
        )
    return account


try:
    with Session(engine) as session, session.begin():
        organiser = fixture_account(
            session,
            os.getenv("VITE_LOCAL_DEMO_EMAIL", "developer@example.test"),
            Role.EVENT_ORGANISER,
        )
        technician = fixture_account(
            session,
            os.getenv("VITE_LOCAL_DEMO_TECHNICAL_SUPPORT_EMAIL", "technical.support@example.test"),
            Role.TECHNICAL_SUPPORT_STAFF,
        )
        coordinator = fixture_account(
            session,
            os.getenv("VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL", "event.coordinator@example.test"),
            Role.EVENT_COORDINATOR,
        )
        manager = fixture_account(
            session,
            os.getenv(
                "VITE_LOCAL_DEMO_OPERATIONS_MANAGER_EMAIL", "operations.manager@example.test"
            ),
            Role.EVENT_OPERATIONS_MANAGER,
        )
        if organiser.organisation_id is None:
            raise SystemExit("Local Event Organiser fixture needs an organisation.")
        prepare_equipment_fixtures(
            session,
            organiser=organiser,
            technician=technician,
            coordinator=coordinator,
            manager=manager,
        )
        # SPL-85's, SPL-131's and SPL-86's scenarios also need the Venue Staff fixture as the
        # booking approver.
        # Optional, so the SPL-90/95/97 scenarios above never depend on that extra account.
        try:
            venue_staff = fixture_account(
                session,
                os.getenv("VITE_LOCAL_DEMO_VENUE_STAFF_EMAIL", "venue.staff@example.test"),
                Role.VENUE_STAFF,
            )
        except SystemExit:
            print("Skipped the SPL-85, SPL-131 and SPL-86 scenarios: no local Venue Staff fixture.")
        else:
            # SPL-131's several-venue journey also has Venue Staff approve a booking.
            prepare_arrangement_fixture(
                session, organiser=organiser, coordinator=coordinator, manager=manager
            )
            prepare_confirmation_fixture(
                session,
                organiser=organiser,
                technician=technician,
                coordinator=coordinator,
                manager=manager,
                venue_staff=venue_staff,
            )
            # SPL-86's cancellation journey: an approved and a requested booking plus held units.
            prepare_cancellation_fixture(
                session,
                organiser=organiser,
                technician=technician,
                coordinator=coordinator,
                manager=manager,
                venue_staff=venue_staff,
            )
finally:
    engine.dispose()
