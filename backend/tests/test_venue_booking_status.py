"""Acceptance coverage for SPL-79 (CS-E10-S1): track the status of an event's venue-booking request.

Each test carries the QA-SPL-79 case identifier it proves. Approved and Rejected outcomes are seeded
as controlled fixtures because SPL-81 and SPL-82 are not built yet (the story's dependency note).
"""

from datetime import date, datetime, time, timedelta, timezone

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
    VenueBookingStatusHistory,
    VenueLayout,
    VenueOperationalBlock,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000000791"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000792"
ORGANISER = "00000000-0000-0000-0000-000000000793"
VENUE_STAFF = "00000000-0000-0000-0000-000000000794"
MANAGER = "00000000-0000-0000-0000-000000000795"
TOKENS = {
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "organiser": ORGANISER,
    "venue-staff": VENUE_STAFF,
    "manager": MANAGER,
}
EVENT_DATE = date(2026, 10, 14)
NO_REQUEST = "No venue-booking request has been made for this event yet."


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/booking-status.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-79 client")
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


def make_event(app, name="Coastal Forum"):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Community planning",
            proposed_date=EVENT_DATE,
            start_time=time(13),
            end_time=time(18),
            expected_attendance=150,
            required_facilities=["Projector"],
            accessibility_needs=["Step-free access"],
            location_preference="Marina Centre",
            status="planning",
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
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(venue)
        session.commit()
        return venue.id


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def request_booking(client, event_id, venue_id):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": venue_id, "layout": "theatre"},
        headers=headers(),
    )


def withdraw(client, event_id, booking_id):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/withdraw", headers=headers()
    )


def status(client, event_id, token="coordinator"):
    return client.get(
        f"/api/event-requests/{event_id}/venue-booking-status", headers=headers(token)
    )


@pytest.fixture
def requested(app, client):
    """Coastal Forum holding a Requested booking at Harbour Hall, made through SPL-77."""

    event_id, venue_id = make_event(app), add_venue(app)
    response = request_booking(client, event_id, venue_id)
    assert response.status_code == 201, response.json
    return {"event": event_id, "venue": venue_id, "booking": response.json["booking"]}


def decide(app, booking_id, resulting_status, note, at):
    """Controlled fixture for an SPL-81/SPL-82 decision by Venue Staff (not yet built)."""

    with Session(app.extensions["engine"]) as session:
        booking = session.get(VenueBooking, booking_id)
        session.add(
            VenueBookingStatusHistory(
                booking_id=booking_id,
                action={"approved": "approve", "rejected": "reject"}.get(
                    resulting_status, resulting_status
                ),
                previous_status=booking.status,
                resulting_status=resulting_status,
                actor_account_id=VENUE_STAFF,
                changed_at=at,
                note=note,
            )
        )
        booking.status = resulting_status
        session.commit()


def snapshot(app, event_id):
    with Session(app.extensions["engine"]) as session:
        bookings = session.scalars(
            select(VenueBooking).where(VenueBooking.event_request_id == event_id)
        ).all()
        ids = [booking.id for booking in bookings]
        return {
            "bookings": [
                {c.name: getattr(b, c.key) for c in b.__mapper__.columns} for b in bookings
            ],
            "occupancy": sorted(
                (row.booking_id, row.day, row.slot, row.kind)
                for row in session.scalars(
                    select(VenueBookingOccupancy).where(VenueBookingOccupancy.booking_id.in_(ids))
                )
            ),
            "history": sorted(
                (row.id, row.booking_id, row.action, row.resulting_status, row.note)
                for row in session.scalars(
                    select(VenueBookingStatusHistory).where(
                        VenueBookingStatusHistory.booking_id.in_(ids)
                    )
                )
            ),
        }


def history_count(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count(VenueBookingStatusHistory.id)))


# AC1 — the request's details and current status


# TC-SPL-79-01
def test_tc_spl_79_01_coordinator_retrieves_the_request_details(app, client, requested):
    response = status(client, requested["event"])

    assert response.status_code == 200, response.json
    body, created = response.json, requested["booking"]
    booking = body["venue_booking_request"]
    for field in ("id", "venue", "date", "event_slots", "setup", "turnaround", "layout"):
        assert booking[field] == created[field], field
    assert booking["venue"] == {"id": requested["venue"], "name": "Harbour Hall"}
    assert (booking["date"], booking["event_slots"]) == ("2026-10-14", ["PM"])
    assert booking["setup"] == {"date": "2026-10-14", "slot": "AM"}
    assert booking["turnaround"] == {"date": "2026-10-14", "slot": "NIGHT"}
    assert booking["layout"] == "theatre"
    assert body["current_status"] == {"status": "requested", "label": "Requested"}


# TC-SPL-79-02
@pytest.mark.parametrize(
    ("stored", "label"),
    [
        ("requested", "Requested"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("withdrawn", "Withdrawn"),
        ("cancelled", "Cancelled"),
    ],
)
def test_tc_spl_79_02_each_current_status_is_reported(app, client, requested, stored, label):
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(VenueBooking)
            .where(VenueBooking.id == requested["booking"]["id"])
            .values(status=stored)
        )
        session.commit()

    body = status(client, requested["event"]).json

    assert body["current_status"] == {"status": stored, "label": label}
    assert body["current_status"]["label"] != stored


# AC2 — every status change, in order, with who, when and any reason or note


# TC-SPL-79-03
def test_tc_spl_79_03_request_and_withdrawal_are_recorded_in_order(app, client, requested):
    withdrawn = withdraw(client, requested["event"], requested["booking"]["id"]).json["booking"]

    history = status(client, requested["event"]).json["history"]

    assert [(entry["action"], entry["status"], entry["status_label"]) for entry in history] == [
        ("request", "requested", "Requested"),
        ("withdraw", "withdrawn", "Withdrawn"),
    ]
    assert all(entry["actor"] == {"id": COORDINATOR, "name": "Casey Lim"} for entry in history)
    assert all(entry["note"] is None for entry in history)
    assert all(entry["changed_at"].endswith("+08:00") for entry in history)
    assert history[0]["changed_at"] == requested["booking"]["requested_at"]
    assert history[1]["changed_at"] == withdrawn["withdrawn_at"]


# TC-SPL-79-04
@pytest.mark.parametrize(
    ("resulting", "text"),
    [("approved", "Confirmed with the hall manager"), ("rejected", "Stage under repair")],
)
def test_tc_spl_79_04_reason_or_note_stays_with_its_action(app, client, requested, resulting, text):
    decide(
        app,
        requested["booking"]["id"],
        resulting,
        text,
        datetime.now(SINGAPORE) + timedelta(minutes=5),
    )

    history = status(client, requested["event"]).json["history"]

    assert len(history) == 2
    assert history[0]["status"] == "requested" and history[0]["note"] is None
    assert history[1]["status"] == resulting
    assert history[1]["note"] == text
    assert history[1]["actor"] == {"id": VENUE_STAFF, "name": "Valerie Tan"}


# TC-SPL-79-05
def test_tc_spl_79_05_history_is_ordered_by_action_time(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(event_request_id=event_id, venue_id=venue_id, status="rejected")
        session.add(booking)
        session.flush()
        for action, resulting, minute, hour in (
            ("reject", "rejected", 30, 9),
            ("request", "requested", 0, 9),
            ("note", "rejected", 0, 10),
        ):
            session.add(
                VenueBookingStatusHistory(
                    booking_id=booking.id,
                    action=action,
                    previous_status=None,
                    resulting_status=resulting,
                    actor_account_id=COORDINATOR,
                    changed_at=datetime(2026, 9, 27, hour, minute, tzinfo=SINGAPORE),
                )
            )
        session.commit()

    history = status(client, event_id).json["history"]

    assert [entry["changed_at"] for entry in history] == [
        "2026-09-27T09:00:00+08:00",
        "2026-09-27T09:30:00+08:00",
        "2026-09-27T10:00:00+08:00",
    ]


# TC-SPL-79-06 (b) — refused actions record nothing
def test_tc_spl_79_06_refused_actions_record_nothing(app, client, requested):
    harbour_talk = make_event(app, "Harbour Talk")
    before = history_count(app)

    conflict = request_booking(client, harbour_talk, requested["venue"])
    assert conflict.status_code == 409
    assert history_count(app) == before

    assert withdraw(client, requested["event"], requested["booking"]["id"]).status_code == 200
    after_withdrawal = history_count(app)
    again = withdraw(client, requested["event"], requested["booking"]["id"])
    assert again.status_code == 409
    assert history_count(app) == after_withdrawal == before + 1


# AC3 — current status separate from history


# TC-SPL-79-07
def test_tc_spl_79_07_current_status_is_separate_from_history(app, client, requested):
    before = status(client, requested["event"]).json
    assert before["current_status"]["status"] == "requested"
    assert "current_status" not in before["history"][0]

    withdraw(client, requested["event"], requested["booking"]["id"])
    after = status(client, requested["event"]).json

    assert after["current_status"] == {"status": "withdrawn", "label": "Withdrawn"}
    assert after["history"][0]["status"] == "requested"
    assert after["venue_booking_request"]["status"] == "withdrawn"


# AC4 — reading changes nothing


# TC-SPL-79-09
def test_tc_spl_79_09_reading_changes_nothing(app, client, requested):
    before = snapshot(app, requested["event"])

    for _ in range(3):
        assert status(client, requested["event"]).status_code == 200

    assert snapshot(app, requested["event"]) == before


# TC-SPL-79-10
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_tc_spl_79_10_other_methods_change_nothing(app, client, requested, method):
    before = snapshot(app, requested["event"])

    response = getattr(client, method)(
        f"/api/event-requests/{requested['event']}/venue-booking-status",
        json={"status": "approved"},
        headers=headers(),
    )

    assert not 200 <= response.status_code < 300
    assert snapshot(app, requested["event"]) == before


# AC5 — only the assigned coordinator


# TC-SPL-79-11
def test_tc_spl_79_11_unassigned_coordinator_is_refused(app, client, requested):
    refused = status(client, requested["event"], token="other-coordinator")
    unknown = status(client, 999999, token="other-coordinator")
    out_of_range = status(client, 2**31)

    assert refused.status_code == unknown.status_code == out_of_range.status_code == 404
    assert refused.json == unknown.json == out_of_range.json
    assert "Coastal Forum" not in refused.get_data(as_text=True)
    assert "Harbour Hall" not in refused.get_data(as_text=True)


# TC-SPL-79-12
@pytest.mark.parametrize(
    ("token", "expected"),
    [("venue-staff", 403), ("organiser", 403), ("manager", 403), (None, 401)],
)
def test_tc_spl_79_12_other_roles_and_no_session_are_refused(
    app, client, requested, token, expected
):
    assert status(client, requested["event"], token=token).status_code == expected


# TC-SPL-79-13
def test_tc_spl_79_13_access_follows_the_current_assignment(app, client, requested):
    with Session(app.extensions["engine"]) as session:
        session.execute(
            update(EventCoordinatorAssignment)
            .where(EventCoordinatorAssignment.event_request_id == requested["event"])
            .values(coordinator_account_id=OTHER_COORDINATOR)
        )
        session.commit()

    former = status(client, requested["event"])
    current = status(client, requested["event"], token="other-coordinator")

    assert former.status_code == 404
    assert current.status_code == 200
    assert current.json["history"][0]["actor"] == {"id": COORDINATOR, "name": "Casey Lim"}


# AC6 — an explicit "no venue-booking request" result


# TC-SPL-79-14
def test_tc_spl_79_14_no_request_returns_an_explicit_result(app, client):
    event_id = make_event(app)

    response = status(client, event_id)

    assert response.status_code == 200
    assert response.json == {
        "venue_booking_request": None,
        "current_status": None,
        "history": [],
        "review": None,
        "earlier_requests": [],
        "message": NO_REQUEST,
    }


# AC7 — review marker, triggering block and time


def mark_for_review(app, venue_id, booking_id, *, remove_block=False):
    with Session(app.extensions["engine"]) as session:
        block = VenueOperationalBlock(
            venue_id=venue_id,
            start_date=EVENT_DATE,
            end_date=EVENT_DATE,
            slots=["PM"],
            reason="Ceiling repair",
            created_by_account_id=VENUE_STAFF,
            created_at=datetime(2026, 9, 27, 9, tzinfo=SINGAPORE),
            removed_by_account_id=VENUE_STAFF if remove_block else None,
            removed_at=datetime(2026, 9, 27, 12, tzinfo=SINGAPORE) if remove_block else None,
        )
        session.add(block)
        session.flush()
        session.execute(
            update(VenueBooking)
            .where(VenueBooking.id == booking_id)
            .values(
                requires_review=True,
                review_trigger_block_id=block.id,
                review_marked_at=datetime(2026, 9, 27, 9, tzinfo=SINGAPORE),
                review_marked_by_account_id=VENUE_STAFF,
            )
        )
        session.commit()
        return block.id


# TC-SPL-79-16
def test_tc_spl_79_16_review_marker_names_block_and_time(app, client, requested):
    block_id = mark_for_review(app, requested["venue"], requested["booking"]["id"])

    review = status(client, requested["event"]).json["review"]

    assert review == {
        "requires_review": True,
        "marked_at": "2026-09-27T09:00:00+08:00",
        "trigger_block": {
            "id": block_id,
            "start_date": "2026-10-14",
            "end_date": "2026-10-14",
            "slots": ["PM"],
            "reason": "Ceiling repair",
        },
    }


# TC-SPL-79-17
def test_tc_spl_79_17_unmarked_and_stored_marker_partitions(app, client, requested):
    unmarked = status(client, requested["event"]).json["review"]
    assert unmarked == {"requires_review": False, "marked_at": None, "trigger_block": None}

    mark_for_review(app, requested["venue"], requested["booking"]["id"], remove_block=True)

    stored = status(client, requested["event"]).json["review"]
    assert stored["requires_review"] is True
    assert stored["trigger_block"]["reason"] == "Ceiling repair"


# Assumption — the latest request is current; earlier requests are listed


# TC-SPL-79-18
def test_tc_spl_79_18_latest_request_is_current_and_earlier_are_listed(app, client, requested):
    event_id, first = requested["event"], requested["booking"]["id"]
    withdraw(client, event_id, first)
    second = request_booking(client, event_id, requested["venue"]).json["booking"]["id"]

    body = status(client, event_id).json

    assert body["venue_booking_request"]["id"] == second
    assert body["current_status"]["status"] == "requested"
    assert [entry["status"] for entry in body["history"]] == ["requested"]
    assert body["earlier_requests"] == [
        {
            "id": first,
            "venue": {"id": requested["venue"], "name": "Harbour Hall"},
            "date": "2026-10-14",
            "status": "withdrawn",
            "status_label": "Withdrawn",
        }
    ]
