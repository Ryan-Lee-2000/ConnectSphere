"""SPL-138 exact closures: real routes, persisted evidence, independent boundaries."""

from datetime import time

import pytest
from app.exact_venue_availability import exact_availability
from app.models import EventRequest, Venue, VenueBooking, VenueOperationalBlock
from app.venue_operational_blocks import operational_block_for_slot
from app.venue_timing import parse_event_interval
from sqlalchemy.orm import Session
from test_exact_venue_bookings import app as app
from test_exact_venue_bookings import base_app as base_app
from test_exact_venue_bookings import client as client
from test_exact_venue_bookings import headers, request_booking, scenario


def close(client, venue, **changes):
    payload = {
        "date": "2026-10-14",
        "start_time": "12:30",
        "end_time": "13:00",
        "reason": "Maintenance",
    }
    payload.update(changes)
    return client.post(
        f"/api/venues/{venue}/operational-blocks", json=payload, headers=headers("venue-staff")
    )


def calendar(client, venue, token="venue-staff"):
    return client.get(
        f"/api/venues/{venue}/occupancy?start_date=2026-10-14&end_date=2026-10-14",
        headers=headers(token),
    )


# TC-SPL-138-01
def test_tc_spl_138_01_create_remove_audit(app, client):
    _, venue = scenario(app)
    created = close(client, venue)
    assert created.status_code == 201
    block = created.json["operational_block"]
    assert block["timing"] == {
        "start": "2026-10-14T12:30:00+08:00",
        "end": "2026-10-14T13:00:00+08:00",
    }
    assert block["slots"] == []
    assert (
        client.get(f"/api/venues/{venue}/operational-blocks", headers=headers("venue-staff")).json[
            "operational_blocks"
        ][0]
        == block
    )
    removed = client.delete(
        f"/api/venues/{venue}/operational-blocks/{block['id']}", headers=headers("venue-staff")
    )
    assert removed.status_code == 200
    assert removed.json["operational_block"]["removed_at"]
    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueOperationalBlock, block["id"])
        assert (
            stored.reason == "Maintenance"
            and stored.removed_by_account_id == stored.created_by_account_id
        )


# TC-SPL-138-02
@pytest.mark.parametrize(
    "changes",
    [
        {"date": "bad"},
        {"start_time": "12:31"},
        {"start_time": "24:00"},
        {"end_time": "12:30"},
        {"end_time": "12:00"},
        {"end_time": "13:00:01"},
        {"reason": " "},
        {"reason": None},
        {"slots": ["AM"]},
        {"created_by_account_id": "forged"},
    ],
)
def test_tc_spl_138_02_invalid_leaves_no_records(app, client, changes):
    _, venue = scenario(app)
    assert close(client, venue, **changes).status_code == 400
    with Session(app.extensions["engine"]) as session:
        assert session.query(VenueOperationalBlock).count() == 0


# TC-SPL-138-03
def test_tc_spl_138_03_closed_hours_and_midnight(app, client):
    _, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        row.operating_intervals = [[540, 1080]]
        row.setup_minutes = row.turnaround_minutes = 0
        session.commit()
    block = close(client, venue, start_time="17:45", end_time="24:00").json["operational_block"]
    assert block["timing"]["end"] == "2026-10-15T00:00:00+08:00"
    client.delete(
        f"/api/venues/{venue}/operational-blocks/{block['id']}", headers=headers("venue-staff")
    )
    with Session(app.extensions["engine"]) as session:
        assert not exact_availability(
            session, session.get(Venue, venue), parse_event_interval("2026-10-14", "18:00", "19:00")
        )[0]
    assert calendar(client, venue).json["days"][0]["intervals"][-1]["status"] == "not_operated"


# TC-SPL-138-04
def test_tc_spl_138_04_calendar_uses_snapshots_not_current_event(app, client):
    event, venue = scenario(app)
    assert request_booking(client, event, venue).status_code == 201
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event).start_time = time(11)
        session.get(Venue, venue).setup_minutes = 60
        session.commit()
    rows = calendar(client, venue).json["days"][0]["intervals"]
    assert [(r["start"][11:16], r["end"][11:16], r["status"]) for r in rows] == [
        ("00:00", "09:30", "available"),
        ("09:30", "10:00", "preparation"),
        ("10:00", "12:00", "requested"),
        ("12:00", "12:45", "preparation"),
        ("12:45", "00:00", "available"),
    ]
    assert rows[1]["reasons"][0]["label"] == "Setup"
    assert rows[3]["reasons"][0]["label"] == "Turnaround"


# TC-SPL-138-05
def test_tc_spl_138_05_legacy_gaps_and_gate_rollback(app, client):
    _, venue = scenario(app)
    response = client.post(
        f"/api/venues/{venue}/operational-blocks",
        headers=headers("venue-staff"),
        json={"start_date": "2026-10-14", "slots": ["AM", "PM"], "reason": "Legacy"},
    )
    assert response.status_code == 201
    rows = calendar(client, venue).json["days"][0]["intervals"]
    assert any(
        r["start"][11:16] == "12:00" and r["end"][11:16] == "13:00" and r["status"] == "available"
        for r in rows
    )
    assert close(client, venue, start_time="19:15", end_time="19:30").status_code == 201
    app.config["EXACT_VENUE_TIMING_ENABLED"] = False
    assert close(client, venue).status_code == 409
    with Session(app.extensions["engine"]) as session:
        assert (
            operational_block_for_slot(
                session, venue, __import__("datetime").date(2026, 10, 14), "NIGHT"
            )
            is not None
        )


# TC-SPL-138-06
def test_tc_spl_138_06_turnaround_marks_and_refuses_approval(app, client):
    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    assert close(client, venue).json["affected_booking_count"] == 1
    assert (
        client.post(
            f"/api/venue-bookings/{booking['id']}/approve", json={}, headers=headers("venue-staff")
        ).status_code
        == 409
    )
    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueBooking, booking["id"])
        assert stored.requires_review and stored.status == "requested"
        assert stored.exact_timing == booking["timing"]
        assert session.get(EventRequest, event).status == "planning"


# TC-SPL-138-07
def test_tc_spl_138_07_removing_one_block_preserves_other_and_review(app, client):
    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    first = close(client, venue).json["operational_block"]["id"]
    second = close(client, venue).json["operational_block"]["id"]
    client.delete(f"/api/venues/{venue}/operational-blocks/{first}", headers=headers("venue-staff"))
    assert any(
        r["status"] == "blocked" for r in calendar(client, venue).json["days"][0]["intervals"]
    )
    client.delete(
        f"/api/venues/{venue}/operational-blocks/{second}", headers=headers("venue-staff")
    )
    with Session(app.extensions["engine"]) as session:
        assert session.get(VenueBooking, booking["id"]).requires_review
        assert session.query(VenueOperationalBlock).count() == 2
    read = client.get(f"/api/venue-bookings/{booking['id']}", headers=headers("venue-staff"))
    assert read.json["review"]["requires_review"] is True
    assert read.json["review"]["trigger_block"]["timing"]["start"] == "2026-10-14T12:30:00+08:00"


# TC-SPL-138-08
@pytest.mark.parametrize(
    "token,read,write",
    [
        ("coordinator", 200, 403),
        ("manager", 200, 403),
        ("other-coordinator", 200, 403),
        ("venue-staff", 200, 201),
        ("organiser", 403, 403),
        (None, 401, 401),
    ],
)
def test_tc_spl_138_08_authority_and_calendar_privacy(app, client, token, read, write):
    _, venue = scenario(app)
    assert close(client, venue, reason="Secret client name").status_code == 201
    response = calendar(client, venue, token)
    assert response.status_code == read
    assert "Secret client name" not in response.get_data(as_text=True)
    assert (
        client.post(
            f"/api/venues/{venue}/operational-blocks",
            headers=headers(token),
            json={
                "date": "2026-10-14",
                "start_time": "15:00",
                "end_time": "16:00",
                "reason": "Test",
            },
        ).status_code
        == write
    )


# TC-SPL-138-11
@pytest.mark.parametrize(
    "start,end,affected",
    [("12:45", "13:00", 0), ("12:30", "12:45", 1), ("09:15", "09:30", 0), ("09:30", "09:45", 1)],
)
def test_tc_spl_138_11_touching_is_not_overlap(app, client, start, end, affected):
    event, venue = scenario(app)
    request_booking(client, event, venue)
    assert (
        close(client, venue, start_time=start, end_time=end).json["affected_booking_count"]
        == affected
    )


# TC-SPL-138-06: all overlapping active bookings, with non-overlap and terminal controls.
def test_tc_spl_138_06_marks_all_and_preserves_unaffected(app, client):
    from test_venue_booking_requests import make_event

    _, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        row.setup_minutes = row.turnaround_minutes = 0
        session.commit()
    ids = []
    for hour in (9, 10, 14):
        event = make_event(app, name=f"Event {hour}", start=time(hour), end=time(hour + 1))
        response = request_booking(
            client, event, venue, start_time=f"{hour:02d}:00", end_time=f"{hour + 1:02d}:00"
        )
        assert response.status_code == 201
        ids.append(response.json["booking"]["id"])
    result = close(client, venue, start_time="09:30", end_time="10:30")
    assert result.json["affected_booking_count"] == 2
    with Session(app.extensions["engine"]) as session:
        assert [session.get(VenueBooking, key).requires_review for key in ids] == [
            True,
            True,
            False,
        ]


# TC-SPL-138-11: buffers are minutes, not 15-minute buckets.
def test_tc_spl_138_11_one_minute_overlap_and_search(app, client):
    event, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        row.turnaround_minutes = 46
        session.commit()
    assert request_booking(client, event, venue).status_code == 201
    assert close(client, venue, start_time="12:45").json["affected_booking_count"] == 1
    rows = calendar(client, venue).json["days"][0]["intervals"]
    assert any(
        r["start"][11:16] == "12:45" and r["end"][11:16] == "12:46" and len(r["reasons"]) == 2
        for r in rows
    )
    # Independent venue with a closure: real search must withhold the candidate.
    _, other = scenario(app)
    close(client, other, start_time="10:00", end_time="10:15")
    response = client.get(
        f"/api/event-requests/{event}/available-venues?date=2026-10-14&start_time=10:00&end_time=12:00",
        headers=headers(),
    )
    assert response.status_code == 200
    assert other not in [v["id"] for v in response.json["venues"]]


# TC-SPL-138-04: incomplete configuration cannot advertise availability.
def test_tc_spl_138_04_missing_preparation_configuration_is_not_free(app, client):
    _, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        session.get(Venue, venue).setup_minutes = None
        session.commit()
    rows = calendar(client, venue).json["days"][0]["intervals"]
    assert rows and all(row["status"] == "review_required" for row in rows)


# TC-SPL-138-05: exercise production legacy reads/writes after rollback, not just the helper.
def test_tc_spl_138_05_exact_closure_blocks_legacy_booking_after_flag_off(app, client):
    import test_venue_booking_requests as legacy

    event = legacy.make_event(app)
    venue = legacy.add_venue(app, setup=0, turnaround=0)
    block = close(client, venue, start_time="13:15", end_time="13:30").json["operational_block"]
    app.config["EXACT_VENUE_TIMING_ENABLED"] = False
    assert legacy.request_booking(client, event, venue).status_code == 409
    found = legacy.search(client, event, __import__("datetime").date(2026, 10, 14), "PM")
    assert "Harbour Hall" not in found
    assert (
        client.delete(
            f"/api/venues/{venue}/operational-blocks/{block['id']}", headers=headers("venue-staff")
        ).status_code
        == 200
    )
    assert legacy.request_booking(client, event, venue).status_code == 201


# TC-SPL-138-07: removal must preserve a separate current requirement failure.
def test_tc_spl_138_07_removal_keeps_independent_event_review(app, client):
    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    block = close(client, venue).json["operational_block"]
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event).expected_attendance = 10000
        session.commit()
    assert (
        client.delete(
            f"/api/venues/{venue}/operational-blocks/{block['id']}", headers=headers("venue-staff")
        ).status_code
        == 200
    )
    response = client.get(f"/api/venue-bookings/{booking['id']}", headers=headers("venue-staff"))
    reasons = response.json["booking"]["review_reasons"]
    assert "Event requirements changed. Review and submit a new request." in reasons
    assert not any("operational block" in reason for reason in reasons)
    assert response.json["review"]["requires_review"]
    assert (
        client.post(
            f"/api/venue-bookings/{booking['id']}/approve", headers=headers("venue-staff"), json={}
        ).status_code
        == 409
    )


# TC-SPL-138-04 / TC-SPL-138-06: setup crosses Singapore midnight and is clipped per day.
def test_tc_spl_138_04_cross_midnight_setup_keeps_original_interval(app, client):
    event, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(EventRequest, event)
        row.start_time, row.end_time = time(0, 15), time(1)
        session.commit()
    booked = request_booking(client, event, venue, start_time="00:15", end_time="01:00")
    assert booked.status_code == 201
    block = close(client, venue, date="2026-10-13", start_time="23:45", end_time="24:00")
    assert block.status_code == 201 and block.json["affected_booking_count"] == 1
    response = client.get(
        f"/api/venues/{venue}/occupancy?start_date=2026-10-13&end_date=2026-10-14",
        headers=headers("venue-staff"),
    )
    yesterday, today = response.json["days"]
    edge = yesterday["intervals"][-1]
    assert edge["start"] == "2026-10-13T23:45:00+08:00"
    assert edge["end"] == "2026-10-14T00:00:00+08:00"
    assert {reason["key"] for reason in edge["reasons"]} == {"setup", "block"}
    assert today["intervals"][0]["status"] == "preparation"
    assert today["intervals"][0]["end"] == "2026-10-14T00:15:00+08:00"
    with Session(app.extensions["engine"]) as session:
        assert (
            session.get(VenueBooking, booked.json["booking"]["id"]).exact_timing
            == booked.json["booking"]["timing"]
        )
