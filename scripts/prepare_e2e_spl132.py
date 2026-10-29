"""Create disposable local-only SPL-132 browser-evidence fixtures.

"E2E SPL-132 Coastal Forum" is Confirmed for 10 Mar 2031 (PM), assigned to the local coordinator,
with Approved PM bookings at its Harbour Hall (the room Venue Staff later block), Breakout Studio
and Garden Terrace. Lakeside Room and Riverside Room are free for the replacement requests.
Rerunning replaces everything with the "E2E SPL-132 " prefix.
"""
# ruff: noqa: E501

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "scripts")]
load_dotenv(ROOT / ".env")

from app.event_requests import SINGAPORE  # noqa: E402
from app.models import (  # noqa: E402
    EmailDelivery,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Notification,
    Role,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingReviewFinding,
    VenueBookingStatusHistory,
    VenueLayout,
    VenueOperationalBlock,
)
from prepare_e2e_hold_expiry import account  # noqa: E402

PREFIX = "E2E SPL-132 "
EVENT = "E2E SPL-132 Coastal Forum"
BOOKED = ("E2E SPL-132 Harbour Hall", "E2E SPL-132 Breakout Studio", "E2E SPL-132 Garden Terrace")
SPARE = ("E2E SPL-132 Lakeside Room", "E2E SPL-132 Riverside Room")
DAY = date(2031, 3, 10)

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-132 fixtures are local-only and refuse a non-local database.")


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
        for model in (VenueBookingStatusHistory, VenueBookingReviewFinding):
            session.execute(delete(model).where(model.booking_id.in_(booking_ids)))
        session.execute(
            delete(VenueBookingOccupancy).where(VenueBookingOccupancy.booking_id.in_(booking_ids))
        )
        # Replacements point at their originals, so the links go before the rows.
        session.execute(
            VenueBooking.__table__.update()
            .where(VenueBooking.id.in_(booking_ids))
            .values(replaces_booking_id=None, review_trigger_block_id=None)
        )
        session.execute(delete(VenueBooking).where(VenueBooking.id.in_(booking_ids)))
    if event_ids:
        notice_ids = select(Notification.id).where(Notification.event_request_id.in_(event_ids))
        # SPL-125: email records block deleting their notices, so they go first.
        session.execute(delete(EmailDelivery).where(EmailDelivery.notification_id.in_(notice_ids)))
        session.execute(delete(Notification).where(Notification.event_request_id.in_(event_ids)))
        session.execute(
            delete(EventStatusHistory).where(EventStatusHistory.event_request_id.in_(event_ids))
        )
        session.execute(delete(EventRequest).where(EventRequest.id.in_(event_ids)))
    if venue_ids:
        session.execute(
            delete(VenueOperationalBlock).where(VenueOperationalBlock.venue_id.in_(venue_ids))
        )
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
            staff = account(
                session,
                os.getenv("VITE_LOCAL_DEMO_VENUE_STAFF_EMAIL", "venue.staff@example.test"),
                Role.VENUE_STAFF,
            )
            organiser = account(
                session,
                os.getenv("VITE_LOCAL_DEMO_EMAIL", "developer@example.test"),
                Role.EVENT_ORGANISER,
            )
            remove_existing(session)
            now = datetime.now(SINGAPORE)
            rooms = [venue(name) for name in BOOKED + SPARE]
            forum = EventRequest(
                organiser_account_id=organiser.id,
                organisation_id=organiser.organisation_id,
                name=EVENT,
                purpose="Local browser evidence only",
                proposed_date=DAY,
                start_time=time(14),
                end_time=time(17),
                expected_attendance=80,
                preferred_room_layout="theatre",
                required_facilities=["Projector"],
                status="confirmed",
                confirmed_by_account_id=coordinator.id,
                confirmed_at=now - timedelta(days=1),
            )
            session.add_all([*rooms, forum])
            session.flush()
            session.add(
                EventCoordinatorAssignment(
                    event_request_id=forum.id,
                    coordinator_account_id=coordinator.id,
                    assigned_by_account_id=manager.id,
                    assigned_at=now - timedelta(days=10),
                )
            )
            for room, attendees in zip(rooms[:3], (80, 30, 20), strict=True):
                booking = VenueBooking(
                    event_request_id=forum.id,
                    venue_id=room.id,
                    status="approved",
                    layout="theatre",
                    expected_attendance=attendees,
                    required_facilities=["Projector"],
                    booking_date=DAY,
                    event_slots=["PM"],
                    requested_by_account_id=coordinator.id,
                    requested_at=now - timedelta(days=5),
                    approved_by_account_id=staff.id,
                    approved_at=now - timedelta(days=4),
                )
                session.add(booking)
                session.flush()
                session.add(
                    VenueBookingOccupancy(
                        booking_id=booking.id, venue_id=room.id, day=DAY, slot="PM", kind="event"
                    )
                )
                for action, previous, resulting, actor, at in (
                    ("request", None, "requested", coordinator.id, booking.requested_at),
                    ("approve", "requested", "approved", staff.id, booking.approved_at),
                ):
                    session.add(
                        VenueBookingStatusHistory(
                            booking_id=booking.id,
                            action=action,
                            previous_status=previous,
                            resulting_status=resulting,
                            actor_account_id=actor,
                            changed_at=at,
                        )
                    )
            print(forum.id)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
