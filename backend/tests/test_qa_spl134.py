"""QA coverage for SPL-134, Adapt Coordinator Lead assignment and supervision.

Case IDs (QA-SPL-134-NNN) match the QA-SPL-134 Confluence page. BB = black-box (HTTP API only),
WB = white-box (drives or inspects internals: helpers, stored rows, the transaction boundary).

The fixtures, account ids and request helpers come from test_coordinator_assignment, exactly as
the SPL-101 suite reuses them, so every case runs against the same trusted account model.
"""

from datetime import date, datetime, time, timedelta

import pytest
from app import coordinator_assignment
from app import notifications as notification_module
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EquipmentRequirement,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Notification,
    Organisation,
    Role,
)
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_coordinator_assignment import (
    ALICE,
    BOB,
    CAROL,
    INACTIVE_COORDINATOR,
    MANAGER,
    MANAGER_AND_ORGANISER,
    ORGANISER,
    TOKENS,
    VENUE_STAFF,
    add_request,
    assign,
    deactivate,
    headers,
    history_count,
    holds_event,
    queue,
    reassign,
    set_status,
)
from test_coordinator_assignment import app as app  # noqa: F401  (pytest fixture)
from test_coordinator_assignment import client as client  # noqa: F401  (pytest fixture)

ACTIVE_STATUSES = [
    "submitted",
    "under_review",
    "returned_for_clarification",
    "approved",
    "planning",
    "confirmed",
]
CLOSED_STATUSES = ["completed", "cancelled", "rejected", "withdrawn"]
BASIC_KEYS = {
    "id",
    "name",
    "purpose",
    "organisation_id",
    "organisation_name",
    "proposed_date",
    "start_time",
    "end_time",
    "expected_attendance",
    "status",
    "status_label",
    # SPL-86: who cancelled the event, when and why (empty until cancelled).
    "cancelled_by",
    "cancelled_at",
    "cancellation_reason",
}


def supervision(client, token="manager"):
    return client.get("/api/event-requests/supervision", headers=headers(token))


def basic_information(client, event_id, token="manager"):
    return client.get(f"/api/event-requests/{event_id}/basic-information", headers=headers(token))


def notices(app, recipient=None, event_id=None):
    with Session(app.extensions["engine"]) as session:
        query = select(Notification).order_by(Notification.id)
        if recipient:
            query = query.where(Notification.recipient_account_id == recipient)
        if event_id:
            query = query.where(Notification.event_request_id == event_id)
        return list(session.scalars(query))


def messages(app, recipient, event_id=None):
    return [notice.message for notice in notices(app, recipient, event_id)]


def stored_coordinator(app, event_id):
    with Session(app.extensions["engine"]) as session:
        row = session.get(EventCoordinatorAssignment, event_id)
        return row.coordinator_account_id if row else None


def entry(client, event_id):
    return {e["id"]: e for e in supervision(client).json["events"]}[event_id]


def add_request_for(app, organiser_id, name="Organiser Is Coordinator"):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=organiser_id,
            organisation_id=app.config["TEST_ORGANISATION_ID"],
            name=name,
            purpose="Overlapping roles",
            proposed_date=date(2026, 10, 12),
            start_time=time(9, 0),
            end_time=time(12, 0),
            expected_attendance=10,
            status="submitted",
            submitted_at=datetime(2026, 9, 1, 9, 0, tzinfo=SINGAPORE),
        )
        session.add(event)
        session.commit()
        return event.id


# =============================================================================================
# AC1  Unassigned queue: nothing is selected automatically; basic information; assign active
# =============================================================================================


# QA-SPL-134-001 | AC1 | BB happy path
def test_qa_spl_134_001_a_submitted_request_waits_in_the_queue_with_no_coordinator(app, client):
    event_id = add_request(app, "Harbour Summit")

    listed = queue(client)
    assert [e["id"] for e in listed.json["events"]] == [event_id]
    assert stored_coordinator(app, event_id) is None
    row = entry(client, event_id)
    assert row["coordinator"] is None
    assert row["reassignable"] is False
    assert notices(app) == []


# QA-SPL-134-002 | AC1 | BB: basic information is exactly the agreed set
def test_qa_spl_134_002_basic_information_is_the_agreed_fields_only(app, client):
    event_id = add_request(app, "Harbour Summit")
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.venue_notes = "PRIVATE venue note"
        event.facilities_notes = "PRIVATE facilities note"
        event.registration_notes = "PRIVATE registration note"
        session.add(
            EquipmentRequirement(
                event_request_id=event_id, equipment_type="PRIVATE mic", quantity=2
            )
        )
        session.commit()

    response = basic_information(client, event_id)

    assert response.status_code == 200
    assert response.json["event"] == {
        "id": event_id,
        "name": "Harbour Summit",
        "purpose": "Client showcase",
        "organisation_id": app.config["TEST_ORGANISATION_ID"],
        "organisation_name": "Northstar Community Partners",
        "proposed_date": "2026-10-12",
        "start_time": "09:00",
        "end_time": "12:00",
        "expected_attendance": 120,
        "status": "submitted",
        "status_label": "Submitted",
        "cancelled_by": None,
        "cancelled_at": None,
        "cancellation_reason": None,
    }
    assert "PRIVATE" not in response.get_data(as_text=True)


# QA-SPL-134-003 | AC1 | BB: the Lead can assign an active coordinator
def test_qa_spl_134_003_the_lead_assigns_an_active_coordinator(app, client):
    event_id = add_request(app)

    response = assign(client, event_id, ALICE)

    assert response.status_code == 201
    assert response.json["assignment"]["coordinator"] == {"id": ALICE, "name": "Alice Tan"}
    assert queue(client).json["count"] == 0  # gone from the queue after reload
    assert entry(client, event_id)["coordinator"]["name"] == "Alice Tan"


# QA-SPL-134-004 | AC1 | BB negative: an inactive coordinator cannot be chosen
def test_qa_spl_134_004_an_inactive_coordinator_is_refused_and_nothing_is_sent(app, client):
    event_id = add_request(app)

    response = assign(client, event_id, INACTIVE_COORDINATOR)

    assert response.status_code == 400
    assert stored_coordinator(app, event_id) is None
    assert history_count(app, event_id) == 0
    assert notices(app) == []


# QA-SPL-134-005 | AC1 | BB negative: only a coordinator account can be chosen
@pytest.mark.parametrize("chosen", [VENUE_STAFF, ORGANISER, MANAGER, "not-a-uuid", None])
def test_qa_spl_134_005_a_non_coordinator_choice_is_refused(app, client, chosen):
    event_id = add_request(app)

    response = assign(client, event_id, chosen)

    assert response.status_code == 400
    assert stored_coordinator(app, event_id) is None
    assert notices(app) == []


# QA-SPL-134-006 | AC1 | BB boundary: ids that cannot name a viewable request
def test_qa_spl_134_006_basic_information_has_one_answer_for_missing_and_draft(app, client):
    draft = add_request(app, "Unsent draft", status="draft")

    assert basic_information(client, draft).status_code == 404
    assert basic_information(client, 424242).status_code == 404
    assert basic_information(client, 2**31).status_code == 404
    assert basic_information(client, 2**31 - 1).status_code == 404


# QA-SPL-134-007 | AC1 | BB security: only the Lead can read basic information
@pytest.mark.parametrize("token", ["organiser", "coordinator", "venue-staff"])
def test_qa_spl_134_007_other_roles_cannot_read_basic_information(app, client, token):
    event_id = add_request(app)

    assert basic_information(client, event_id, token).status_code == 403
    assert client.get(f"/api/event-requests/{event_id}/basic-information").status_code == 401


# QA-SPL-134-008 | AC1 | WB: the serialiser omits every private column
def test_qa_spl_134_008_the_basic_serialiser_has_no_private_columns(app):
    event_id = add_request(app)
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assert set(coordinator_assignment._serialize_basic_event(event)) == BASIC_KEYS


# QA-SPL-134-009 | AC1 | BB negative: a request cannot be given a second coordinator by the queue
def test_qa_spl_134_009_a_request_that_is_already_assigned_cannot_be_assigned_again(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    count = len(notices(app))

    assert assign(client, event_id, BOB).status_code == 409
    assert stored_coordinator(app, event_id) == ALICE
    assert len(notices(app)) == count


# =============================================================================================
# AC2  Supervision: every assignment and every active submitted event; reassign any of them
# =============================================================================================


# QA-SPL-134-010 | AC2 | BB happy path: each active status is listed
@pytest.mark.parametrize("status", ACTIVE_STATUSES)
def test_qa_spl_134_010_every_active_status_is_listed_with_its_coordinator(app, client, status):
    event_id = add_request(app, "Active event")
    assert assign(client, event_id, ALICE).status_code == 201
    set_status(app, event_id, status)

    row = entry(client, event_id)

    assert row["status"] == status
    assert row["coordinator"] == {"id": ALICE, "name": "Alice Tan"}
    assert row["reassignable"] is True
    assert set(row) == BASIC_KEYS | {"coordinator", "reassignable"}


# QA-SPL-134-011 | AC2 | BB negative: drafts and closed events with no assignment are excluded
@pytest.mark.parametrize("status", ["draft", *CLOSED_STATUSES])
def test_qa_spl_134_011_inactive_events_without_an_assignment_are_not_listed(app, client, status):
    add_request(app, "Not active", status=status)

    assert supervision(client).json == {"events": [], "count": 0}


# QA-SPL-134-012 | AC2 | BB boundary: a closed event that still has an assignment stays visible
@pytest.mark.parametrize("status", CLOSED_STATUSES)
def test_qa_spl_134_012_a_closed_assignment_stays_listed_but_cannot_be_reassigned(
    app, client, status
):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    set_status(app, event_id, status)

    row = entry(client, event_id)
    assert row["coordinator"]["id"] == ALICE
    assert row["reassignable"] is False
    assert reassign(client, event_id, BOB).status_code == 409


# QA-SPL-134-013 | AC2 | BB: the view is organisation-wide with no partition
def test_qa_spl_134_013_events_from_every_organisation_are_listed(app, client):
    first = add_request(app, "Northstar event")
    with Session(app.extensions["engine"]) as session:
        other = Organisation(name="Harbourfront Arts Collective")
        session.add(other)
        session.flush()
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=other.id,
            name="Harbourfront event",
            purpose="Different client",
            proposed_date=date(2026, 11, 1),
            start_time=time(13, 0),
            end_time=time(15, 0),
            expected_attendance=30,
            status="under_review",
            submitted_at=datetime(2026, 9, 2, 9, 0, tzinfo=SINGAPORE),
        )
        session.add(event)
        session.commit()
        second = event.id

    rows = {e["id"]: e for e in supervision(client).json["events"]}

    assert set(rows) == {first, second}
    assert rows[second]["organisation_name"] == "Harbourfront Arts Collective"
    assert rows[first]["organisation_name"] == "Northstar Community Partners"


# QA-SPL-134-014 | AC2 | BB: an active event without a coordinator is shown as such
def test_qa_spl_134_014_unassigned_active_events_are_visible_but_not_reassignable(app, client):
    event_id = add_request(app)

    row = entry(client, event_id)

    assert row["coordinator"] is None
    assert row["reassignable"] is False
    assert reassign(client, event_id, ALICE).status_code == 409  # nothing to reassign yet


# QA-SPL-134-015 | AC2 | BB boundary: deterministic order, undated events last
def test_qa_spl_134_015_events_are_ordered_by_date_then_id_with_undated_last(app, client):
    later = add_request(app, "Later", proposed_date=date(2026, 12, 1))
    sooner_b = add_request(app, "Sooner B", proposed_date=date(2026, 10, 1))
    sooner_a = add_request(app, "Sooner A", proposed_date=date(2026, 10, 1))
    undated = add_request(app, "Undated", proposed_date=date(2026, 10, 1))
    with Session(app.extensions["engine"]) as session:
        # The submitted-fields constraint requires a date while Submitted, so go via Under review.
        event = session.get(EventRequest, undated)
        event.status = "under_review"
        event.proposed_date = None
        session.commit()

    ids = [e["id"] for e in supervision(client).json["events"]]

    assert ids == [sooner_b, sooner_a, later, undated]
    assert supervision(client).json["count"] == 4


# QA-SPL-134-016 | AC2 | BB security: only the Lead sees supervision
@pytest.mark.parametrize("token", ["organiser", "coordinator", "coordinator-b", "venue-staff"])
def test_qa_spl_134_016_other_roles_are_refused_supervision(app, client, token):
    add_request(app, "Secret planning")

    response = supervision(client, token)

    assert response.status_code == 403
    assert "Secret planning" not in response.get_data(as_text=True)
    assert client.get("/api/event-requests/supervision").status_code == 401


# QA-SPL-134-017 | AC2 | BB: the Lead can reassign any coordinator's event
def test_qa_spl_134_017_the_lead_reassigns_events_held_by_different_coordinators(app, client):
    alice_event = add_request(app, "Alice's")
    bob_event = add_request(app, "Bob's")
    assert assign(client, alice_event, ALICE).status_code == 201
    assert assign(client, bob_event, BOB).status_code == 201

    assert reassign(client, alice_event, CAROL).status_code == 200
    assert reassign(client, bob_event, ALICE).status_code == 200

    assert entry(client, alice_event)["coordinator"]["id"] == CAROL
    assert entry(client, bob_event)["coordinator"]["id"] == ALICE


# QA-SPL-134-018 | AC2 | BB boundary: an empty organisation
def test_qa_spl_134_018_no_events_gives_an_empty_list_not_an_error(app, client):
    response = supervision(client)

    assert response.status_code == 200
    assert response.json == {"events": [], "count": 0}


# QA-SPL-134-019 | AC2 | BB: the view reads current state after a status change
def test_qa_spl_134_019_an_event_leaves_the_active_set_when_it_is_cancelled_unassigned(app, client):
    event_id = add_request(app)
    assert [e["id"] for e in supervision(client).json["events"]] == [event_id]

    set_status(app, event_id, "cancelled")

    assert supervision(client).json["events"] == []


# QA-SPL-134-020 | AC2 | WB: statement count does not grow with the number of events
def test_qa_spl_134_020_supervision_uses_a_constant_number_of_queries(app, client):
    def count_statements(events):
        for index in range(events):
            event_id = add_request(app, f"Event {index}")
            if stored_coordinator(app, event_id) is None:
                assign(client, event_id, ALICE if index % 2 else BOB)
        seen = []
        engine = app.extensions["engine"]

        def record(conn, cursor, statement, *args):
            if statement.lstrip().upper().startswith("SELECT"):
                seen.append(statement)

        sa_event.listen(engine, "before_cursor_execute", record)
        try:
            assert supervision(client).status_code == 200
        finally:
            sa_event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    few = count_statements(2)
    many = count_statements(10)

    assert many == few


# =============================================================================================
# AC3  Reassignment: authority moves, existing arrangements intact
# =============================================================================================


# QA-SPL-134-021 | AC3 | BB happy path: management authority moves
def test_qa_spl_134_021_authority_moves_to_the_new_coordinator(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    path = f"/api/event-requests/assigned/{event_id}"
    assert client.get(path, headers=headers("coordinator")).status_code == 200

    assert reassign(client, event_id, BOB).status_code == 200

    assert client.get(path, headers=headers("coordinator")).status_code == 404
    assert client.get(path, headers=headers("coordinator-b")).status_code == 200
    assert holds_event(app, event_id, BOB) is True
    assert holds_event(app, event_id, ALICE) is False


# QA-SPL-134-022 | AC3 | BB: the event's arrangements are untouched
def test_qa_spl_134_022_arrangements_and_details_survive_reassignment(app, client):
    event_id = add_request(app, "Intact event")
    with Session(app.extensions["engine"]) as session:
        session.add(
            EquipmentRequirement(event_request_id=event_id, equipment_type="Mic", quantity=3)
        )
        session.commit()
    assert assign(client, event_id, ALICE).status_code == 201

    def snapshot():
        with Session(app.extensions["engine"]) as session:
            event = session.get(EventRequest, event_id)
            columns = {c.name: getattr(event, c.name) for c in EventRequest.__table__.columns}
            lines = [
                (line.equipment_type, line.quantity, line.status)
                for line in event.equipment_requirements
            ]
            return columns, lines

    before = snapshot()
    assert reassign(client, event_id, BOB).status_code == 200

    assert snapshot() == before


# QA-SPL-134-023 | AC3 | BB: reassignment never moves the event's status
@pytest.mark.parametrize("status", ACTIVE_STATUSES)
def test_qa_spl_134_023_status_is_unchanged_by_reassignment(app, client, status):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    set_status(app, event_id, status)

    response = reassign(client, event_id, BOB)

    assert response.status_code == 200
    assert response.json["assignment"]["status"] == status
    assert entry(client, event_id)["status"] == status


# QA-SPL-134-024 | AC3 | BB negative: closed events refuse reassignment and change nothing
@pytest.mark.parametrize("status", CLOSED_STATUSES)
def test_qa_spl_134_024_a_closed_event_is_refused_and_leaves_no_trace(app, client, status):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    set_status(app, event_id, status)
    before = (len(notices(app)), history_count(app, event_id))

    response = reassign(client, event_id, BOB)

    assert response.status_code == 409
    assert stored_coordinator(app, event_id) == ALICE
    assert (len(notices(app)), history_count(app, event_id)) == before


# QA-SPL-134-025 | AC3 | BB negative: same, inactive and unknown targets are refused
@pytest.mark.parametrize("target", [ALICE, INACTIVE_COORDINATOR, VENUE_STAFF, "nope", None])
def test_qa_spl_134_025_an_unsuitable_new_coordinator_is_refused(app, client, target):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    before = len(notices(app))

    assert reassign(client, event_id, target).status_code == 400

    assert stored_coordinator(app, event_id) == ALICE
    assert len(notices(app)) == before
    assert history_count(app, event_id) == 1


# QA-SPL-134-026 | AC3 | BB: history keeps who, from, to, when across several moves
def test_qa_spl_134_026_history_records_every_move_in_order(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200
    assert reassign(client, event_id, ALICE).status_code == 200

    rows = client.get(
        f"/api/event-requests/{event_id}/coordinator-history", headers=headers()
    ).json["history"]

    assert [
        ((r["previous_coordinator"] or {}).get("name"), r["new_coordinator"]["name"]) for r in rows
    ] == [(None, "Alice Tan"), ("Alice Tan", "Bob Lim"), ("Bob Lim", "Alice Tan")]
    assert {r["changed_by"]["name"] for r in rows} == {"Morgan Manager"}


# QA-SPL-134-027 | AC3 | WB: a competing change makes the update affect no row
def test_qa_spl_134_027_a_concurrent_change_is_refused_and_leaves_no_notices(
    app, client, monkeypatch
):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    base = len(notices(app))
    original = coordinator_assignment._chosen_coordinator

    def chosen_then_competitor_wins(*args, **kwargs):
        account = original(*args, **kwargs)
        with Session(app.extensions["engine"]) as other:
            other.get(EventCoordinatorAssignment, event_id).coordinator_account_id = CAROL
            other.commit()
        return account

    monkeypatch.setattr(coordinator_assignment, "_chosen_coordinator", chosen_then_competitor_wins)

    response = reassign(client, event_id, BOB)

    assert response.status_code == 409
    assert "changed while you were reassigning" in response.get_json()["error"]
    assert stored_coordinator(app, event_id) == CAROL
    assert len(notices(app)) == base
    assert history_count(app, event_id) == 1


# QA-SPL-134-028 | AC3 | WB: a terminal transition between read and write is explained
def test_qa_spl_134_028_a_status_change_during_reassignment_is_refused(app, client, monkeypatch):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    original = coordinator_assignment._chosen_coordinator

    def chosen_then_event_cancelled(*args, **kwargs):
        account = original(*args, **kwargs)
        set_status(app, event_id, "cancelled")
        return account

    monkeypatch.setattr(coordinator_assignment, "_chosen_coordinator", chosen_then_event_cancelled)

    response = reassign(client, event_id, BOB)

    assert response.status_code == 409
    assert "cannot be reassigned" in response.get_json()["error"]
    assert stored_coordinator(app, event_id) == ALICE


# =============================================================================================
# AC4  Access: coordinators manage only their own; only the Lead assigns or reassigns
# =============================================================================================


# QA-SPL-134-029 | AC4 | BB security: non-Lead roles cannot assign or reassign
@pytest.mark.parametrize("token", ["organiser", "coordinator", "coordinator-b", "venue-staff"])
def test_qa_spl_134_029_non_lead_roles_cannot_assign_or_reassign(app, client, token):
    fresh = add_request(app, "Fresh")
    held = add_request(app, "Held")
    assert assign(client, held, ALICE).status_code == 201
    base = len(notices(app))

    assert assign(client, fresh, BOB, token=token).status_code == 403
    assert reassign(client, held, BOB, token=token).status_code == 403

    assert stored_coordinator(app, fresh) is None
    assert stored_coordinator(app, held) == ALICE
    assert len(notices(app)) == base


# QA-SPL-134-030 | AC4 | BB security: no session is refused before anything runs
def test_qa_spl_134_030_unauthenticated_calls_are_refused(app, client):
    held = add_request(app)
    assert assign(client, held, ALICE).status_code == 201

    put = client.put(
        f"/api/event-requests/{held}/coordinator", json={"coordinator_account_id": BOB}
    )
    post = client.post(
        f"/api/event-requests/{held}/coordinator", json={"coordinator_account_id": BOB}
    )

    assert (put.status_code, post.status_code) == (401, 401)
    assert stored_coordinator(app, held) == ALICE


# QA-SPL-134-031 | AC4 | BB: a coordinator sees only events assigned to them
def test_qa_spl_134_031_a_coordinator_sees_only_their_own_events(app, client):
    mine = add_request(app, "Mine")
    theirs = add_request(app, "Theirs")
    assert assign(client, mine, ALICE).status_code == 201
    assert assign(client, theirs, BOB).status_code == 201

    listed = client.get("/api/event-requests/assigned", headers=headers("coordinator")).json
    assert [e["id"] for e in listed["events"]] == [mine]
    other = client.get(f"/api/event-requests/assigned/{theirs}", headers=headers("coordinator"))
    missing = client.get("/api/event-requests/assigned/99999", headers=headers("coordinator"))
    assert other.status_code == missing.status_code == 404
    assert other.get_json() == missing.get_json()


# QA-SPL-134-032 | AC4 | BB security: submitted identity, role and actor fields are rejected
@pytest.mark.parametrize(
    "extra",
    [{"assigned_by_account_id": ALICE}, {"role": "event_operations_manager"}, {"actor": ALICE}],
)
def test_qa_spl_134_032_a_client_cannot_choose_actor_or_role(app, client, extra):
    event_id = add_request(app)

    response = client.post(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": ALICE, **extra},
        headers=headers("coordinator"),
    )
    spoofed = client.post(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": ALICE, **extra},
        headers={**headers("manager")},
    )

    assert response.status_code == 403
    assert spoofed.status_code == 400
    assert stored_coordinator(app, event_id) is None


# QA-SPL-134-033 | AC4 | BB: the actor recorded is the verified session, not the body
def test_qa_spl_134_033_the_recorded_actor_is_the_signed_in_lead(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE, token="manager-and-organiser").status_code == 201

    with Session(app.extensions["engine"]) as session:
        row = session.get(EventCoordinatorAssignment, event_id)
        assert row.assigned_by_account_id == MANAGER_AND_ORGANISER


# QA-SPL-134-034 | AC4 | BB: a deactivated Lead loses the authority at once
def test_qa_spl_134_034_a_deactivated_lead_is_refused(app, client):
    event_id = add_request(app)
    deactivate(app, MANAGER)

    assert supervision(client).status_code == 403
    assert assign(client, event_id, ALICE).status_code == 403
    assert stored_coordinator(app, event_id) is None


# QA-SPL-134-035 | AC4 | BB: after reassignment the former coordinator is locked out
def test_qa_spl_134_035_the_former_coordinator_loses_access_after_reassignment(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200

    listed = client.get("/api/event-requests/assigned", headers=headers("coordinator")).json
    assert listed["events"] == []
    assert (
        client.get(
            f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
        ).status_code
        == 404
    )
    # ...and holding a coordinator role is not enough to reassign it back.
    assert reassign(client, event_id, ALICE, token="coordinator").status_code == 403


# QA-SPL-134-036 | AC4 | WB: the stored role is unchanged and the display title is client-only
def test_qa_spl_134_036_the_stored_role_name_is_unchanged(app):
    assert Role.EVENT_OPERATIONS_MANAGER.value == "event_operations_manager"
    with Session(app.extensions["engine"]) as session:
        roles = session.scalars(
            select(AccountRole.role).where(AccountRole.account_id == MANAGER)
        ).all()
        assert roles == ["event_operations_manager"]


# =============================================================================================
# AC5  Notifications: each affected account notified exactly once, naming event and change
# =============================================================================================


# QA-SPL-134-037 | AC5 | BB happy path: assignment notifies the coordinator and the organiser once
def test_qa_spl_134_037_assignment_notifies_coordinator_and_organiser_once(app, client):
    event_id = add_request(app, "Harbour Summit")

    assert assign(client, event_id, ALICE).status_code == 201

    to_alice = messages(app, ALICE, event_id)
    to_organiser = messages(app, ORGANISER, event_id)
    assert to_alice == ["You have been assigned to Harbour Summit."]
    assert to_organiser == [
        "Alice Tan is now the Event Coordinator responsible for Harbour Summit."
    ]
    assert len(notices(app)) == 2
    assert notices(app, MANAGER) == []  # the actor is not notified of their own action


# QA-SPL-134-038 | AC5 | BB happy path: reassignment notifies former, new and organiser once
def test_qa_spl_134_038_reassignment_notifies_former_new_and_organiser_once(app, client):
    event_id = add_request(app, "Harbour Summit")
    assert assign(client, event_id, ALICE).status_code == 201
    before = len(notices(app))

    assert reassign(client, event_id, BOB).status_code == 200

    fresh = notices(app)[before:]
    assert sorted(n.recipient_account_id for n in fresh) == sorted([ALICE, BOB, ORGANISER])
    by_recipient = {n.recipient_account_id: n.message for n in fresh}
    assert by_recipient[ALICE] == (
        "You are no longer responsible for Harbour Summit. It has been reassigned to Bob Lim."
    )
    assert by_recipient[BOB] == "You have been assigned to Harbour Summit."
    assert by_recipient[ORGANISER] == (
        "Bob Lim has taken over Harbour Summit from Alice Tan as the Event Coordinator "
        "responsible for it."
    )
    assert all(n.event_request_id == event_id for n in fresh)


# QA-SPL-134-039 | AC5 | BB: refused or repeated actions add nothing
def test_qa_spl_134_039_retries_and_refusals_add_no_notices(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200
    settled = len(notices(app))

    for _ in range(3):
        assert assign(client, event_id, ALICE).status_code == 409
        assert reassign(client, event_id, BOB).status_code == 400  # already Bob
    assert reassign(client, event_id, INACTIVE_COORDINATOR).status_code == 400
    assert reassign(client, event_id, ALICE, token="coordinator").status_code == 403

    assert len(notices(app)) == settled == 5


# QA-SPL-134-040 | AC5 | BB: each distinct change is its own notice, never merged or lost
def test_qa_spl_134_040_back_and_forth_reassignments_each_notify_once(app, client):
    event_id = add_request(app, "Harbour Summit")
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200
    assert reassign(client, event_id, ALICE).status_code == 200

    # Alice: assigned, removed, assigned again. Bob: assigned, removed. Organiser: three changes.
    assert len(notices(app, ALICE)) == 3
    assert len(notices(app, BOB)) == 2
    assert len(notices(app, ORGANISER)) == 3
    keys = [n.dedupe_key for n in notices(app)]
    assert len(keys) == len(set(keys))


# QA-SPL-134-041 | AC5 | BB negative: a refused assignment leaves no notice at all
@pytest.mark.parametrize("status", CLOSED_STATUSES + ["under_review"])
def test_qa_spl_134_041_assignment_of_a_non_submitted_event_notifies_nobody(app, client, status):
    event_id = add_request(app, status=status)

    assert assign(client, event_id, ALICE).status_code == 409

    assert notices(app) == []


# QA-SPL-134-042 | AC5 | WB: the same change cannot be notified twice at the database
def test_qa_spl_134_042_the_database_rejects_a_duplicate_notice_for_one_change(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        alice = session.get(Account, ALICE)
        history_id = session.scalar(select(EventCoordinatorHistory.id))
        notification_module.add_assignment_change_notices(
            session,
            event,
            history_id=history_id,
            new_coordinator=alice,
            previous_coordinator=None,
            already_notified={ALICE},
        )
        with pytest.raises(IntegrityError):
            session.commit()


# QA-SPL-134-043 | AC5 | WB: notices commit or roll back with the reassignment
def test_qa_spl_134_043_a_failed_notice_rolls_the_reassignment_back(app, client, monkeypatch):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    base = len(notices(app))

    def explode(*args, **kwargs):
        raise RuntimeError("notice store unavailable")

    monkeypatch.setattr(coordinator_assignment, "add_assignment_change_notices", explode)

    with pytest.raises(RuntimeError):
        reassign(client, event_id, BOB)

    assert stored_coordinator(app, event_id) == ALICE
    assert history_count(app, event_id) == 1
    assert len(notices(app)) == base


# QA-SPL-134-044 | AC5 | WB: notices commit or roll back with the assignment
def test_qa_spl_134_044_a_failed_notice_rolls_the_assignment_back(app, client, monkeypatch):
    event_id = add_request(app)

    def explode(*args, **kwargs):
        raise RuntimeError("notice store unavailable")

    monkeypatch.setattr(coordinator_assignment, "add_assignment_change_notices", explode)

    with pytest.raises(RuntimeError):
        assign(client, event_id, ALICE)

    assert stored_coordinator(app, event_id) is None
    assert history_count(app, event_id) == 0
    assert notices(app) == []


# QA-SPL-134-045 | AC5 | BB boundary: one person in two parts is notified once
def test_qa_spl_134_045_an_organiser_who_is_the_new_coordinator_gets_one_notice(app, client):
    event_id = add_request_for(app, ALICE, "Alice's own event")

    assert assign(client, event_id, ALICE).status_code == 201

    assert messages(app, ALICE, event_id) == ["You have been assigned to Alice's own event."]


# QA-SPL-134-046 | AC5 | BB boundary: an organiser who is the former coordinator gets one notice
def test_qa_spl_134_046_an_organiser_who_is_the_former_coordinator_gets_one_notice(app, client):
    event_id = add_request_for(app, ALICE, "Alice's own event")
    assert assign(client, event_id, ALICE).status_code == 201
    before = len(notices(app, ALICE))

    assert reassign(client, event_id, BOB).status_code == 200

    added = notices(app, ALICE)[before:]
    assert [n.message for n in added] == [
        "You are no longer responsible for Alice's own event. It has been reassigned to Bob Lim."
    ]


# QA-SPL-134-047 | AC5 | BB: recipients read their notices in their own inbox, others cannot
def test_qa_spl_134_047_each_recipient_sees_their_notice_in_their_inbox(app, client):
    event_id = add_request(app, "Harbour Summit")
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200

    def inbox(token):
        return client.get("/api/notifications", headers=headers(token)).get_json()

    organiser = inbox("organiser")
    assert organiser["unread_count"] == 2
    assert [n["event"]["name"] for n in organiser["notifications"]] == ["Harbour Summit"] * 2
    assert organiser["notifications"][0]["message"].startswith("Bob Lim has taken over")
    assert inbox("coordinator")["unread_count"] == 2
    assert inbox("coordinator-b")["unread_count"] == 1
    assert inbox("manager")["notifications"] == []
    assert inbox("venue-staff")["notifications"] == []
    # The old coordinator can still read why, but is refused the event itself.
    assert (
        client.get(
            f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
        ).status_code
        == 404
    )


# QA-SPL-134-053 | AC5 | BB (review finding): each notice links to a page its recipient can open
def test_qa_spl_134_053_each_notice_links_to_the_recipients_own_event_page(app, client):
    event_id = add_request(app, "Harbour Summit")
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200

    def links(token):
        body = client.get("/api/notifications", headers=headers(token)).get_json()
        return [n["link"] for n in body["notifications"]]

    # The organiser has no coordinator page, so both of their notices open the organisation page.
    assert links("organiser") == [f"/workspace/organisation-events/{event_id}"] * 2
    assert links("coordinator-b") == [f"/workspace/assigned-events/{event_id}"]
    assert links("coordinator") == [f"/workspace/assigned-events/{event_id}"] * 2


# QA-SPL-134-048 | AC5 | BB boundary: awkward event names stay intact in every notice
@pytest.mark.parametrize(
    "name",
    ['Ünïcødé Gala 2026 — "Quoted" & <b>Bold</b>', "X" * 200, "  spaced  name  "],
)
def test_qa_spl_134_048_notices_carry_the_event_name_verbatim(app, client, name):
    event_id = add_request(app, name)
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200

    assert len(notices(app, event_id=event_id)) == 5
    assert all(name in n.message for n in notices(app, event_id=event_id))


# QA-SPL-134-049 | AC5 | BB: notice times are Singapore time and ordered by the change
def test_qa_spl_134_049_notices_are_stamped_in_singapore_time(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    payload = client.get("/api/notifications", headers=headers("organiser")).get_json()
    stamp = payload["notifications"][0]["created_at"]

    assert stamp.endswith("+08:00")
    assert abs(datetime.fromisoformat(stamp) - datetime.now(SINGAPORE)) < timedelta(minutes=2)


# QA-SPL-134-050 | AC5 | WB: helper stores one row per recipient with a change-specific key
def test_qa_spl_134_050_the_helper_keys_each_notice_to_its_history_row(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200

    with Session(app.extensions["engine"]) as session:
        history_ids = session.scalars(
            select(EventCoordinatorHistory.id).order_by(EventCoordinatorHistory.id)
        ).all()
    keys = {(n.recipient_account_id, n.dedupe_key) for n in notices(app)}

    first, second = history_ids
    assert keys == {
        (ALICE, f"coordinator_assigned:{first}"),
        (ORGANISER, f"organiser_coordinator_changed:{first}"),
        (BOB, f"coordinator_assigned:{second}"),
        (ALICE, f"coordinator_removed:{second}"),
        (ORGANISER, f"organiser_coordinator_changed:{second}"),
    }


# QA-SPL-134-051 | Regression | BB: the queue payload and ordering are unchanged
def test_qa_spl_134_051_the_unassigned_queue_payload_is_unchanged(app, client):
    event_id = add_request(app)

    event = queue(client).json["events"][0]

    assert set(event) == {
        "id",
        "name",
        "organisation_id",
        "organisation_name",
        "proposed_date",
        "submitted_at",
    }
    assert event["id"] == event_id


# QA-SPL-134-052 | AC1 | BB negative: a body that is not a JSON object is refused
@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b""])
def test_qa_spl_134_052_a_malformed_assignment_body_is_refused(app, client, body):
    event_id = add_request(app)

    for method in (client.post, client.put):
        response = method(
            f"/api/event-requests/{event_id}/coordinator",
            data=body,
            headers={**headers(), "Content-Type": "application/json"},
        )
        assert response.status_code == 400

    assert stored_coordinator(app, event_id) is None
    assert notices(app) == []


# keep the token table referenced so a renamed fixture fails loudly here
assert {"manager", "organiser", "coordinator", "coordinator-b", "venue-staff"} <= set(TOKENS)
