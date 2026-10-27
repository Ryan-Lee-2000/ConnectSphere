"""QA coverage for SPL-105: the assigned coordinator marks an event completed after it has ended.

Each test carries the QA-SPL-105 case it proves (BB = black-box, WB = white-box). Expected values
come from the Jira acceptance criteria (AC1/AC2 as amended on 26 Oct 2026) and the customer
answers (Q71, Q20/Q77, Q125, Q136, Week 7 change 6), not from the implementation. The clock is
frozen through ``event_completion._now``. Races and the migration run on PostgreSQL in
test_qa_spl105_postgres.py. Fixtures are shared with SPL-85's suite.
"""

from datetime import datetime, timedelta

import pytest
import test_event_confirmation as base
from app import event_completion
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EquipmentRequirement,
    EventChangeRequest,
    EventCoordinatorAssignment,
    EventRegistration,
    EventRequest,
    EventStatusHistory,
    Notification,
    Organisation,
    Role,
    VenueBooking,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_event_confirmation import (
    COORDINATOR,
    EVENT_DATE,
    IDENTITIES,
    OTHER_COORDINATOR,
    add_booking,
    add_event,
    headers,
)

app = base.app
client = base.client

# The shared fixture event runs 14:00-17:00 SGT on EVENT_DATE (20 Nov 2026).
EVENT_END = datetime(EVENT_DATE.year, EVENT_DATE.month, EVENT_DATE.day, 17, 0, tzinfo=SINGAPORE)
COLLEAGUE = "00000000-0000-0000-0000-000000010501"
OUTSIDER = "00000000-0000-0000-0000-000000010502"
ATTENDEE = "00000000-0000-0000-0000-000000010503"
NOTE = "142 attended. The PA failed for ten minutes during the second session."
NOT_PREPARING = (
    "draft",
    "submitted",
    "under_review",
    "returned_for_clarification",
    "approved",
    "planning",
    "confirmed",
    "postponed",
    "cancelled",
    "rejected",
    "withdrawn",
    "completed",
)


@pytest.fixture(autouse=True)
def extra_people(app, monkeypatch):
    """A same-client organiser, an organiser of another client and an attendee (AC5/AC6)."""

    with Session(app.extensions["engine"]) as session:
        session.add(Organisation(id=98, name="Other Client"))
        for account_id, name, role, organisation in (
            (COLLEAGUE, "Cora Colleague", Role.EVENT_ORGANISER, 99),
            (OUTSIDER, "Otto Outsider", Role.EVENT_ORGANISER, 98),
            (ATTENDEE, "Ari Attendee", Role.ATTENDEE, None),
        ):
            session.add(
                Account(
                    id=account_id, display_name=name, is_active=True, organisation_id=organisation
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
    monkeypatch.setitem(IDENTITIES, "colleague", COLLEAGUE)
    monkeypatch.setitem(IDENTITIES, "outsider", OUTSIDER)
    monkeypatch.setitem(IDENTITIES, "attendee", ATTENDEE)


# Helpers ------------------------------------------------------------------------------------


def at(moment, monkeypatch):
    monkeypatch.setattr(event_completion, "_now", lambda: moment)


def complete(client, event_id, identity="coordinator", body=None):
    return client.post(
        f"/api/event-requests/{event_id}/complete",
        json={} if body is None else body,
        headers=headers(identity),
    )


def exact_timing(start_hour, end_hour, *, setup=0, turnaround=0):
    def iso(hour, minutes=0):
        moment = datetime(EVENT_DATE.year, EVENT_DATE.month, EVENT_DATE.day, tzinfo=SINGAPORE)
        return (moment + timedelta(hours=hour, minutes=minutes)).isoformat()

    return {
        "event": {"start": iso(start_hour), "end": iso(end_hour)},
        "occupied": {"start": iso(start_hour, -setup), "end": iso(end_hour, turnaround)},
    }


def row(app, event_id):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        return {
            "status": event.status,
            "completed_by": event.completed_by_account_id,
            "completed_at": event.completed_at,
            "note": event.completion_note,
            "history": [
                (item.action, item.previous_status, item.resulting_status, item.actor_account_id)
                for item in session.scalars(
                    select(EventStatusHistory)
                    .where(EventStatusHistory.event_request_id == event_id)
                    .order_by(EventStatusHistory.id)
                )
            ],
        }


def count(app, model):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(model))


def completed_event(app, client, monkeypatch, note=None):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)
    response = complete(client, event_id, body={"note": note})
    assert response.status_code == 200, response.json
    return event_id


# AC1: only a Preparing event, only at or after its end ------------------------------------


# QA-SPL-105-001 | AC1 | BB
def test_qa_spl_105_001_preparing_event_is_completed_exactly_at_its_end(app, client, monkeypatch):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)

    response = complete(client, event_id)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "completed"
    assert response.json["event"]["status_label"] == "Completed"
    assert response.json["event"]["completed_by"] == {
        "id": COORDINATOR,
        "name": "Casey Coordinator",
    }
    assert response.json["event"]["completed_at"] == EVENT_END.isoformat()
    assert response.json["transition"]["previous_status"] == "preparing"
    assert response.json["transition"]["resulting_status"] == "completed"
    assert row(app, event_id)["status"] == "completed"


# QA-SPL-105-002 | AC1 | BB
def test_qa_spl_105_002_one_second_before_the_end_is_refused(app, client, monkeypatch):
    event_id = add_event(app, status="preparing")
    at(EVENT_END - timedelta(seconds=1), monkeypatch)
    before = row(app, event_id)

    response = complete(client, event_id)

    assert response.status_code == 409
    assert response.json["error"] == "This event can be completed from 20 Nov 2026, 17:00 SGT."
    assert row(app, event_id) == before


# QA-SPL-105-003 | AC1 | BB
def test_qa_spl_105_003_well_after_the_end_is_accepted(app, client, monkeypatch):
    event_id = add_event(app, status="preparing")
    at(EVENT_END + timedelta(days=3), monkeypatch)

    assert complete(client, event_id).status_code == 200
    assert row(app, event_id)["status"] == "completed"


# QA-SPL-105-004 | AC1 | BB
def test_qa_spl_105_004_a_later_approved_room_moves_the_end(app, client, monkeypatch):
    """TC-SPL-105-03: the second room ends at 20:00, so 19:00 is too early and 20:00 is not."""

    event_id = add_event(app, status="preparing")
    add_booking(app, event_id, venue_id=1, exact_timing=exact_timing(14, 17))
    add_booking(app, event_id, venue_id=2, exact_timing=exact_timing(15, 20))

    at(EVENT_END + timedelta(hours=2), monkeypatch)
    early = complete(client, event_id)
    assert early.status_code == 409
    assert early.json["error"] == "This event can be completed from 20 Nov 2026, 20:00 SGT."
    assert row(app, event_id)["status"] == "preparing"

    at(EVENT_END + timedelta(hours=3), monkeypatch)
    assert complete(client, event_id).status_code == 200


# QA-SPL-105-005 | AC1 | WB
@pytest.mark.parametrize("status", ["requested", "rejected", "withdrawn", "cancelled"])
def test_qa_spl_105_005_only_approved_bookings_count_towards_the_end(
    app, client, monkeypatch, status
):
    event_id = add_event(app, status="preparing")
    add_booking(app, event_id, status=status, venue_id=2, exact_timing=exact_timing(15, 22))
    at(EVENT_END, monkeypatch)

    assert complete(client, event_id).status_code == 200


# QA-SPL-105-006 | AC1 | WB
def test_qa_spl_105_006_turnaround_after_the_event_is_not_part_of_its_end(app, client, monkeypatch):
    event_id = add_event(app, status="preparing")
    add_booking(app, event_id, exact_timing=exact_timing(14, 17, setup=60, turnaround=180))
    at(EVENT_END, monkeypatch)

    assert complete(client, event_id).status_code == 200


# QA-SPL-105-007 | AC1 | WB
def test_qa_spl_105_007_an_unreadable_booking_end_refuses_rather_than_guesses(
    app, client, monkeypatch
):
    event_id = add_event(app, status="preparing")
    add_booking(app, event_id, exact_timing={"unreadable": True})
    at(EVENT_END + timedelta(days=1), monkeypatch)

    response = complete(client, event_id)

    assert response.status_code == 409
    assert response.json["error"] == event_completion.END_NOT_RECORDED
    assert row(app, event_id)["status"] == "preparing"


# QA-SPL-105-007 | AC1 | WB
@pytest.mark.parametrize("missing", ["proposed_date", "end_time"])
def test_qa_spl_105_007_no_recorded_end_means_no_end(missing):
    event = EventRequest(proposed_date=EVENT_DATE, end_time=EVENT_END.time(), venue_bookings=[])
    setattr(event, missing, None)

    assert event_completion.event_end(event) is None
    assert event_completion.completion_available_at(event) is None


# QA-SPL-105-008 | AC1 | WB
def test_qa_spl_105_008_slot_era_approved_booking_uses_the_event_times(app, client, monkeypatch):
    event_id = add_event(app, status="preparing")
    add_booking(app, event_id)  # A slot-era booking: no exact timing of its own.
    at(EVENT_END, monkeypatch)

    assert complete(client, event_id).status_code == 200


# AC2: every other status is refused with a reason ------------------------------------------


# QA-SPL-105-010 | AC2 | BB
@pytest.mark.parametrize("status", [s for s in NOT_PREPARING if s not in ("draft", "completed")])
def test_qa_spl_105_010_every_non_preparing_status_is_refused(app, client, monkeypatch, status):
    event_id = add_event(app, status=status)
    at(EVENT_END + timedelta(days=1), monkeypatch)
    before = row(app, event_id)

    response = complete(client, event_id)

    assert response.status_code == 409
    if status == "confirmed":
        assert response.json["error"] == (
            "This event has not entered Preparation after safety approval, "
            "so it cannot be completed."
        )
    else:
        assert "cannot be completed" in response.json["error"]
        assert response.json["error"].startswith("This event is ")
    assert row(app, event_id) == before


# QA-SPL-105-011 | AC2 | BB
def test_qa_spl_105_011_a_completed_event_cannot_be_completed_again(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch, note=NOTE)
    first = row(app, event_id)

    at(EVENT_END + timedelta(days=1), monkeypatch)
    again = complete(client, event_id, body={"note": "A second, different note."})

    assert again.status_code == 409
    assert again.json["error"] == "This event is already completed."
    assert row(app, event_id) == first
    assert [entry[0] for entry in first["history"]].count("complete") == 1


# QA-SPL-105-012 | AC2 | BB
def test_qa_spl_105_012_a_draft_has_no_coordinator_so_it_is_not_found(app, client, monkeypatch):
    event_id = add_event(app, status="draft")
    with Session(app.extensions["engine"]) as session:
        session.delete(session.get(EventCoordinatorAssignment, event_id))
        session.commit()
    at(EVENT_END + timedelta(days=1), monkeypatch)

    response = complete(client, event_id)

    assert response.status_code == 404
    assert row(app, event_id)["status"] == "draft"


# QA-SPL-105-013 | AC2 | WB
def test_qa_spl_105_013_the_shared_transition_rule_allows_preparing_only(app):
    from app.event_review import COMPLETE, TRANSITION_RULES

    rule = TRANSITION_RULES[COMPLETE]
    assert rule.previous_status == "preparing"
    assert rule.resulting_status == "completed"


# AC3: only the assigned coordinator ---------------------------------------------------------


# QA-SPL-105-020 | AC3 | BB
def test_qa_spl_105_020_another_coordinator_is_told_the_event_is_not_found(
    app, client, monkeypatch
):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)
    before = row(app, event_id)

    response = complete(client, event_id, identity="other-coordinator")

    assert response.status_code == 404
    assert response.json["error"] == "Assigned event not found."
    assert row(app, event_id) == before


# QA-SPL-105-021 | AC3 | BB
@pytest.mark.parametrize(
    "identity", ["lead", "organiser", "technical", "venue-staff", "colleague", "attendee"]
)
def test_qa_spl_105_021_other_roles_are_refused(app, client, monkeypatch, identity):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)

    response = complete(client, event_id, identity=identity)

    assert response.status_code == 403
    assert row(app, event_id)["status"] == "preparing"


# QA-SPL-105-022 | AC3 | BB
def test_qa_spl_105_022_no_session_is_refused(app, client, monkeypatch):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)

    response = client.post(f"/api/event-requests/{event_id}/complete", json={})

    assert response.status_code == 401
    assert row(app, event_id)["status"] == "preparing"


# QA-SPL-105-023 | AC3 | BB
@pytest.mark.parametrize("event_id", [987654, 2**31])
def test_qa_spl_105_023_unknown_events_are_not_found(client, event_id):
    assert complete(client, event_id).status_code == 404


# QA-SPL-105-024 | AC3 | WB
def test_qa_spl_105_024_after_reassignment_only_the_new_coordinator_can_complete(
    app, client, monkeypatch
):
    event_id = add_event(app, status="preparing")
    with Session(app.extensions["engine"]) as session:
        session.get(EventCoordinatorAssignment, event_id).coordinator_account_id = OTHER_COORDINATOR
        session.commit()
    at(EVENT_END, monkeypatch)

    assert complete(client, event_id).status_code == 404
    response = complete(client, event_id, identity="other-coordinator")

    assert response.status_code == 200
    assert row(app, event_id)["completed_by"] == OTHER_COORDINATOR


# AC4: what is recorded ----------------------------------------------------------------------


# QA-SPL-105-030 | AC4 | BB
def test_qa_spl_105_030_actor_time_and_history_are_recorded_together(app, client, monkeypatch):
    event_id = add_event(app, status="preparing")
    moment = EVENT_END + timedelta(minutes=25)
    at(moment, monkeypatch)

    assert complete(client, event_id).status_code == 200

    saved = row(app, event_id)
    assert saved["completed_by"] == COORDINATOR
    assert saved["completed_at"].replace(tzinfo=None) == moment.replace(tzinfo=None)
    assert saved["note"] is None
    assert saved["history"][-1] == ("complete", "preparing", "completed", COORDINATOR)


# QA-SPL-105-031 | AC4 | BB
def test_qa_spl_105_031_the_note_is_saved_trimmed_and_shown_to_the_coordinator(
    app, client, monkeypatch
):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)

    response = complete(client, event_id, body={"note": f"  {NOTE}\n"})

    assert response.json["event"]["completion_note"] == NOTE
    assert row(app, event_id)["note"] == NOTE
    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers())
    assert detail.json["event"]["completion_note"] == NOTE
    assert detail.json["event"]["completed_by"]["id"] == COORDINATOR


# QA-SPL-105-032 | AC4 | BB
@pytest.mark.parametrize(
    ("note", "status", "stored"),
    [
        ("x" * 2000, 200, "x" * 2000),
        ("x" * 2001, 400, None),
        ("   ", 200, None),
        (None, 200, None),
    ],
    ids=["at-limit", "over-limit", "blank", "null"],
)
def test_qa_spl_105_032_note_length_and_blank_boundaries(
    app, client, monkeypatch, note, status, stored
):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)

    response = complete(client, event_id, body={"note": note})

    assert response.status_code == status
    saved = row(app, event_id)
    assert saved["note"] == stored
    assert saved["status"] == ("completed" if status == 200 else "preparing")
    if status == 400:
        assert response.json["error"] == "Keep the closing note to 2000 characters or fewer."


# QA-SPL-105-033 | AC4 | BB
@pytest.mark.parametrize(
    "body",
    [
        {"note": "fine", "status": "completed"},
        {"completed_by_account_id": OTHER_COORDINATOR},
        {"note": 42},
        ["note"],
        "note",
    ],
    ids=["extra-status", "client-actor", "note-not-text", "list", "string"],
)
def test_qa_spl_105_033_the_body_cannot_set_anything_else(app, client, monkeypatch, body):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)

    response = complete(client, event_id, body=body)

    assert response.status_code == 400
    assert row(app, event_id)["status"] == "preparing"


# QA-SPL-105-033 | AC4 | BB
def test_qa_spl_105_033_a_request_without_a_json_body_is_refused(app, client, monkeypatch):
    event_id = add_event(app, status="preparing")
    at(EVENT_END, monkeypatch)

    response = client.post(f"/api/event-requests/{event_id}/complete", headers=headers())

    assert response.status_code == 400
    assert row(app, event_id)["status"] == "preparing"


# QA-SPL-105-034 | AC4 | WB
@pytest.mark.parametrize(
    "values",
    [
        {"completion_note": "orphan note"},
        {"completed_at": EVENT_END},
        {"completed_by_account_id": COORDINATOR},
    ],
    ids=["note-alone", "time-alone", "actor-alone"],
)
def test_qa_spl_105_034_the_database_keeps_actor_time_and_note_together(app, values):
    event_id = add_event(app, status="preparing")
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        for field, value in values.items():
            setattr(event, field, value)
        with pytest.raises(IntegrityError):
            session.commit()


# QA-SPL-105-035 | AC4 | BB
def test_qa_spl_105_035_completion_sends_no_notification(app, client, monkeypatch):
    before = count(app, Notification)

    completed_event(app, client, monkeypatch, note=NOTE)

    assert count(app, Notification) == before


# AC5: a Completed event is read-only --------------------------------------------------------


# QA-SPL-105-040 | AC5 | BB
def test_qa_spl_105_040_information_edits_are_refused(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch)

    response = client.patch(
        f"/api/event-requests/assigned/{event_id}/event-information",
        json={"purpose": "Rewritten after the event"},
        headers=headers(),
    )

    assert response.status_code == 409
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).purpose == "Annual leadership programme"


# QA-SPL-105-041 | AC5 | BB
def test_qa_spl_105_041_cancellation_is_refused(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch)

    response = client.post(
        f"/api/event-requests/{event_id}/cancel",
        json={"reason": "Trying to cancel a finished event."},
        headers=headers(),
    )

    assert response.status_code == 409
    assert row(app, event_id)["status"] == "completed"


# QA-SPL-105-042 | AC5 | BB
def test_qa_spl_105_042_reassignment_is_refused(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch)

    response = client.put(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": OTHER_COORDINATOR},
        headers=headers("lead"),
    )

    assert response.status_code == 409
    with Session(app.extensions["engine"]) as session:
        assignment = session.get(EventCoordinatorAssignment, event_id)
        assert assignment.coordinator_account_id == COORDINATOR


# QA-SPL-105-043 | AC5 | BB
def test_qa_spl_105_043_change_requests_are_refused(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch)

    response = client.post(
        f"/api/event-requests/{event_id}/change-requests",
        json={"items": [{"field": "name", "requested_value": "Renamed", "reason": "Rebrand"}]},
        headers=headers("organiser"),
    )

    assert response.status_code == 409
    assert count(app, EventChangeRequest) == 0


# QA-SPL-105-044 | AC5 | BB
def test_qa_spl_105_044_arrangements_cannot_be_added(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch)

    booking = client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": 1, "layout": "theatre"},
        headers=headers(),
    )
    equipment = client.post(
        f"/api/event-requests/{event_id}/equipment-requirements",
        json={"equipment_type": "Wireless Microphone", "quantity": 1},
        headers=headers(),
    )

    assert booking.status_code == 409
    assert equipment.status_code == 409
    assert count(app, VenueBooking) == 0
    assert count(app, EquipmentRequirement) == 0


# QA-SPL-105-045 | AC5 | BB
def test_qa_spl_105_045_registration_cannot_be_changed_or_joined(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch)

    settings = client.put(
        f"/api/event-requests/{event_id}/registration", json={}, headers=headers()
    )
    joining = client.post(
        f"/api/event-requests/{event_id}/registrations",
        json={"name": "Ari Attendee", "email": "ari@example.test"},
        headers=headers("attendee"),
    )

    assert settings.status_code == 409
    assert joining.status_code in (404, 409)
    assert count(app, EventRegistration) == 0


# AC6: still viewable by everyone who could view it ------------------------------------------


# QA-SPL-105-050 | AC6 | BB
def test_qa_spl_105_050_responsible_organiser_still_sees_it_without_the_note(
    app, client, monkeypatch
):
    event_id = completed_event(app, client, monkeypatch, note=NOTE)

    response = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))

    assert response.status_code == 200
    event = response.json["event_request"]
    assert event["status"] == "completed"
    assert event["status_label"] == "Completed"
    assert event["completed_by"]["name"] == "Casey Coordinator"
    assert event["completed_at"] == EVENT_END.isoformat()
    assert "completion_note" not in event


# QA-SPL-105-051 | AC6 | BB
def test_qa_spl_105_051_same_client_organiser_still_sees_it(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch, note=NOTE)

    response = client.get(f"/api/organisation/events/{event_id}", headers=headers("colleague"))

    assert response.status_code == 200
    assert response.json["event"]["status"] == "completed"
    assert "completion_note" not in response.json["event"]


# QA-SPL-105-052 | AC6 | BB
def test_qa_spl_105_052_assigned_coordinator_still_sees_it_in_list_and_detail(
    app, client, monkeypatch
):
    event_id = completed_event(app, client, monkeypatch)

    listing = client.get("/api/event-requests/assigned", headers=headers())
    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers())

    assert [event["id"] for event in listing.json["events"]] == [event_id]
    assert detail.status_code == 200
    assert detail.json["event"]["status"] == "completed"


# QA-SPL-105-053 | AC6 | BB
def test_qa_spl_105_053_the_lead_still_sees_it_without_the_note(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch, note=NOTE)

    response = client.get("/api/event-requests/supervision", headers=headers("lead"))

    assert response.status_code == 200
    listed = [event for event in response.json["events"] if event["id"] == event_id]
    assert listed and listed[0]["status"] == "completed"
    assert NOTE not in str(response.json)


# QA-SPL-105-054 | AC6 | BB
def test_qa_spl_105_054_another_client_still_cannot_see_it(app, client, monkeypatch):
    event_id = completed_event(app, client, monkeypatch)

    own = client.get(f"/api/event-requests/{event_id}", headers=headers("outsider"))
    shared = client.get(f"/api/organisation/events/{event_id}", headers=headers("outsider"))

    assert own.status_code == 404
    assert shared.status_code == 404


# Cross-cutting -------------------------------------------------------------------------------


# QA-SPL-105-060 | AC1 | BB
def test_qa_spl_105_060_detail_tells_the_coordinator_when_completion_opens(app, client):
    event_id = add_event(app, status="preparing")
    add_booking(app, event_id, venue_id=2, exact_timing=exact_timing(15, 20))

    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers())

    assert (
        detail.json["event"]["completion_available_at"]
        == (EVENT_END + timedelta(hours=3)).isoformat()
    )
