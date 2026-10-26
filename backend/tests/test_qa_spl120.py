"""QA acceptance coverage for SPL-120: coordinators view assigned-event registrations."""

from datetime import date, datetime, time, timezone

import pytest
from app import create_app
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRegistration,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy.orm import Session

MANAGER = "00000000-0000-0000-0000-000000001200"
ORGANISER = "00000000-0000-0000-0000-000000001201"
COORDINATOR = "00000000-0000-0000-0000-000000001202"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000001203"
ATTENDEE = "00000000-0000-0000-0000-000000001204"
SECOND_ATTENDEE = "00000000-0000-0000-0000-000000001205"
TOKENS = {
    "organiser": ORGANISER,
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
}
OPEN = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
CLOSE = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
REGISTERED = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/spl120.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-120 client")
        session.add(organisation)
        session.flush()
        session.add_all(
            [
                Account(id=MANAGER, display_name="Morgan Manager", organisation_id=organisation.id),
                Account(
                    id=ORGANISER,
                    display_name="Olivia Organiser",
                    organisation_id=organisation.id,
                ),
                Account(id=COORDINATOR, display_name="Casey Coordinator"),
                Account(id=OTHER_COORDINATOR, display_name="Cameron Coordinator"),
                Account(id=ATTENDEE, display_name="Avery Attendee"),
                Account(id=SECOND_ATTENDEE, display_name="Blake Attendee"),
                AccountRole(account_id=MANAGER, role=Role.EVENT_OPERATIONS_MANAGER.value),
                AccountRole(account_id=ORGANISER, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=COORDINATOR, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=OTHER_COORDINATOR, role=Role.EVENT_COORDINATOR.value),
            ]
        )
        session.commit()
        app.config["ORGANISATION_ID"] = organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"}


def make_event(app, *, assigned_to=COORDINATOR, enabled=True, capacity=80, status="planning"):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name="SPL-120 Registration List",
            purpose="Coordinator registration overview",
            proposed_date=date(2026, 11, 20),
            start_time=time(14),
            end_time=time(17),
            expected_attendance=80,
            status=status,
            registration_opens_at=OPEN if enabled else None,
            registration_closes_at=CLOSE if enabled else None,
            registration_capacity=capacity if enabled else None,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=assigned_to,
                assigned_by_account_id=MANAGER,
                assigned_at=REGISTERED,
            )
        )
        session.commit()
        return event.id


def add_registration(
    app,
    event_id,
    *,
    attendee=ATTENDEE,
    status="registered",
    name="Avery Attendee",
    email="avery@example.test",
    requirements="Step-free access",
    registered_at=REGISTERED,
):
    with Session(app.extensions["engine"]) as session:
        registration = EventRegistration(
            event_request_id=event_id,
            attendee_account_id=attendee,
            status=status,
            name=name,
            email=email,
            contact_number="+65 9000 1200",
            special_requirements=requirements,
            registered_at=registered_at,
            withdrawn_at=registered_at if status == "withdrawn" else None,
        )
        session.add(registration)
        session.commit()
        return registration.id


def coordinator_list(client, event_id, token="coordinator"):
    return client.get(
        f"/api/event-requests/assigned/{event_id}/registrations", headers=headers(token)
    )


# QA-SPL-120-001 | AC1 | BB assigned happy path
def test_qa_spl_120_001_assigned_coordinator_can_view(app, client):
    event_id = make_event(app)
    response = coordinator_list(client, event_id)
    assert response.status_code == 200
    assert response.json["registration_list"]["enabled"] is True


# QA-SPL-120-002 | AC1 | BB assignment scope
def test_qa_spl_120_002_other_coordinator_is_refused_without_disclosure(app, client):
    event_id = make_event(app)
    response = coordinator_list(client, event_id, "other-coordinator")
    assert response.status_code == 404
    assert response.json == {"error": "Assigned event not found."}


# QA-SPL-120-003 | AC1 | BB missing-event boundary
def test_qa_spl_120_003_missing_event_uses_same_generic_refusal(client):
    response = coordinator_list(client, 999_999)
    assert response.status_code == 404
    assert response.json == {"error": "Assigned event not found."}


# QA-SPL-120-004 | AC1 | WB database-id overflow boundary
def test_qa_spl_120_004_oversized_id_is_rejected_before_database_lookup(client):
    response = coordinator_list(client, 2**31)
    assert response.status_code == 404
    assert response.json == {"error": "Assigned event not found."}


# QA-SPL-120-005 | AC1 | BB role boundary
def test_qa_spl_120_005_non_coordinator_role_is_refused(app, client):
    event_id = make_event(app)
    assert coordinator_list(client, event_id, "organiser").status_code == 403


# QA-SPL-120-006 | AC1 | WB current-assignment rule
def test_qa_spl_120_006_reassignment_immediately_moves_access(app, client):
    event_id = make_event(app)
    with Session(app.extensions["engine"]) as session:
        assignment = session.get(EventCoordinatorAssignment, event_id)
        assignment.coordinator_account_id = OTHER_COORDINATOR
        session.commit()
    assert coordinator_list(client, event_id).status_code == 404
    assert coordinator_list(client, event_id, "other-coordinator").status_code == 200


# QA-SPL-120-007 | AC2 | BB parity with CS-E19-S6
def test_qa_spl_120_007_payload_matches_organiser_registration_list(app, client):
    event_id = make_event(app)
    add_registration(app, event_id)
    coordinator = coordinator_list(client, event_id).json["registration_list"]
    organiser = client.get(
        f"/api/organisation/events/{event_id}/registrations", headers=headers("organiser")
    ).json["registration_list"]
    assert coordinator == organiser


# QA-SPL-120-008 | AC2 | BB count, capacity and attendee fields
def test_qa_spl_120_008_count_capacity_and_all_approved_fields_are_returned(app, client):
    event_id = make_event(app, capacity=80)
    registration_id = add_registration(app, event_id)
    result = coordinator_list(client, event_id).json["registration_list"]
    assert (result["registered_count"], result["capacity"]) == (1, 80)
    assert result["registered"] == [
        {
            "id": registration_id,
            "name": "Avery Attendee",
            "email": "avery@example.test",
            "contact_number": "+65 9000 1200",
            "special_requirements": "Step-free access",
        }
    ]


# QA-SPL-120-009 | AC2 | BB registered/withdrawn distinction
def test_qa_spl_120_009_withdrawn_attendees_are_separate_and_not_counted(app, client):
    event_id = make_event(app)
    add_registration(app, event_id, name="Current")
    add_registration(
        app,
        event_id,
        attendee=SECOND_ATTENDEE,
        status="withdrawn",
        name="Former",
        email="former@example.test",
    )
    result = coordinator_list(client, event_id).json["registration_list"]
    assert result["registered_count"] == 1
    assert [row["name"] for row in result["registered"]] == ["Current"]
    assert [row["name"] for row in result["withdrawn"]] == ["Former"]


# QA-SPL-120-010 | AC2 | WB deterministic ordering
def test_qa_spl_120_010_equal_signup_times_use_id_as_tie_break(app, client):
    event_id = make_event(app)
    first = add_registration(app, event_id, name="Avery")
    second = add_registration(
        app,
        event_id,
        attendee=SECOND_ATTENDEE,
        name="Blake",
        email="blake@example.test",
    )
    rows = coordinator_list(client, event_id).json["registration_list"]["registered"]
    assert [row["id"] for row in rows] == [first, second]


# QA-SPL-120-011 | AC2 | BB registration-disabled boundary
def test_qa_spl_120_011_disabled_registration_returns_shared_empty_contract(app, client):
    event_id = make_event(app, enabled=False)
    assert coordinator_list(client, event_id).json["registration_list"] == {
        "enabled": False,
        "capacity": None,
        "registered_count": 0,
        "registered": [],
        "withdrawn": [],
    }


# QA-SPL-120-012 | AC2 | BB nullable and allowlist boundary
def test_qa_spl_120_012_nullable_requirements_do_not_expand_the_payload(app, client):
    event_id = make_event(app)
    add_registration(app, event_id, requirements=None)
    attendee = coordinator_list(client, event_id).json["registration_list"]["registered"][0]
    assert attendee["special_requirements"] is None
    assert set(attendee) == {"id", "name", "email", "contact_number", "special_requirements"}


# QA-SPL-120-013 | AC3 | WB event-page capability contract
def test_qa_spl_120_013_assigned_event_detail_advertises_registration_list(app, client):
    event_id = make_event(app)
    response = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers())
    assert response.status_code == 200
    assert response.headers["X-ConnectSphere-Registration-List"] == "available"
