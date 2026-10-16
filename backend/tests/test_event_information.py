"""SPL-108 acceptance tests for assigned-coordinator ordinary information edits."""

from datetime import date, datetime, time

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.event_statuses import (
    ACTIVE_EVENT_STATUSES,
    EVENT_REQUEST_STATUSES,
    INACTIVE_EVENT_STATUSES,
)
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventDetailChange,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

ORGANISER = "00000000-0000-0000-0000-000000001081"
COORDINATOR = "00000000-0000-0000-0000-000000001082"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000001083"
ASSIGNED_AT = datetime(2026, 10, 16, 9, 0, tzinfo=SINGAPORE)


@pytest.fixture
def app(tmp_path):
    tokens = {
        "organiser": ORGANISER,
        "coordinator": COORDINATOR,
        "other": OTHER_COORDINATOR,
    }
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/event-information.db",
            "IDENTITY_VERIFIER": tokens.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-108 Client")
        session.add(organisation)
        session.flush()
        accounts = (
            (ORGANISER, "Olivia Organiser", Role.EVENT_ORGANISER),
            (COORDINATOR, "Casey Coordinator", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Riley Coordinator", Role.EVENT_COORDINATOR),
        )
        for account_id, name, role in accounts:
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
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


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"}


def seed_event(app, *, status="planning", assigned_to=COORDINATOR):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["TEST_ORGANISATION_ID"],
            name="SPL-108 Client Forum",
            purpose="Original purpose",
            description="Original description",
            event_notes="Original note",
            registration_notes="Original registration note",
            event_contact_name="Original Contact",
            event_contact_email="original@example.com",
            event_contact_phone="+65 6000 0000",
            proposed_date=date(2026, 11, 20),
            start_time=time(9),
            end_time=time(12),
            expected_attendance=80,
            status=status,
            submitted_at=ASSIGNED_AT,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=assigned_to,
                assigned_by_account_id=COORDINATOR,
                assigned_at=ASSIGNED_AT,
            )
        )
        session.commit()
        return event.id


def endpoint(event_id):
    return f"/api/event-requests/assigned/{event_id}/event-information"


def audit_rows(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(
            select(EventDetailChange)
            .where(EventDetailChange.event_request_id == event_id)
            .order_by(EventDetailChange.id)
        ).all()


# AC1: exact whitelist and all active lifecycle stages.
def test_tc_spl_108_001_updates_every_ordinary_information_field(app, client):
    event_id = seed_event(app)
    values = {
        "purpose": "Updated purpose",
        "description": "Updated description",
        "event_notes": "Coordinator note",
        "registration_notes": "Bring photo identification",
        "event_contact_name": "Avery Tan",
        "event_contact_email": "avery@example.com",
        "event_contact_phone": "+65 6123 4567",
    }

    response = client.patch(endpoint(event_id), json=values, headers=headers())

    assert response.status_code == 200
    assert {field: response.json["event"][field] for field in values} == values


@pytest.mark.parametrize("status", sorted(ACTIVE_EVENT_STATUSES))
def test_tc_spl_108_002_all_shared_active_statuses_allow_an_edit(app, client, status):
    event_id = seed_event(app, status=status)

    response = client.patch(endpoint(event_id), json={"event_notes": status}, headers=headers())

    assert response.status_code == 200
    assert response.json["event"]["event_notes"] == status


# AC2: reject arrangement-owned input and prove no side effects outside the whitelist.
@pytest.mark.parametrize("field,value", [("status", "confirmed"), ("proposed_date", "2027-01-01")])
def test_tc_spl_108_003_rejects_status_and_arrangement_fields(app, client, field, value):
    event_id = seed_event(app)

    response = client.patch(endpoint(event_id), json={field: value}, headers=headers())

    assert response.status_code == 400
    assert response.json["error"].startswith("Event information accepts only")
    assert audit_rows(app, event_id) == []


def test_tc_spl_108_004_validates_contact_details_without_mutation(app, client):
    event_id = seed_event(app)

    response = client.patch(
        endpoint(event_id), json={"event_contact_email": "not-an-email"}, headers=headers()
    )

    assert response.status_code == 400
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assert event.event_contact_email == "original@example.com"
        assert event.status == "planning"
        assert event.proposed_date == date(2026, 11, 20)
        assert event.expected_attendance == 80
        assert event.required_facilities == []
        assert event.registration_required is False
    assert audit_rows(app, event_id) == []


# AC3: atomic old/new/actor/time evidence and no history for a semantic no-op.
def test_tc_spl_108_005_records_only_changed_fields_with_actor_and_time(app, client):
    event_id = seed_event(app)

    response = client.patch(
        endpoint(event_id),
        json={"purpose": "New purpose", "description": "Original description"},
        headers=headers(),
    )

    assert response.status_code == 200
    rows = audit_rows(app, event_id)
    assert len(rows) == 1
    assert rows[0].changes == {"purpose": {"previous": "Original purpose", "new": "New purpose"}}
    assert rows[0].changed_by_account_id == COORDINATOR
    assert rows[0].changed_at is not None


def test_tc_spl_108_006_trimmed_no_op_creates_no_audit_record(app, client):
    event_id = seed_event(app)

    response = client.patch(
        endpoint(event_id), json={"purpose": "  Original purpose  "}, headers=headers()
    )

    assert response.status_code == 200
    assert response.json["change"] is None
    assert audit_rows(app, event_id) == []


# AC4: assignment scope uses the same generic 404 for protected and absent records.
def test_tc_spl_108_007_another_coordinator_receives_generic_not_found(app, client):
    event_id = seed_event(app)

    response = client.patch(
        endpoint(event_id), json={"purpose": "Probing"}, headers=headers("other")
    )

    assert response.status_code == 404
    assert response.json == {"error": "Assigned event not found."}


def test_tc_spl_108_008_unknown_event_receives_the_same_generic_not_found(client):
    response = client.patch(endpoint(999999), json={"purpose": "Missing"}, headers=headers("other"))

    assert response.status_code == 404
    assert response.json == {"error": "Assigned event not found."}


# AC5: organisers cannot use the coordinator route and their submitted values remain unchanged.
def test_tc_spl_108_009_organiser_is_forbidden_from_the_edit_route(app, client):
    event_id = seed_event(app)

    response = client.patch(
        endpoint(event_id), json={"purpose": "Organiser override"}, headers=headers("organiser")
    )

    assert response.status_code == 403
    assert audit_rows(app, event_id) == []


def test_tc_spl_108_010_organiser_cannot_clear_contact_details(app, client):
    event_id = seed_event(app)

    response = client.patch(
        endpoint(event_id), json={"event_contact_email": None}, headers=headers("organiser")
    )

    assert response.status_code == 403
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).event_contact_email == "original@example.com"


# AC6: every inactive state is refused using the same shared policy, with no mutation.
@pytest.mark.parametrize("status", sorted(INACTIVE_EVENT_STATUSES))
def test_tc_spl_108_011_all_shared_inactive_statuses_refuse_edits(app, client, status):
    event_id = seed_event(app, status=status)

    response = client.patch(endpoint(event_id), json={"purpose": "Too late"}, headers=headers())

    assert response.status_code == 409
    assert response.json == {
        "error": "Event information can only be edited while the event is active."
    }
    assert audit_rows(app, event_id) == []


def test_tc_spl_108_012_active_and_inactive_sets_cover_the_status_vocabulary_once():
    assert ACTIVE_EVENT_STATUSES.isdisjoint(INACTIVE_EVENT_STATUSES)
    assert ACTIVE_EVENT_STATUSES | INACTIVE_EVENT_STATUSES == set(EVENT_REQUEST_STATUSES)
    assert "planning" in ACTIVE_EVENT_STATUSES
    assert "completed" in INACTIVE_EVENT_STATUSES
