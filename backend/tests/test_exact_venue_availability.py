"""SPL-129 protected configuration and read-only exact-time search."""

from datetime import datetime, timezone

import pytest
import test_venue_availability as legacy_tests
from app.models import (
    EventRequest,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueOperationalBlock,
)
from sqlalchemy.orm import Session
from test_venue_availability import SEARCH_DATE, TOKENS, VENUE_STAFF, add_venue, headers

base_app = legacy_tests.app


@pytest.fixture
def app(base_app):
    base_app.config["EXACT_VENUE_TIMING_ENABLED"] = True
    base_app.config["IDENTITY_VERIFIER"] = (TOKENS | {"staff": VENUE_STAFF}).__getitem__
    return base_app


@pytest.fixture
def client(app):
    return app.test_client()


def configure(client, venue_id, **overrides):
    data = {"setup_minutes": 30, "turnaround_minutes": 45, "operating_intervals": [[540, 1080]]}
    data.update(overrides)
    return client.patch(f"/api/venues/{venue_id}", json=data, headers=headers("staff"))


def search(client, app, **overrides):
    data = {"date": "2026-10-12", "start_time": "10:00", "end_time": "12:00"}
    data.update(overrides)
    return client.get(
        f"/api/event-requests/{app.config['TEST_EVENT_ID']}/available-venues",
        query_string=data,
        headers=headers(),
    )


# TC-SPL-129-01


def test_tc_spl_129_01_staff_saves_complete_configuration(client, app):
    venue_id = add_venue(app, "Hall", setup=1)
    response = configure(client, venue_id)
    assert response.status_code == 200
    venue = response.json["venue"]
    assert venue["setup_minutes"] == 30
    assert venue["turnaround_minutes"] == 45
    assert venue["operating_intervals"] == [[540, 1080]]
    assert venue["setup_buffer_slots"] == 1
    assert venue["timing_readiness"] == "ready"
    assert venue["timing_revision"] == 1
    fetched = client.get(f"/api/venues/{venue_id}", headers=headers()).json["venue"]
    assert fetched == venue


# TC-SPL-129-04


def test_tc_spl_129_04_search_and_saved_suitability_have_separate_intervals(client, app):
    venue_id = add_venue(app, "Hall")
    assert configure(client, venue_id).status_code == 200
    response = search(client, app)
    assert response.status_code == 200
    venue = response.json["venues"][0]
    assert venue["timing"]["event"] == {
        "start": "2026-10-12T10:00:00+08:00",
        "end": "2026-10-12T12:00:00+08:00",
    }
    assert venue["timing"]["occupied"] == {
        "start": "2026-10-12T09:30:00+08:00",
        "end": "2026-10-12T12:45:00+08:00",
    }
    assert venue["suitability"]["checks"][0]["passed"] is False  # saved event 07:00–18:00


# TC-SPL-129-03


@pytest.mark.parametrize(
    "overrides",
    [
        {"setup_minutes": -1},
        {"turnaround_minutes": True},
        {"setup_minutes": 1.5},
        {"operating_intervals": [[540, 500]]},
        {"operating_intervals": [[540, 600], [599, 700]]},
    ],
)
def test_tc_spl_129_03_invalid_settings_are_atomic(client, app, overrides):
    venue_id = add_venue(app, "Hall")
    assert configure(client, venue_id).status_code == 200
    before = client.get(f"/api/venues/{venue_id}", headers=headers()).json
    assert configure(client, venue_id, **overrides).status_code == 400
    assert client.get(f"/api/venues/{venue_id}", headers=headers()).json == before


# TC-SPL-129-05


@pytest.mark.parametrize(
    "status,available",
    [
        ("requested", False),
        ("approved", False),
        ("withdrawn", True),
        ("rejected", True),
        ("cancelled", True),
    ],
)
def test_tc_spl_129_05_active_claims_only(client, app, status, available):
    venue_id = add_venue(app, "Hall")
    configure(client, venue_id)
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=app.config["TEST_EVENT_ID"], venue_id=venue_id, status=status
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id, venue_id=venue_id, day=SEARCH_DATE, slot="AM", kind="event"
            )
        )
        session.commit()
    response = search(client, app)
    assert response.status_code == 200
    assert bool(response.json["venues"]) is available
    assert "Community forum" not in response.get_data(as_text=True)


# TC-SPL-129-05


@pytest.mark.parametrize("removed,available", [(False, False), (True, True)])
def test_tc_spl_129_05_active_blocks_only(client, app, removed, available):
    venue_id = add_venue(app, "Hall")
    configure(client, venue_id)
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueOperationalBlock(
                venue_id=venue_id,
                start_date=SEARCH_DATE,
                end_date=SEARCH_DATE,
                slots=["AM"],
                reason="Maintenance",
                created_by_account_id=VENUE_STAFF,
                created_at=datetime.now(timezone.utc),
                removed_at=datetime.now(timezone.utc) if removed else None,
            )
        )
        session.commit()
    assert bool(search(client, app).json["venues"]) is available


# TC-SPL-129-08


def test_tc_spl_129_08_missing_evidence_fails_closed(client, app):
    venue_id = add_venue(app, "Unconfirmed")
    assert search(client, app).json["venues"] == []
    configure(client, venue_id)
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueBooking(
                event_request_id=app.config["TEST_EVENT_ID"], venue_id=venue_id, status="requested"
            )
        )
        session.commit()
    assert search(client, app).json["venues"] == []


# TC-SPL-129-09


def test_tc_spl_129_09_explicit_settings_do_not_rewrite_old_claims(client, app):
    venue_id = add_venue(app, "Legacy", setup=1)
    before = client.get(f"/api/venues/{venue_id}", headers=headers()).json["venue"]
    assert before["setup_minutes"] is None
    assert before["timing_readiness"] == "configuration_required"
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=app.config["TEST_EVENT_ID"], venue_id=venue_id, status="approved"
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id, venue_id=venue_id, day=SEARCH_DATE, slot="AM", kind="setup"
            )
        )
        session.commit()
    assert configure(client, venue_id, setup_minutes=0, turnaround_minutes=0).status_code == 200
    assert search(client, app).json["venues"] == []
    with Session(app.extensions["engine"]) as session:
        assert session.get(Venue, venue_id).setup_buffer_slots == 1
        assert session.query(VenueBookingOccupancy).one().kind == "setup"


# TC-SPL-129-10


@pytest.mark.parametrize(
    "filters",
    [
        {"expected_attendance": "101"},
        {"preferred_room_layout": "banquet"},
        {"required_facility": "Projector"},
        {"accessibility_need": "Lift"},
        {"location_preference": "Tokyo"},
    ],
)
def test_tc_spl_129_10_all_profile_filters_remain(client, app, filters):
    venue_id = add_venue(app, "Hall")
    configure(client, venue_id)
    assert len(search(client, app).json["venues"]) == 1
    assert search(client, app, **filters).json["venues"] == []


# TC-SPL-129-11


@pytest.mark.parametrize(
    "token,status", [(None, 401), ("organiser", 403), ("other-coordinator", 404)]
)
def test_tc_spl_129_11_search_access(client, app, token, status):
    response = client.get(
        f"/api/event-requests/{app.config['TEST_EVENT_ID']}/available-venues?date=2026-10-12&start_time=10:00&end_time=12:00",
        headers=headers(token) if token else {},
    )
    assert response.status_code == status


# TC-SPL-129-11


def test_tc_spl_129_11_nonplanning_and_staff_only(client, app):
    venue_id = add_venue(app, "Hall")
    response = client.patch(
        f"/api/venues/{venue_id}",
        json={"setup_minutes": 30, "turnaround_minutes": 45, "operating_intervals": [[540, 1080]]},
        headers=headers(),
    )
    assert response.status_code == 403
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, app.config["TEST_EVENT_ID"]).status = "under_review"
        session.commit()
    assert search(client, app).status_code == 409


# TC-SPL-129-12


def test_tc_spl_129_12_reads_never_mutate_and_gate_preserves_old_workflow(client, app):
    venue_id = add_venue(app, "Hall")
    configure(client, venue_id)
    with Session(app.extensions["engine"]) as session:
        before = session.get(EventRequest, app.config["TEST_EVENT_ID"]).start_time
    assert search(client, app).status_code == 200
    assert search(client, app, start_time="10:07").status_code == 400
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, app.config["TEST_EVENT_ID"]).start_time == before
        assert session.query(VenueBooking).count() == 0
        assert session.query(VenueBookingOccupancy).count() == 0
    app.config["EXACT_VENUE_TIMING_ENABLED"] = False
    assert configure(client, venue_id).status_code == 409
    assert search(client, app).status_code == 409
    old = client.get(
        f"/api/event-requests/{app.config['TEST_EVENT_ID']}/available-venues?date=2026-10-12&slot=AM",
        headers=headers(),
    )
    assert old.status_code == 200
    assert len(old.json["venues"]) == 1
