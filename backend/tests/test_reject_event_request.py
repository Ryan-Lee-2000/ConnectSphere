"""Acceptance coverage for CS-E06-S5 / SPL-68 reject an event request."""

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
            "DATABASE_URL": f"sqlite:///{tmp_path}/rejection.db",
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


def reject(client, event_id: int, token="alice", **kwargs):
    if "json" not in kwargs and "data" not in kwargs:
        kwargs["json"] = {"reason": "The venue plan is not workable."}
    return client.post(f"/api/event-requests/{event_id}/reject", headers=headers(token), **kwargs)


def stored(app, event_id: int):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        audit = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        return (
            event.status,
            (event.rejected_by_account_id, event.rejected_at, event.rejection_reason),
            audit,
        )


def assert_unchanged(app, event_id: int, status: str):
    assert stored(app, event_id) == (status, (None, None, None), [])


# TC-SPL-68-01
def test_tc_spl_68_01_assigned_coordinator_rejects_and_the_decision_is_recorded(app, client):
    event_id = assigned_request(app)

    response = reject(client, event_id, json={"reason": "  Clashes with exams.  "})

    assert response.status_code == 200
    event = response.json["event"]
    assert (event["status"], event["status_label"]) == ("rejected", "Not approved")
    assert event["rejected_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert event["rejected_at"]
    assert event["rejection_reason"] == "Clashes with exams."
    assert response.json["transition"]["action"] == "reject"
    assert response.json["transition"]["previous_status"] == "under_review"
    assert response.json["transition"]["resulting_status"] == "rejected"
    status, (rejecter, rejected_at, reason), audit = stored(app, event_id)
    assert (status, rejecter, reason) == ("rejected", ALICE, "Clashes with exams.")
    assert rejected_at is not None
    assert [row.action for row in audit] == ["reject"]


# TC-SPL-68-02
@pytest.mark.parametrize("token", ["organiser", "manager"])
def test_tc_spl_68_02_other_roles_are_refused_and_nothing_changes(app, client, token):
    event_id = assigned_request(app)

    assert reject(client, event_id, token).status_code == 403
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-68-03
def test_tc_spl_68_03_an_unassigned_coordinator_gets_not_found_and_nothing_changes(app, client):
    event_id = assigned_request(app)

    response = reject(client, event_id, "bob")

    assert response.status_code == 404
    assert response.json["error"] == "Assigned event not found."
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-68-04
@pytest.mark.parametrize("reason", ["", "   ", "\n\t", None, 5, ["x"]])
def test_tc_spl_68_04_a_blank_or_non_text_reason_is_refused(app, client, reason):
    event_id = assigned_request(app)

    response = reject(client, event_id, json={"reason": reason})

    assert response.status_code == 400
    assert response.json["error"] == "Enter a reason for rejecting the request."
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-68-05
@pytest.mark.parametrize(
    "body",
    [{}, {"status": "planning"}, {"reason": "x", "status": "planning"}, [], "rejected"],
)
def test_tc_spl_68_05_a_missing_reason_or_client_supplied_status_is_refused(app, client, body):
    event_id = assigned_request(app)

    response = reject(client, event_id, json=body)

    assert response.status_code == 400
    assert_unchanged(app, event_id, "under_review")


# TC-SPL-68-06
@pytest.mark.parametrize(
    "status", ["submitted", "returned_for_clarification", "planning", "rejected"]
)
def test_tc_spl_68_06_only_an_event_under_review_can_be_rejected(app, client, status):
    event_id = assigned_request(app, status=status)

    response = reject(client, event_id)

    assert response.status_code == 409
    assert response.json["error"] == "Only an event under review can be rejected."
    assert_unchanged(app, event_id, status)


# TC-SPL-68-07
def test_tc_spl_68_07_rejecting_twice_keeps_the_first_decision(app, client):
    event_id = assigned_request(app)
    reject(client, event_id, json={"reason": "First reason."})

    second = reject(client, event_id, json={"reason": "Second reason."})

    assert second.status_code == 409
    status, (rejecter, _, reason), audit = stored(app, event_id)
    assert (status, rejecter, reason, len(audit)) == ("rejected", ALICE, "First reason.", 1)


# TC-SPL-68-08
def test_tc_spl_68_08_the_organiser_retrieves_the_outcome_and_others_cannot(app, client):
    event_id = assigned_request(app)
    before = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))
    assert before.json["event_request"]["rejected_by"] is None
    assert before.json["event_request"]["rejection_reason"] is None
    reject(client, event_id, json={"reason": "Out of scope."})

    after = client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))

    assert after.status_code == 200
    outcome = after.json["event_request"]
    assert (outcome["status"], outcome["status_label"]) == ("rejected", "Not approved")
    assert outcome["rejected_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert outcome["rejected_at"]
    assert outcome["rejection_reason"] == "Out of scope."
    manager = client.get(f"/api/event-requests/{event_id}", headers=headers("manager"))
    assert manager.status_code == 403


# TC-SPL-68-09
def test_tc_spl_68_09_the_coordinator_detail_shows_the_decision(app, client):
    event_id = assigned_request(app)
    reject(client, event_id, json={"reason": "Out of scope."})

    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers("alice"))

    assert detail.json["event"]["status"] == "rejected"
    assert detail.json["event"]["rejection_reason"] == "Out of scope."
    assert detail.json["event"]["rejected_by"] == {"id": ALICE, "name": "Alice Tan"}


# TC-SPL-68-10
def test_tc_spl_68_10_a_rejected_request_cannot_be_reviewed_or_planned_further(app, client):
    event_id = assigned_request(app)
    reject(client, event_id)
    base = f"/api/event-requests/{event_id}"

    for action, body in (
        ("begin-review", None),
        ("approve", None),
        ("request-clarification", {"message": "More detail please."}),
        ("reject", {"reason": "Again."}),
    ):
        response = client.post(f"{base}/{action}", headers=headers("alice"), json=body)
        assert response.status_code == 409, action
    status, (_, _, reason), audit = stored(app, event_id)
    assert (status, reason, len(audit)) == ("rejected", "The venue plan is not workable.", 1)
    with Session(app.extensions["engine"]) as session:
        assert session.scalars(select(VenueBooking)).all() == []


# TC-SPL-68-11
def test_tc_spl_68_11_the_database_refuses_a_partial_rejection_record(app):
    event_id = assigned_request(app)
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).rejection_reason = "No decision-maker or time"
        with pytest.raises(IntegrityError):
            session.commit()


# TC-SPL-68-16
def test_tc_spl_68_16_a_reason_over_2000_characters_is_refused(app, client):
    event_id = assigned_request(app)

    assert reject(client, event_id, json={"reason": "x" * 2001}).status_code == 400
    assert_unchanged(app, event_id, "under_review")
    assert reject(client, event_id, json={"reason": "x" * 2000}).status_code == 200
