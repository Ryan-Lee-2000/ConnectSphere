"""Acceptance coverage for CS-E07-S2 / SPL-70 begin-review transition."""

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
)
from sqlalchemy import select
from sqlalchemy.orm import Session

MANAGER = "00000000-0000-0000-0000-000000000071"
ORGANISER = "00000000-0000-0000-0000-000000000072"
ALICE = "00000000-0000-0000-0000-000000000073"
BOB = "00000000-0000-0000-0000-000000000074"
TOKENS = {
    "manager": MANAGER,
    "organiser": ORGANISER,
    "alice": ALICE,
    "bob": BOB,
}


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/begin-review.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        session.add(organisation)
        session.flush()
        accounts = (
            (MANAGER, "Morgan Manager", Role.EVENT_OPERATIONS_MANAGER),
            (ORGANISER, "Olivia Organiser", Role.EVENT_ORGANISER),
            (ALICE, "Alice Tan", Role.EVENT_COORDINATOR),
            (BOB, "Bob Lim", Role.EVENT_COORDINATOR),
        )
        for account_id, name, role in accounts:
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


def assigned_request(app, *, coordinator=ALICE, status="submitted") -> int:
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
                coordinator_account_id=coordinator,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 21, 9, tzinfo=SINGAPORE),
            )
        )
        session.commit()
        return event.id


def begin_review(client, event_id: int, token="alice", **kwargs):
    return client.post(
        f"/api/event-requests/{event_id}/begin-review",
        headers=headers(token),
        **kwargs,
    )


def stored_status(app, event_id: int):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        return event.status, event.status_changed_at


def audit_rows(app, event_id: int):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()


def test_assigned_coordinator_begins_review_and_records_audit_evidence(app, client):
    event_id = assigned_request(app)

    response = begin_review(client, event_id)

    assert response.status_code == 200
    assert response.json["event"] == {
        "id": event_id,
        "name": "Community Forum",
        "status": "under_review",
        "status_label": "Under review",
        "proposed_date": "2026-10-12",
    }
    assert response.json["transition"]["action"] == "begin_review"
    assert response.json["transition"]["previous_status"] == "submitted"
    assert response.json["transition"]["resulting_status"] == "under_review"
    assert response.json["transition"]["actor"] == {"id": ALICE, "name": "Alice Tan"}
    assert response.json["transition"]["changed_at"]
    status, changed_at = stored_status(app, event_id)
    assert status == "under_review"
    assert changed_at is not None
    rows = audit_rows(app, event_id)
    assert len(rows) == 1
    assert rows[0].action == "begin_review"
    assert rows[0].previous_status == "submitted"
    assert rows[0].resulting_status == "under_review"
    assert rows[0].actor_account_id == ALICE
    assert rows[0].changed_at is not None


@pytest.mark.parametrize("token", ["manager", "organiser"])
def test_non_coordinator_role_is_refused_without_changing_event(app, client, token):
    event_id = assigned_request(app)

    response = begin_review(client, event_id, token)

    assert response.status_code == 403
    assert stored_status(app, event_id)[0] == "submitted"
    assert audit_rows(app, event_id) == []


def test_unassigned_coordinator_is_refused_without_changing_event(app, client):
    event_id = assigned_request(app)

    response = begin_review(client, event_id, "bob")

    assert response.status_code == 404
    assert stored_status(app, event_id)[0] == "submitted"
    assert audit_rows(app, event_id) == []


def test_event_not_in_submitted_is_refused_without_a_second_transition(app, client):
    event_id = assigned_request(app, status="under_review")

    response = begin_review(client, event_id)

    assert response.status_code == 409
    assert stored_status(app, event_id)[0] == "under_review"
    assert audit_rows(app, event_id) == []


def test_client_cannot_supply_an_arbitrary_target_status(app, client):
    event_id = assigned_request(app)

    response = begin_review(client, event_id, json={"status": "approved"})

    assert response.status_code == 400
    assert stored_status(app, event_id)[0] == "submitted"
    assert audit_rows(app, event_id) == []


def test_repeating_begin_review_is_refused_and_keeps_one_audit_record(app, client):
    event_id = assigned_request(app)
    assert begin_review(client, event_id).status_code == 200

    response = begin_review(client, event_id)

    assert response.status_code == 409
    assert stored_status(app, event_id)[0] == "under_review"
    assert len(audit_rows(app, event_id)) == 1
