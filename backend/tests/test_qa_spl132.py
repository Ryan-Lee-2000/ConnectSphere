"""SPL-132 QA cases: replacing a venue booking after operational disruption (Week 7 change 2).

Each case carries its QA-SPL-132-NNN identifier (see the QA-SPL-132 Confluence page). The fixture
is SPL-106's: a Planning event on 15 Jun 2030 assigned to the coordinator, a "QA hall" booking for
10:00-11:00 made through the real route, and optionally an Approved sibling at "QA sibling". The
disruption clock (venue_disruption._now) is real here; cases about ended bookings move it.
PostgreSQL races are in test_qa_spl132_postgres.py.
"""

from datetime import datetime, time, timedelta

import pytest
import test_qa_spl106_requirements as venue
from app import notifications as notifications_module
from app import venue_booking_approvals as approvals_module
from app import venue_disruption
from app.models import (
    EquipmentRequirement,
    EventRequest,
    EventStatusHistory,
    Notification,
    VenueBooking,
    VenueBookingReviewFinding,
    VenueBookingStatusHistory,
)
from app.venue_timing import SGT
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

base = venue.base
base_app = venue.base_app
app = venue.app
client = venue.client
EVENT = "Coastal Forum"
HALL = "QA hall"
REASON = "Burst pipe in the plant room"
BOOKING_END = datetime.combine(venue.DAY, time(11), tzinfo=SGT)


def block(client, venue_id, start="10:00", end="11:00", token="venue-staff"):
    body = {"date": venue.DAY.isoformat(), "start_time": start, "end_time": end, "reason": REASON}
    return client.post(
        f"/api/venues/{venue_id}/operational-blocks", json=body, headers=base.headers(token)
    )


def blocked(client, venue_id, **kwargs):
    response = block(client, venue_id, **kwargs)
    assert response.status_code == 201, response.json
    return response.json


def block_id(created):
    return created["operational_block"]["id"]


def other_request(app, client, hall, start="10:00", end="11:00"):
    """Another coordinator's event asks for the hall, to show whether the time is held."""

    other = base.make_event(
        app,
        "Harbour Talks",
        day=venue.DAY,
        start=time(10),
        end=time(12),
        attendance=300,
        coordinator=base.OTHER_COORDINATOR,
    )
    return client.post(
        f"/api/event-requests/{other}/venue-bookings",
        json={
            "venue_id": hall,
            "layout": "theatre",
            "attendee_count": 150,
            "required_facilities": ["Projector"],
            "date": venue.DAY.isoformat(),
            "start_time": start,
            "end_time": end,
            "venue_revision": 1,
        },
        headers=base.headers("other-coordinator"),
    )


def remove(client, venue_id, block_id, token="venue-staff"):
    return client.delete(
        f"/api/venues/{venue_id}/operational-blocks/{block_id}", headers=base.headers(token)
    )


def replace(client, event, original, venue_id, token="coordinator", **changes):
    return (
        venue.request(client, event, venue_id, replaces_booking_id=original["id"], **changes)
        if token == "coordinator"
        else client.post(
            f"/api/event-requests/{event}/venue-bookings",
            json={
                "venue_id": venue_id,
                "layout": "theatre",
                "attendee_count": 150,
                "required_facilities": ["Projector"],
                "date": venue.DAY.isoformat(),
                "start_time": "10:00",
                "end_time": "11:00",
                "venue_revision": 1,
                "replaces_booking_id": original["id"],
            },
            headers=base.headers(token),
        )
    )


def approve(client, booking, token="venue-staff"):
    return client.post(
        f"/api/venue-bookings/{booking['id']}/approve", json={}, headers=base.headers(token)
    )


def reject(client, booking):
    return client.post(
        f"/api/venue-bookings/{booking['id']}/reject",
        json={"reason": "maintenance"},
        headers=base.headers("venue-staff"),
    )


def withdraw(client, event, booking, token="coordinator"):
    return client.post(
        f"/api/event-requests/{event}/venue-bookings/{booking['id']}/withdraw",
        headers=base.headers(token),
    )


def cancel(client, event, booking):
    return client.post(
        f"/api/event-requests/{event}/venue-bookings/{booking['id']}/cancel",
        json={"reason": "The breakout room is no longer needed."},
        headers=base.headers(),
    )


def confirm(client, event):
    return client.post(f"/api/event-requests/{event}/confirm", headers=base.headers())


def read(client, event, booking, token="coordinator"):
    return client.get(
        f"/api/event-requests/{event}/venue-bookings/{booking['id']}", headers=base.headers(token)
    )


def stored(app, booking):
    with Session(app.extensions["engine"]) as session:
        row = session.get(VenueBooking, booking["id"])
        return {
            "status": row.status,
            "requires_review": row.requires_review,
            "replaces_booking_id": row.replaces_booking_id,
        }


def event_row(app, event):
    with Session(app.extensions["engine"]) as session:
        row = session.get(EventRequest, event)
        return {
            "status": row.status,
            "proposed_date": row.proposed_date,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "registration_required": row.registration_required,
            "registration_capacity": row.registration_capacity,
            "registration_notes": row.registration_notes,
        }


def set_event(app, event, **values):
    with Session(app.extensions["engine"]) as session:
        row = session.get(EventRequest, event)
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()


def set_booking(app, booking, status):
    with Session(app.extensions["engine"]) as session:
        session.get(VenueBooking, booking["id"]).status = status
        session.commit()


def findings(app, booking):
    with Session(app.extensions["engine"]) as session:
        return [
            (row.reason_type, row.resolved_at is None)
            for row in session.scalars(
                select(VenueBookingReviewFinding).where(
                    VenueBookingReviewFinding.booking_id == booking["id"]
                )
            )
        ]


def history(app, booking):
    with Session(app.extensions["engine"]) as session:
        return [
            (row.action, row.previous_status, row.resulting_status, row.note)
            for row in session.scalars(
                select(VenueBookingStatusHistory)
                .where(VenueBookingStatusHistory.booking_id == booking["id"])
                .order_by(VenueBookingStatusHistory.id)
            )
        ]


def notices(app, account=base.COORDINATOR, like="arrangement_booking_flagged:%"):
    with Session(app.extensions["engine"]) as session:
        return [
            row.message
            for row in session.scalars(
                select(Notification)
                .where(
                    Notification.recipient_account_id == account,
                    Notification.dedupe_key.like(like),
                )
                .order_by(Notification.id)
            )
        ]


def organiser_notices(app):
    return notices(app, base.ORGANISER, like="%returned_to_planning%")


def flag_message(name=EVENT, hall=HALL):
    day = venue.DAY
    return (
        f"Venue booking for {name} at {hall} on {day:%a} {day.day} {day:%b %Y}, 10:00–11:00 SGT "
        f"needs a replacement: Venue Staff marked the venue unavailable ({REASON})."
    )


def at(monkeypatch, instant):
    monkeypatch.setattr(venue_disruption, "_now", lambda: instant)


def confirmed(app, client):
    """An event with one Approved QA hall booking, confirmed by its coordinator."""

    event, hall, [booking] = venue.scenario(app, client, approved=True)
    response = confirm(client, event)
    assert response.status_code == 200, response.json
    return event, hall, booking


def disrupted(app, client, *, approved=False, siblings=False):
    event, hall, bookings = venue.scenario(app, client, approved=approved, siblings=siblings)
    created = blocked(client, hall)
    return event, hall, bookings, created


# AC1 - a future Requested or Approved booking is flagged with the reason; ended ones are not


# QA-SPL-132-001 | AC1 | BB happy
def test_qa_spl_132_001_a_block_flags_a_future_requested_booking_with_its_reason(app, client):
    event, hall, [booking] = venue.scenario(app, client)
    created = blocked(client, hall)
    assert created["affected_booking_count"] == 1
    shown = read(client, event, booking).json["booking"]
    assert shown["requires_review"] is True
    assert shown["review_trigger_block_id"] == block_id(created)
    review = client.get(
        f"/api/venue-bookings/{booking['id']}", headers=base.headers("venue-staff")
    ).json["review"]
    assert review["trigger_block"]["reason"] == REASON
    assert findings(app, booking) == [("operational_block", True)]


# QA-SPL-132-002 | AC1 | BB happy
def test_qa_spl_132_002_an_approved_booking_is_flagged_and_stays_approved(app, client):
    event, hall, [booking] = venue.scenario(app, client, approved=True)
    assert blocked(client, hall)["affected_booking_count"] == 1
    assert stored(app, booking) == {
        "status": "approved",
        "requires_review": True,
        "replaces_booking_id": None,
    }


# QA-SPL-132-003 | AC1 | BB negative
def test_qa_spl_132_003_a_booking_that_has_already_ended_is_not_flagged(app, client, monkeypatch):
    event, hall, [booking] = venue.scenario(app, client)
    at(monkeypatch, BOOKING_END + timedelta(days=1))
    assert blocked(client, hall)["affected_booking_count"] == 0
    assert stored(app, booking)["requires_review"] is False
    assert findings(app, booking) == []
    assert notices(app) == []


@pytest.mark.parametrize(
    ("instant", "flagged"),
    [
        (BOOKING_END - timedelta(minutes=1), True),
        (BOOKING_END, False),
        (BOOKING_END + timedelta(minutes=1), False),
    ],
)
# QA-SPL-132-004 | AC1 | BB boundary
def test_qa_spl_132_004_the_booking_end_is_the_boundary(app, client, monkeypatch, instant, flagged):
    _, hall, [booking] = venue.scenario(app, client)
    at(monkeypatch, instant)
    assert blocked(client, hall)["affected_booking_count"] == int(flagged)
    assert stored(app, booking)["requires_review"] is flagged


@pytest.mark.parametrize("status", ["withdrawn", "rejected", "cancelled"])
# QA-SPL-132-005 | AC1 | BB negative
def test_qa_spl_132_005_an_inactive_booking_is_not_flagged(app, client, status):
    _, hall, [booking] = venue.scenario(app, client)
    set_booking(app, booking, status)
    assert blocked(client, hall)["affected_booking_count"] == 0
    assert stored(app, booking)["requires_review"] is False


@pytest.mark.parametrize("status", ["cancelled", "completed"])
# QA-SPL-132-006 | AC1 | WB
def test_qa_spl_132_006_an_ended_event_is_not_flagged(app, client, status):
    event, hall, [booking] = venue.scenario(app, client)
    set_event(app, event, status=status)
    assert blocked(client, hall)["affected_booking_count"] == 0
    assert notices(app) == []


@pytest.mark.parametrize(("token", "code"), [("coordinator", 403), ("organiser", 403), (None, 401)])
# QA-SPL-132-007 | AC1 | BB security
def test_qa_spl_132_007_only_venue_staff_can_mark_a_venue_unavailable(app, client, token, code):
    _, hall, [booking] = venue.scenario(app, client)
    assert block(client, hall, token=token).status_code == code
    assert stored(app, booking)["requires_review"] is False
    assert notices(app) == []


# QA-SPL-132-008 | AC1 | BB boundary
def test_qa_spl_132_008_a_block_that_only_touches_the_booking_flags_nothing(app, client):
    _, hall, [booking] = venue.scenario(app, client)
    assert blocked(client, hall, start="11:00", end="12:00")["affected_booking_count"] == 0
    assert blocked(client, hall, start="09:00", end="10:00")["affected_booking_count"] == 0
    assert stored(app, booking)["requires_review"] is False


# AC2 - one in-system notice per affected booking, naming the event, venue, time and reason


# QA-SPL-132-010 | AC2 | BB happy
def test_qa_spl_132_010_the_coordinator_is_told_the_event_venue_time_and_reason(app, client):
    disrupted(app, client)
    assert notices(app) == [flag_message()]


# QA-SPL-132-011 | AC2 | BB
def test_qa_spl_132_011_each_affected_event_coordinator_gets_one_notice(app, client):
    _, hall, _ = venue.scenario(app, client)
    other = base.make_event(
        app,
        "Harbour Talks",
        day=venue.DAY,
        start=time(10),
        end=time(12),
        attendance=300,
        coordinator=base.OTHER_COORDINATOR,
    )
    response = client.post(
        f"/api/event-requests/{other}/venue-bookings",
        json={
            "venue_id": hall,
            "layout": "theatre",
            "attendee_count": 150,
            "required_facilities": ["Projector"],
            "date": venue.DAY.isoformat(),
            "start_time": "11:00",
            "end_time": "12:00",
            "venue_revision": 1,
        },
        headers=base.headers("other-coordinator"),
    )
    assert response.status_code == 201, response.json
    assert blocked(client, hall, start="09:00", end="13:00")["affected_booking_count"] == 2
    assert len(notices(app)) == 1
    [message] = notices(app, base.OTHER_COORDINATOR)
    assert message.startswith("Venue booking for Harbour Talks at QA hall on ")
    assert "11:00–12:00 SGT" in message


# QA-SPL-132-012 | AC2 | WB
def test_qa_spl_132_012_the_notice_is_the_spl121_notice_and_is_never_sent_twice(app, client):
    event, hall, [booking], created = disrupted(app, client)
    with Session(app.extensions["engine"]) as session:
        row = session.get(VenueBooking, booking["id"])
        event_row_ = session.get(EventRequest, event)
        from app.models import VenueOperationalBlock

        # SPL-121's unique dedupe key refuses a repeat rather than storing a second notice.
        venue_disruption.notify_disruption(
            session, row, event_row_, session.get(VenueOperationalBlock, block_id(created))
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        keys = session.scalars(
            select(Notification.dedupe_key).where(
                Notification.recipient_account_id == base.COORDINATOR
            )
        ).all()
    flagged = [key for key in keys if key.startswith("arrangement_booking_flagged:")]
    assert flagged == [
        f"arrangement_booking_flagged:block-{block_id(created)}-booking-{booking['id']}"
    ]


# QA-SPL-132-013 | AC2 | BB security
def test_qa_spl_132_013_nobody_else_receives_the_disruption_notice(app, client):
    disrupted(app, client)
    for account in (base.OTHER_COORDINATOR, base.ORGANISER, base.VENUE_STAFF, base.MANAGER):
        assert notices(app, account) == [], account


# QA-SPL-132-014 | AC2 | BB
def test_qa_spl_132_014_only_the_affected_booking_is_named(app, client):
    event, hall, [booking, sibling] = venue.scenario(app, client, siblings=True)
    assert blocked(client, hall)["affected_booking_count"] == 1
    [message] = notices(app)
    assert "QA sibling" not in message and HALL in message


# QA-SPL-132-015 | AC2 | BB
def test_qa_spl_132_015_a_second_block_over_the_same_booking_is_a_new_notice(app, client):
    _, hall, _ = venue.scenario(app, client)
    blocked(client, hall)
    blocked(client, hall, start="10:30", end="11:00")
    assert len(notices(app)) == 2


# QA-SPL-132-016 | AC2 | WB
def test_qa_spl_132_016_a_notice_failure_rolls_back_the_whole_block(app, client, monkeypatch):
    _, hall, [booking] = venue.scenario(app, client)

    def broken(*args, **kwargs):
        raise RuntimeError("notice store unavailable")

    monkeypatch.setattr(notifications_module, "add_arrangement_notice", broken)
    with pytest.raises(RuntimeError):
        block(client, hall)
    assert stored(app, booking)["requires_review"] is False
    assert findings(app, booking) == []


# AC3 - the event is never cancelled or rescheduled; its other arrangements are unchanged


# QA-SPL-132-020 | AC3 | BB happy
def test_qa_spl_132_020_the_event_keeps_its_status_date_and_times(app, client):
    event, hall, _ = venue.scenario(app, client)
    before = event_row(app, event)
    blocked(client, hall)
    assert event_row(app, event) == before
    assert before["status"] == "planning"


# QA-SPL-132-021 | AC3 | BB
def test_qa_spl_132_021_the_other_venue_booking_is_unchanged(app, client):
    event, hall, [booking, sibling] = venue.scenario(app, client, approved=True, siblings=True)
    before = read(client, event, sibling).json["booking"]
    blocked(client, hall)
    after = read(client, event, sibling).json["booking"]
    assert after == {**before, "replaceable": False}
    assert after["status"] == "approved" and after["requires_review"] is False


# QA-SPL-132-022 | AC3 | WB
def test_qa_spl_132_022_equipment_requirements_are_unchanged(app, client):
    event, hall, _ = venue.scenario(app, client)
    with Session(app.extensions["engine"]) as session:
        session.add(
            EquipmentRequirement(
                event_request_id=event,
                equipment_type="Wireless microphone",
                quantity=2,
                required_start_date=venue.DAY,
                required_end_date=venue.DAY,
                status="requested",
                essentiality="essential",
            )
        )
        session.commit()

    def lines():
        with Session(app.extensions["engine"]) as session:
            return [
                (row.equipment_type, row.quantity, row.status, row.required_start_date)
                for row in session.scalars(
                    select(EquipmentRequirement).where(
                        EquipmentRequirement.event_request_id == event
                    )
                )
            ]

    before = lines()
    blocked(client, hall)
    assert lines() == before and len(before) == 1


# QA-SPL-132-023 | AC3 | WB
def test_qa_spl_132_023_registration_settings_are_unchanged(app, client):
    event, hall, _ = venue.scenario(app, client)
    set_event(
        app,
        event,
        registration_required=True,
        registration_opens_at=datetime(2030, 5, 1, 9, tzinfo=SGT),
        registration_closes_at=datetime(2030, 6, 10, 18, tzinfo=SGT),
        registration_capacity=120,
        registration_notes="Bring your staff pass.",
    )
    before = event_row(app, event)
    blocked(client, hall)
    assert event_row(app, event) == before


# QA-SPL-132-024 | AC3 | BB
def test_qa_spl_132_024_the_disrupted_booking_itself_is_not_cancelled(app, client):
    event, hall, [booking] = venue.scenario(app, client, approved=True)
    remove(client, hall, block_id(blocked(client, hall)))
    assert stored(app, booking)["status"] == "approved"
    assert history(app, booking)[-1][0] == "approve"
    # The original still holds its time, so another event cannot take it.
    assert other_request(app, client, hall).status_code == 409


# AC4 - the replacement search is seeded from the affected arrangement (API side)


# QA-SPL-132-030 | AC4 | BB happy
def test_qa_spl_132_030_the_booking_read_gives_the_seed_and_says_it_is_replaceable(app, client):
    event, hall, [booking], _ = disrupted(app, client)
    shown = read(client, event, booking).json["booking"]
    assert shown["replaceable"] is True
    assert shown["timing"]["event"]["start"].startswith(f"{venue.DAY.isoformat()}T10:00")
    assert shown["timing"]["event"]["end"].startswith(f"{venue.DAY.isoformat()}T11:00")
    assert shown["expected_attendance"] == 150
    assert shown["layout"] == "theatre"
    assert shown["required_facilities"] == ["Projector"]


# QA-SPL-132-031 | AC4 | BB negative
def test_qa_spl_132_031_an_undisrupted_booking_is_not_replaceable(app, client):
    event, _, [booking] = venue.scenario(app, client)
    assert read(client, event, booking).json["booking"]["replaceable"] is False


# QA-SPL-132-032 | AC4 | BB security
@pytest.mark.parametrize(("token", "code"), [("other-coordinator", 404), ("organiser", 403)])
def test_qa_spl_132_032_only_the_assigned_coordinator_reads_the_seed(app, client, token, code):
    event, _, [booking], _ = disrupted(app, client)
    assert read(client, event, booking, token=token).status_code == code


# AC5 - a replacement linked to the original goes through the normal checks and approval


# QA-SPL-132-040 | AC5 | BB happy
def test_qa_spl_132_040_a_replacement_is_requested_and_linked_both_ways(app, client):
    event, hall, [booking], _ = disrupted(app, client)
    annex = venue.room(app, "QA annex")
    response = replace(client, event, booking, annex)
    assert response.status_code == 201, response.json
    created = response.json["booking"]
    assert created["status"] == "requested"
    assert created["replaces"] == {
        "id": booking["id"],
        "venue": {"id": hall, "name": HALL},
        "status": "requested",
    }
    original = read(client, event, booking).json["booking"]
    assert original["replacements"] == [
        {"id": created["id"], "venue": {"id": annex, "name": "QA annex"}, "status": "requested"}
    ]
    assert original["replaceable"] is False
    assert stored(app, booking)["status"] == "requested"


# QA-SPL-132-041 | AC5 | BB negative
def test_qa_spl_132_041_an_undisrupted_booking_cannot_be_replaced(app, client):
    event, _, [booking] = venue.scenario(app, client)
    response = replace(client, event, booking, venue.room(app, "QA annex"))
    assert response.status_code == 409
    assert response.json["error"] == venue_disruption.NOT_DISRUPTED


@pytest.mark.parametrize("target", ["other_event", "missing", "too_large"])
# QA-SPL-132-042 | AC5 | BB negative
def test_qa_spl_132_042_the_original_must_belong_to_this_event(app, client, target):
    event, hall, [booking], _ = disrupted(app, client)
    other = base.make_event(app, "Other Forum", day=venue.DAY, start=time(10), end=time(12))
    original_id = {
        "other_event": booking["id"],
        "missing": 999999,
        "too_large": 2**31,
    }[target]
    host = other if target == "other_event" else event
    response = venue.request(
        client, host, venue.room(app, "QA annex"), replaces_booking_id=original_id
    )
    assert response.status_code == 404, response.json


@pytest.mark.parametrize("value", [True, "1", 0, -1, 1.5])
# QA-SPL-132-043 | AC5 | BB boundary
def test_qa_spl_132_043_a_malformed_original_id_is_refused(app, client, value):
    event, _, [booking], _ = disrupted(app, client)
    response = venue.request(client, event, venue.room(app, "QA annex"), replaces_booking_id=value)
    assert response.status_code == 400, response.json
    assert response.json["error"] == "Choose the venue booking this request replaces."


# QA-SPL-132-044 | AC5 | BB negative
def test_qa_spl_132_044_only_one_replacement_can_be_pending(app, client):
    event, _, [booking], _ = disrupted(app, client)
    assert replace(client, event, booking, venue.room(app, "QA annex")).status_code == 201
    response = replace(client, event, booking, venue.room(app, "QA loft"))
    assert response.status_code == 409
    assert response.json["error"] == venue_disruption.REPLACEMENT_PENDING


# QA-SPL-132-045 | AC5 | BB negative
def test_qa_spl_132_045_the_normal_availability_check_still_applies(app, client):
    event, hall, [booking], _ = disrupted(app, client)
    # The blocked hall itself is unavailable, so it cannot be its own replacement.
    response = replace(client, event, booking, hall)
    assert response.status_code == 409, response.json
    assert stored(app, booking)["status"] == "requested"


# QA-SPL-132-046 | AC5 | BB negative
def test_qa_spl_132_046_the_normal_suitability_check_still_applies(app, client):
    event, _, [booking], _ = disrupted(app, client)
    small = venue.room(app, "QA closet")
    venue.capacity(client, small, 20)
    response = replace(client, event, booking, small)
    assert response.status_code == 409, response.json
    assert read(client, event, booking).json["booking"]["replacements"] == []


# QA-SPL-132-047 | AC5 | BB negative
def test_qa_spl_132_047_an_inactive_original_cannot_be_replaced(app, client):
    event, _, [booking], _ = disrupted(app, client)
    assert withdraw(client, event, booking).status_code == 200
    response = replace(client, event, booking, venue.room(app, "QA annex"))
    assert response.status_code == 409
    assert response.json["error"] == venue_disruption.ONLY_ACTIVE


@pytest.mark.parametrize(("token", "code"), [("other-coordinator", 404), ("organiser", 403)])
# QA-SPL-132-048 | AC5 | BB security
def test_qa_spl_132_048_only_the_assigned_coordinator_requests_a_replacement(
    app, client, token, code
):
    event, _, [booking], _ = disrupted(app, client)
    response = replace(client, event, booking, venue.room(app, "QA annex"), token=token)
    assert response.status_code == code
    assert read(client, event, booking).json["booking"]["replacements"] == []


# QA-SPL-132-049 | AC5 | BB
def test_qa_spl_132_049_venue_staff_see_what_the_request_replaces(app, client):
    event, hall, [booking], _ = disrupted(app, client)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    review = client.get(
        f"/api/venue-bookings/{created['id']}", headers=base.headers("venue-staff")
    ).json
    assert review["booking"]["replaces"]["id"] == booking["id"]
    assert review["booking"]["replaces"]["venue"]["name"] == HALL


# AC6 - a rejected or withdrawn replacement leaves the original flagged; request again


@pytest.mark.parametrize("ending", ["reject", "withdraw"])
# QA-SPL-132-050 | AC6 | BB happy
def test_qa_spl_132_050_an_ended_replacement_leaves_the_original_flagged(app, client, ending):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    response = reject(client, created) if ending == "reject" else withdraw(client, event, created)
    assert response.status_code == 200, response.json
    assert stored(app, booking) == {
        "status": "approved",
        "requires_review": True,
        "replaces_booking_id": None,
    }
    assert read(client, event, booking).json["booking"]["replaceable"] is True


@pytest.mark.parametrize("ending", ["reject", "withdraw"])
# QA-SPL-132-051 | AC6 | BB
def test_qa_spl_132_051_the_coordinator_can_request_again(app, client, ending):
    event, _, [booking], _ = disrupted(app, client)
    first = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    ended = reject(client, first) if ending == "reject" else withdraw(client, event, first)
    assert ended.status_code == 200, ended.json
    second = replace(client, event, booking, venue.room(app, "QA loft"))
    assert second.status_code == 201, second.json
    links = read(client, event, booking).json["booking"]["replacements"]
    assert [link["status"] for link in links] == [
        "requested",
        "rejected" if ending == "reject" else "withdrawn",
    ]


# QA-SPL-132-052 | AC6 | WB
def test_qa_spl_132_052_the_database_allows_one_requested_replacement_only(app, client):
    event, hall, [booking], _ = disrupted(app, client)
    with Session(app.extensions["engine"]) as session:
        for _ in range(2):
            session.add(
                VenueBooking(
                    event_request_id=event,
                    venue_id=hall,
                    status="requested",
                    replaces_booking_id=booking["id"],
                )
            )
        with pytest.raises(IntegrityError):
            session.flush()


# QA-SPL-132-053 | AC6 | WB
def test_qa_spl_132_053_ended_replacements_do_not_count_against_the_unique_rule(app, client):
    event, hall, [booking], _ = disrupted(app, client)
    with Session(app.extensions["engine"]) as session:
        for status in ("rejected", "withdrawn", "requested"):
            session.add(
                VenueBooking(
                    event_request_id=event,
                    venue_id=hall,
                    status=status,
                    replaces_booking_id=booking["id"],
                )
            )
        session.flush()


# QA-SPL-132-054 | AC6 | BB
def test_qa_spl_132_054_a_rejected_replacement_keeps_its_link_and_releases_nothing(app, client):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    reject(client, created)
    assert stored(app, created)["replaces_booking_id"] == booking["id"]
    assert [row[0] for row in history(app, booking)] == ["request", "approve"]


# AC7 - approval releases the original in the same transaction, once; links and histories kept


# QA-SPL-132-060 | AC7 | BB happy
def test_qa_spl_132_060_approving_cancels_an_approved_original(app, client):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    response = approve(client, created)
    assert response.status_code == 200, response.json
    assert stored(app, booking)["status"] == "cancelled"
    assert stored(app, created)["status"] == "approved"
    assert history(app, booking)[-1] == (
        "replaced",
        "approved",
        "cancelled",
        f"Replaced by the QA annex booking (#{created['id']}).",
    )


# QA-SPL-132-061 | AC7 | BB
def test_qa_spl_132_061_approving_withdraws_a_requested_original(app, client):
    event, _, [booking], _ = disrupted(app, client)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    assert approve(client, created).status_code == 200
    assert stored(app, booking)["status"] == "withdrawn"
    assert history(app, booking)[-1][:3] == ("replaced", "requested", "withdrawn")


# QA-SPL-132-062 | AC7 | BB negative
def test_qa_spl_132_062_repeating_the_approval_releases_nothing_further(app, client):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    assert approve(client, created).status_code == 200
    before = history(app, booking)
    assert approve(client, created).status_code == 409
    assert history(app, booking) == before
    assert [row[0] for row in before].count("replaced") == 1


# QA-SPL-132-063 | AC7 | WB
def test_qa_spl_132_063_a_failure_after_the_release_rolls_back_both(app, client, monkeypatch):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]

    def broken(*args, **kwargs):
        raise RuntimeError("attendee notice store unavailable")

    monkeypatch.setattr(approvals_module, "add_venue_change_notices", broken)
    with pytest.raises(RuntimeError):
        approve(client, created)
    assert stored(app, booking)["status"] == "approved"
    assert stored(app, created)["status"] == "requested"


# QA-SPL-132-064 | AC7 | BB
def test_qa_spl_132_064_both_links_and_histories_are_kept_after_release(app, client):
    event, hall, [booking], _ = disrupted(app, client, approved=True)
    annex = venue.room(app, "QA annex")
    created = replace(client, event, booking, annex).json["booking"]
    approve(client, created)
    original = read(client, event, booking).json["booking"]
    replacement = read(client, event, created).json["booking"]
    assert original["replacements"] == [
        {"id": created["id"], "venue": {"id": annex, "name": "QA annex"}, "status": "approved"}
    ]
    assert replacement["replaces"] == {
        "id": booking["id"],
        "venue": {"id": hall, "name": HALL},
        "status": "cancelled",
    }
    assert [row[0] for row in history(app, created)] == ["request", "approve"]
    assert [row[0] for row in history(app, booking)] == ["request", "approve", "replaced"]


# QA-SPL-132-065 | AC7 | WB
def test_qa_spl_132_065_an_original_released_elsewhere_is_left_alone(app, client):
    event, _, [booking], _ = disrupted(app, client)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    set_booking(app, booking, "withdrawn")
    with Session(app.extensions["engine"]) as session:
        released = venue_disruption.release_replaced_original(
            session,
            session.get(VenueBooking, created["id"]),
            actor_id=base.VENUE_STAFF,
            now=datetime.now(SGT),
        )
        assert released is None
        no_link = VenueBooking(event_request_id=event, venue_id=1, status="requested")
        assert (
            venue_disruption.release_replaced_original(
                session, no_link, actor_id=base.VENUE_STAFF, now=datetime.now(SGT)
            )
            is None
        )
    assert "replaced" not in [row[0] for row in history(app, booking)]


# QA-SPL-132-066 | AC7 | BB
def test_qa_spl_132_066_the_approval_notice_says_the_original_was_released(app, client):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    approve(client, created)
    [message] = notices(app, like="arrangement_booking_approved:%")[-1:]
    assert message == (
        f"Venue booking for {EVENT} at QA annex was approved. "
        f"It replaces the {HALL} booking, which has been released."
    )


# QA-SPL-132-067 | AC7 | BB
def test_qa_spl_132_067_the_released_time_is_free_for_other_events(app, client):
    event, hall, [booking], created_block = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    approve(client, created)
    remove(client, hall, block_id(created_block))
    response = other_request(app, client, hall)
    assert response.status_code == 201, response.json


# AC8 - removing the unavailability clears the flag; no replacement is required


# QA-SPL-132-070 | AC8 | BB happy
def test_qa_spl_132_070_removing_the_block_clears_the_flag(app, client):
    event, hall, [booking], created = disrupted(app, client)
    assert remove(client, hall, block_id(created)).status_code == 200
    shown = read(client, event, booking).json["booking"]
    assert shown["requires_review"] is False
    assert shown["replaceable"] is False
    assert findings(app, booking) == [("operational_block", False)]


# QA-SPL-132-071 | AC8 | BB
def test_qa_spl_132_071_after_removal_no_replacement_is_needed_to_confirm(app, client):
    event, hall, [booking], created = disrupted(app, client, approved=True)
    assert confirm(client, event).status_code == 409
    remove(client, hall, block_id(created))
    response = confirm(client, event)
    assert response.status_code == 200, response.json


# QA-SPL-132-072 | AC8 | BB negative
def test_qa_spl_132_072_after_removal_a_replacement_is_refused(app, client):
    event, hall, [booking], created = disrupted(app, client)
    remove(client, hall, block_id(created))
    response = replace(client, event, booking, venue.room(app, "QA annex"))
    assert response.status_code == 409
    assert response.json["error"] == venue_disruption.NOT_DISRUPTED


# QA-SPL-132-073 | AC8 | BB
def test_qa_spl_132_073_removing_one_of_two_blocks_keeps_the_flag(app, client):
    event, hall, [booking], first = disrupted(app, client)
    blocked(client, hall, start="10:30", end="11:00")
    remove(client, hall, block_id(first))
    assert read(client, event, booking).json["booking"]["replaceable"] is True
    assert stored(app, booking)["requires_review"] is True


# QA-SPL-132-074 | AC8 | BB security
def test_qa_spl_132_074_only_venue_staff_remove_the_block(app, client):
    event, hall, [booking], created = disrupted(app, client)
    assert remove(client, hall, block_id(created), token="coordinator").status_code == 403
    assert stored(app, booking)["requires_review"] is True


# AC9 - the coordinator may withdraw the affected booking without replacement


# QA-SPL-132-080 | AC9 | BB happy
def test_qa_spl_132_080_a_requested_disrupted_booking_can_be_withdrawn(app, client):
    event, _, [booking, sibling], _ = disrupted(app, client, siblings=True)
    response = withdraw(client, event, booking)
    assert response.status_code == 200, response.json
    assert stored(app, booking)["status"] == "withdrawn"
    assert stored(app, sibling)["status"] == "requested"


# QA-SPL-132-081 | AC9 | BB happy
def test_qa_spl_132_081_an_approved_disrupted_booking_can_be_cancelled(app, client):
    event, _, [booking, sibling], _ = disrupted(app, client, approved=True, siblings=True)
    response = cancel(client, event, booking)
    assert response.status_code == 200, response.json
    assert stored(app, booking)["status"] == "cancelled"
    assert stored(app, sibling)["status"] == "approved"


# QA-SPL-132-082 | AC9 | BB
def test_qa_spl_132_082_withdrawing_the_disrupted_booking_lets_the_event_confirm(app, client):
    event, _, [booking, sibling], _ = disrupted(app, client, approved=True, siblings=True)
    assert confirm(client, event).status_code == 409
    cancel(client, event, booking)
    response = confirm(client, event)
    assert response.status_code == 200, response.json


# QA-SPL-132-083 | AC9 | BB security
def test_qa_spl_132_083_another_coordinator_cannot_withdraw_it(app, client):
    event, _, [booking], _ = disrupted(app, client)
    assert withdraw(client, event, booking, token="other-coordinator").status_code == 404
    assert stored(app, booking)["status"] == "requested"


# QA-SPL-132-084 | AC9 | BB
def test_qa_spl_132_084_a_withdrawn_original_releases_its_pending_link(app, client):
    event, _, [booking], _ = disrupted(app, client)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    withdraw(client, event, booking)
    # The pending replacement stays a normal request; approving it releases nothing further.
    assert approve(client, created).status_code == 200
    assert [row[0] for row in history(app, booking)] == ["request", "withdraw"]


# AC10 - a Confirmed event returns to Planning through SPL-109; the organiser is informed


# QA-SPL-132-090 | AC10 | BB happy
def test_qa_spl_132_090_a_confirmed_event_returns_to_planning(app, client):
    event, hall, _ = confirmed(app, client)
    blocked(client, hall)
    assert event_row(app, event)["status"] == "planning"
    with Session(app.extensions["engine"]) as session:
        row = session.scalars(
            select(EventStatusHistory)
            .where(EventStatusHistory.event_request_id == event)
            .order_by(EventStatusHistory.id.desc())
        ).first()
        assert (row.action, row.previous_status, row.resulting_status) == (
            "significant_change",
            "confirmed",
            "planning",
        )
        assert row.actor_account_id == base.VENUE_STAFF
        assert session.get(EventRequest, event).confirmed_at is None


# QA-SPL-132-091 | AC10 | BB happy
def test_qa_spl_132_091_the_organiser_is_informed(app, client):
    event, hall, _ = confirmed(app, client)
    blocked(client, hall)
    assert organiser_notices(app) == [
        f"{EVENT} has returned to Planning because a booked venue became unavailable. "
        "It must be confirmed again once the venue arrangement is resolved."
    ]


# QA-SPL-132-092 | AC10 | BB
def test_qa_spl_132_092_a_preparing_event_also_returns_to_planning(app, client):
    event, hall, _ = confirmed(app, client)
    set_event(app, event, status="preparing")
    blocked(client, hall)
    assert event_row(app, event)["status"] == "planning"
    assert len(organiser_notices(app)) == 1


# QA-SPL-132-093 | AC10 | BB negative
def test_qa_spl_132_093_a_planning_event_is_not_transitioned(app, client):
    event, hall, _ = venue.scenario(app, client, approved=True)
    blocked(client, hall)
    assert event_row(app, event)["status"] == "planning"
    assert organiser_notices(app) == []


# QA-SPL-132-094 | AC10 | BB negative
def test_qa_spl_132_094_an_ended_booking_does_not_unconfirm_the_event(app, client, monkeypatch):
    event, hall, _ = confirmed(app, client)
    at(monkeypatch, BOOKING_END)
    blocked(client, hall)
    assert event_row(app, event)["status"] == "confirmed"
    assert organiser_notices(app) == []


# QA-SPL-132-095 | AC10 | BB
def test_qa_spl_132_095_after_returning_the_replacement_can_be_requested(app, client):
    event, hall, booking = confirmed(app, client)
    blocked(client, hall)
    response = replace(client, event, booking, venue.room(app, "QA annex"))
    assert response.status_code == 201, response.json


# QA-SPL-132-096 | AC10 | BB
def test_qa_spl_132_096_a_block_that_misses_the_booking_keeps_the_event_confirmed(app, client):
    event, hall, _ = confirmed(app, client)
    blocked(client, hall, start="14:00", end="15:00")
    assert event_row(app, event)["status"] == "confirmed"


# AC11 - an unresolved disruption blocks confirmation; never reconfirmed automatically


# QA-SPL-132-100 | AC11 | BB happy
def test_qa_spl_132_100_an_unresolved_disruption_blocks_confirmation(app, client):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    response = confirm(client, event)
    assert response.status_code == 409
    assert {(blocker["code"], blocker["booking_id"]) for blocker in response.json["blockers"]} == {
        ("venue_booking_review_required", booking["id"])
    }


# QA-SPL-132-101 | AC11 | BB
def test_qa_spl_132_101_a_pending_replacement_still_blocks_confirmation(app, client):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    codes = {blocker["code"] for blocker in confirm(client, event).json["blockers"]}
    assert codes == {"venue_booking_review_required", "venue_booking_pending"}
    assert created["status"] == "requested"


# QA-SPL-132-102 | AC11 | BB happy
def test_qa_spl_132_102_an_approved_replacement_lets_the_coordinator_confirm(app, client):
    event, _, [booking], _ = disrupted(app, client, approved=True)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    approve(client, created)
    assert event_row(app, event)["status"] == "planning"
    response = confirm(client, event)
    assert response.status_code == 200, response.json


# QA-SPL-132-103 | AC11 | BB negative
def test_qa_spl_132_103_removing_the_block_never_reconfirms_the_event(app, client):
    event, hall, _ = confirmed(app, client)
    created = blocked(client, hall)
    remove(client, hall, block_id(created))
    assert event_row(app, event)["status"] == "planning"
    assert [message for message in notices(app, base.ORGANISER, like="%confirmed%")] == [
        f"{EVENT} has been confirmed."
    ]


# QA-SPL-132-104 | AC11 | BB negative
def test_qa_spl_132_104_approving_the_replacement_never_reconfirms_the_event(app, client):
    event, hall, booking = confirmed(app, client)
    blocked(client, hall)
    created = replace(client, event, booking, venue.room(app, "QA annex")).json["booking"]
    approve(client, created)
    assert event_row(app, event)["status"] == "planning"


# QA-SPL-132-105 | AC11 | BB
def test_qa_spl_132_105_a_disrupted_sibling_still_blocks_confirmation(app, client):
    event, _, [booking, sibling] = venue.scenario(app, client, approved=True, siblings=True)
    with Session(app.extensions["engine"]) as session:
        sibling_venue = session.get(VenueBooking, sibling["id"]).venue_id
    blocked(client, sibling_venue, start="11:00", end="12:00")
    blockers = confirm(client, event).json["blockers"]
    assert [blocker["booking_id"] for blocker in blockers] == [sibling["id"]]


# Cases added after the coverage measurement on 29 Oct 2026 (QA-SPL-132 "Cases added later").


@pytest.mark.parametrize(
    ("day", "start", "end", "expected"),
    [
        (venue.DAY, time(9), time(12), " on Sat 15 Jun 2030, 09:00–12:00 SGT"),
        (venue.DAY, None, None, " on Sat 15 Jun 2030"),
        (None, time(9), time(12), ""),
    ],
)
# QA-SPL-132-160 | AC2 | WB
def test_qa_spl_132_160_a_slot_booking_notice_uses_the_event_times(day, start, end, expected):
    from types import SimpleNamespace

    booking = SimpleNamespace(exact_timing=None, booking_date=day)
    event = SimpleNamespace(start_time=start, end_time=end)
    assert notifications_module.booking_time(booking, event) == expected


# QA-SPL-132-161 | AC5 | BB negative
def test_qa_spl_132_161_an_unknown_field_beside_the_link_is_refused(app, client):
    event, _, [booking], _ = disrupted(app, client)
    response = venue.request(
        client, event, venue.room(app, "QA annex"), replaces_booking_id=booking["id"], notes="x"
    )
    assert response.status_code == 400
    assert response.json["error"].startswith("Send venue, layout, date")
