from datetime import date, datetime

import pytest
from app import create_app
from app.models import (
    Account,
    AccountRole,
    Base,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueOperationalBlock,
)
from app.venue_operational_blocks import operational_block_for_slot
from sqlalchemy.orm import Session

VENUE_STAFF_ID = "00000000-0000-0000-0000-000000000089"


@pytest.fixture
def operational_block_app(tmp_path):
    identities = {
        "venue-staff": VENUE_STAFF_ID,
        "coordinator": "00000000-0000-0000-0000-000000000090",
    }
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/test.db",
            "IDENTITY_VERIFIER": identities.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(Account(id=account_id) for account_id in identities.values())
        organisation = Organisation(name="Operational Blocks Test Client")
        venue = Venue(
            name="Harbour Hall",
            location="Marina Centre",
            facilities=[],
            accessibility_features=[],
            operating_slots=["AM", "PM"],
        )
        session.add_all(
            [
                AccountRole(account_id=VENUE_STAFF_ID, role=Role.VENUE_STAFF.value),
                AccountRole(
                    account_id=identities["coordinator"], role=Role.EVENT_COORDINATOR.value
                ),
                organisation,
                venue,
            ]
        )
        session.flush()
        event = EventRequest(
            organiser_account_id=VENUE_STAFF_ID,
            organisation_id=organisation.id,
            name="Operations Conference",
            status="planning",
        )
        session.add(event)
        session.commit()
        app.config.update(TEST_EVENT_ID=event.id, TEST_VENUE_ID=venue.id)
    yield app
    engine.dispose()


@pytest.fixture
def client(operational_block_app):
    return operational_block_app.test_client()


def headers(token="venue-staff"):
    return {"Authorization": f"Bearer {token}"}


def test_tc_spl_89_01_venue_staff_records_an_active_operational_block(client):
    response = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-07",
            "slots": ["AM", "PM"],
            "reason": "Annual fire-safety inspection",
        },
        headers=headers(),
    )

    assert response.status_code == 201
    block = response.json["operational_block"]
    assert block["venue_id"] == 1
    assert block["start_date"] == "2026-10-05"
    assert block["end_date"] == "2026-10-07"
    assert block["slots"] == ["AM", "PM"]
    assert block["reason"] == "Annual fire-safety inspection"
    assert block["created_by_account_id"] == VENUE_STAFF_ID
    assert datetime.fromisoformat(block["created_at"]).tzinfo is not None
    assert block["removed_by_account_id"] is None
    assert block["removed_at"] is None

    listed = client.get("/api/venues/1/operational-blocks", headers=headers())
    assert listed.status_code == 200
    assert listed.json == {"operational_blocks": [block]}


def test_tc_spl_89_02_venue_staff_removes_only_the_selected_block_with_audit(client):
    first = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "Inspection",
        },
        headers=headers(),
    ).json["operational_block"]
    second = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-06",
            "end_date": "2026-10-06",
            "slots": ["PM"],
            "reason": "Maintenance",
        },
        headers=headers(),
    ).json["operational_block"]

    removed_response = client.delete(
        f"/api/venues/1/operational-blocks/{first['id']}", headers=headers()
    )

    assert removed_response.status_code == 200
    removed = removed_response.json["operational_block"]
    assert removed["id"] == first["id"]
    assert removed["removed_by_account_id"] == VENUE_STAFF_ID
    assert datetime.fromisoformat(removed["removed_at"]).tzinfo is not None

    active = client.get("/api/venues/1/operational-blocks", headers=headers())
    assert active.json == {"operational_blocks": [second]}


def test_tc_spl_89_03_invalid_or_unauthorised_attempts_leave_no_block(client):
    invalid_payloads = [
        {
            "start_date": "2026-10-07",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "Invalid date order",
        },
        {
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "   ",
        },
        {
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["NIGHT"],
            "reason": "Venue does not operate at night",
        },
    ]
    for payload in invalid_payloads:
        response = client.post("/api/venues/1/operational-blocks", json=payload, headers=headers())
        assert response.status_code == 400

    unauthorised = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "Forged block",
        },
        headers=headers("coordinator"),
    )
    assert unauthorised.status_code == 403

    active = client.get("/api/venues/1/operational-blocks", headers=headers())
    assert active.json == {"operational_blocks": []}


def test_tc_spl_89_04_active_blocks_feed_shared_availability_for_the_inclusive_range(
    client, operational_block_app
):
    created = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-07",
            "slots": ["AM"],
            "reason": "Inspection",
        },
        headers=headers(),
    ).json["operational_block"]

    engine = operational_block_app.extensions["engine"]
    with Session(engine) as session:
        for blocked_day in (date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)):
            assert operational_block_for_slot(session, 1, blocked_day, "AM").id == created["id"]
        assert operational_block_for_slot(session, 1, date(2026, 10, 8), "AM") is None
        assert operational_block_for_slot(session, 1, date(2026, 10, 6), "PM") is None

    client.delete(f"/api/venues/1/operational-blocks/{created['id']}", headers=headers())
    with Session(engine) as session:
        assert operational_block_for_slot(session, 1, date(2026, 10, 6), "AM") is None


def test_tc_spl_89_07_block_marks_only_overlapping_active_bookings_without_mutating_them(
    client, operational_block_app
):
    engine = operational_block_app.extensions["engine"]
    with Session(engine) as session:
        other_venue = Venue(name="Garden Room", operating_slots=["AM", "PM"])
        session.add(other_venue)
        session.flush()
        bookings = {
            "requested": VenueBooking(
                event_request_id=operational_block_app.config["TEST_EVENT_ID"],
                venue_id=operational_block_app.config["TEST_VENUE_ID"],
                status="requested",
            ),
            "approved": VenueBooking(
                event_request_id=operational_block_app.config["TEST_EVENT_ID"],
                venue_id=operational_block_app.config["TEST_VENUE_ID"],
                status="approved",
            ),
            "outside_range": VenueBooking(
                event_request_id=operational_block_app.config["TEST_EVENT_ID"],
                venue_id=operational_block_app.config["TEST_VENUE_ID"],
                status="requested",
            ),
            "other_venue": VenueBooking(
                event_request_id=operational_block_app.config["TEST_EVENT_ID"],
                venue_id=other_venue.id,
                status="approved",
            ),
            "rejected": VenueBooking(
                event_request_id=operational_block_app.config["TEST_EVENT_ID"],
                venue_id=operational_block_app.config["TEST_VENUE_ID"],
                status="rejected",
            ),
        }
        session.add_all(bookings.values())
        session.flush()
        session.add_all(
            [
                VenueBookingOccupancy(
                    booking_id=bookings["requested"].id,
                    venue_id=bookings["requested"].venue_id,
                    day=date(2026, 10, 5),
                    slot="AM",
                    kind="event",
                ),
                VenueBookingOccupancy(
                    booking_id=bookings["approved"].id,
                    venue_id=bookings["approved"].venue_id,
                    day=date(2026, 10, 7),
                    slot="PM",
                    kind="turnaround",
                ),
                VenueBookingOccupancy(
                    booking_id=bookings["outside_range"].id,
                    venue_id=bookings["outside_range"].venue_id,
                    day=date(2026, 10, 8),
                    slot="AM",
                    kind="event",
                ),
                VenueBookingOccupancy(
                    booking_id=bookings["other_venue"].id,
                    venue_id=bookings["other_venue"].venue_id,
                    day=date(2026, 10, 5),
                    slot="AM",
                    kind="event",
                ),
            ]
        )
        session.commit()
        booking_ids = {name: booking.id for name, booking in bookings.items()}

    response = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-07",
            "slots": ["AM", "PM"],
            "reason": "Essential electrical works",
        },
        headers=headers(),
    )

    assert response.status_code == 201
    assert response.json["affected_booking_count"] == 2
    block_id = response.json["operational_block"]["id"]
    with Session(engine) as session:
        stored = {
            name: session.get(VenueBooking, booking_id) for name, booking_id in booking_ids.items()
        }
        for name, expected_status in (("requested", "requested"), ("approved", "approved")):
            booking = stored[name]
            assert booking.status == expected_status
            assert booking.requires_review is True
            assert booking.review_trigger_block_id == block_id
            assert booking.review_marked_by_account_id == VENUE_STAFF_ID
            assert booking.review_marked_at is not None
        for name in ("outside_range", "other_venue", "rejected"):
            booking = stored[name]
            assert booking.requires_review is False
            assert booking.review_trigger_block_id is None
            assert booking.review_marked_at is None
            assert booking.review_marked_by_account_id is None


def test_tc_spl_89_08_refused_block_creation_does_not_mark_an_existing_booking(
    client, operational_block_app
):
    engine = operational_block_app.extensions["engine"]
    with Session(engine) as session:
        booking = VenueBooking(
            event_request_id=operational_block_app.config["TEST_EVENT_ID"],
            venue_id=operational_block_app.config["TEST_VENUE_ID"],
            status="requested",
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id,
                venue_id=booking.venue_id,
                day=date(2026, 10, 5),
                slot="AM",
                kind="event",
            )
        )
        session.commit()
        booking_id = booking.id

    response = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "Unauthorised maintenance block",
        },
        headers=headers("coordinator"),
    )

    assert response.status_code == 403
    with Session(engine) as session:
        booking = session.get(VenueBooking, booking_id)
        assert booking.requires_review is False
        assert booking.review_trigger_block_id is None
        assert session.query(VenueOperationalBlock).count() == 0
