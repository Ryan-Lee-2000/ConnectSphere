"""Acceptance coverage for CS-E06-S4 / SPL-67 approve an event request."""

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
from sqlalchemy.orm import Session

MANAGER = "00000000-0000-0000-0000-000000000081"
ORGANISER = "00000000-0000-0000-0000-000000000082"
ALICE = "00000000-0000-0000-0000-000000000083"
BOB = "00000000-0000-0000-0000-000000000084"
TOKENS = {"manager": MANAGER, "organiser": ORGANISER, "alice": ALICE, "bob": BOB}


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/approval.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (MANAGER, "Morgan Manager", Role.EVENT_OPERATIONS_MANAGER),
            (ORGANISER, "Olivia Organiser", Role.EVENT_ORGANISER),
            (ALICE, "Alice Tan", Role.EVENT_COORDINATOR),
            (BOB, "Bob Lim", Role.EVENT_COORDINATOR),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    is_active=True,
                    organisation_id=organisation.id,
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


def approve(client, event_id: int, token="alice", **kwargs):
    return client.post(f"/api/event-requests/{event_id}/approve", headers=headers(token), **kwargs)


def stored(app, event_id: int):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        audit = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        return event.status, event.approved_by_account_id, event.approved_at, audit


def assert_unchanged(app, event_id: int, status: str):
    current, approver, approved_at, audit = stored(app, event_id)
    assert (current, approver, approved_at, audit) == (status, None, None, [])


# TC-SPL-67-01
# SPL-67 AC-1,3 Test-01
def test_tc_spl_67_01_assigned_coordinator_approves_and_the_decision_is_recorded(app, client):
    event_id = assigned_request(app)

    response = approve(client, event_id)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "planning"
    assert response.json["event"]["status_label"] == "In planning"
    assert response.json["message"] == "Request approved. Event planning can begin."
    assert response.json["event"]["approved_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert response.json["event"]["approved_at"]
    assert response.json["transition"]["action"] == "approve"
    assert response.json["transition"]["previous_status"] == "under_review"
    assert response.json["transition"]["resulting_status"] == "planning"
    status, approver, approved_at, audit = stored(app, event_id)
    assert (status, approver) == ("planning", ALICE)
    assert approved_at is not None
    assert [row.action for row in audit] == ["approve"]


# TC-SPL-67-02
# SPL-67 AC-1,6 Test-02
@pytest.mark.parametrize("token", ["organiser", "manager"])
def test_tc_spl_67_02_other_roles_are_refused_and_nothing_changes(app, client, token):
    event_id = assigned_request(app)

    assert approve(client, event_id, token).status_code == 403
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-67-03
# SPL-67 AC-1,6 Test-03
def test_tc_spl_67_03_an_unassigned_coordinator_gets_not_found_and_nothing_changes(app, client):
    event_id = assigned_request(app)

    response = approve(client, event_id, "bob")

    assert response.status_code == 404
    assert response.json["error"] == "Assigned event not found."
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-67-04
# SPL-67 AC-1,6 Test-04
@pytest.mark.parametrize(
    "status", ["submitted", "returned_for_clarification", "planning", "rejected"]
)
def test_tc_spl_67_04_only_an_event_under_review_can_be_approved(app, client, status):
    event_id = assigned_request(app, status=status)

    response = approve(client, event_id)

    assert response.status_code == 409
    assert response.json["error"] == "Only an event under review can be approved."
    assert_unchanged(app, event_id, status)


# TC-SPL-67-05
# SPL-67 AC-6 Test-05
@pytest.mark.parametrize("body", [{"status": "confirmed"}, {"a": 1}, [], "planning"])
def test_tc_spl_67_05_a_client_supplied_status_or_body_is_refused(app, client, body):
    event_id = assigned_request(app)

    response = approve(client, event_id, json=body)

    assert response.status_code == 400
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-67-06
# SPL-67 AC-6 Test-06
def test_tc_spl_67_06_approving_twice_keeps_one_decision(app, client):
    event_id = assigned_request(app)
    first = approve(client, event_id)

    second = approve(client, event_id)

    assert second.status_code == 409
    status, approver, approved_at, audit = stored(app, event_id)
    assert (status, approver, len(audit)) == ("planning", ALICE, 1)
    assert approved_at is not None
    assert first.json["event"]["approved_at"]


# TC-SPL-67-07
# SPL-67 AC-4 Test-07
def test_tc_spl_67_07_the_organiser_retrieves_the_outcome_and_others_cannot(app, client):
    event_id = assigned_request(app)
    before = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))
    assert before.json["event_request"]["approved_by"] is None
    assert before.json["event_request"]["approved_at"] is None
    approve(client, event_id)

    after = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))

    assert after.status_code == 200
    outcome = after.json["event_request"]
    assert outcome["status"] == "planning"
    assert outcome["approved_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert outcome["approved_at"]
    manager = client.get(f"/api/event-requests/{event_id}", headers=headers("manager"))
    assert manager.status_code == 403


# TC-SPL-67-08
# SPL-67 AC-3 Test-08
def test_tc_spl_67_08_the_coordinator_detail_shows_the_decision(app, client):
    event_id = assigned_request(app)
    approve(client, event_id)

    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers("alice"))

    assert detail.json["event"]["status"] == "planning"
    assert detail.json["event"]["approved_by"] == {"id": ALICE, "name": "Alice Tan"}


# TC-SPL-67-09
# SPL-67 AC-5 Test-09
def test_tc_spl_67_09_approval_books_nothing_and_leaves_the_request_details_alone(app, client):
    event_id = assigned_request(app)
    with Session(app.extensions["engine"]) as session:
        before = session.get(EventRequest, event_id)
        snapshot = (before.venue_id, before.registration_required, before.name, before.start_time)
        assert session.scalars(select(VenueBooking)).all() == []

    approve(client, event_id)

    with Session(app.extensions["engine"]) as session:
        after = session.get(EventRequest, event_id)
        current = (after.venue_id, after.registration_required, after.name, after.start_time)
        assert current == snapshot
        assert session.scalars(select(VenueBooking)).all() == []
        assert after.status not in ("confirmed", "approved")
