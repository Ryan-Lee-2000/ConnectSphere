"""QA coverage for SPL-133: tentative venue holds expire at a visible deadline.

Each test carries the QA-SPL-133 case it proves (BB = black-box, WB = white-box). Expected values
come from the Jira acceptance criteria as amended on 26 Oct 2026 (7-day default capped at the
booking's start, 14-day maximum, one outcome per hold) and Week 7 change 4, not from the code.
The hold clock is frozen through ``venue_hold_expiry._now``. Races and the migration run on
PostgreSQL in test_qa_spl133_postgres.py. Fixtures are shared with SPL-77's suite.
"""

from datetime import date, datetime, time, timedelta

import pytest
import test_venue_booking_requests as base
from app import venue_hold_expiry
from app.event_requests import SINGAPORE
from app.models import (
    EventRequest,
    Notification,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingStatusHistory,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_venue_booking_requests import (
    COORDINATOR,
    VENUE_STAFF,
    add_venue,
    count,
    headers,
    make_event,
    request_booking,
)

app = base.app
client = base.client

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=SINGAPORE)
FAR_DAY = date(2026, 11, 20)  # starts 13:00, so the 7-day default applies
NEAR_DAY = date(2026, 11, 3)  # starts 09:00, before the 7-day default
DEFAULT = NOW + timedelta(days=7)


# Helpers ------------------------------------------------------------------------------------


@pytest.fixture
def clock(monkeypatch):
    """A movable hold clock: ``clock.at(moment)`` sets what the expiry rules see as now."""

    class Clock:
        now = NOW

        def at(self, moment):
            self.now = moment

    frozen = Clock()
    monkeypatch.setattr(venue_hold_expiry, "_now", lambda: frozen.now)
    return frozen


def iso(moment):
    return moment.astimezone(SINGAPORE).isoformat()


def hold(app, client, *, day=FAR_DAY, start=time(13), end=time(18), name="Coastal Forum"):
    event_id = make_event(app, name, day=day, start=start, end=end)
    venue_id = add_venue(app, f"{name} Hall")
    response = request_booking(client, event_id, venue_id)
    assert response.status_code == 201, response.json
    return event_id, venue_id, response.json["booking"]


def booking_row(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        booking = session.get(VenueBooking, booking_id)
        session.expunge(booking)
        return booking


def history(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        return [
            (entry.action, entry.previous_status, entry.resulting_status, entry.actor_account_id)
            for entry in session.scalars(
                select(VenueBookingStatusHistory)
                .where(VenueBookingStatusHistory.booking_id == booking_id)
                .order_by(VenueBookingStatusHistory.id)
            )
        ]


def notices(app, fragment=""):
    with Session(app.extensions["engine"]) as session:
        return [
            (notice.recipient_account_id, notice.message)
            for notice in session.scalars(select(Notification).order_by(Notification.id))
            if fragment in notice.message
        ]


def change(client, booking_id, value, token="venue-staff"):
    return client.put(
        f"/api/venue-bookings/{booking_id}/hold-deadline",
        json={"expires_at": value} if not isinstance(value, dict) else value,
        headers=headers(token),
    )


def approve(client, booking_id):
    return client.post(
        f"/api/venue-bookings/{booking_id}/approve", json={}, headers=headers("venue-staff")
    )


def touch(client):
    """Any authenticated request: due holds are processed before it runs (AC5)."""

    return client.get("/api/venue-bookings/pending", headers=headers("venue-staff"))


# AC1: the system sets the deadline ----------------------------------------------------------


# QA-SPL-133-001 | AC1 | BB
def test_qa_spl_133_001_a_new_hold_expires_seven_days_after_the_request(app, client, clock):
    _, _, booking = hold(app, client)

    assert booking["status"] == "requested"
    assert booking["expires_at"] == iso(DEFAULT)
    assert booking_row(app, booking["id"]).expires_at.replace(tzinfo=None) == DEFAULT.replace(
        tzinfo=None
    )


# QA-SPL-133-002 | AC1 | BB
def test_qa_spl_133_002_a_booking_starting_sooner_expires_at_its_start(app, client, clock):
    _, _, booking = hold(app, client, day=NEAR_DAY, start=time(9), end=time(11))

    assert booking["expires_at"] == iso(datetime(2026, 11, 3, 9, 0, tzinfo=SINGAPORE))


# QA-SPL-133-003 | AC1 | BB
@pytest.mark.parametrize(
    ("start_offset", "expected_offset"),
    [
        (timedelta(days=7, minutes=-15), timedelta(days=7, minutes=-15)),
        (timedelta(days=7), timedelta(days=7)),
        (timedelta(days=7, minutes=15), timedelta(days=7)),
    ],
    ids=["start-just-before-7-days", "start-exactly-7-days", "start-just-after-7-days"],
)
def test_qa_spl_133_003_the_earlier_of_seven_days_and_the_start_wins(
    app, client, clock, start_offset, expected_offset
):
    start = NOW + start_offset
    _, _, booking = hold(app, client, day=start.date(), start=start.time(), end=time(23, 45))

    assert booking["expires_at"] == iso(NOW + expected_offset)


# QA-SPL-133-004 | AC1 | BB security
def test_qa_spl_133_004_the_coordinator_cannot_send_a_deadline(app, client, clock):
    event_id = make_event(app, day=FAR_DAY)
    venue_id = add_venue(app)

    response = request_booking(client, event_id, venue_id, expires_at=iso(NOW + timedelta(days=13)))

    assert response.status_code == 400
    assert count(app, VenueBooking) == 0


# QA-SPL-133-005 | AC1 | WB
def test_qa_spl_133_005_a_start_already_passed_does_not_cap_the_deadline():
    past_start = NOW - timedelta(days=1)

    assert venue_hold_expiry.default_deadline(past_start, NOW) == DEFAULT
    assert venue_hold_expiry.default_deadline(None, NOW) == DEFAULT


# QA-SPL-133-006 | AC1 | WB
def test_qa_spl_133_006_an_exact_booking_uses_its_own_start():
    start = datetime(2026, 11, 2, 14, 0, tzinfo=SINGAPORE)
    booking = VenueBooking(
        exact_timing={"event": {"start": start.isoformat(), "end": "x"}}, booking_date=None
    )
    unreadable = VenueBooking(exact_timing={"event": {}}, booking_date=None)
    event = EventRequest(start_time=time(9))

    assert venue_hold_expiry.booking_event_start(booking, event) == start
    assert venue_hold_expiry.booking_event_start(unreadable, event) is None
    assert venue_hold_expiry.default_deadline(start, NOW) == start


# AC2: both sides can see the deadline -------------------------------------------------------


# QA-SPL-133-010 | AC2 | BB
def test_qa_spl_133_010_coordinator_and_venue_staff_see_the_deadline(app, client, clock):
    event_id, _, booking = hold(app, client)

    status = client.get(f"/api/event-requests/{event_id}/venue-booking-status", headers=headers())
    review = client.get(f"/api/venue-bookings/{booking['id']}", headers=headers("venue-staff"))
    queue = touch(client)

    assert status.json["bookings"][0]["booking"]["expires_at"] == iso(DEFAULT)
    assert review.json["booking"]["expires_at"] == iso(DEFAULT)
    assert queue.json["requests"][0]["expires_at"] == iso(DEFAULT)


# AC3: Venue Staff move the deadline within the limits ---------------------------------------


# QA-SPL-133-020 | AC3 | BB
@pytest.mark.parametrize(
    "new_deadline",
    [NOW + timedelta(days=2), NOW + timedelta(days=12)],
    ids=["earlier", "later"],
)
def test_qa_spl_133_020_venue_staff_move_the_deadline_with_history_and_notice(
    app, client, clock, new_deadline
):
    _, _, booking = hold(app, client)

    response = change(client, booking["id"], iso(new_deadline))

    assert response.status_code == 200, response.json
    assert response.json["booking"]["expires_at"] == iso(new_deadline)
    assert history(app, booking["id"])[-1] == (
        "change_deadline",
        "requested",
        "requested",
        VENUE_STAFF,
    )
    with Session(app.extensions["engine"]) as session:
        note = session.scalars(
            select(VenueBookingStatusHistory.note).order_by(VenueBookingStatusHistory.id.desc())
        ).first()
    assert note == (
        f"Hold deadline moved from {venue_hold_expiry.format_deadline(DEFAULT)} to "
        f"{venue_hold_expiry.format_deadline(new_deadline)}."
    )
    changed = notices(app, "now expires at")
    assert changed == [
        (
            COORDINATOR,
            "The hold on Coastal Forum Hall for Coastal Forum now expires at "
            f"{venue_hold_expiry.format_deadline(new_deadline)}.",
        )
    ]


# QA-SPL-133-021 | AC3 | BB boundary
@pytest.mark.parametrize(
    ("offset", "status"),
    [
        (timedelta(0), 400),
        (timedelta(minutes=1), 200),
        (timedelta(days=14), 200),
        (timedelta(days=14, minutes=1), 400),
    ],
    ids=["now", "one-minute-ahead", "exactly-14-days", "14-days-and-a-minute"],
)
def test_qa_spl_133_021_the_deadline_must_be_future_and_within_14_days(
    app, client, clock, offset, status
):
    _, _, booking = hold(app, client, day=date(2026, 12, 1))

    response = change(client, booking["id"], iso(NOW + offset))

    assert response.status_code == status, response.json
    expected = NOW + offset if status == 200 else DEFAULT
    assert response.status_code != 200 or response.json["booking"]["expires_at"] == iso(expected)
    stored = booking_row(app, booking["id"]).expires_at.replace(tzinfo=None)
    assert stored == expected.replace(tzinfo=None)


# QA-SPL-133-022 | AC3 | BB boundary
@pytest.mark.parametrize(
    ("deadline", "status"),
    [
        (datetime(2026, 11, 3, 9, 0, tzinfo=SINGAPORE), 200),
        (datetime(2026, 11, 3, 9, 1, tzinfo=SINGAPORE), 400),
    ],
    ids=["at-the-start", "after-the-start"],
)
def test_qa_spl_133_022_the_deadline_cannot_be_after_the_booking_starts(
    app, client, clock, deadline, status
):
    _, _, booking = hold(app, client, day=NEAR_DAY, start=time(9), end=time(11))
    change(client, booking["id"], iso(NOW + timedelta(hours=2)))

    response = change(client, booking["id"], iso(deadline))

    assert response.status_code == status, response.json
    if status == 400:
        assert response.json["error"] == (
            "The deadline cannot be after the booking starts (3 Nov 2026, 09:00 SGT)."
        )


# QA-SPL-133-023 | AC3 | BB
@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, "Send only the new deadline."),
        ({"expires_at": "2026-11-05T12:00", "status": "approved"}, "Send only the new deadline."),
        ({"expires_at": 1793000000}, "The deadline must be a date and time."),
        ({"expires_at": "next Friday"}, "The deadline must be a date and time."),
    ],
    ids=["empty", "extra-field", "number", "not-a-date"],
)
def test_qa_spl_133_023_the_body_carries_only_a_valid_deadline(app, client, clock, body, message):
    _, _, booking = hold(app, client)

    response = change(client, booking["id"], body)

    assert response.status_code == 400
    assert response.json["error"] == message
    assert len(history(app, booking["id"])) == 1


# QA-SPL-133-023 | AC3 | BB
def test_qa_spl_133_023_a_time_without_offset_is_singapore_time(app, client, clock):
    _, _, booking = hold(app, client)

    naive = change(client, booking["id"], "2026-11-05T12:00")
    offset = change(client, booking["id"], "2026-11-06T04:00:00+00:00")

    assert naive.json["booking"]["expires_at"] == "2026-11-05T12:00:00+08:00"
    assert offset.json["booking"]["expires_at"] == "2026-11-06T12:00:00+08:00"


# QA-SPL-133-024 | AC3 | BB security
@pytest.mark.parametrize("token", ["coordinator", "organiser", "manager"])
def test_qa_spl_133_024_only_venue_staff_change_the_deadline(app, client, clock, token):
    _, _, booking = hold(app, client)

    assert change(client, booking["id"], iso(NOW + timedelta(days=2)), token).status_code == 403
    assert len(history(app, booking["id"])) == 1


# QA-SPL-133-024 | AC3 | BB security
def test_qa_spl_133_024_no_session_and_unknown_bookings_are_refused(app, client, clock):
    _, _, booking = hold(app, client)

    anonymous = client.put(
        f"/api/venue-bookings/{booking['id']}/hold-deadline", json={"expires_at": "x"}
    )
    missing = change(client, 98765, iso(NOW + timedelta(days=2)))
    huge = change(client, 2**31, iso(NOW + timedelta(days=2)))

    assert anonymous.status_code == 401
    assert missing.status_code == 404
    assert huge.status_code == 404


# QA-SPL-133-025 | AC3 | BB
def test_qa_spl_133_025_only_a_requested_hold_can_change_and_no_op_is_silent(app, client, clock):
    _, _, approved = hold(app, client, name="Approved Gala")
    assert approve(client, approved["id"]).status_code == 200
    _, _, held = hold(app, client, name="Held Forum")
    before = len(notices(app))

    refused = change(client, approved["id"], iso(NOW + timedelta(days=2)))
    unchanged = change(client, held["id"], iso(DEFAULT))

    assert refused.status_code == 409
    assert refused.json["error"] == (
        "Only a Requested hold with a deadline can have its deadline changed."
    )
    assert unchanged.status_code == 200
    assert len(history(app, held["id"])) == 1
    assert len(notices(app)) == before


# QA-SPL-133-026 | AC3/AC5 | BB
def test_qa_spl_133_026_a_due_hold_cannot_have_its_deadline_moved(app, client, monkeypatch, clock):
    _, _, booking = hold(app, client)
    # Skip the request hook, so the deadline route itself meets the due hold.
    monkeypatch.setitem(app.extensions, "process_due_holds", lambda: None)
    clock.at(DEFAULT)

    response = change(client, booking["id"], iso(DEFAULT + timedelta(days=1)))

    assert response.status_code == 409
    assert response.json["error"] == (
        "This hold has expired, so its deadline can no longer be changed."
    )
    assert booking_row(app, booking["id"]).status == "expired"


# AC4: approval only strictly before the deadline --------------------------------------------


# QA-SPL-133-030 | AC4/AC10 | BB boundary
def test_qa_spl_133_030_approval_one_second_before_the_deadline_wins_for_good(app, client, clock):
    _, _, booking = hold(app, client)
    clock.at(DEFAULT - timedelta(seconds=1))

    approved = approve(client, booking["id"])
    clock.at(DEFAULT + timedelta(days=3))
    touch(client)

    assert approved.status_code == 200
    assert booking_row(app, booking["id"]).status == "approved"
    assert notices(app, "expired") == []
    assert "expire" not in [entry[0] for entry in history(app, booking["id"])]


# QA-SPL-133-031 | AC4/AC9 | BB boundary
def test_qa_spl_133_031_approval_at_the_deadline_is_refused_as_expired(app, client, clock):
    _, _, booking = hold(app, client)
    clock.at(DEFAULT)

    response = approve(client, booking["id"])

    assert response.status_code == 409
    assert response.json["error"] == (
        "This hold expired at 8 Nov 2026, 10:00 SGT, so it can no longer be approved."
    )
    assert booking_row(app, booking["id"]).status == "expired"
    assert len(notices(app, "expired at")) == 1


# QA-SPL-133-032 | AC4/AC10 | WB
def test_qa_spl_133_032_approval_expires_a_due_hold_the_hook_has_not_reached(
    app, client, monkeypatch, clock
):
    _, _, booking = hold(app, client)
    monkeypatch.setitem(app.extensions, "process_due_holds", lambda: None)
    clock.at(DEFAULT + timedelta(minutes=5))

    response = approve(client, booking["id"])

    assert response.status_code == 409
    assert "expired at 8 Nov 2026, 10:00 SGT" in response.json["error"]
    assert history(app, booking["id"])[-1] == ("expire", "requested", "expired", None)
    assert len(notices(app, "expired at")) == 1


# AC5: an expired hold stops blocking at once ------------------------------------------------


def claims(app, booking_id):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(
            select(VenueBookingOccupancy.slot).where(VenueBookingOccupancy.booking_id == booking_id)
        ).all()


# QA-SPL-133-040 | AC5/AC6 | BB
def test_qa_spl_133_040_the_time_is_free_for_another_event_after_expiry(app, client, clock):
    _, venue_id, booking = hold(app, client)
    rival = make_event(app, "Rival Summit", day=FAR_DAY)
    assert request_booking(client, rival, venue_id).status_code == 409
    clock.at(DEFAULT)

    response = request_booking(client, rival, venue_id)

    assert response.status_code == 201, response.json
    assert booking_row(app, booking["id"]).status == "expired"
    assert claims(app, booking["id"]) == []
    assert claims(app, response.json["booking"]["id"]) != []


# QA-SPL-133-041 | AC5 | BB
def test_qa_spl_133_041_search_calendar_and_queue_stop_showing_the_hold(app, client, clock):
    _, venue_id, booking = hold(app, client)
    rival = make_event(app, "Rival Summit", day=FAR_DAY)
    assert "Coastal Forum Hall" not in base.search(client, rival, FAR_DAY, "PM")
    clock.at(DEFAULT)

    after = base.search(client, rival, FAR_DAY, "PM")
    calendar = client.get(
        f"/api/venues/{venue_id}/occupancy?start_date={FAR_DAY}&end_date={FAR_DAY}",
        headers=headers("venue-staff"),
    )
    queue = touch(client)

    assert "Coastal Forum Hall" in after
    statuses = {entry["slot"]: entry["status"] for entry in calendar.json["days"][0]["slots"]}
    assert statuses["PM"] == "available"
    assert [item["id"] for item in queue.json["requests"]] == []
    assert booking_row(app, booking["id"]).status == "expired"


# QA-SPL-133-042 | AC5/AC10 | WB
def test_qa_spl_133_042_expiry_releases_only_its_own_claims(app, client, clock):
    _, _, early = hold(app, client, name="Early Fair")
    clock.at(NOW + timedelta(days=1))
    _, _, later = hold(app, client, name="Later Fair")
    other_claims = claims(app, later["id"])
    clock.at(DEFAULT)

    touch(client)

    assert booking_row(app, early["id"]).status == "expired"
    assert booking_row(app, later["id"]).status == "requested"
    assert claims(app, later["id"]) == other_claims != []


# AC6: an Expired hold is not an arrangement -------------------------------------------------


# QA-SPL-133-050 | AC6 | BB
def test_qa_spl_133_050_coordinator_sees_expired_and_can_request_again(app, client, clock):
    event_id, venue_id, booking = hold(app, client)
    clock.at(DEFAULT)

    confirm = client.post(f"/api/event-requests/{event_id}/confirm", headers=headers())
    status = client.get(f"/api/event-requests/{event_id}/venue-booking-status", headers=headers())
    again = request_booking(client, event_id, venue_id)

    assert confirm.status_code == 409
    assert "no_approved_venue_booking" in {item["code"] for item in confirm.json["blockers"]}
    expired = status.json["bookings"][0]
    assert expired["current_status"] == {"status": "expired", "label": "Expired"}
    assert expired["history"][-1]["actor"] == {"id": None, "name": "ConnectSphere"}
    assert expired["history"][-1]["note"] == "Hold expired at 8 Nov 2026, 10:00 SGT."
    assert again.status_code == 201
    assert again.json["booking"]["expires_at"] == iso(DEFAULT + timedelta(days=7))
    assert booking["id"] != again.json["booking"]["id"]


# AC7: Approved bookings never expire --------------------------------------------------------


# QA-SPL-133-060 | AC7 | BB
def test_qa_spl_133_060_an_approved_booking_keeps_its_time_past_any_deadline(app, client, clock):
    _, _, booking = hold(app, client)
    assert approve(client, booking["id"]).status_code == 200
    held = sorted(claims(app, booking["id"]))
    clock.at(DEFAULT + timedelta(days=30))

    touch(client)

    assert booking_row(app, booking["id"]).status == "approved"
    assert sorted(claims(app, booking["id"])) == held != []
    assert notices(app, "expired") == []


# AC8/AC9: notices -----------------------------------------------------------------------


# QA-SPL-133-070 | AC8 | BB
def test_qa_spl_133_070_the_coordinator_is_told_the_deadline_when_the_hold_is_made(
    app, client, clock
):
    hold(app, client)

    assert notices(app, "is held for") == [
        (
            COORDINATOR,
            "Coastal Forum Hall is held for Coastal Forum until 8 Nov 2026, 10:00 SGT. "
            "Venue Staff must approve it before then.",
        )
    ]


# QA-SPL-133-071 | AC9 | BB
def test_qa_spl_133_071_the_coordinator_is_told_once_when_the_hold_expires(app, client, clock):
    hold(app, client)
    clock.at(DEFAULT)

    for _ in range(3):
        touch(client)
    clock.at(DEFAULT + timedelta(days=2))
    touch(client)

    assert notices(app, "expired at") == [
        (
            COORDINATOR,
            "The hold on Coastal Forum Hall for Coastal Forum expired at 8 Nov 2026, 10:00 SGT. "
            "Request the venue again if it is still needed.",
        )
    ]


# QA-SPL-133-072 | AC8/AC9 | BB
def test_qa_spl_133_072_an_event_without_a_coordinator_notifies_nobody(app, client, clock):
    event_id, _, booking = hold(app, client)
    with Session(app.extensions["engine"]) as session:
        from app.models import EventCoordinatorAssignment

        session.delete(session.get(EventCoordinatorAssignment, event_id))
        session.commit()
    before = len(notices(app))
    clock.at(DEFAULT)

    touch(client)

    assert booking_row(app, booking["id"]).status == "expired"
    assert len(notices(app)) == before


# AC10: one outcome, processed once ----------------------------------------------------------


# QA-SPL-133-080 | AC10 | BB
def test_qa_spl_133_080_late_processing_never_frees_a_booking_made_after_expiry(app, client, clock):
    _, venue_id, first = hold(app, client)
    rival = make_event(app, "Rival Summit", day=FAR_DAY)
    clock.at(DEFAULT + timedelta(days=4))
    second = request_booking(client, rival, venue_id).json["booking"]
    held = sorted(claims(app, second["id"]))

    for _ in range(2):
        with Session(app.extensions["engine"]) as session:
            venue_hold_expiry.process_due_holds(session, DEFAULT + timedelta(days=5))
            session.commit()

    assert booking_row(app, first["id"]).status == "expired"
    assert booking_row(app, second["id"]).status == "requested"
    assert sorted(claims(app, second["id"])) == held != []
    assert len(notices(app, "expired at")) == 1


# QA-SPL-133-081 | AC10 | WB
def test_qa_spl_133_081_expire_booking_acts_only_on_a_due_requested_hold(app, client, clock):
    _, _, booking = hold(app, client)

    with Session(app.extensions["engine"]) as session:
        row = session.get(VenueBooking, booking["id"])
        assert venue_hold_expiry.expire_booking(session, row, DEFAULT - timedelta(seconds=1)) is (
            False
        )
        assert venue_hold_expiry.expire_booking(session, row, DEFAULT) is True
        assert venue_hold_expiry.expire_booking(session, row, DEFAULT) is False
        session.commit()
        legacy = VenueBooking(status="requested", expires_at=None)
        assert venue_hold_expiry.expire_booking(session, legacy, DEFAULT) is False

    assert [entry[0] for entry in history(app, booking["id"])] == ["request", "expire"]


# QA-SPL-133-082 | AC10 | BB
def test_qa_spl_133_082_withdraw_and_reject_cannot_revive_an_expired_hold(app, client, clock):
    event_id, _, booking = hold(app, client)
    clock.at(DEFAULT)

    withdraw = client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{booking['id']}/withdraw",
        headers=headers(),
    )
    reject = client.post(
        f"/api/venue-bookings/{booking['id']}/reject",
        json={"reason": "Too late"},
        headers=headers("venue-staff"),
    )

    assert withdraw.status_code == 409
    assert reject.status_code == 409
    assert booking_row(app, booking["id"]).status == "expired"
    assert [entry[0] for entry in history(app, booking["id"])] == ["request", "expire"]
