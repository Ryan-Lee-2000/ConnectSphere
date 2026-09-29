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


# TC-SPL-69-01
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


# TC-SPL-69-02
@pytest.mark.parametrize("body", [None, {}, {"note": None}, {"note": ""}, {"note": "   "}])
def test_tc_spl_69_02_the_note_is_optional(app, client, body):
    event_id = assigned_request(app)

    response = withdraw(client, event_id, body)

    assert response.status_code == 200
    assert response.json["event"]["withdrawal_note"] is None


# TC-SPL-69-03
@pytest.mark.parametrize("token", ["organiser", "manager", "other-organiser"])
def test_tc_spl_69_03_other_roles_are_refused_without_change(app, client, token):
    event_id = assigned_request(app)
    assert withdraw(client, event_id, {"note": "No longer needed"}, token).status_code == 403
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-69-04
def test_tc_spl_69_04_unassigned_coordinator_gets_not_found_without_change(app, client):
    event_id = assigned_request(app)
    response = withdraw(client, event_id, {"note": "No longer needed"}, "bob")
    assert response.status_code == 404
    assert response.json["error"] == "Assigned event not found."
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-69-05
@pytest.mark.parametrize("status", ["draft", "planning", "rejected", "withdrawn", "cancelled"])
def test_tc_spl_69_05_invalid_status_is_refused_without_change(app, client, status):
    event_id = assigned_request(app, status=status)
    response = withdraw(client, event_id, {"note": "No longer needed"})
    assert response.status_code == 409
    assert response.json["error"] == (
        "Only a Submitted, Under Review, or Returned for Clarification event can be withdrawn."
    )
    assert_unchanged(app, event_id, status)


# TC-SPL-69-06
@pytest.mark.parametrize(
    "body",
    [
        {"status": "withdrawn"},
        {"note": "Valid", "status": "withdrawn"},
        {"note": 5},
        {"note": ["text"]},
        [],
    ],
)
def test_tc_spl_69_06_invalid_body_is_refused_without_change(app, client, body):
    event_id = assigned_request(app)
    assert withdraw(client, event_id, body).status_code == 400
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-69-07
def test_tc_spl_69_07_note_length_boundary(app, client):
    over = assigned_request(app)
    assert withdraw(client, over, {"note": "x" * 2001}).status_code == 400
    assert_unchanged(app, over, "under_review")
    at_limit = assigned_request(app)
    assert withdraw(client, at_limit, {"note": "x" * 2000}).status_code == 200


# TC-SPL-69-08
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


# TC-SPL-69-09
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


# TC-SPL-69-10
def test_tc_spl_69_10_database_refuses_partial_withdrawal_evidence(app):
    event_id = assigned_request(app)
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).withdrawal_note = "No actor or timestamp"
        with pytest.raises(IntegrityError):
            session.commit()
