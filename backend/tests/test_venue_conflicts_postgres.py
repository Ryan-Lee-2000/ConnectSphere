"""PostgreSQL concurrency proof for SPL-83's venue-slot uniqueness boundary."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from app.models import (
    Account,
    EventRequest,
    Organisation,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
)
from app.venue_conflicts import VenueOccupancyConflict, claim_venue_occupancy
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(os.environ["INTEGRATION_DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture
def concurrent_bookings(engine):
    account_id = str(uuid.uuid4())
    with Session(engine) as session:
        organisation = Organisation(name=f"Conflict Client {uuid.uuid4()}")
        account = Account(id=account_id, display_name="Concurrency Coordinator")
        venue = Venue(
            name=f"Concurrency Hall {uuid.uuid4()}",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=1,
            turnaround_buffer_slots=1,
        )
        session.add_all([organisation, account, venue])
        session.flush()
        request = EventRequest(
            organiser_account_id=account.id,
            organisation_id=organisation.id,
            name="Concurrent booking test",
            status="planning",
        )
        session.add(request)
        session.flush()
        bookings = [
            VenueBooking(
                event_request_id=request.id,
                venue_id=venue.id,
                status="requested",
            )
            for _ in range(2)
        ]
        session.add_all(bookings)
        session.commit()
        scenario = {
            "account_id": account_id,
            "organisation_id": organisation.id,
            "event_request_id": request.id,
            "venue_id": venue.id,
            "booking_ids": [booking.id for booking in bookings],
        }

    yield scenario

    with Session(engine) as session:
        session.execute(
            delete(VenueBookingOccupancy).where(
                VenueBookingOccupancy.booking_id.in_(scenario["booking_ids"])
            )
        )
        session.execute(delete(VenueBooking).where(VenueBooking.id.in_(scenario["booking_ids"])))
        session.execute(delete(EventRequest).where(EventRequest.id == scenario["event_request_id"]))
        session.execute(delete(Venue).where(Venue.id == scenario["venue_id"]))
        session.execute(delete(Account).where(Account.id == scenario["account_id"]))
        session.execute(delete(Organisation).where(Organisation.id == scenario["organisation_id"]))
        session.commit()


def test_tc_spl_83_06_at_most_one_concurrent_claim_succeeds(engine, concurrent_bookings):
    barrier = threading.Barrier(2, timeout=10)
    first_insert_threads: set[int] = set()
    lock = threading.Lock()

    def align_first_occupancy_insert(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        if not statement.lstrip().startswith("INSERT INTO venue_booking_occupancy"):
            return
        thread_id = threading.get_ident()
        with lock:
            if thread_id in first_insert_threads:
                return
            first_insert_threads.add(thread_id)
        barrier.wait()

    event.listen(engine, "before_cursor_execute", align_first_occupancy_insert)

    def claim(booking_id):
        with Session(engine) as session:
            booking = session.get(VenueBooking, booking_id)
            try:
                claim_venue_occupancy(
                    session,
                    booking,
                    event_slots=[(date(2026, 10, 8), "PM")],
                )
                session.commit()
                return "success"
            except VenueOccupancyConflict:
                session.rollback()
                return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, concurrent_bookings["booking_ids"]))
    finally:
        event.remove(engine, "before_cursor_execute", align_first_occupancy_insert)

    assert sorted(results) == ["conflict", "success"]
    with Session(engine) as session:
        occupied = session.scalars(
            select(VenueBookingOccupancy).where(
                VenueBookingOccupancy.booking_id.in_(concurrent_bookings["booking_ids"])
            )
        ).all()
        assert len(occupied) == 3
        assert (
            session.scalar(
                select(func.count(func.distinct(VenueBookingOccupancy.booking_id))).where(
                    VenueBookingOccupancy.booking_id.in_(concurrent_bookings["booking_ids"])
                )
            )
            == 1
        )
