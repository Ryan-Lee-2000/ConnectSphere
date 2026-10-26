"""Create disposable local-only SPL-105 browser-evidence fixtures.

Two Preparing events assigned to the local coordinator: one that ended two days ago (it can be
completed) and one that ends in 2031 (completion is not yet available). Rerunning replaces them.
"""
# ruff: noqa: E501

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
load_dotenv(ROOT / ".env")

from app.event_requests import SINGAPORE  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    AccountRole,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Role,
    Venue,
    VenueBooking,
)

PREFIX = "E2E SPL-105 "
ENDED = "E2E SPL-105 Harbour Awards Night"
UPCOMING = "E2E SPL-105 Riverside Gala"

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-105 fixtures are local-only and refuse a non-local database.")


def account(session: Session, email: str, role: Role) -> Account:
    account_id = session.scalar(
        text("SELECT id FROM auth.users WHERE email = :email"), {"email": email}
    )
    row = session.get(Account, str(account_id)) if account_id else None
    if (
        row is None
        or session.scalar(
            select(AccountRole.account_id).where(
                AccountRole.account_id == row.id, AccountRole.role == role.value
            )
        )
        is None
    ):
        raise SystemExit(f"Run npm run setup first: {role.value} fixture is missing.")
    return row


def remove_existing(session: Session) -> None:
    ids = session.scalars(select(EventRequest.id).where(EventRequest.name.like(f"{PREFIX}%"))).all()
    if ids:
        session.execute(delete(EventStatusHistory).where(EventStatusHistory.event_request_id.in_(ids)))
        for event in session.scalars(select(EventRequest).where(EventRequest.id.in_(ids))).all():
            session.delete(event)
        session.flush()


engine = create_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        coordinator = account(
            session,
            os.getenv("VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL", "event.coordinator@example.test"),
            Role.EVENT_COORDINATOR,
        )
        manager = account(
            session,
            os.getenv("VITE_LOCAL_DEMO_OPERATIONS_MANAGER_EMAIL", "operations.manager@example.test"),
            Role.EVENT_OPERATIONS_MANAGER,
        )
        organiser = account(
            session, os.getenv("VITE_LOCAL_DEMO_EMAIL", "developer@example.test"), Role.EVENT_ORGANISER
        )
        staff = account(
            session, os.getenv("VITE_LOCAL_DEMO_VENUE_STAFF_EMAIL", "venue.staff@example.test"), Role.VENUE_STAFF
        )
        remove_existing(session)
        venue = session.scalar(select(Venue).where(Venue.layouts.any()).order_by(Venue.id))
        if venue is None:
            raise SystemExit("Run npm run setup first: a venue with a layout is required.")
        layout = venue.layouts[0]
        now = datetime.now(SINGAPORE)
        for name, day in ((ENDED, now.date() - timedelta(days=2)), (UPCOMING, date(2031, 1, 22))):
            event = EventRequest(
                organiser_account_id=organiser.id,
                organisation_id=organiser.organisation_id,
                name=name,
                purpose="Disposable event-completion evidence event",
                proposed_date=day,
                start_time=time(10),
                end_time=time(12),
                expected_attendance=min(20, layout.capacity),
                status="preparing",
                submitted_at=now - timedelta(days=30),
            )
            session.add(event)
            session.flush()
            session.add(
                EventCoordinatorAssignment(
                    event_request_id=event.id,
                    coordinator_account_id=coordinator.id,
                    assigned_by_account_id=manager.id,
                    assigned_at=now - timedelta(days=29),
                )
            )
            session.add(
                VenueBooking(
                    event_request_id=event.id,
                    venue_id=venue.id,
                    status="approved",
                    layout=layout.layout,
                    expected_attendance=min(20, layout.capacity),
                    booking_date=day,
                    event_slots=["AM"],
                    requested_by_account_id=coordinator.id,
                    requested_at=now - timedelta(days=20),
                    approved_by_account_id=staff.id,
                    approved_at=now - timedelta(days=19),
                )
            )
finally:
    engine.dispose()
