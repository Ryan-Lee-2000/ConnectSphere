from datetime import UTC, date, datetime

import pytest
from app import create_app
from app.models import (
    Account,
    Base,
    EventRequest,
    Organisation,
    Venue,
    VenueBooking,
    VenueOperationalBlock,
)
from app.venue_conflicts import (
    VenueOccupancyConflict,
    claim_venue_occupancy,
    occupancy_for_booking,
    transition_booking_status,
)
from sqlalchemy.orm import Session

ACCOUNT_ID = "00000000-0000-0000-0000-000000000083"


@pytest.fixture
def conflict_app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/venue-conflicts.db",
            "IDENTITY_VERIFIER": lambda _token: ACCOUNT_ID,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Conflict Test Client")
        account = Account(id=ACCOUNT_ID, display_name="Casey Coordinator")
        venue = Venue(
            name="Harbour Hall",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=1,
            turnaround_buffer_slots=1,
        )
        session.add_all([organisation, account, venue])
        session.flush()
        event = EventRequest(
            organiser_account_id=account.id,
            organisation_id=organisation.id,
            name="Community Forum",
            status="planning",
        )
        session.add(event)
        session.commit()
        app.config.update(TEST_EVENT_ID=event.id, TEST_VENUE_ID=venue.id)
    yield app
    engine.dispose()


@pytest.mark.parametrize("active_status", ["requested", "approved"])
def test_tc_spl_83_01_active_booking_claims_event_and_preparation_slots(
    conflict_app, active_status
):
    engine = conflict_app.extensions["engine"]
    with Session(engine) as session:
        booking = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=conflict_app.config["TEST_VENUE_ID"],
            status=active_status,
        )
        session.add(booking)
        session.flush()

        claim_venue_occupancy(
            session,
            booking,
            event_slots=[(date(2026, 10, 8), "PM")],
        )
        session.commit()

        assert [
            (occupied.day, occupied.slot, occupied.kind)
            for occupied in occupancy_for_booking(session, booking.id)
        ] == [
            (date(2026, 10, 8), "AM", "setup"),
            (date(2026, 10, 8), "PM", "event"),
            (date(2026, 10, 8), "NIGHT", "turnaround"),
        ]


def test_tc_spl_83_02_operational_block_refuses_the_whole_claim_with_date_and_slot(
    conflict_app,
):
    engine = conflict_app.extensions["engine"]
    with Session(engine) as session:
        session.add(
            VenueOperationalBlock(
                venue_id=conflict_app.config["TEST_VENUE_ID"],
                start_date=date(2026, 10, 8),
                end_date=date(2026, 10, 8),
                slots=["PM"],
                reason="Safety inspection",
                created_by_account_id=ACCOUNT_ID,
                created_at=datetime.now(UTC),
            )
        )
        booking = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=conflict_app.config["TEST_VENUE_ID"],
            status="requested",
        )
        session.add(booking)
        session.flush()

        with pytest.raises(VenueOccupancyConflict) as refused:
            claim_venue_occupancy(
                session,
                booking,
                event_slots=[(date(2026, 10, 8), "PM")],
            )

        assert refused.value.day == date(2026, 10, 8)
        assert refused.value.slot == "PM"
        assert refused.value.source == "operational_block"
        assert occupancy_for_booking(session, booking.id) == ()


def test_tc_spl_83_03_requested_booking_refuses_a_second_claim_for_the_same_slot(
    conflict_app,
):
    engine = conflict_app.extensions["engine"]
    with Session(engine) as session:
        first = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=conflict_app.config["TEST_VENUE_ID"],
            status="requested",
        )
        second = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=conflict_app.config["TEST_VENUE_ID"],
            status="requested",
        )
        session.add_all([first, second])
        session.flush()
        claim_venue_occupancy(
            session,
            first,
            event_slots=[(date(2026, 10, 8), "PM")],
        )

        with pytest.raises(VenueOccupancyConflict) as refused:
            claim_venue_occupancy(
                session,
                second,
                event_slots=[(date(2026, 10, 8), "PM")],
            )

        assert refused.value.day == date(2026, 10, 8)
        assert refused.value.slot == "AM"
        assert refused.value.source == "booking"
        assert occupancy_for_booking(session, second.id) == ()

        later = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=first.venue_id,
            status="requested",
        )
        other_venue = Venue(
            name="Garden Room",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        session.add_all([later, other_venue])
        session.flush()
        elsewhere = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=other_venue.id,
            status="requested",
        )
        session.add(elsewhere)
        session.flush()

        claim_venue_occupancy(
            session,
            later,
            event_slots=[(date(2026, 10, 9), "PM")],
        )
        claim_venue_occupancy(
            session,
            elsewhere,
            event_slots=[(date(2026, 10, 8), "PM")],
        )

        assert len(occupancy_for_booking(session, later.id)) == 3
        assert len(occupancy_for_booking(session, elsewhere.id)) == 1


@pytest.mark.parametrize("terminal_status", ["rejected", "withdrawn", "cancelled"])
def test_tc_spl_83_04_terminal_booking_releases_occupancy(conflict_app, terminal_status):
    engine = conflict_app.extensions["engine"]
    with Session(engine) as session:
        first = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=conflict_app.config["TEST_VENUE_ID"],
            status="requested",
        )
        session.add(first)
        session.flush()
        claim_venue_occupancy(
            session,
            first,
            event_slots=[(date(2026, 10, 8), "PM")],
        )

        transition_booking_status(session, first, terminal_status)

        assert first.status == terminal_status
        assert occupancy_for_booking(session, first.id) == ()
        replacement = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=conflict_app.config["TEST_VENUE_ID"],
            status="requested",
        )
        session.add(replacement)
        session.flush()
        claim_venue_occupancy(
            session,
            replacement,
            event_slots=[(date(2026, 10, 8), "PM")],
        )
        assert len(occupancy_for_booking(session, replacement.id)) == 3


def test_tc_spl_83_05_approval_rechecks_operational_blocks_without_changing_booking(
    conflict_app,
):
    engine = conflict_app.extensions["engine"]
    with Session(engine) as session:
        booking = VenueBooking(
            event_request_id=conflict_app.config["TEST_EVENT_ID"],
            venue_id=conflict_app.config["TEST_VENUE_ID"],
            status="requested",
        )
        session.add(booking)
        session.flush()
        claim_venue_occupancy(
            session,
            booking,
            event_slots=[(date(2026, 10, 8), "PM")],
        )
        session.add(
            VenueOperationalBlock(
                venue_id=booking.venue_id,
                start_date=date(2026, 10, 8),
                end_date=date(2026, 10, 8),
                slots=["PM"],
                reason="Emergency maintenance",
                created_by_account_id=ACCOUNT_ID,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()

        with pytest.raises(VenueOccupancyConflict) as refused:
            transition_booking_status(session, booking, "approved")

        assert refused.value.day == date(2026, 10, 8)
        assert refused.value.slot == "PM"
        assert booking.status == "requested"
        assert len(occupancy_for_booking(session, booking.id)) == 3
