"""PostgreSQL concurrency proof for SPL-83's venue-slot uniqueness boundary."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest
from app.models import (
    Account,
    EventRequest,
    Organisation,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueOperationalBlock,
)
from app.venue_conflicts import VenueOccupancyConflict, claim_venue_occupancy
from app.venue_operational_blocks import record_operational_block
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


@pytest.fixture
def booking_block_race(engine):
    account_id = str(uuid.uuid4())
    with Session(engine) as session:
        organisation = Organisation(name=f"Block Race Client {uuid.uuid4()}")
        account = Account(id=account_id, display_name="Block Race Staff")
        venue = Venue(
            name=f"Block Race Hall {uuid.uuid4()}",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        session.add_all([organisation, account, venue])
        session.flush()
        request = EventRequest(
            organiser_account_id=account.id,
            organisation_id=organisation.id,
            name="Booking and block race test",
            status="planning",
        )
        session.add(request)
        session.flush()
        booking = VenueBooking(
            event_request_id=request.id,
            venue_id=venue.id,
            status="requested",
        )
        session.add(booking)
        session.commit()
        scenario = {
            "account_id": account_id,
            "organisation_id": organisation.id,
            "event_request_id": request.id,
            "venue_id": venue.id,
            "booking_id": booking.id,
        }

    yield scenario

    with Session(engine) as session:
        session.execute(
            delete(VenueOperationalBlock).where(
                VenueOperationalBlock.venue_id == scenario["venue_id"]
            )
        )
        session.execute(
            delete(VenueBookingOccupancy).where(
                VenueBookingOccupancy.booking_id == scenario["booking_id"]
            )
        )
        session.execute(delete(VenueBooking).where(VenueBooking.id == scenario["booking_id"]))
        session.execute(delete(EventRequest).where(EventRequest.id == scenario["event_request_id"]))
        session.execute(delete(Venue).where(Venue.id == scenario["venue_id"]))
        session.execute(delete(Account).where(Account.id == scenario["account_id"]))
        session.execute(delete(Organisation).where(Organisation.id == scenario["organisation_id"]))
        session.commit()


def test_tc_spl_83_06_at_most_one_concurrent_claim_succeeds(engine, concurrent_bookings):
    barrier = threading.Barrier(2, timeout=10)
    first_lock_threads: set[int] = set()
    lock = threading.Lock()

    def align_first_shared_slot_lock(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        if "pg_advisory_xact_lock" not in statement:
            return
        thread_id = threading.get_ident()
        with lock:
            if thread_id in first_lock_threads:
                return
            first_lock_threads.add(thread_id)
        barrier.wait()

    event.listen(engine, "before_cursor_execute", align_first_shared_slot_lock)

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
        event.remove(engine, "before_cursor_execute", align_first_shared_slot_lock)

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


def test_tc_spl_89_09_booking_and_block_writes_cannot_create_unmarked_overlap(
    engine, booking_block_race
):
    barrier = threading.Barrier(2, timeout=10)
    first_lock_threads: set[int] = set()
    guard = threading.Lock()

    def align_first_shared_slot_lock(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        if "pg_advisory_xact_lock" not in statement:
            return
        thread_id = threading.get_ident()
        with guard:
            if thread_id in first_lock_threads:
                return
            first_lock_threads.add(thread_id)
        barrier.wait()

    event.listen(engine, "before_cursor_execute", align_first_shared_slot_lock)

    def claim_booking():
        with Session(engine) as session:
            booking = session.get(VenueBooking, booking_block_race["booking_id"])
            try:
                claim_venue_occupancy(
                    session,
                    booking,
                    event_slots=[(date(2026, 10, 9), "PM")],
                )
                session.commit()
                return "claimed"
            except VenueOccupancyConflict:
                session.rollback()
                return "blocked"

    def create_block():
        with Session(engine) as session:
            record_operational_block(
                session,
                venue_id=booking_block_race["venue_id"],
                attributes={
                    "start_date": date(2026, 10, 9),
                    "end_date": date(2026, 10, 9),
                    "slots": ["PM"],
                    "reason": "Concurrent maintenance",
                },
                created_by_account_id=booking_block_race["account_id"],
                created_at=datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc),
            )
            session.commit()
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claim_future = executor.submit(claim_booking)
            block_future = executor.submit(create_block)
            claim_result = claim_future.result(timeout=15)
            assert block_future.result(timeout=15) == "created"
    finally:
        event.remove(engine, "before_cursor_execute", align_first_shared_slot_lock)

    with Session(engine) as session:
        booking = session.get(VenueBooking, booking_block_race["booking_id"])
        occupancy_count = session.scalar(
            select(func.count(VenueBookingOccupancy.id)).where(
                VenueBookingOccupancy.booking_id == booking.id
            )
        )
        assert (
            session.scalar(
                select(func.count(VenueOperationalBlock.id)).where(
                    VenueOperationalBlock.venue_id == booking_block_race["venue_id"]
                )
            )
            == 1
        )
        if claim_result == "claimed":
            assert occupancy_count == 1
            assert booking.requires_review is True
            assert booking.review_trigger_block_id is not None
            assert booking.review_marked_at is not None
        else:
            assert claim_result == "blocked"
            assert occupancy_count == 0
            assert booking.requires_review is False
