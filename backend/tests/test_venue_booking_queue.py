"""Acceptance coverage for SPL-80 (CS-E10-S2): view pending venue-booking requests.

Each test carries the QA-SPL-80 case identifier it proves. Expected values come from the story's
acceptance criteria and the interpretations recorded in docs/tasks/SPL-80.md, which were agreed
before any of this code existed.
"""

import json
from datetime import date, datetime, time, timezone

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from sqlalchemy import update
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000000801"
ORGANISER = "00000000-0000-0000-0000-000000000802"
VENUE_STAFF = "00000000-0000-0000-0000-000000000803"
MANAGER = "00000000-0000-0000-0000-000000000804"
ATTENDEE = "00000000-0000-0000-0000-000000000805"
# The second client organisation's coordinator, for the organisation-wide case (TC-SPL-80-02).
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000806"
TOKENS = {
    "coordinator": COORDINATOR,
    "organiser": ORGANISER,
    "venue-staff": VENUE_STAFF,
    "manager": MANAGER,
    "attendee": ATTENDEE,
    "other-coordinator": OTHER_COORDINATOR,
}
EVENT_DATE = date(2026, 10, 14)
EMPTY_MESSAGE = "No venue-booking requests are awaiting review."
# TC-SPL-80-12: attendee contact details that must never reach Venue Staff.
REGISTRATION_NOTES = "Alex Tan, 9123 4567, alex@example.test"


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/booking-queue.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        other_organisation = Organisation(name="Southbank Civic Trust")
        session.add_all([organisation, other_organisation])
        session.flush()
        for account_id, name, role, org in (
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR, organisation),
            (ORGANISER, "Devon Lee", Role.EVENT_ORGANISER, organisation),
            # Venue Staff hold no client organisation: they work for the venue operator. This is
            # the evidence behind reading AC1's "organisation-wide" as the whole estate.
            (VENUE_STAFF, "Valerie Tan", Role.VENUE_STAFF, None),
            (MANAGER, "Morgan Ong", Role.EVENT_OPERATIONS_MANAGER, None),
            (ATTENDEE, "Avery Ng", Role.ATTENDEE, organisation),
            (OTHER_COORDINATOR, "Taylor Tan", Role.EVENT_COORDINATOR, other_organisation),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    organisation_id=org.id if org else None,
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
        app.config["ORGANISATION_ID"] = organisation.id
        app.config["OTHER_ORGANISATION_ID"] = other_organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="venue-staff"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def make_event(
    app,
    name="Coastal Forum",
    *,
    day=EVENT_DATE,
    start=time(13),
    end=time(18),
    coordinator=COORDINATOR,
    organisation_key="ORGANISATION_ID",
):
    """An event in Planning with a coordinator assigned, ready for an SPL-77 request."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config[organisation_key],
            name=name,
            purpose="Community planning",
            description="An open forum for the coastal redevelopment plan.",
            proposed_date=day,
            start_time=start,
            end_time=end,
            expected_attendance=150,
            preferred_room_layout="theatre",
            required_facilities=["Projector"],
            accessibility_needs=["Step-free access"],
            facilities_notes="Lectern needed",
            location_preference="Marina Centre",
            venue_notes="Ground floor preferred",
            # AC4: attendee-facing data the decision does not need.
            registration_required=True,
            registration_notes=REGISTRATION_NOTES,
            status="planning",
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=coordinator,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()
        return event.id


def add_venue(app, name="Harbour Hall", *, setup=1, turnaround=1, slots=("AM", "PM", "NIGHT")):
    with Session(app.extensions["engine"]) as session:
        venue = Venue(
            name=name,
            location="Level 3, Marina Centre",
            facilities=["Projector", "PA system"],
            accessibility_features=["Step-free access"],
            operating_slots=list(slots),
            setup_buffer_slots=setup,
            turnaround_buffer_slots=turnaround,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(venue)
        session.commit()
        return venue.id


def request_booking(client, event_id, venue_id, token="coordinator"):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": venue_id, "layout": "theatre"},
        headers=headers(token),
    )


def pending(client, token="venue-staff"):
    return client.get("/api/venue-bookings/pending", headers=headers(token))


def review(client, booking_id, token="venue-staff"):
    return client.get(f"/api/venue-bookings/{booking_id}", headers=headers(token))


def set_status(app, booking_id, status):
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(VenueBooking).where(VenueBooking.id == booking_id).values(status=status)
        )
        session.commit()


def seed_booking(app, event_id, venue_id, *, requested_at, status="requested"):
    """A booking written straight to the table, so a request time can be controlled or omitted.

    SPL-83 and SPL-89 create bookings this way too, which is why `requested_at` is nullable and
    why TC-SPL-80-09 has a NULL row to order.
    """

    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=event_id,
            venue_id=venue_id,
            status=status,
            layout="theatre",
            expected_attendance=150,
            booking_date=EVENT_DATE,
            event_slots=["PM"],
            requested_by_account_id=COORDINATOR,
            requested_at=requested_at,
        )
        session.add(booking)
        session.commit()
        return booking.id


@pytest.fixture
def requested(app, client):
    """The request under test: Coastal Forum at Harbour Hall, Requested through SPL-77."""

    event_id, venue_id = make_event(app), add_venue(app)
    response = request_booking(client, event_id, venue_id)
    assert response.status_code == 201, response.json
    return {"event": event_id, "venue": venue_id, "booking": response.json["booking"]}


# ── AC1 — an organisation-wide list of Requested bookings, for Venue Staff ────────────────────


# TC-SPL-80-01
def test_tc_spl_80_01_venue_staff_retrieve_the_pending_queue(client, requested):
    response = pending(client)

    assert response.status_code == 200, response.json
    assert response.json["count"] == 1
    assert [item["id"] for item in response.json["requests"]] == [requested["booking"]["id"]]


# TC-SPL-80-02
def test_tc_spl_80_02_queue_spans_every_client_organisation(app, client, requested):
    """AC1's "organisation-wide" is the venue operator's whole estate, not one client."""

    southbank = make_event(
        app,
        name="Southbank Summit",
        day=date(2026, 10, 20),
        coordinator=OTHER_COORDINATOR,
        organisation_key="OTHER_ORGANISATION_ID",
    )
    other_booking = request_booking(client, southbank, requested["venue"], "other-coordinator")
    assert other_booking.status_code == 201, other_booking.json

    response = pending(client)

    assert response.json["count"] == 2
    assert {item["event"]["name"] for item in response.json["requests"]} == {
        "Coastal Forum",
        "Southbank Summit",
    }


# TC-SPL-80-03
@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("coordinator", 403),
        ("organiser", 403),
        ("manager", 403),
        ("attendee", 403),
        (None, 401),
    ],
)
def test_tc_spl_80_03_other_roles_and_no_session_are_refused(client, requested, token, expected):
    # Venue Staff must succeed in the same test: an unrouted address also answers 403, so
    # without this the case would pass even if the queue did not exist at all.
    assert pending(client).status_code == 200

    response = pending(client, token)

    assert response.status_code == expected
    assert "Coastal Forum" not in response.get_data(as_text=True)


# ── AC2 — each item identifies the request ───────────────────────────────────────────────────


# TC-SPL-80-04
def test_tc_spl_80_04_queue_item_carries_every_identifying_field(client, requested):
    item = pending(client).json["requests"][0]

    assert item["event"]["name"] == "Coastal Forum"
    assert item["venue"] == {"id": requested["venue"], "name": "Harbour Hall"}
    assert item["date"] == "2026-10-14"
    assert item["event_slots"] == ["PM"]
    # SPL-87 derived these from the venue's buffers when SPL-77 claimed the occupancy.
    assert item["setup"] == {"date": "2026-10-14", "slot": "AM"}
    assert item["turnaround"] == {"date": "2026-10-14", "slot": "NIGHT"}
    assert item["layout"] == "theatre"
    assert item["expected_attendance"] == 150
    assert item["requested_by"] == {"id": COORDINATOR, "name": "Casey Lim"}
    # Singapore time, so Venue Staff never read the wrong calendar day (Q36).
    assert item["requested_at"].endswith("+08:00")


# TC-SPL-80-05
def test_tc_spl_80_05_venue_without_preparation_reports_no_slots(app, client):
    event_id = make_event(app)
    venue_id = add_venue(app, "Riverside Room", setup=0, turnaround=0, slots=("AM", "PM"))
    assert request_booking(client, event_id, venue_id).status_code == 201

    item = pending(client).json["requests"][0]

    assert (item["setup"], item["turnaround"]) == (None, None)
    assert item["event_slots"] == ["PM"]


# ── AC5 — requests that are not Requested are excluded ───────────────────────────────────────


# TC-SPL-80-06
@pytest.mark.parametrize("status", ["approved", "rejected", "withdrawn", "cancelled"])
def test_tc_spl_80_06_non_requested_statuses_are_excluded(app, client, requested, status):
    set_status(app, requested["booking"]["id"], status)

    response = pending(client)

    assert response.json["count"] == 0
    assert response.json["requests"] == []


# TC-SPL-80-07
def test_tc_spl_80_07_request_leaves_the_queue_when_it_leaves_requested(client, requested):
    assert pending(client).json["count"] == 1

    withdrawn = client.post(
        f"/api/event-requests/{requested['event']}/venue-bookings/"
        f"{requested['booking']['id']}/withdraw",
        headers=headers("coordinator"),
    )
    assert withdrawn.status_code == 200, withdrawn.json

    after = pending(client)
    assert after.json["count"] == 0
    assert after.json["message"] == EMPTY_MESSAGE


# ── AC6 — a clear empty state ────────────────────────────────────────────────────────────────


# TC-SPL-80-08
def test_tc_spl_80_08_empty_queue_is_explicit(client):
    response = pending(client)

    assert response.status_code == 200
    assert response.json == {"requests": [], "count": 0, "message": EMPTY_MESSAGE}


# ── Ordering — oldest request first ──────────────────────────────────────────────────────────


# TC-SPL-80-09
def test_tc_spl_80_09_oldest_request_first_nulls_last(app, client):
    """The longest-waiting request is first, and rows with no request time sort last.

    NULL ordering differs between PostgreSQL and SQLite, so the order is made explicit rather
    than left to the database's default.
    """

    venue_id = add_venue(app)
    later = seed_booking(
        app,
        make_event(app, name="Later"),
        venue_id,
        requested_at=datetime(2026, 9, 27, 9, 30, tzinfo=SINGAPORE),
    )
    earlier = seed_booking(
        app,
        make_event(app, name="Earlier"),
        venue_id,
        requested_at=datetime(2026, 9, 27, 9, 0, tzinfo=SINGAPORE),
    )
    untimed = seed_booking(app, make_event(app, name="Untimed"), venue_id, requested_at=None)

    order = [item["id"] for item in pending(client).json["requests"]]

    assert order == [earlier, later, untimed]


# ── AC3 — opening a request to decide ────────────────────────────────────────────────────────


# TC-SPL-80-10
def test_tc_spl_80_10_decision_view_carries_the_event_information(client, requested):
    event = review(client, requested["booking"]["id"]).json["event"]

    assert event["name"] == "Coastal Forum"
    assert event["organisation"]["name"] == "Northstar Community Partners"
    assert event["purpose"] == "Community planning"
    assert event["description"] == "An open forum for the coastal redevelopment plan."
    assert (event["proposed_date"], event["start_time"], event["end_time"]) == (
        "2026-10-14",
        "13:00",
        "18:00",
    )
    assert event["expected_attendance"] == 150
    assert event["preferred_room_layout"] == "theatre"
    assert event["required_facilities"] == ["Projector"]
    assert event["accessibility_needs"] == ["Step-free access"]
    assert event["facilities_notes"] == "Lectern needed"
    assert event["location_preference"] == "Marina Centre"
    assert event["venue_notes"] == "Ground floor preferred"


# TC-SPL-80-11
def test_tc_spl_80_11_spl81_keys_are_unchanged(client, requested):
    """Widening the payload for AC3 must not disturb the contract SPL-81 already relies on."""

    body = review(client, requested["booking"]["id"]).json

    assert (body["event"]["id"], body["event"]["name"], body["event"]["status"]) == (
        requested["event"],
        "Coastal Forum",
        "planning",
    )
    assert body["booking"] == requested["booking"]
    assert body["review"] == {"requires_review": False, "marked_at": None, "trigger_block": None}


# ── AC4 — personal attendee information is not displayed ─────────────────────────────────────


# TC-SPL-80-12
def test_tc_spl_80_12_personal_attendee_information_is_not_disclosed(client, requested):
    """Asserted over the whole body, so a field added to `event_requests` cannot leak silently."""

    queue_body = pending(client).get_data(as_text=True)
    decision_body = review(client, requested["booking"]["id"]).get_data(as_text=True)

    for body in (queue_body, decision_body):
        payload = json.loads(body)
        assert REGISTRATION_NOTES not in body
        assert "registration_notes" not in body
        assert "registration_required" not in body
        assert "organiser_account_id" not in body
        assert ORGANISER not in body
        # The event is identified by name, so the omission above is not a false pass.
        assert "Coastal Forum" in json.dumps(payload)
