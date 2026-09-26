"""Acceptance coverage for CS-E06-S2 / SPL-65 request clarification."""

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

MANAGER = "00000000-0000-0000-0000-000000000081"
ORGANISER = "00000000-0000-0000-0000-000000000082"
ALICE = "00000000-0000-0000-0000-000000000083"
BOB = "00000000-0000-0000-0000-000000000084"
TOKENS = {"manager": MANAGER, "organiser": ORGANISER, "alice": ALICE, "bob": BOB}
MESSAGE = "Please confirm the expected attendance and the room layout."


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/clarification.db",
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


def ask(client, event_id: int, token="alice", body=None):
    return client.post(
        f"/api/event-requests/{event_id}/request-clarification",
        headers=headers(token),
        json={"message": MESSAGE} if body is None else body,
    )


def stored_status(app, event_id: int) -> str:
    with Session(app.extensions["engine"]) as session:
        return session.get(EventRequest, event_id).status


def stored_rows(app, event_id: int):
    with Session(app.extensions["engine"]) as session:
        clarifications = session.scalars(
            select(ClarificationRequest).where(ClarificationRequest.event_request_id == event_id)
        ).all()
        audit = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        return clarifications, audit


def assert_nothing_recorded(app, event_id: int, status: str):
    clarifications, audit = stored_rows(app, event_id)
    assert stored_status(app, event_id) == status
    assert clarifications == []
    assert audit == []


# TC-SPL-65-01
def test_tc_spl_65_01_assigned_coordinator_requests_clarification_and_it_is_recorded(app, client):
    event_id = assigned_request(app)

    response = ask(client, event_id)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "returned_for_clarification"
    assert response.json["event"]["status_label"] == "Returned for clarification"
    assert response.json["transition"]["action"] == "request_clarification"
    assert response.json["transition"]["previous_status"] == "under_review"
    assert response.json["transition"]["resulting_status"] == "returned_for_clarification"
    assert response.json["transition"]["actor"] == {"id": ALICE, "name": "Alice Tan"}
    [only] = response.json["clarifications"]
    assert only["message"] == MESSAGE
    assert only["author"] == {"id": ALICE, "name": "Alice Tan"}
    assert only["created_at"]
    assert stored_status(app, event_id) == "returned_for_clarification"
    clarifications, audit = stored_rows(app, event_id)
    assert [(row.message, row.author_account_id) for row in clarifications] == [(MESSAGE, ALICE)]
    assert clarifications[0].created_at is not None
    assert [(row.action, row.previous_status, row.resulting_status) for row in audit] == [
        ("request_clarification", "under_review", "returned_for_clarification")
    ]


# TC-SPL-65-02
@pytest.mark.parametrize("message", ["", "   \n\t ", None, 7])
def test_tc_spl_65_02_blank_or_invalid_message_is_refused(app, client, message):
    event_id = assigned_request(app)

    response = ask(client, event_id, body={"message": message})

    assert response.status_code == 400
    assert_nothing_recorded(app, event_id, "under_review")


# TC-SPL-65-02
def test_tc_spl_65_02_message_is_stored_trimmed(app, client):
    event_id = assigned_request(app)

    assert ask(client, event_id, body={"message": f"  {MESSAGE}\n"}).status_code == 200

    assert stored_rows(app, event_id)[0][0].message == MESSAGE


# TC-SPL-65-02
def test_tc_spl_65_02_overlong_message_is_refused(app, client):
    event_id = assigned_request(app)

    response = ask(client, event_id, body={"message": "x" * 2001})

    assert response.status_code == 400
    assert_nothing_recorded(app, event_id, "under_review")


# TC-SPL-65-03
@pytest.mark.parametrize("token", ["manager", "organiser"])
def test_tc_spl_65_03_other_roles_are_refused(app, client, token):
    event_id = assigned_request(app)

    assert ask(client, event_id, token).status_code == 403
    assert_nothing_recorded(app, event_id, "under_review")


# TC-SPL-65-03
def test_tc_spl_65_03_unassigned_coordinator_is_refused(app, client):
    event_id = assigned_request(app)

    assert ask(client, event_id, "bob").status_code == 404
    assert_nothing_recorded(app, event_id, "under_review")


# TC-SPL-65-04
@pytest.mark.parametrize("status", ["submitted", "returned_for_clarification", "approved"])
def test_tc_spl_65_04_refused_outside_under_review(app, client, status):
    event_id = assigned_request(app, status=status)

    assert ask(client, event_id).status_code == 409
    assert_nothing_recorded(app, event_id, status)


# TC-SPL-65-05
def test_tc_spl_65_05_client_cannot_supply_a_target_status(app, client):
    event_id = assigned_request(app)

    response = ask(client, event_id, body={"message": MESSAGE, "status": "approved"})

    assert response.status_code == 400
    assert_nothing_recorded(app, event_id, "under_review")


# TC-SPL-65-06
def test_tc_spl_65_06_organiser_retrieves_the_message_with_the_request(app, client):
    event_id = assigned_request(app)
    assert ask(client, event_id).status_code == 200

    own = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))
    same_client = client.get(f"/api/organisation/events/{event_id}", headers=headers("organiser"))

    assert own.status_code == 200
    assert own.json["event_request"]["status"] == "returned_for_clarification"
    assert [row["message"] for row in own.json["event_request"]["clarifications"]] == [MESSAGE]
    assert same_client.status_code == 200
    assert same_client.json["event"]["status_label"] == "Returned for clarification"
    assert [row["message"] for row in same_client.json["event"]["clarifications"]] == [MESSAGE]


# TC-SPL-65-07
def test_tc_spl_65_07_history_is_kept_when_clarification_is_requested_again(app, client):
    event_id = assigned_request(app)
    assert ask(client, event_id, body={"message": "First question"}).status_code == 200
    # The organiser's reply and resubmission belong to a later story; put the request back
    # under review the way that story eventually will.
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "under_review"
        session.commit()

    assert ask(client, event_id, body={"message": "Second question"}).status_code == 200

    detail = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))
    assert [row["message"] for row in detail.json["event_request"]["clarifications"]] == [
        "Second question",
        "First question",
    ]
    assert len(stored_rows(app, event_id)[1]) == 2


# TC-SPL-65-08
def test_tc_spl_65_08_coordinator_detail_lists_the_history(app, client):
    event_id = assigned_request(app)
    assert ask(client, event_id).status_code == 200

    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers("alice"))

    assert [row["message"] for row in detail.json["event"]["clarifications"]] == [MESSAGE]
