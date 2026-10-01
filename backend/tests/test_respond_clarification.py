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
    EquipmentRequirement,
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


# TC-SPL-66-06: AC 5.
@pytest.mark.parametrize("token", ["other", "coordinator", "manager"])
def test_tc_spl_66_06_unrelated_accounts_are_refused_without_changes(app, client, token):
    event_id, clarification_id = clarification_event(app)

    before = request_snapshot(app, event_id)
    response = respond(client, event_id, clarification_id, token=token)

    assert response.status_code == (404 if token == "other" else 403)
    assert request_snapshot(app, event_id) == before
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

    before = request_snapshot(app, event_id)
    assert respond(client, event_id, clarification_id).status_code == 409
    assert request_snapshot(app, event_id) == before
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


def request_snapshot(app, event_id):
    """Capture saved content, assignment and equipment independently of API serialization."""
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        # Only these workflow fields may change when the organiser answers.
        content = {
            column.name: getattr(event, column.name)
            for column in EventRequest.__table__.columns
            if column.name not in {"status", "status_changed_at"}
        }
        equipment = [
            {
                column.name: getattr(line, column.name)
                for column in EquipmentRequirement.__table__.columns
            }
            for line in event.equipment_requirements
        ]
        assignment = {
            column.name: getattr(event.coordinator_assignment, column.name)
            for column in EventCoordinatorAssignment.__table__.columns
        }
        return content, equipment, assignment


# TC-SPL-66-07: AC 1 — use the retrieved outstanding ID, not a hard-coded response target.
def test_tc_spl_66_07_owner_retrieves_outstanding_question_before_answering(app, client):
    event_id, clarification_id = clarification_event(app)
    retrieved = client.get(f"/api/event-requests/{event_id}", headers=headers())

    assert retrieved.status_code == 200
    [question] = retrieved.json["event_request"]["clarifications"]
    assert question["id"] == clarification_id
    assert question["message"] == "Please confirm the revised attendance estimate."
    assert question["response"] is None
    answer = respond(client, event_id, question["id"])
    assert answer.status_code == 200
    assert answer.json["clarifications"][0]["response"] == "Attendance remains 120 people."


# TC-SPL-66-02: AC 2 — both authorised readers see the same complete saved evidence.
def test_tc_spl_66_02_response_evidence_is_retained_for_organiser_and_coordinator(app, client):
    event_id, clarification_id = clarification_event(app)
    before = datetime.now(SINGAPORE)
    result = respond(client, event_id, clarification_id)
    after = datetime.now(SINGAPORE)
    assert result.status_code == 200

    own = client.get(f"/api/event-requests/{event_id}", headers=headers())
    assigned = client.get(
        f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
    )
    assert own.status_code == assigned.status_code == 200
    [evidence] = own.json["event_request"]["clarifications"]
    assert assigned.json["event"]["clarifications"] == [evidence]
    assert evidence["id"] == clarification_id
    assert evidence["message"] == "Please confirm the revised attendance estimate."
    assert evidence["author"] == {"id": COORDINATOR, "name": "Alice Tan"}
    assert evidence["created_at"] == "2026-09-28T10:00:00+08:00"
    assert evidence["response"] == "Attendance remains 120 people."
    assert evidence["respondent"] == {"id": ORGANISER, "name": "Olivia Organiser"}
    assert before <= datetime.fromisoformat(evidence["responded_at"]) <= after
    assert stored(app, event_id, clarification_id)[1:3] == (evidence["response"], ORGANISER)


# TC-SPL-66-08: AC 2 — a later cycle must append evidence without overwriting the first answer.
def test_tc_spl_66_08_second_clarification_retains_both_questions_and_responses(app, client):
    event_id, first_id = clarification_event(app)
    first = respond(client, event_id, first_id)
    assert first.status_code == 200
    original_evidence = first.json["clarifications"][0]
    next_question = client.post(
        f"/api/event-requests/{event_id}/request-clarification",
        headers=headers("coordinator"),
        json={"message": "Please confirm accessibility needs."},
    )
    assert next_question.status_code == 200
    second_id = next_question.json["clarifications"][0]["id"]
    assert second_id != first_id
    assert (
        respond(
            client, event_id, second_id, body={"response": "Step-free access is required."}
        ).status_code
        == 200
    )

    retrieved = client.get(f"/api/event-requests/{event_id}", headers=headers())
    assert retrieved.status_code == 200
    newest, oldest = retrieved.json["event_request"]["clarifications"]
    assert oldest == original_evidence
    assert newest["id"] == second_id
    assert newest["message"] == "Please confirm accessibility needs."
    assert newest["response"] == "Step-free access is required."
    assert newest["respondent"] == {"id": ORGANISER, "name": "Olivia Organiser"}
    assert newest["responded_at"]


# TC-SPL-66-09: AC 3 — the persisted transition and unchanged assignment must agree.
def test_tc_spl_66_09_response_resumes_review_with_one_audit_and_same_assignment(app, client):
    event_id, clarification_id = clarification_event(app)
    original_assignment = request_snapshot(app, event_id)[2]
    assert respond(client, event_id, clarification_id).status_code == 200

    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        answer = session.get(ClarificationRequest, clarification_id)
        [audit] = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        assert event.status == "under_review"
        assert (audit.action, audit.previous_status, audit.resulting_status) == (
            "respond_clarification",
            "returned_for_clarification",
            "under_review",
        )
        assert audit.actor_account_id == ORGANISER
        assert event.status_changed_at == answer.responded_at == audit.changed_at
        assert answer.responded_at is not None
    assert request_snapshot(app, event_id)[2] == original_assignment


# TC-SPL-66-10: AC 3 — replying must preserve the current assignee, not restore the question author.
def test_tc_spl_66_10_response_preserves_a_reassigned_coordinator(app, client):
    event_id, clarification_id = clarification_event(app)
    replacement = "00000000-0000-0000-0000-000000000095"
    with Session(app.extensions["engine"]) as session:
        session.add(Account(id=replacement, display_name="Casey Lim", is_active=True))
        session.add(AccountRole(account_id=replacement, role=Role.EVENT_COORDINATOR.value))
        session.get(EventCoordinatorAssignment, event_id).coordinator_account_id = replacement
        session.commit()
    original_assignment = request_snapshot(app, event_id)[2]

    response = respond(client, event_id, clarification_id)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "under_review"
    assert stored(app, event_id, clarification_id)[0] == "under_review"
    assert request_snapshot(app, event_id)[2] == original_assignment
    assert original_assignment["coordinator_account_id"] == replacement
    assert response.json["clarifications"][0]["author"]["id"] == COORDINATOR


def populate_request_content(app, event_id):
    """Use nonempty values so clearing optional content cannot pass the preservation check."""
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.description = "An organiser's submitted description."
        event.preferred_room_layout = "Theatre"
        event.required_facilities = ["Projector", "PA system"]
        event.facilities_notes = "Two microphones"
        event.accessibility_needs = ["Step-free access"]
        event.location_preference = "Marina Centre"
        event.venue_notes = "Near public transport"
        event.registration_required = True
        event.registration_notes = "Named attendee registration"
        event.equipment_requirements = [
            EquipmentRequirement(equipment_type="Podium", quantity=2, notes="Lockable"),
            EquipmentRequirement(equipment_type="Microphone", quantity=3, notes="Wireless"),
        ]
        session.commit()


# TC-SPL-66-11: AC 4 — even an answer mentioning new values must not edit submitted content.
def test_tc_spl_66_11_successful_response_preserves_all_request_content_and_equipment(app, client):
    event_id, clarification_id = clarification_event(app)
    populate_request_content(app, event_id)
    before = request_snapshot(app, event_id)

    response = respond(
        client,
        event_id,
        clarification_id,
        body={"response": "Could attendance be 200 and the layout be Banquet?"},
    )

    assert response.status_code == 200
    assert stored(app, event_id, clarification_id)[0] == "under_review"
    assert request_snapshot(app, event_id) == before


# TC-SPL-66-12: AC 4 — attempted request edits must reject the entire response transaction.
@pytest.mark.parametrize(
    "injected",
    [
        {"expected_attendance": 200},
        {"name": "Replacement event"},
        {"proposed_date": "2026-12-01"},
        {"required_facilities": []},
        {"registration_required": False},
        {"equipment_requirements": []},
    ],
)
def test_tc_spl_66_12_injected_request_fields_are_refused_without_any_changes(
    app, client, injected
):
    event_id, clarification_id = clarification_event(app)
    populate_request_content(app, event_id)
    before = request_snapshot(app, event_id)

    response = respond(
        client, event_id, clarification_id, body={"response": "Confirmed", **injected}
    )

    assert response.status_code == 400
    assert request_snapshot(app, event_id) == before
    assert stored(app, event_id, clarification_id)[:5] == (
        "returned_for_clarification",
        None,
        None,
        None,
        [],
    )
