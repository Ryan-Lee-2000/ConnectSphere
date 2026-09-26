"""Acceptance coverage for CS-E01-S3: view events in my client organisation."""

from datetime import date, time

import pytest
from app import create_app
from app.event_statuses import status_explanation
from app.models import Account, AccountRole, Base, EventRequest, Organisation, Role
from sqlalchemy.orm import Session

ORGANISER_ONE = "00000000-0000-0000-0000-000000000041"
ORGANISER_TWO = "00000000-0000-0000-0000-000000000042"
OTHER_ORGANISER = "00000000-0000-0000-0000-000000000043"
UNASSIGNED_ORGANISER = "00000000-0000-0000-0000-000000000044"
COORDINATOR = "00000000-0000-0000-0000-000000000045"


@pytest.fixture
def organisation_app(tmp_path):
    identities = {
        "organiser-one": ORGANISER_ONE,
        "organiser-two": ORGANISER_TWO,
        "other-organiser": OTHER_ORGANISER,
        "unassigned-organiser": UNASSIGNED_ORGANISER,
        "coordinator": COORDINATOR,
    }
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/organisation-events.db",
            "IDENTITY_VERIFIER": identities.get,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        northstar = Organisation(name="Northstar Community Partners")
        lighthouse = Organisation(name="Lighthouse Learning Group")
        session.add_all([northstar, lighthouse])
        session.flush()
        session.add_all(
            [
                Account(
                    id=ORGANISER_ONE,
                    display_name="Aisha Rahman",
                    organisation_id=northstar.id,
                ),
                Account(
                    id=ORGANISER_TWO,
                    display_name="Marcus Tan",
                    organisation_id=northstar.id,
                ),
                Account(
                    id=OTHER_ORGANISER,
                    display_name="Priya Nair",
                    organisation_id=lighthouse.id,
                ),
                Account(id=UNASSIGNED_ORGANISER, display_name="Unassigned Organiser"),
                Account(id=COORDINATOR, display_name="Casey Lim"),
            ]
        )
        session.add_all(
            [
                AccountRole(account_id=account_id, role=Role.EVENT_ORGANISER.value)
                for account_id in (
                    ORGANISER_ONE,
                    ORGANISER_TWO,
                    OTHER_ORGANISER,
                    UNASSIGNED_ORGANISER,
                )
            ]
            + [AccountRole(account_id=COORDINATOR, role=Role.EVENT_COORDINATOR.value)]
        )
        session.commit()
    yield app
    engine.dispose()


@pytest.fixture
def client(organisation_app):
    return organisation_app.test_client()


def headers(identity="organiser-one"):
    return {"Authorization": f"Bearer {identity}"}


def seed_event(app, *, organiser, organisation_id, name, status="submitted"):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=organiser,
            organisation_id=organisation_id,
            name=name,
            purpose="Bring community partners together",
            description="A practical working session.",
            proposed_date=date(2026, 12, 4),
            start_time=time(9, 30),
            end_time=time(12, 0),
            expected_attendance=80,
            status=status,
            required_facilities=[],
            registration_required=False,
        )
        session.add(event)
        session.commit()
        return event.id


def test_tc_cs_e01_s3_01_lists_own_and_colleague_submitted_events_only(organisation_app, client):
    mine = seed_event(
        organisation_app,
        organiser=ORGANISER_ONE,
        organisation_id=1,
        name="My submitted event",
    )
    colleague = seed_event(
        organisation_app,
        organiser=ORGANISER_TWO,
        organisation_id=1,
        name="Colleague event",
        status="approved",
    )
    seed_event(
        organisation_app,
        organiser=ORGANISER_TWO,
        organisation_id=1,
        name="Private draft",
        status="draft",
    )
    seed_event(
        organisation_app,
        organiser=OTHER_ORGANISER,
        organisation_id=2,
        name="Other client event",
    )

    response = client.get("/api/organisation/events", headers=headers())

    assert response.status_code == 200
    assert response.json == {
        "events": [
            {
                "id": mine,
                "name": "My submitted event",
                "proposed_date": "2026-12-04",
                "responsible_organiser": "Aisha Rahman",
            },
            {
                "id": colleague,
                "name": "Colleague event",
                "proposed_date": "2026-12-04",
                "responsible_organiser": "Marcus Tan",
            },
        ]
    }


def test_tc_cs_e01_s3_02_opens_the_approved_read_only_detail(organisation_app, client):
    event_id = seed_event(
        organisation_app,
        organiser=ORGANISER_TWO,
        organisation_id=1,
        name="Colleague event",
    )

    response = client.get(f"/api/organisation/events/{event_id}", headers=headers())

    assert response.status_code == 200
    assert response.json == {
        "event": {
            "id": event_id,
            "name": "Colleague event",
            "purpose": "Bring community partners together",
            "description": "A practical working session.",
            "proposed_date": "2026-12-04",
            "start_time": "09:30",
            "end_time": "12:00",
            "expected_attendance": 80,
            "responsible_organiser": "Marcus Tan",
            "status": "submitted",
            "status_label": "Submitted",
            "status_explanation": status_explanation("submitted"),
            "clarifications": [],
        }
    }


@pytest.mark.parametrize("hidden_status", ["submitted", "draft"])
def test_tc_cs_e01_s3_03_cross_client_and_draft_direct_requests_reveal_nothing(
    organisation_app, client, hidden_status
):
    event_id = seed_event(
        organisation_app,
        organiser=(OTHER_ORGANISER if hidden_status == "submitted" else ORGANISER_TWO),
        organisation_id=(2 if hidden_status == "submitted" else 1),
        name="Protected event information",
        status=hidden_status,
    )

    response = client.get(f"/api/organisation/events/{event_id}", headers=headers())

    assert response.status_code == 404
    assert response.json == {"error": "Event not found."}
    assert "Protected event information" not in response.get_data(as_text=True)


def test_tc_cs_e01_s3_04_supplied_identifiers_cannot_change_the_scope(organisation_app, client):
    hidden_id = seed_event(
        organisation_app,
        organiser=OTHER_ORGANISER,
        organisation_id=2,
        name="Other client event",
    )

    response = client.get(
        "/api/organisation/events",
        query_string={
            "organisation_id": "2",
            "account_id": OTHER_ORGANISER,
            "organiser_account_id": OTHER_ORGANISER,
        },
        headers={
            **headers(),
            "X-Organisation-Id": "2",
            "X-Account-Id": OTHER_ORGANISER,
        },
    )
    detail = client.get(
        f"/api/organisation/events/{hidden_id}?organisation_id=2",
        headers=headers(),
    )

    assert response.status_code == 200
    assert response.json == {"events": []}
    assert detail.status_code == 404


def test_tc_cs_e01_s3_05_empty_organisation_is_a_success(client):
    response = client.get("/api/organisation/events", headers=headers("other-organiser"))

    assert response.status_code == 200
    assert response.json == {"events": []}


@pytest.mark.parametrize("identity", ["coordinator", "unassigned-organiser"])
def test_tc_cs_e01_s3_06_requires_the_role_and_trusted_membership(client, identity):
    response = client.get("/api/organisation/events", headers=headers(identity))

    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}
