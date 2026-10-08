"""SPL-137 acceptance cases through protected booking APIs."""

from datetime import time

import pytest
import test_venue_booking_requests as legacy
from app.models import EventRequest, Venue
from sqlalchemy.orm import Session

base_app = legacy.app


@pytest.fixture
def app(base_app):
    base_app.config["EXACT_VENUE_TIMING_ENABLED"] = True
    return base_app


@pytest.fixture
def client(app):
    return app.test_client()


def scenario(app):
    event = legacy.make_event(app, start=time(10), end=time(12))
    venue = legacy.add_venue(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        row.setup_minutes = 30
        row.turnaround_minutes = 45
        row.operating_intervals = [[0, 1440]]
        row.timing_revision = 1
        session.commit()
    return event, venue


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def request_booking(client, event, venue, **changes):
    data = {
        "venue_id": venue,
        "layout": "theatre",
        "date": "2026-10-14",
        "start_time": "10:00",
        "end_time": "12:00",
        "venue_revision": 1,
    }
    data.update(changes)
    return client.post(f"/api/event-requests/{event}/venue-bookings", json=data, headers=headers())


def test_tc_01_exact_request_and_approval_preserve_reviewed_interval(app, client):
    event, venue = scenario(app)
    response = request_booking(client, event, venue)
    assert response.status_code == 201, response.json
    booking = response.json["booking"]
    assert booking["timing"]["event"]["start"] == "2026-10-14T10:00:00+08:00"
    assert booking["timing"]["occupied"] == {
        "start": "2026-10-14T09:30:00+08:00",
        "end": "2026-10-14T12:45:00+08:00",
    }
    approved = client.post(
        f"/api/venue-bookings/{booking['id']}/approve", json={}, headers=headers("venue-staff")
    )
    assert approved.status_code == 200, approved.json
    assert approved.json["booking"]["status"] == "approved"
    assert approved.json["booking"]["timing"] == booking["timing"]


def test_tc_04_overlap_refused_touching_allowed_and_block_marks_exact(app, client):
    event, venue = scenario(app)
    first = request_booking(client, event, venue).json["booking"]
    second_event = legacy.make_event(app, name="Second event", start=time(12), end=time(13))
    conflict = request_booking(client, second_event, venue, start_time="12:00", end_time="13:00")
    assert conflict.status_code == 409
    second_event = legacy.make_event(app, name="Touching event", start=time(13, 15), end=time(14))
    touching = request_booking(client, second_event, venue, start_time="13:15", end_time="14:00")
    assert touching.status_code == 201
    block = client.post(
        f"/api/venues/{venue}/operational-blocks",
        headers=headers("venue-staff"),
        json={"start_date": "2026-10-14", "slots": ["AM"], "reason": "Maintenance"},
    )
    assert block.status_code == 201
    assert block.json["affected_booking_count"] == 1
    reviewed = client.get(f"/api/venue-bookings/{first['id']}", headers=headers("venue-staff"))
    assert reviewed.json["review"]["requires_review"] is True
    assert (
        client.post(
            f"/api/venue-bookings/{first['id']}/approve", json={}, headers=headers("venue-staff")
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"start_time": "10:07"},
        {"end_time": "09:00"},
        {"status": "approved"},
        {"occupied_start": "2026-10-14T00:00:00+08:00"},
    ],
)
def test_tc_02_invalid_and_server_owned_fields_refused(app, client, changes):
    event, venue = scenario(app)
    assert request_booking(client, event, venue, **changes).status_code == 400
    body = client.get(f"/api/event-requests/{event}/venue-booking-status", headers=headers()).json
    assert body["venue_booking_request"] is None
    assert body["history"] == []


@pytest.mark.parametrize(
    "token,status",
    [("other-coordinator", 404), ("organiser", 403), ("venue-staff", 403), (None, 401)],
)
def test_tc_02_authority(app, client, token, status):
    event, venue = scenario(app)
    result = client.post(
        f"/api/event-requests/{event}/venue-bookings",
        headers=headers(token),
        json={
            "venue_id": venue,
            "layout": "theatre",
            "date": "2026-10-14",
            "start_time": "10:00",
            "end_time": "12:00",
            "venue_revision": 1,
        },
    )
    assert result.status_code == status


@pytest.mark.parametrize(
    "change",
    ["event", "date", "start", "end", "buffers", "hours", "layout", "facilities", "accessibility"],
)
def test_tc_03_05_changed_requirements_refuse_approval_without_mutation(app, client, change):
    from app.models import EventRequest

    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        if change == "event":
            session.get(EventRequest, event).expected_attendance = 180
        if change == "date":
            session.get(EventRequest, event).proposed_date = legacy.EVENT_DATE.replace(day=15)
        if change == "start":
            session.get(EventRequest, event).start_time = time(10, 15)
        if change == "end":
            session.get(EventRequest, event).end_time = time(11, 45)
        if change == "buffers":
            row.setup_minutes = 60
        if change == "hours":
            row.operating_intervals = [[600, 720]]
        if change == "layout":
            row.layouts[0].capacity = 1
        if change == "facilities":
            row.facilities = []
        if change == "accessibility":
            row.accessibility_features = []
        session.commit()
    result = client.post(
        f"/api/venue-bookings/{booking['id']}/approve", json={}, headers=headers("venue-staff")
    )
    assert result.status_code == 409, result.json
    read = client.get(f"/api/event-requests/{event}/venue-booking-status", headers=headers()).json
    assert read["venue_booking_request"]["timing"] == booking["timing"]
    assert read["venue_booking_request"]["status"] == "requested"
    assert read["venue_booking_request"]["review_reasons"]
    assert len(read["history"]) == 1


@pytest.mark.parametrize("action", ["reject", "withdraw"])
def test_tc_10_12_release_is_booking_specific_and_preserves_history(app, client, action):
    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    other = legacy.make_event(app, name="Other", start=time(14), end=time(15))
    second = request_booking(client, other, venue, start_time="14:00", end_time="15:00").json[
        "booking"
    ]
    if action == "reject":
        path = f"/api/venue-bookings/{booking['id']}/reject"
        options = {"json": {"reason": "Venue unavailable"}, "headers": headers("venue-staff")}
    else:
        path = f"/api/event-requests/{event}/venue-bookings/{booking['id']}/withdraw"
        options = {"headers": headers()}
    assert client.post(path, **options).status_code == 200
    assert client.post(path, **options).status_code == 409
    body = client.get(f"/api/event-requests/{event}/venue-booking-status", headers=headers()).json
    assert len(body["history"]) == 2
    assert body["venue_booking_request"]["timing"] == booking["timing"]
    assert (
        request_booking(
            client,
            legacy.make_event(app, name="Still blocked", start=time(14), end=time(15)),
            venue,
            start_time="14:00",
            end_time="15:00",
        ).status_code
        == 409
    )
    assert request_booking(client, event, venue).status_code == 201
    assert (
        client.get(f"/api/venue-bookings/{second['id']}", headers=headers("venue-staff")).json[
            "booking"
        ]["status"]
        == "requested"
    )


def test_tc_03_stale_search_cannot_silently_change_occupied_time(app, client):
    event, venue = scenario(app)
    response = client.patch(
        f"/api/venues/{venue}",
        headers=headers("venue-staff"),
        json={"setup_minutes": 60, "turnaround_minutes": 45, "operating_intervals": [[0, 1440]]},
    )
    assert response.status_code == 200
    assert request_booking(client, event, venue).status_code == 409
    assert request_booking(client, event, venue, venue_revision=2).status_code == 201


def test_tc_11_cancel_helper_checks_assignment_and_repeated_release(app, client):
    from datetime import datetime, timezone

    from app.exact_venue_bookings import cancel_booking
    from werkzeug.exceptions import HTTPException

    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    assert (
        client.post(
            f"/api/venue-bookings/{booking['id']}/approve", json={}, headers=headers("venue-staff")
        ).status_code
        == 200
    )
    with Session(app.extensions["engine"]) as session:
        with pytest.raises(HTTPException) as wrong:
            cancel_booking(
                session,
                booking["id"],
                coordinator_id=legacy.OTHER_COORDINATOR,
                changed_at=datetime.now(timezone.utc),
            )
        assert wrong.value.code == 404
        session.rollback()
        cancelled = cancel_booking(
            session,
            booking["id"],
            coordinator_id=legacy.COORDINATOR,
            changed_at=datetime.now(timezone.utc),
        )
        assert cancelled.status == "cancelled"
        session.commit()
        with pytest.raises(HTTPException) as repeated:
            cancel_booking(
                session,
                booking["id"],
                coordinator_id=legacy.COORDINATOR,
                changed_at=datetime.now(timezone.utc),
            )
        assert repeated.value.code == 409
    body = client.get(f"/api/event-requests/{event}/venue-booking-status", headers=headers()).json
    assert [item["action"] for item in body["history"]] == ["request", "approve", "cancel"]
    assert body["venue_booking_request"]["timing"] == booking["timing"]
    assert request_booking(client, event, venue).status_code == 201


@pytest.mark.parametrize("legacy_first", [True, False])
def test_tc_06_mixed_exact_and_legacy_bookings_protect_each_other(app, client, legacy_first):
    event, venue = scenario(app)
    other = legacy.make_event(app, name="Legacy or exact", start=time(10), end=time(12))
    if legacy_first:
        app.config["EXACT_VENUE_TIMING_ENABLED"] = False
        result = client.post(
            f"/api/event-requests/{event}/venue-bookings",
            headers=headers(),
            json={"venue_id": venue, "layout": "theatre"},
        )
        assert result.status_code == 201
        app.config["EXACT_VENUE_TIMING_ENABLED"] = True
        assert request_booking(client, other, venue).status_code == 409
    else:
        assert request_booking(client, event, venue).status_code == 201
        app.config["EXACT_VENUE_TIMING_ENABLED"] = False
        result = client.post(
            f"/api/event-requests/{other}/venue-bookings",
            headers=headers(),
            json={"venue_id": venue, "layout": "theatre"},
        )
        assert result.status_code == 409
        search = client.get(
            f"/api/event-requests/{other}/available-venues?date=2026-10-14&slot=AM",
            headers=headers(),
        )
        assert search.status_code == 200
        assert search.json["venues"] == []


@pytest.mark.parametrize("start,end", [("10:00", "10:15"), ("00:00", "00:15")])
def test_tc_01_zero_buffer_and_midnight_snapshots(app, client, start, end):
    event, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        session.get(EventRequest, event).start_time = time.fromisoformat(start)
        session.get(EventRequest, event).end_time = time.fromisoformat(end)
        row.setup_minutes = 0
        row.turnaround_minutes = 0
        session.commit()
    response = request_booking(client, event, venue, start_time=start, end_time=end)
    assert response.status_code == 201, response.json
    timing = response.json["booking"]["timing"]
    assert timing["event"] == timing["occupied"]
    assert timing["event"]["start"] == f"2026-10-14T{start}:00+08:00"


def test_tc_02_nonplanning_and_approval_cannot_amend_request(app, client):
    from app.models import EventRequest

    event, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(EventRequest, event)
        row.status = "confirmed"
        session.commit()
    assert request_booking(client, event, venue).status_code == 409
    with Session(app.extensions["engine"]) as session:
        row = session.get(EventRequest, event)
        row.status = "planning"
        session.commit()
    booking = request_booking(client, event, venue).json["booking"]
    assert (
        client.post(
            f"/api/venue-bookings/{booking['id']}/approve",
            json={"start_time": "09:00"},
            headers=headers("venue-staff"),
        ).status_code
        == 400
    )


def test_tc_06_unconfirmed_or_missing_legacy_evidence_refused(app, client):
    from app.models import VenueBooking

    event, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        row.operating_intervals = None
        session.commit()
    assert request_booking(client, event, venue).status_code == 409
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        row.operating_intervals = [[0, 1440]]
        other = legacy.make_event(app, name="Ambiguous legacy")
        session.add(VenueBooking(event_request_id=other, venue_id=venue, status="approved"))
        session.commit()
    assert request_booking(client, event, venue).status_code == 409


def test_tc_05_selected_layout_must_match_saved_requirement(app, client):
    from app.models import EventRequest

    event, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event).preferred_room_layout = "boardroom"
        session.commit()
    assert request_booking(client, event, venue, layout="theatre").status_code == 409
    assert request_booking(client, event, venue, layout="boardroom").status_code == 201


@pytest.mark.parametrize(
    "changes",
    [{"date": "2026-10-15"}, {"start_time": "10:15"}, {"end_time": "11:45"}, {"end_time": "24:00"}],
)
def test_tc_02_request_must_match_saved_event_schedule(app, client, changes):
    event, venue = scenario(app)
    response = request_booking(client, event, venue, **changes)
    assert response.status_code == 409, response.json
    assert "saved event" in response.json["error"]
    body = client.get(f"/api/event-requests/{event}/venue-booking-status", headers=headers()).json
    assert body["venue_booking_request"] is None
    assert body["history"] == []


def test_tc_03_preexisting_mismatched_booking_cannot_be_approved(app, client):
    from app.models import VenueBooking

    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    # Reproduce a record accepted by the old implementation, with an unchanged parent snapshot.
    with Session(app.extensions["engine"]) as session:
        row = session.get(VenueBooking, booking["id"])
        timing = dict(row.exact_timing)
        timing["event"] = {"start": "2026-10-14T11:00:00+08:00", "end": "2026-10-14T12:00:00+08:00"}
        timing["occupied"] = {
            "start": "2026-10-14T10:30:00+08:00",
            "end": "2026-10-14T12:45:00+08:00",
        }
        row.exact_timing = timing
        session.commit()
    response = client.post(
        f"/api/venue-bookings/{booking['id']}/approve", json={}, headers=headers("venue-staff")
    )
    assert response.status_code == 409, response.json
    body = client.get(f"/api/event-requests/{event}/venue-booking-status", headers=headers()).json
    assert body["venue_booking_request"]["status"] == "requested"
    assert any(
        "saved event" in reason for reason in body["venue_booking_request"]["review_reasons"]
    )
    assert body["venue_booking_request"]["timing"] == timing
    assert len(body["history"]) == 1
