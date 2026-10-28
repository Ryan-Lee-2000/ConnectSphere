"""Create disposable local-only SPL-133 browser-evidence fixtures.

Two Planning events assigned to the local coordinator on 10 Feb 2031, each with its own venue:
"E2E SPL-133 Harbour Launch" has no booking yet (the walkthrough requests one), and
"E2E SPL-133 Riverside Forum" holds a Requested booking whose deadline passed a minute ago, so the
first request of the walkthrough expires it. Rerunning replaces both.
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
    EmailDelivery,
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    Role,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingStatusHistory,
    VenueLayout,
)

PREFIX = "E2E SPL-133 "
LAUNCH = "E2E SPL-133 Harbour Launch"
FORUM = "E2E SPL-133 Riverside Forum"
HARBOUR_ROOM = "E2E SPL-133 Harbour Room"
RIVER_ROOM = "E2E SPL-133 River Room"
DAY = date(2031, 2, 10)

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-133 fixtures are local-only and refuse a non-local database.")


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
    event_ids = session.scalars(
        select(EventRequest.id).where(EventRequest.name.like(f"{PREFIX}%"))
    ).all()
    venue_ids = session.scalars(select(Venue.id).where(Venue.name.like(f"{PREFIX}%"))).all()
    booking_ids = session.scalars(
        select(VenueBooking.id).where(
            (VenueBooking.event_request_id.in_(event_ids)) | (VenueBooking.venue_id.in_(venue_ids))
        )
    ).all()
    if booking_ids:
        session.execute(
            delete(VenueBookingStatusHistory).where(
                VenueBookingStatusHistory.booking_id.in_(booking_ids)
            )
        )
        session.execute(delete(VenueBooking).where(VenueBooking.id.in_(booking_ids)))
    if event_ids:
        notice_ids = select(Notification.id).where(Notification.event_request_id.in_(event_ids))
        # SPL-125: email records block deleting their notices, so they go first.
        session.execute(delete(EmailDelivery).where(EmailDelivery.notification_id.in_(notice_ids)))
        session.execute(delete(Notification).where(Notification.event_request_id.in_(event_ids)))
        session.execute(delete(EventRequest).where(EventRequest.id.in_(event_ids)))
    if venue_ids:
        session.execute(delete(Venue).where(Venue.id.in_(venue_ids)))
    session.flush()


def venue(name: str) -> Venue:
    row = Venue(
        name=name,
        location="E2E Test Location",
        facilities=["Projector"],
        operating_slots=["AM", "PM", "NIGHT"],
        setup_buffer_slots=0,
        turnaround_buffer_slots=0,
    )
    row.layouts = [VenueLayout(layout="theatre", capacity=150)]
    return row


def event(name: str, organiser: Account) -> EventRequest:
    return EventRequest(
        organiser_account_id=organiser.id,
        organisation_id=organiser.organisation_id,
        name=name,
        purpose="Local browser evidence only",
        proposed_date=DAY,
        start_time=time(14),
        end_time=time(17),
        expected_attendance=80,
        preferred_room_layout="theatre",
        required_facilities=["Projector"],
        status="planning",
    )


def main() -> None:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session, session.begin():
            coordinator = account(
                session,
                os.getenv(
                    "VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL", "event.coordinator@example.test"
                ),
                Role.EVENT_COORDINATOR,
            )
            manager = account(
                session,
                os.getenv(
                    "VITE_LOCAL_DEMO_OPERATIONS_MANAGER_EMAIL", "operations.manager@example.test"
                ),
                Role.EVENT_OPERATIONS_MANAGER,
            )
            organiser = account(
                session,
                os.getenv("VITE_LOCAL_DEMO_EMAIL", "developer@example.test"),
                Role.EVENT_ORGANISER,
            )
            remove_existing(session)
            now = datetime.now(SINGAPORE)
            harbour, river = venue(HARBOUR_ROOM), venue(RIVER_ROOM)
            launch, forum = event(LAUNCH, organiser), event(FORUM, organiser)
            session.add_all([harbour, river, launch, forum])
            session.flush()
            for row in (launch, forum):
                session.add(
                    EventCoordinatorAssignment(
                        event_request_id=row.id,
                        coordinator_account_id=coordinator.id,
                        assigned_by_account_id=manager.id,
                        assigned_at=now - timedelta(days=10),
                    )
                )
            hold = VenueBooking(
                event_request_id=forum.id,
                venue_id=river.id,
                status="requested",
                layout="theatre",
                expected_attendance=80,
                required_facilities=["Projector"],
                booking_date=DAY,
                event_slots=["PM"],
                requested_by_account_id=coordinator.id,
                requested_at=now - timedelta(days=7, minutes=1),
                expires_at=now - timedelta(minutes=1),
            )
            session.add(hold)
            session.flush()
            session.add(
                VenueBookingOccupancy(
                    booking_id=hold.id, venue_id=river.id, day=DAY, slot="PM", kind="event"
                )
            )
            session.add(
                VenueBookingStatusHistory(
                    booking_id=hold.id,
                    action="request",
                    previous_status=None,
                    resulting_status="requested",
                    actor_account_id=coordinator.id,
                    changed_at=hold.requested_at,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
