"""Acceptance coverage for CS-E06-S6 / SPL-69 record event-request withdrawal."""

from datetime import date, datetime, time

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Organisation,
    Role,
    VenueBooking,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

MANAGER = "00000000-0000-0000-0000-000000000091"
ORGANISER = "00000000-0000-0000-0000-000000000092"
OTHER_ORGANISER = "00000000-0000-0000-0000-000000000093"
ALICE = "00000000-0000-0000-0000-000000000094"
BOB = "00000000-0000-0000-0000-000000000095"
TOKENS = {
    "manager": MANAGER,
    "organiser": ORGANISER,
    "other-organiser": OTHER_ORGANISER,
    "alice": ALICE,
    "bob": BOB,
}


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/withdrawal.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        other = Organisation(name="Unrelated Client")
        session.add_all([organisation, other])
        session.flush()
        for account_id, name, role, organisation_id in (
            (MANAGER, "Morgan Manager", Role.EVENT_OPERATIONS_MANAGER, None),
            (ORGANISER, "Olivia Organiser", Role.EVENT_ORGANISER, organisation.id),
            (OTHER_ORGANISER, "Oscar Organiser", Role.EVENT_ORGANISER, other.id),
            (ALICE, "Alice Tan", Role.EVENT_COORDINATOR, None),
            (BOB, "Bob Lim", Role.EVENT_COORDINATOR, None),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    is_active=True,
                    organisation_id=organisation_id,
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
        application.config["TEST_ORGANISATION_ID"] = organisation.id
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token: str = "alice"):
    return {"Authorization": f"Bearer {token}"}


def assigned_request(app, *, status="under_review") -> int:
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["TEST_ORGANISATION_ID"],
            name="Community Forum",
            purpose="Community consultation",
            proposed_date=date(2026, 10, 12),
            start_time=time(9),
            end_time=time(12),
            expected_attendance=120,
            status=status,
            submitted_at=datetime(2026, 9, 20, 9, tzinfo=SINGAPORE),
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=ALICE,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 21, 9, tzinfo=SINGAPORE),
            )
        )
        session.commit()
        return event.id


def withdraw(client, event_id: int, body=None, token="alice"):
    return client.post(
        f"/api/event-requests/{event_id}/withdraw",
        headers=headers(token),
        json={} if body is None else body,
    )


def stored(app, event_id: int):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        audit = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        assignment = session.get(EventCoordinatorAssignment, event_id)
        return (
            event.status,
            event.withdrawn_by_account_id,
            event.withdrawn_at,
            event.withdrawal_note,
            assignment.coordinator_account_id,
            audit,
        )


def assert_unchanged(app, event_id: int, status: str):
    current, actor, changed_at, note, coordinator, audit = stored(app, event_id)
    assert (current, actor, changed_at, note, coordinator, audit) == (
        status,
        None,
        None,
        None,
        ALICE,
        [],
    )


# TC-SPL-69-01: AC 1, 3.
@pytest.mark.parametrize("status", ["submitted", "under_review", "returned_for_clarification"])
def test_tc_spl_69_01_assigned_coordinator_records_withdrawal_from_allowed_states(
    app, client, status
):
    event_id = assigned_request(app, status=status)

    response = withdraw(client, event_id, {"note": "  Organiser withdrew by email.  "})

    assert response.status_code == 200
    event = response.json["event"]
    assert (event["status"], event["status_label"]) == ("withdrawn", "Withdrawn")
    assert event["withdrawn_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert event["withdrawn_at"]
    assert event["withdrawal_note"] == "Organiser withdrew by email."
    transition = response.json["transition"]
    assert (
        transition["action"],
        transition["previous_status"],
        transition["resulting_status"],
    ) == (
        "withdraw",
        status,
        "withdrawn",
    )
    stored_status, actor, changed_at, note, coordinator, audit = stored(app, event_id)
    assert (stored_status, actor, note, coordinator) == (
        "withdrawn",
        ALICE,
        "Organiser withdrew by email.",
        ALICE,
    )
    assert changed_at is not None
    assert [(row.action, row.previous_status, row.resulting_status) for row in audit] == [
        ("withdraw", status, "withdrawn")
    ]


# TC-SPL-69-02: AC 2.
@pytest.mark.parametrize("body", [None, {}, {"note": None}, {"note": ""}, {"note": "   "}])
def test_tc_spl_69_02_the_note_is_optional(app, client, body):
    event_id = assigned_request(app)

    response = withdraw(client, event_id, body)

    assert response.status_code == 200
    assert response.json["event"]["withdrawal_note"] is None


# TC-SPL-69-03: AC 6.
@pytest.mark.parametrize("token", ["organiser", "manager", "other-organiser"])
def test_tc_spl_69_03_other_roles_are_refused_without_change(app, client, token):
    event_id = assigned_request(app)
    before = event_snapshot(app, event_id)
    assert withdraw(client, event_id, {"note": "No longer needed"}, token).status_code == 403
    assert event_snapshot(app, event_id) == before
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-69-04: AC 6.
def test_tc_spl_69_04_unassigned_coordinator_gets_not_found_without_change(app, client):
    event_id = assigned_request(app)
    before = event_snapshot(app, event_id)
    response = withdraw(client, event_id, {"note": "No longer needed"}, "bob")
    assert event_snapshot(app, event_id) == before
    assert response.status_code == 404
    assert response.json["error"] == "Assigned event not found."
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-69-05: AC 1, 4, 6.
@pytest.mark.parametrize("status", ["draft", "planning", "rejected", "withdrawn", "cancelled"])
def test_tc_spl_69_05_invalid_status_is_refused_without_change(app, client, status):
    event_id = assigned_request(app, status=status)
    response = withdraw(client, event_id, {"note": "No longer needed"})
    assert response.status_code == 409
    assert response.json["error"] == (
        "Only a Submitted, Under Review, or Returned for Clarification event can be withdrawn."
    )
    assert_unchanged(app, event_id, status)


# TC-SPL-69-06: AC 6.
@pytest.mark.parametrize(
    "body",
    [
        {"status": "withdrawn"},
        {"note": "Valid", "status": "withdrawn"},
        {"note": "Valid", "withdrawn_by_account_id": BOB},
        {"note": "Valid", "withdrawn_at": "2026-01-01T00:00:00+08:00"},
        {"note": 5},
        {"note": ["text"]},
        [],
    ],
)
def test_tc_spl_69_06_invalid_body_is_refused_without_change(app, client, body):
    event_id = assigned_request(app)
    before = event_snapshot(app, event_id)
    assert withdraw(client, event_id, body).status_code == 400
    assert event_snapshot(app, event_id) == before
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-69-07: AC 2, 6.
def test_tc_spl_69_07_note_length_boundary(app, client):
    over = assigned_request(app)
    assert withdraw(client, over, {"note": "x" * 2001}).status_code == 400
    assert_unchanged(app, over, "under_review")
    at_limit = assigned_request(app)
    assert withdraw(client, at_limit, {"note": "x" * 2000}).status_code == 200


# TC-SPL-69-08: AC 4.
def test_tc_spl_69_08_withdrawn_request_remains_retrievable_by_responsible_users(app, client):
    event_id = assigned_request(app)
    withdraw(client, event_id, {"note": "Organiser confirmed by phone."})

    organiser = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))
    coordinator = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers("alice"))

    assert organiser.status_code == coordinator.status_code == 200
    assert organiser.json["event_request"]["withdrawal_note"] == "Organiser confirmed by phone."
    assert coordinator.json["event"]["withdrawn_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert (
        client.get(
            f"/api/event-requests/{event_id}", headers=headers("other-organiser")
        ).status_code
        == 404
    )


# TC-SPL-69-09: AC 4.
def test_tc_spl_69_09_withdrawn_request_cannot_continue_review_or_planning(app, client):
    event_id = assigned_request(app)
    withdraw(client, event_id)
    base = f"/api/event-requests/{event_id}"
    for action, body in (
        ("begin-review", None),
        ("approve", None),
        ("request-clarification", {"message": "More detail please."}),
        ("reject", {"reason": "No."}),
        ("withdraw", {}),
    ):
        response = client.post(f"{base}/{action}", headers=headers("alice"), json=body)
        assert response.status_code == 409, action
    assert stored(app, event_id)[0] == "withdrawn"
    with Session(app.extensions["engine"]) as session:
        assert session.scalars(select(VenueBooking)).all() == []


# TC-SPL-69-10: AC 3, 6.
def test_tc_spl_69_10_database_refuses_partial_withdrawal_evidence(app):
    event_id = assigned_request(app)
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).withdrawal_note = "No actor or timestamp"
        with pytest.raises(IntegrityError):
            session.commit()


def event_snapshot(app, event_id):
    """Read persisted fields and audits so refused actions cannot hide unrelated mutations."""
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assignment = session.get(EventCoordinatorAssignment, event_id)
        return (
            {column.name: getattr(event, column.name) for column in EventRequest.__table__.columns},
            {
                column.name: getattr(assignment, column.name)
                for column in EventCoordinatorAssignment.__table__.columns
            },
            [
                {
                    column.name: getattr(row, column.name)
                    for column in EventStatusHistory.__table__.columns
                }
                for row in session.scalars(
                    select(EventStatusHistory)
                    .where(EventStatusHistory.event_request_id == event_id)
                    .order_by(EventStatusHistory.id)
                )
            ],
        )


# TC-SPL-69-15: AC 5 — real withdrawal and rejection retain different outcomes and evidence.
def test_tc_spl_69_15_withdrawal_is_distinct_from_rejection(app, client):
    withdrawn_id = assigned_request(app)
    rejected_id = assigned_request(app)

    assert (
        withdraw(client, withdrawn_id, {"note": "Organiser no longer needs the event."}).status_code
        == 200
    )
    rejected = client.post(
        f"/api/event-requests/{rejected_id}/reject",
        headers=headers(),
        json={"reason": "The request cannot be supported."},
    )
    assert rejected.status_code == 200

    withdrawn = client.get(f"/api/event-requests/assigned/{withdrawn_id}", headers=headers())
    rejected = client.get(f"/api/event-requests/assigned/{rejected_id}", headers=headers())
    assert withdrawn.status_code == rejected.status_code == 200
    assert (withdrawn.json["event"]["status"], withdrawn.json["event"]["status_label"]) == (
        "withdrawn",
        "Withdrawn",
    )
    assert (rejected.json["event"]["status"], rejected.json["event"]["status_label"]) == (
        "rejected",
        "Not approved",
    )
    withdrawn_fields, _, withdrawal_audit = event_snapshot(app, withdrawn_id)
    rejected_fields, _, rejection_audit = event_snapshot(app, rejected_id)
    assert withdrawn_fields["withdrawn_by_account_id"] == ALICE
    assert withdrawn_fields["withdrawn_at"] is not None
    assert withdrawn_fields["rejected_by_account_id"] is None
    assert withdrawn_fields["rejected_at"] is None
    assert withdrawn_fields["rejection_reason"] is None
    assert rejected_fields["rejected_by_account_id"] == ALICE
    assert rejected_fields["rejected_at"] is not None
    assert rejected_fields["withdrawn_by_account_id"] is None
    assert rejected_fields["withdrawn_at"] is None
    assert rejected_fields["withdrawal_note"] is None
    assert [row["action"] for row in withdrawal_audit] == ["withdraw"]
    assert [row["action"] for row in rejection_audit] == ["reject"]


# TC-SPL-69-16: AC 5 — an existing Cancelled outcome cannot be relabelled as Withdrawn.
def test_tc_spl_69_16_withdrawal_is_distinct_from_event_cancellation(app, client):
    # Cancellation is outside SPL-69: seed its outcome rather than inventing a cancellation API.
    cancelled_id = assigned_request(app, status="cancelled")
    withdrawn_id = assigned_request(app)
    cancelled_before = event_snapshot(app, cancelled_id)
    assert withdraw(client, withdrawn_id).status_code == 200
    assert withdraw(client, cancelled_id).status_code == 409

    cancelled = client.get(f"/api/event-requests/{cancelled_id}", headers=headers("organiser"))
    withdrawn = client.get(f"/api/event-requests/{withdrawn_id}", headers=headers("organiser"))
    assert cancelled.status_code == withdrawn.status_code == 200
    assert (
        cancelled.json["event_request"]["status"],
        cancelled.json["event_request"]["status_label"],
    ) == ("cancelled", "Cancelled")
    assert (
        withdrawn.json["event_request"]["status"],
        withdrawn.json["event_request"]["status_label"],
    ) == ("withdrawn", "Withdrawn")
    assert event_snapshot(app, cancelled_id) == cancelled_before
    assert cancelled.json["event_request"]["withdrawn_by"] is None
    assert cancelled.json["event_request"]["withdrawn_at"] is None
    assert withdrawn.json["event_request"]["withdrawn_by"]["id"] == ALICE


# TC-SPL-69-17: AC 1 — reassignment transfers withdrawal permission to the current coordinator.
def test_tc_spl_69_17_only_reassigned_coordinator_can_record_withdrawal(app, client):
    event_id = assigned_request(app)
    with Session(app.extensions["engine"]) as session:
        session.get(EventCoordinatorAssignment, event_id).coordinator_account_id = BOB
        session.commit()
    before = event_snapshot(app, event_id)

    assert withdraw(client, event_id, token="alice").status_code == 404
    assert event_snapshot(app, event_id) == before
    response = withdraw(client, event_id, token="bob")

    assert response.status_code == 200
    assert response.json["event"]["withdrawn_by"] == {"id": BOB, "name": "Bob Lim"}
    fields, assignment, _ = event_snapshot(app, event_id)
    assert fields["status"] == "withdrawn"
    assert fields["withdrawn_by_account_id"] == BOB
    assert assignment == before[1]


# TC-SPL-69-18: AC 3 — actor and server time remain consistent across storage, reads and audit.
def test_tc_spl_69_18_withdrawal_actor_and_timestamp_are_persisted_consistently(app, client):
    event_id = assigned_request(app)
    before = datetime.now(SINGAPORE)
    response = withdraw(client, event_id)
    after = datetime.now(SINGAPORE)
    assert response.status_code == 200
    recorded = response.json["event"]
    assert before <= datetime.fromisoformat(recorded["withdrawn_at"]) <= after

    for path, token, key in (
        (f"/api/event-requests/{event_id}", "organiser", "event_request"),
        (f"/api/event-requests/assigned/{event_id}", "alice", "event"),
    ):
        retrieved = client.get(path, headers=headers(token))
        assert retrieved.status_code == 200
        assert retrieved.json[key]["status"] == "withdrawn"
        assert retrieved.json[key]["withdrawn_at"] == recorded["withdrawn_at"]
        assert retrieved.json[key]["withdrawn_by"] == {"id": ALICE, "name": "Alice Tan"}
    fields, _, audits = event_snapshot(app, event_id)
    [audit] = audits
    assert fields["withdrawn_at"] == fields["status_changed_at"] == audit["changed_at"]
    assert fields["withdrawn_by_account_id"] == audit["actor_account_id"] == ALICE
    assert audit["resulting_status"] == "withdrawn"


# TC-SPL-69-19: AC 2 — a supplied note is retained, including meaningful internal newlines.
def test_tc_spl_69_19_supplied_note_is_trimmed_and_retained(app, client):
    event_id = assigned_request(app)
    note = "Organiser withdrew by email.\nNo replacement date requested."

    response = withdraw(client, event_id, {"note": f"  {note}  "})

    assert response.status_code == 200
    assert response.json["event"]["withdrawal_note"] == note
    assert stored(app, event_id)[3] == note
    retrieved = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))
    assert retrieved.status_code == 200
    assert retrieved.json["event_request"]["withdrawal_note"] == note
