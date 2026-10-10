"""SPL-107 acceptance through protected HTTP routes; expected times are independent."""

import pytest
import test_venue_booking_requests as legacy
from app.models import Venue
from sqlalchemy.orm import Session
from test_exact_venue_bookings import app as app
from test_exact_venue_bookings import base_app as base_app
from test_exact_venue_bookings import client as client
from test_exact_venue_bookings import headers, request_booking, scenario


def overview(client, token="coordinator", day="2026-10-14"):
    return client.get(f"/api/venues/occupancy-overview?date={day}", headers=headers(token))


# TC-SPL-107-01
def test_tc_spl_107_01_all_venues_and_exact_periods(app, client):
    event, venue = scenario(app)
    other = legacy.add_venue(app, name="Empty room")
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, other)
        row.operating_intervals = [[540, 1080]]
        row.setup_minutes = row.turnaround_minutes = 0
        session.commit()
    assert request_booking(client, event, venue).status_code == 201
    response = overview(client)
    assert response.status_code == 200
    assert response.json["date"] == "2026-10-14"
    assert response.json["timezone"] == "Asia/Singapore"
    venues = {row["id"]: row for row in response.json["venues"]}
    assert set(venues) == {venue, other}
    assert [
        (r["start"][11:16], r["end"][11:16], r["status"]) for r in venues[venue]["intervals"]
    ] == [
        ("00:00", "09:30", "available"),
        ("09:30", "10:00", "preparation"),
        ("10:00", "12:00", "requested"),
        ("12:00", "12:45", "preparation"),
        ("12:45", "00:00", "available"),
    ]
    assert [r["status"] for r in venues[other]["intervals"]] == [
        "not_operated",
        "available",
        "not_operated",
    ]
    assert venues[venue]["intervals"][1]["reasons"][0]["label"] == "Setup"
    assert venues[venue]["intervals"][3]["reasons"][0]["label"] == "Turnaround"


# TC-SPL-107-04
def test_tc_spl_107_04_review_marker_survives_removal_and_dynamic_edits(app, client):
    from datetime import time

    from app.models import EventRequest
    from test_timed_venue_closures import close

    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    assert (
        client.post(
            f"/api/venue-bookings/{booking['id']}/approve", json={}, headers=headers("venue-staff")
        ).status_code
        == 200
    )
    block = close(client, venue).json["operational_block"]
    for remove in (False, True):
        if remove:
            assert (
                client.delete(
                    f"/api/venues/{venue}/operational-blocks/{block['id']}",
                    headers=headers("venue-staff"),
                ).status_code
                == 200
            )
        rows = overview(client).json["venues"][0]["intervals"]
        event_row = next(r for r in rows if r["status"] == "booked")
        assert event_row["requires_review"] is True
        assert event_row["start"].endswith("10:00:00+08:00")
        assert event_row["end"].endswith("12:00:00+08:00")
    # A separate unmarked booking acquires a dynamic review requirement after a saved-event edit.
    second_event, second_venue = scenario(app)
    assert request_booking(client, second_event, second_venue).status_code == 201
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, second_event).start_time = time(11)
        session.commit()
    rows = next(v for v in overview(client).json["venues"] if v["id"] == second_venue)["intervals"]
    assert next(r for r in rows if r["status"] == "requested")["requires_review"] is True
    per_venue = client.get(
        f"/api/venues/{second_venue}/occupancy?start_date=2026-10-14&end_date=2026-10-14",
        headers=headers(),
    ).json
    assert [r["requires_review"] for r in rows] == [
        r["requires_review"] for r in per_venue["days"][0]["intervals"]
    ]
    detail = client.get(f"/api/event-requests/{event}/venue-booking-status", headers=headers()).json
    assert detail["review"]["requires_review"] is True


# TC-SPL-107-05, TC-SPL-107-06


@pytest.mark.parametrize(
    "token,permitted",
    [
        ("venue-staff", True),
        ("coordinator", True),
        ("other-coordinator", False),
        ("manager", False),
    ],
)
def test_tc_spl_107_05_06_details_follow_existing_permissions(app, client, token, permitted):
    from test_timed_venue_closures import close

    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    close(client, venue, reason="Private client closure note")
    response = overview(client, token)
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert ("Coastal Forum" in text) == permitted
    assert ("Private client closure note" in text) == (token == "venue-staff")
    links = [
        link
        for row in response.json["venues"][0]["intervals"]
        for reason in row["reasons"]
        for link in reason.get("links", [])
    ]
    if token == "venue-staff":
        assert any(link["href"] == f"/workspace/venue-bookings/{booking['id']}" for link in links)
    elif token == "coordinator":
        assert any(link["href"] == f"/workspace/assigned-events/{event}" for link in links)
    else:
        assert links == []
        assert "event_request_id" not in text and "booking_id" not in text
        assert (
            client.get(f"/api/venue-bookings/{booking['id']}", headers=headers(token)).status_code
            == 403
        )
        assert client.get(
            f"/api/event-requests/{event}/venue-booking-status", headers=headers(token)
        ).status_code in (403, 404)


# TC-SPL-107-02
@pytest.mark.parametrize(
    "query",
    [
        "",
        "?date=",
        "?date=bad",
        "?date=2026-02-30",
        "?date=20261014",
        "?date=9999-12-31",
        "?date=2026-10-14&date=2026-10-15",
        "?date=2026-10-14&role=venue_staff",
    ],
)
def test_tc_spl_107_02_invalid_date_contract(client, query):
    assert (
        client.get("/api/venues/occupancy-overview" + query, headers=headers()).status_code == 400
    )


# TC-SPL-107-02
def test_tc_spl_107_02_singapore_midnight_clips_without_changing_occupancy(app, client):
    from datetime import time

    from app.models import EventRequest

    event, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(EventRequest, event)
        row.start_time, row.end_time = time(0, 15), time(1)
        session.commit()
    assert (
        request_booking(client, event, venue, start_time="00:15", end_time="01:00").status_code
        == 201
    )
    previous = overview(client, day="2026-10-13").json["venues"][0]["intervals"][-1]
    assert previous["start"] == "2026-10-13T23:45:00+08:00"
    assert previous["end"] == "2026-10-14T00:00:00+08:00"
    assert previous["reasons"][0]["label"] == "Setup"
    today = overview(client).json["venues"][0]["intervals"]
    assert today[0]["start"] == "2026-10-14T00:00:00+08:00"
    assert today[0]["end"] == "2026-10-14T00:15:00+08:00"
    assert today[0]["reasons"][0]["period"]["start"] == previous["start"]


# TC-SPL-107-03
@pytest.mark.parametrize("turnaround,expected", [(45, 201), (46, 409)])
def test_tc_spl_107_03_touching_and_one_minute_conflict_agree_with_booking_and_search(
    app, client, turnaround, expected
):
    from datetime import time

    event, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue)
        row.setup_minutes = 0
        row.turnaround_minutes = turnaround
        session.commit()
    assert request_booking(client, event, venue).status_code == 201
    intervals = overview(client).json["venues"][0]["intervals"]
    end = "12:45" if turnaround == 45 else "12:46"
    assert (
        next(r for r in intervals if any(x["key"] == "turnaround" for x in r["reasons"]))["end"][
            11:16
        ]
        == end
    )
    second = legacy.make_event(app, start=time(12, 45), end=time(13, 45))
    found = client.get(
        f"/api/event-requests/{second}/available-venues?date=2026-10-14&start_time=12:45&end_time=13:45",
        headers=headers(),
    )
    assert found.status_code == 200
    assert (venue in [v["id"] for v in found.json["venues"]]) == (expected == 201)
    assert (
        request_booking(client, second, venue, start_time="12:45", end_time="13:45").status_code
        == expected
    )


# TC-SPL-107-06
def test_tc_spl_107_06_reassignment_removes_detail_and_destination_access(app, client):
    from app.models import EventCoordinatorAssignment

    event, venue = scenario(app)
    request_booking(client, event, venue)
    assert "Coastal Forum" in overview(client).get_data(as_text=True)
    with Session(app.extensions["engine"]) as session:
        session.get(
            EventCoordinatorAssignment, event
        ).coordinator_account_id = legacy.OTHER_COORDINATOR
        session.commit()
    assert "Coastal Forum" not in overview(client).get_data(as_text=True)
    assert (
        client.get(
            f"/api/event-requests/{event}/venue-booking-status", headers=headers()
        ).status_code
        == 404
    )
    assert "Coastal Forum" in overview(client, "other-coordinator").get_data(as_text=True)


# TC-SPL-107-07
@pytest.mark.parametrize("token", ["venue-staff", "coordinator", "manager"])
def test_tc_spl_107_07_allowlist_and_empty_catalogue(client, token):
    result = overview(client, token)
    assert result.status_code == 200 and result.json["venues"] == []


# TC-SPL-107-08
@pytest.mark.parametrize("role", [None, "event_organiser", "attendee", "technical_support_staff"])
def test_tc_spl_107_08_other_roles_cannot_read_even_with_forged_role(app, client, role):
    from app.models import AccountRole
    from sqlalchemy import delete

    if role:
        with Session(app.extensions["engine"]) as session:
            session.execute(delete(AccountRole).where(AccountRole.account_id == legacy.ORGANISER))
            session.add(AccountRole(account_id=legacy.ORGANISER, role=role))
            session.commit()
    result = client.get(
        "/api/venues/occupancy-overview?date=2026-10-14&role=venue_staff",
        headers=headers("organiser" if role else None),
    )
    assert result.status_code == (403 if role else 401)
    assert "venues" not in result.json


# TC-SPL-107-11
def test_tc_spl_107_11_unknown_legacy_and_gate_preserved(app, client):
    event, venue = scenario(app)
    legacy.seed_booking(app, event, venue, "requested")
    rows = overview(client).json["venues"][0]["intervals"]
    assert all(r["status"] == "review_required" for r in rows)
    assert all(r["requires_review"] for r in rows)
    app.config["EXACT_VENUE_TIMING_ENABLED"] = False
    assert overview(client).status_code == 409
    old = client.get(
        f"/api/venues/{venue}/occupancy?start_date=2026-10-14&end_date=2026-10-14",
        headers=headers(),
    )
    assert old.status_code == 200 and "slots" in old.json["days"][0]


# TC-SPL-107-11
@pytest.mark.parametrize("status", ["rejected", "withdrawn", "cancelled"])
def test_tc_spl_107_11_terminal_bookings_have_no_occupancy(app, client, status):
    from app.models import VenueBooking

    event, venue = scenario(app)
    booking = request_booking(client, event, venue).json["booking"]
    with Session(app.extensions["engine"]) as session:
        session.get(VenueBooking, booking["id"]).status = status
        session.commit()
    assert all(r["status"] == "available" for r in overview(client).json["venues"][0]["intervals"])


# TC-SPL-107-10
@pytest.mark.parametrize("field,value", [("setup_minutes", None), ("operating_intervals", None)])
def test_tc_spl_107_10_missing_configuration_never_claims_availability(app, client, field, value):
    _, venue = scenario(app)
    with Session(app.extensions["engine"]) as session:
        setattr(session.get(Venue, venue), field, value)
        session.commit()
    intervals = overview(client).json["venues"][0]["intervals"]
    assert all(row["status"] == "review_required" for row in intervals)
    assert all(row["requires_review"] for row in intervals)


# TC-SPL-107-11
def test_tc_spl_107_11_explicit_legacy_claims_keep_their_original_boundaries(app, client):
    from datetime import date

    event, venue = scenario(app)
    legacy.seed_booking(
        app, event, venue, "approved", occupancy=[(date(2026, 10, 14), "AM", "event")]
    )
    # Historical AM is 07:00-12:00, recorded in docs/tasks/SPL-129.md and SPL-51.
    rows = overview(client, "other-coordinator").json["venues"][0]["intervals"]
    assert [(row["start"][11:16], row["end"][11:16], row["status"]) for row in rows] == [
        ("00:00", "07:00", "available"),
        ("07:00", "12:00", "booked"),
        ("12:00", "00:00", "available"),
    ]
    assert "Coastal Forum" not in overview(client, "other-coordinator").get_data(as_text=True)
