"""Acceptance coverage for CS-E06-S3 / SPL-66 respond to clarification."""

from datetime import date, datetime, time

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    ClarificationRequest,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Organisation,
    Role,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

MANAGER = "00000000-0000-0000-0000-000000000091"
ORGANISER = "00000000-0000-0000-0000-000000000092"
OTHER_ORGANISER = "00000000-0000-0000-0000-000000000093"
COORDINATOR = "00000000-0000-0000-0000-000000000094"
TOKENS = {
    "manager": MANAGER,
    "organiser": ORGANISER,
    "other": OTHER_ORGANISER,
    "coordinator": COORDINATOR,
}


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/clarification-response.db",
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
            (OTHER_ORGANISER, "Oscar Organiser", Role.EVENT_ORGANISER),
            (COORDINATOR, "Alice Tan", Role.EVENT_COORDINATOR),
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


def headers(token="organiser"):
    return {"Authorization": f"Bearer {token}"}


def clarification_event(app, *, status="returned_for_clarification"):
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
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 21, 9, tzinfo=SINGAPORE),
            )
        )
        clarification = ClarificationRequest(
            event_request_id=event.id,
            message="Please confirm the revised attendance estimate.",
            author_account_id=COORDINATOR,
            created_at=datetime(2026, 9, 28, 10, tzinfo=SINGAPORE),
        )
        session.add(clarification)
        session.commit()
        return event.id, clarification.id


def respond(client, event_id, clarification_id, token="organiser", body=None):
    return client.post(
        f"/api/event-requests/{event_id}/clarifications/{clarification_id}/respond",
        headers=headers(token),
        json={"response": "Attendance remains 120 people."} if body is None else body,
    )


def stored(app, event_id, clarification_id):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        clarification = session.get(ClarificationRequest, clarification_id)
        audits = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        assignment = session.scalar(
            select(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event_id
            )
        )
        return (
            event.status,
            clarification.response,
            clarification.respondent_account_id,
            clarification.responded_at,
            audits,
            assignment.coordinator_account_id,
        )


# TC-SPL-66-01: AC 1, 2, 3 and 4.
def test_tc_spl_66_01_creator_responds_and_review_resumes_without_editing_request(app, client):
    event_id, clarification_id = clarification_event(app)

    response = respond(
        client, event_id, clarification_id, body={"response": "  Attendance remains 120 people.  "}
    )

    assert response.status_code == 200
    assert response.json["event"]["status"] == "under_review"
    assert response.json["transition"]["action"] == "respond_clarification"
    assert response.json["transition"]["previous_status"] == "returned_for_clarification"
    [answer] = response.json["clarifications"]
    assert answer["message"] == "Please confirm the revised attendance estimate."
    assert answer["response"] == "Attendance remains 120 people."
    assert answer["respondent"] == {"id": ORGANISER, "name": "Olivia Organiser"}
    assert answer["responded_at"]
    status, text, respondent, responded_at, audits, coordinator = stored(
        app, event_id, clarification_id
    )
    assert (status, text, respondent, coordinator) == (
        "under_review",
        "Attendance remains 120 people.",
        ORGANISER,
        COORDINATOR,
    )
    assert responded_at is not None
    assert [(row.action, row.previous_status, row.resulting_status) for row in audits] == [
        ("respond_clarification", "returned_for_clarification", "under_review")
    ]
    own = client.get(f"/api/event-requests/{event_id}", headers=headers())
    assert own.json["event_request"]["expected_attendance"] == 120
    assert (
        own.json["event_request"]["clarifications"][0]["response"]
        == "Attendance remains 120 people."
    )


# TC-SPL-66-02: AC 5.
@pytest.mark.parametrize("token", ["other", "coordinator", "manager"])
def test_tc_spl_66_02_unrelated_accounts_are_refused_without_changes(app, client, token):
    event_id, clarification_id = clarification_event(app)

    response = respond(client, event_id, clarification_id, token=token)

    assert response.status_code in (403, 404)
    status, text, respondent, responded_at, audits, coordinator = stored(
        app, event_id, clarification_id
    )
    assert (status, text, respondent, responded_at, audits, coordinator) == (
        "returned_for_clarification",
        None,
        None,
        None,
        [],
        COORDINATOR,
    )


# TC-SPL-66-03: AC 5.
@pytest.mark.parametrize("status", ["submitted", "under_review", "planning", "rejected"])
def test_tc_spl_66_03_invalid_event_status_is_refused_without_changes(app, client, status):
    event_id, clarification_id = clarification_event(app, status=status)

    assert respond(client, event_id, clarification_id).status_code == 409
    assert stored(app, event_id, clarification_id)[:5] == (status, None, None, None, [])


# TC-SPL-66-04: AC 1 and 5.
@pytest.mark.parametrize(
    "body",
    [
        {"response": ""},
        {"response": "   "},
        {"response": 7},
        {},
        {"response": "ok", "status": "approved"},
    ],
)
def test_tc_spl_66_04_invalid_response_is_refused_without_changes(app, client, body):
    event_id, clarification_id = clarification_event(app)

    assert respond(client, event_id, clarification_id, body=body).status_code == 400
    assert stored(app, event_id, clarification_id)[:5] == (
        "returned_for_clarification",
        None,
        None,
        None,
        [],
    )


# TC-SPL-66-05: AC 1 and 5.
def test_tc_spl_66_05_answered_clarification_cannot_be_answered_twice(app, client):
    event_id, clarification_id = clarification_event(app)
    assert respond(client, event_id, clarification_id).status_code == 200

    assert respond(client, event_id, clarification_id).status_code == 409
    assert stored(app, event_id, clarification_id)[1] == "Attendance remains 120 people."
