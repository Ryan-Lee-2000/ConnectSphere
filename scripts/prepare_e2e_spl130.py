"""Prepare isolated real-Auth browser fixtures for SPL-130."""

import os
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from app.exact_venue_availability import timing_for  # noqa: E402
from app.exact_venue_bookings import requirements  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    AccountRole,
    EmailDelivery,
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from app.venue_timing import parse_event_interval  # noqa: E402

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-130 browser fixtures are local-only.")

engine = create_engine(database_url)


def account_for(session: Session, role: Role) -> Account:
    account = session.scalar(
        select(Account)
        .join(AccountRole)
        .where(AccountRole.role == role.value, Account.is_active.is_(True))
        .order_by(Account.id)
    )
    if account is None:
        raise SystemExit(f"Run scripts/seed.py first: no active {role.value} fixture exists.")
    return account


def add_event(
    session: Session,
    *,
    name: str,
    organiser: Account,
    coordinator: Account,
    manager: Account,
    organisation: Organisation,
    venue: Venue,
    start: time,
    end: time,
    booking_status: str,
) -> VenueBooking:
    event = EventRequest(
        organiser_account_id=organiser.id,
        organisation_id=organisation.id,
        name=name,
        purpose="SPL-130 isolated browser evidence",
        proposed_date=date(2026, 12, 20),
        start_time=start,
        end_time=end,
        expected_attendance=40,
        preferred_room_layout="theatre",
        required_facilities=[],
        accessibility_needs=[],
        status="planning",
    )
    session.add(event)
    session.flush()
    session.add(
        EventCoordinatorAssignment(
            event_request_id=event.id,
            coordinator_account_id=coordinator.id,
            assigned_by_account_id=manager.id,
            assigned_at=datetime.now(timezone.utc),
        )
    )
    event_interval = parse_event_interval(
        event.proposed_date.isoformat(), start.strftime("%H:%M"), end.strftime("%H:%M")
    )
    _, exact_timing = timing_for(venue, event_interval)
    booking = VenueBooking(
        event_request_id=event.id,
        venue_id=venue.id,
        status=booking_status,
        exact_timing=exact_timing,
        reviewed_requirements=requirements(event),
        layout="theatre",
        expected_attendance=40,
        booking_date=event.proposed_date,
        requested_by_account_id=coordinator.id,
        requested_at=datetime.now(timezone.utc),
    )
    if booking_status == "approved":
        booking.approved_by_account_id = manager.id
        booking.approved_at = datetime.now(timezone.utc)
    session.add(booking)
    session.flush()
    return booking


try:
    with Session(engine) as session, session.begin():
        # SPL-125: email records block deleting their notices, which the event delete cascades to.
        session.execute(
            delete(EmailDelivery).where(
                EmailDelivery.notification_id.in_(
                    select(Notification.id).where(
                        Notification.event_request_id.in_(
                            select(EventRequest.id).where(
                                EventRequest.name.like("SPL-130 Browser %")
                            )
                        )
                    )
                )
            )
        )
        prior_events = session.scalars(
            select(EventRequest).where(EventRequest.name.like("SPL-130 Browser %"))
        ).all()
        for event in prior_events:
            session.delete(event)
        session.flush()
        prior_venue = session.scalar(select(Venue).where(Venue.name == "SPL-130 Timing Hall"))
        if prior_venue is not None:
            session.delete(prior_venue)
            session.flush()

        organiser = account_for(session, Role.EVENT_ORGANISER)
        coordinator = account_for(session, Role.EVENT_COORDINATOR)
        manager = account_for(session, Role.EVENT_OPERATIONS_MANAGER)
        organisation = session.get(Organisation, organiser.organisation_id)
        if organisation is None:
            raise SystemExit("The local organiser fixture needs an organisation.")

        venue = Venue(
            name="SPL-130 Timing Hall",
            location="Isolated browser fixture",
            facilities=[],
            accessibility_features=[],
            operating_slots=["AM", "PM"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
            setup_minutes=0,
            turnaround_minutes=0,
            operating_intervals=[[540, 1080]],
            timing_revision=1,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=100)]
        session.add(venue)
        session.flush()
        requested = add_event(
            session,
            name="SPL-130 Browser Requested",
            organiser=organiser,
            coordinator=coordinator,
            manager=manager,
            organisation=organisation,
            venue=venue,
            start=time(10),
            end=time(11),
            booking_status="requested",
        )
        approved = add_event(
            session,
            name="SPL-130 Browser Approved",
            organiser=organiser,
            coordinator=coordinator,
            manager=manager,
            organisation=organisation,
            venue=venue,
            start=time(11),
            end=time(12),
            booking_status="approved",
        )
        print(f"SPL130_VENUE_NAME={venue.name}")
        print(f"SPL130_REQUESTED_BOOKING_ID={requested.id}")
        print(f"SPL130_APPROVED_BOOKING_ID={approved.id}")
        print(f"SPL130_REQUESTED_EVENT_ID={requested.event_request_id}")
finally:
    engine.dispose()
