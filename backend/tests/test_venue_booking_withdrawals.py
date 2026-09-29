"""Acceptance coverage for SPL-78 (CS-E09-S4): withdraw a pending venue-booking request.

Each test carries the QA-SPL-78 case identifier it proves. Expected values come from the story's
acceptance criteria, its recorded assumptions and the answered customer questions.
"""

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
    VenueBookingOccupancy,
    VenueLayout,
    VenueOperationalBlock,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000000781"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000782"
ORGANISER = "00000000-0000-0000-0000-000000000783"
VENUE_STAFF = "00000000-0000-0000-0000-000000000784"
MANAGER = "00000000-0000-0000-0000-000000000785"
TOKENS = {
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "organiser": ORGANISER,
    "venue-staff": VENUE_STAFF,
    "manager": MANAGER,
}
EVENT_DATE = date(2026, 10, 14)
HARBOUR_CLAIM = {
    (EVENT_DATE, "AM", "setup"),
    (EVENT_DATE, "PM", "event"),
    (EVENT_DATE, "NIGHT", "turnaround"),
}
UNCHANGED_COLUMNS = (
    "event_request_id",
    "venue_id",
    "layout",
    "expected_attendance",
    "booking_date",
    "event_slots",
    "setup_date",
    "setup_slot",
    "turnaround_date",
    "turnaround_slot",
    "requested_by_account_id",
    "requested_at",
    "requires_review",
    "review_trigger_block_id",
    "review_marked_at",
    "review_marked_by_account_id",
)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/booking-withdrawals.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-78 client")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Taylor Tan", Role.EVENT_COORDINATOR),
            (ORGANISER, "Devon Lee", Role.EVENT_ORGANISER),
            (VENUE_STAFF, "Valerie Tan", Role.VENUE_STAFF),
            (MANAGER, "Morgan Ong", Role.EVENT_OPERATIONS_MANAGER),
        ):
            session.add(Account(id=account_id, display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
        app.config["ORGANISATION_ID"] = organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def make_event(app, name="Coastal Forum", *, start=time(13), end=time(18), status="planning"):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Community planning",
            proposed_date=EVENT_DATE,
            start_time=start,
            end_time=end,
            expected_attendance=150,
            required_facilities=["Projector"],
            accessibility_needs=["Step-free access"],
            location_preference="Marina Centre",
            status=status,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()
        return event.id


def add_venue(app, name="Harbour Hall"):
    with Session(app.extensions["engine"]) as session:
        venue = Venue(
            name=name,
            location="Level 3, Marina Centre",
            facilities=["Projector", "PA system"],
            accessibility_features=["Step-free access"],
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=1,
            turnaround_buffer_slots=1,
        )
        venue.layouts = [
            VenueLayout(layout="theatre", capacity=200),
            VenueLayout(layout="boardroom", capacity=150),
            VenueLayout(layout="classroom", capacity=120),
        ]
        session.add(venue)
        session.commit()
        return venue.id


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def request_booking(client, event_id, venue_id, layout="theatre", token="coordinator"):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": venue_id, "layout": layout},
        headers=headers(token),
    )


def withdraw(client, event_id, booking_id, token="coordinator", **kwargs):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/withdraw",
        headers=headers(token),
        **kwargs,
    )


def read(client, event_id, booking_id, token="coordinator"):
    return client.get(
        f"/api/event-requests/{event_id}/venue-bookings/{booking_id}", headers=headers(token)
    )


def search(client, event_id, *slots):
    query = "&".join([f"date={EVENT_DATE.isoformat()}", *(f"slot={slot}" for slot in slots)])
    response = client.get(
        f"/api/event-requests/{event_id}/available-venues?{query}", headers=headers()
    )
    assert response.status_code == 200, response.json
    return {venue["name"] for venue in response.json["venues"]}


@pytest.fixture
def requested(app, client):
    """The booking under test: Coastal Forum at Harbour Hall, Requested through SPL-77."""

    event_id, venue_id = make_event(app), add_venue(app)
    response = request_booking(client, event_id, venue_id)
    assert response.status_code == 201, response.json
    return {"event": event_id, "venue": venue_id, "booking": response.json["booking"]}


def stored(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        booking = session.get(VenueBooking, booking_id)
        row = {column.name: getattr(booking, column.key) for column in booking.__mapper__.columns}
        return {**row, "status": booking.status}


def occupancy(app, *, booking_id=None, venue_id=None):
    with Session(app.extensions["engine"]) as session:
        query = select(VenueBookingOccupancy)
        if booking_id is not None:
            query = query.where(VenueBookingOccupancy.booking_id == booking_id)
        if venue_id is not None:
            query = query.where(VenueBookingOccupancy.venue_id == venue_id)
        return {(row.day, row.slot, row.kind) for row in session.scalars(query)}


def seed_booking(app, event_id, venue_id, status, rows=()):
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(event_request_id=event_id, venue_id=venue_id, status=status)
        session.add(booking)
        session.flush()
        for day, slot, kind in rows:
            session.add(
                VenueBookingOccupancy(
                    booking_id=booking.id, venue_id=venue_id, day=day, slot=slot, kind=kind
                )
            )
        session.commit()
        return booking.id


def assert_unchanged(app, booking_id):
    """The booking is still Requested, holding its three slots, with no withdrawal record."""

    row = stored(app, booking_id)
    assert row["status"] == "requested"
    assert row["withdrawn_by_account_id"] is None and row["withdrawn_at"] is None
    assert occupancy(app, booking_id=booking_id) == HARBOUR_CLAIM


# AC1 — the assigned coordinator may withdraw a Requested booking


# TC-SPL-78-01
# SPL-78 AC-1,2 Test-01
def test_tc_spl_78_01_assigned_coordinator_withdraws_a_requested_booking(app, client, requested):
    booking_id = requested["booking"]["id"]

    response = withdraw(client, requested["event"], booking_id)

    assert response.status_code == 200, response.json
    assert response.json["booking"]["status"] == "withdrawn"
    assert stored(app, booking_id)["status"] == "withdrawn"
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count(VenueBooking.id))) == 1


# TC-SPL-78-02
# SPL-78 AC-1 Test-02
def test_tc_spl_78_02_authority_follows_the_current_assignment(app, client, requested):
    booking_id = requested["booking"]["id"]
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(EventCoordinatorAssignment)
            .where(EventCoordinatorAssignment.event_request_id == requested["event"])
            .values(coordinator_account_id=OTHER_COORDINATOR)
        )
        session.commit()

    former = withdraw(client, requested["event"], booking_id)
    assert former.status_code == 404
    assert_unchanged(app, booking_id)

    current = withdraw(client, requested["event"], booking_id, token="other-coordinator")
    assert current.status_code == 200, current.json
    assert current.json["booking"]["withdrawn_by"] == {
        "id": OTHER_COORDINATOR,
        "name": "Taylor Tan",
    }


# TC-SPL-78-03
# SPL-78 AC-1 Test-03
@pytest.mark.parametrize("condition", ["event-cancelled", "event-postponed", "marked-for-review"])
def test_tc_spl_78_03_withdrawal_is_gated_by_booking_status_only(app, client, requested, condition):
    booking_id = requested["booking"]["id"]
    with Session(app.extensions["engine"]) as session:
        if condition.startswith("event-"):
            session.execute(
                update(EventRequest)
                .where(EventRequest.id == requested["event"])
                .values(status=condition.removeprefix("event-"))
            )
        else:
            block = VenueOperationalBlock(
                venue_id=requested["venue"],
                start_date=EVENT_DATE,
                end_date=EVENT_DATE,
                slots=["PM"],
                reason="Ceiling repair",
                created_by_account_id=VENUE_STAFF,
                created_at=datetime(2026, 9, 27, 9, tzinfo=timezone.utc),
            )
            session.add(block)
            session.flush()
            session.execute(
                update(VenueBooking)
                .where(VenueBooking.id == booking_id)
                .values(
                    requires_review=True,
                    review_trigger_block_id=block.id,
                    review_marked_at=datetime(2026, 9, 27, 9, tzinfo=timezone.utc),
                    review_marked_by_account_id=VENUE_STAFF,
                )
            )
        session.commit()

    response = withdraw(client, requested["event"], booking_id)

    assert response.status_code == 200, response.json
    assert stored(app, booking_id)["status"] == "withdrawn"
    assert occupancy(app, booking_id=booking_id) == set()
    if condition == "marked-for-review":
        assert response.json["booking"]["requires_review"] is True
        assert response.json["booking"]["review_trigger_block_id"] is not None


# AC2 — Withdrawn, recording who and when


# TC-SPL-78-04
# SPL-78 AC-2 Test-04
def test_tc_spl_78_04_withdrawer_and_time_are_recorded(app, client, requested):
    booking_id = requested["booking"]["id"]
    before = datetime.now(SINGAPORE)

    response = withdraw(client, requested["event"], booking_id)

    after = datetime.now(SINGAPORE)
    booking = response.json["booking"]
    assert booking["withdrawn_by"] == {"id": COORDINATOR, "name": "Casey Lim"}
    assert booking["withdrawn_at"].endswith("+08:00")
    assert before <= datetime.fromisoformat(booking["withdrawn_at"]) <= after
    row = stored(app, booking_id)
    assert row["withdrawn_by_account_id"] == COORDINATOR
    assert row["withdrawn_at"] is not None


# TC-SPL-78-05
# SPL-78 AC-2,4 Test-05
def test_tc_spl_78_05_original_request_details_are_unchanged(app, client, requested):
    booking_id = requested["booking"]["id"]
    before = stored(app, booking_id)

    assert withdraw(client, requested["event"], booking_id).status_code == 200

    after = stored(app, booking_id)
    assert {column: after[column] for column in UNCHANGED_COLUMNS} == {
        column: before[column] for column in UNCHANGED_COLUMNS
    }
    assert after["requested_by_account_id"] == COORDINATOR
    assert (after["setup_slot"], after["turnaround_slot"]) == ("AM", "NIGHT")


# AC3 — released slots no longer count as occupied


# TC-SPL-78-06
# SPL-78 AC-3 Test-06
def test_tc_spl_78_06_withdrawn_slots_return_to_search(app, client, requested):
    harbour_talk = make_event(app, "Harbour Talk")
    for slot in ("PM", "AM", "NIGHT"):
        assert "Harbour Hall" not in search(client, harbour_talk, slot)

    assert withdraw(client, requested["event"], requested["booking"]["id"]).status_code == 200

    for slot in ("PM", "AM", "NIGHT"):
        assert "Harbour Hall" in search(client, harbour_talk, slot)
    assert occupancy(app, booking_id=requested["booking"]["id"]) == set()


# TC-SPL-78-07
# SPL-78 AC-3 Test-07
def test_tc_spl_78_07_another_event_can_claim_released_slots(app, client, requested):
    harbour_talk = make_event(app, "Harbour Talk")

    blocked = request_booking(client, harbour_talk, requested["venue"])
    assert blocked.status_code == 409
    assert blocked.json["conflict"] == {"date": "2026-10-14", "slot": "AM"}

    assert withdraw(client, requested["event"], requested["booking"]["id"]).status_code == 200

    claimed = request_booking(client, harbour_talk, requested["venue"])
    assert claimed.status_code == 201, claimed.json
    assert occupancy(app, booking_id=claimed.json["booking"]["id"]) == HARBOUR_CLAIM


# TC-SPL-78-08
# SPL-78 AC-3 Test-08
def test_tc_spl_78_08_other_occupancy_is_untouched(app, client, requested):
    harbour_talk = make_event(app, "Harbour Talk")
    neighbour = seed_booking(
        app,
        harbour_talk,
        requested["venue"],
        "requested",
        rows=[
            (date(2026, 10, 16), "AM", "setup"),
            (date(2026, 10, 16), "PM", "event"),
            (date(2026, 10, 16), "NIGHT", "turnaround"),
        ],
    )
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueOperationalBlock(
                venue_id=requested["venue"],
                start_date=date(2026, 10, 15),
                end_date=date(2026, 10, 15),
                slots=["AM"],
                reason="Deep clean",
                created_by_account_id=VENUE_STAFF,
                created_at=datetime(2026, 9, 27, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()

    assert withdraw(client, requested["event"], requested["booking"]["id"]).status_code == 200

    assert occupancy(app, booking_id=neighbour) == {
        (date(2026, 10, 16), "AM", "setup"),
        (date(2026, 10, 16), "PM", "event"),
        (date(2026, 10, 16), "NIGHT", "turnaround"),
    }
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count(VenueOperationalBlock.id))) == 1


# AC4 — the withdrawn request is kept and still retrievable


# TC-SPL-78-09
# SPL-78 AC-4 Test-09
def test_tc_spl_78_09_withdrawn_request_is_retrievable(app, client, requested):
    event_id, created = requested["event"], requested["booking"]
    assert withdraw(client, event_id, created["id"]).status_code == 200

    by_id = read(client, event_id, created["id"])
    latest = client.get(f"/api/event-requests/{event_id}/venue-bookings/latest", headers=headers())

    assert by_id.status_code == 200 and latest.status_code == 200
    for booking in (by_id.json["booking"], latest.json["booking"]):
        for field, value in created.items():
            if field not in {"status", "withdrawn_by", "withdrawn_at"}:
                assert booking[field] == value, field
        assert booking["status"] == "withdrawn"
        assert booking["withdrawn_by"] == {"id": COORDINATOR, "name": "Casey Lim"}
        assert booking["withdrawn_at"].endswith("+08:00")


# TC-SPL-78-10
# SPL-78 AC-4 Test-10
def test_tc_spl_78_10_withdrawn_row_is_retained(app, client, requested):
    def bookings():
        with Session(app.extensions["engine"]) as session:
            return session.scalar(
                select(func.count(VenueBooking.id)).where(
                    VenueBooking.event_request_id == requested["event"]
                )
            )

    assert bookings() == 1
    assert withdraw(client, requested["event"], requested["booking"]["id"]).status_code == 200
    assert bookings() == 1
    assert stored(app, requested["booking"]["id"])["status"] == "withdrawn"


# TC-SPL-78-11
# SPL-78 AC-4 Test-11
@pytest.mark.parametrize(
    ("token", "expected"),
    [("other-coordinator", 404), ("venue-staff", 403), ("organiser", 403), (None, 401)],
)
def test_tc_spl_78_11_others_cannot_read_the_booking(app, client, requested, token, expected):
    event_id, booking_id = requested["event"], requested["booking"]["id"]
    assert withdraw(client, event_id, booking_id).status_code == 200

    response = read(client, event_id, booking_id, token=token)
    latest = client.get(
        f"/api/event-requests/{event_id}/venue-bookings/latest", headers=headers(token)
    )

    assert response.status_code == latest.status_code == expected
    if expected == 404:
        assert "Coastal Forum" not in response.get_data(as_text=True)
        assert "Harbour Hall" not in response.get_data(as_text=True)


# TC-SPL-78-11 — a booking read under another event's URL is not found.
# SPL-78 AC-4 Test-11
def test_tc_spl_78_11_booking_read_under_another_event_is_not_found(app, client, requested):
    harbour_talk = make_event(app, "Harbour Talk")

    mismatched = read(client, harbour_talk, requested["booking"]["id"])
    unknown = read(client, requested["event"], 999999)

    assert mismatched.status_code == unknown.status_code == 404
    assert mismatched.json == unknown.json


# AC5 — a new request is possible after withdrawal


# TC-SPL-78-12
# SPL-78 AC-5 Test-12
def test_tc_spl_78_12_same_venue_and_slots_can_be_requested_again(app, client, requested):
    event_id, original = requested["event"], requested["booking"]["id"]
    assert withdraw(client, event_id, original).status_code == 200

    again = request_booking(client, event_id, requested["venue"])

    assert again.status_code == 201, again.json
    new_id = again.json["booking"]["id"]
    assert new_id != original
    assert stored(app, original)["status"] == "withdrawn"
    assert occupancy(app, booking_id=original) == set()
    assert occupancy(app, booking_id=new_id) == HARBOUR_CLAIM
    latest = client.get(f"/api/event-requests/{event_id}/venue-bookings/latest", headers=headers())
    assert latest.json["booking"]["id"] == new_id


# TC-SPL-78-13
# SPL-78 AC-5 Test-13
def test_tc_spl_78_13_withdrawal_is_what_unlocks_a_new_request(app, client, requested):
    east = add_venue(app, "Harbour Hall East")

    before = request_booking(client, requested["event"], east)
    assert before.status_code == 409
    assert "already has an active venue-booking request" in before.json["error"]

    assert withdraw(client, requested["event"], requested["booking"]["id"]).status_code == 200

    after = request_booking(client, requested["event"], east)
    assert after.status_code == 201, after.json


# AC6 — refused withdrawals change nothing


# TC-SPL-78-14
# SPL-78 AC-6 Test-14
@pytest.mark.parametrize("status", ["approved", "rejected", "cancelled", "withdrawn"])
def test_tc_spl_78_14_only_requested_bookings_can_be_withdrawn(app, client, status):
    event_id, venue_id = make_event(app), add_venue(app)
    held = HARBOUR_CLAIM if status == "approved" else ()
    booking_id = seed_booking(app, event_id, venue_id, status, rows=held)
    earlier = datetime(2026, 9, 27, 9, tzinfo=SINGAPORE)
    if status == "withdrawn":
        with Session(app.extensions["engine"]) as session:
            session.execute(
                update(VenueBooking)
                .where(VenueBooking.id == booking_id)
                .values(withdrawn_by_account_id=COORDINATOR, withdrawn_at=earlier)
            )
            session.commit()

    response = withdraw(client, event_id, booking_id)

    assert response.status_code == 409
    assert response.json["error"] == "Only a Requested venue-booking request can be withdrawn."
    row = stored(app, booking_id)
    assert row["status"] == status
    assert occupancy(app, booking_id=booking_id) == set(held)
    if status == "withdrawn":
        assert row["withdrawn_at"].replace(tzinfo=None) == earlier.replace(tzinfo=None)
    else:
        assert row["withdrawn_at"] is None


# TC-SPL-78-15
# SPL-78 AC-6 Test-15
def test_tc_spl_78_15_unassigned_coordinator_is_refused(app, client, requested):
    event_id, booking_id = requested["event"], requested["booking"]["id"]

    real = withdraw(client, event_id, booking_id, token="other-coordinator")
    unknown = withdraw(client, event_id, 999999, token="other-coordinator")

    assert real.status_code == unknown.status_code == 404
    assert real.json == unknown.json
    assert_unchanged(app, booking_id)


# TC-SPL-78-16
# SPL-78 AC-6 Test-16
@pytest.mark.parametrize(
    ("token", "expected"),
    [("venue-staff", 403), ("organiser", 403), ("manager", 403), (None, 401)],
)
def test_tc_spl_78_16_other_roles_and_no_session_are_refused(
    app, client, requested, token, expected
):
    response = withdraw(client, requested["event"], requested["booking"]["id"], token=token)

    assert response.status_code == expected
    assert_unchanged(app, requested["booking"]["id"])


# TC-SPL-78-17
# SPL-78 AC-6 Test-17
def test_tc_spl_78_17_booking_under_another_event_is_refused(app, client, requested):
    harbour_talk = make_event(app, "Harbour Talk")

    response = withdraw(client, harbour_talk, requested["booking"]["id"])

    assert response.status_code == 404
    assert_unchanged(app, requested["booking"]["id"])


# TC-SPL-78-18
# SPL-78 AC-6 Test-18
@pytest.mark.parametrize(
    "body",
    [
        {"status": "cancelled"},
        {"withdrawn_by_account_id": OTHER_COORDINATOR},
        {"withdrawn_at": "2026-01-01T00:00:00+08:00"},
        [],
    ],
)
def test_tc_spl_78_18_parameters_are_refused(app, client, requested, body):
    response = withdraw(client, requested["event"], requested["booking"]["id"], json=body)

    assert response.status_code == 400
    assert_unchanged(app, requested["booking"]["id"])


# TC-SPL-78-18 — control partition: an empty JSON object carries no parameters.
# SPL-78 AC-6 Test-18
def test_tc_spl_78_18_an_empty_object_is_accepted(app, client, requested):
    response = withdraw(client, requested["event"], requested["booking"]["id"], json={})

    assert response.status_code == 200, response.json


# AC7 — no amendment; withdraw and resubmit


# TC-SPL-78-20
# SPL-78 AC-7 Test-20
@pytest.mark.parametrize("method", ["put", "patch"])
def test_tc_spl_78_20_a_booking_cannot_be_amended(app, client, requested, method):
    east = add_venue(app, "Harbour Hall East")
    booking_id = requested["booking"]["id"]
    before = stored(app, booking_id)

    response = getattr(client, method)(
        f"/api/event-requests/{requested['event']}/venue-bookings/{booking_id}",
        json={"venue_id": east, "layout": "boardroom"},
        headers=headers(),
    )

    assert response.status_code == 405
    assert "Withdraw" in response.json["error"]
    assert stored(app, booking_id) == before
    assert occupancy(app, booking_id=booking_id) == HARBOUR_CLAIM


# TC-SPL-78-21
# SPL-78 AC-7 Test-21
def test_tc_spl_78_21_withdraw_and_resubmit_the_alternative(app, client, requested):
    east = add_venue(app, "Harbour Hall East")
    original = requested["booking"]["id"]

    assert withdraw(client, requested["event"], original).status_code == 200
    alternative = request_booking(client, requested["event"], east, layout="boardroom")

    assert alternative.status_code == 201, alternative.json
    old, new = stored(app, original), stored(app, alternative.json["booking"]["id"])
    assert (old["status"], old["venue_id"], old["layout"]) == (
        "withdrawn",
        requested["venue"],
        "theatre",
    )
    assert (new["status"], new["venue_id"], new["layout"]) == ("requested", east, "boardroom")
    assert occupancy(app, venue_id=requested["venue"]) == set()
    assert occupancy(app, booking_id=alternative.json["booking"]["id"]) == HARBOUR_CLAIM


# TC-SPL-78-15 — boundary partition: ids beyond the database's integer range are simply not found.
# SPL-78 AC-6 Test-15
def test_tc_spl_78_15_out_of_range_ids_are_not_found(app, client, requested):
    unassigned = withdraw(
        client, requested["event"], requested["booking"]["id"], token="other-coordinator"
    )

    huge_booking = withdraw(client, requested["event"], 2**31)
    huge_event = withdraw(client, 2**31, requested["booking"]["id"])

    assert huge_booking.status_code == huge_event.status_code == 404
    assert huge_booking.json == huge_event.json == unassigned.json
    assert_unchanged(app, requested["booking"]["id"])
