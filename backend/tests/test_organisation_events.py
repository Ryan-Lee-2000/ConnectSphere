"""Acceptance coverage for CS-E01-S3: view events in my client organisation."""

from datetime import date, datetime, time

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.event_statuses import status_explanation
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueBooking,
)
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


def seed_spl110_arrangements(app, *, configured_registration=True):
    """A current organiser summary with approved, pending and unavailable arrangements."""

    event_id = seed_event(
        app,
        organiser=ORGANISER_TWO,
        organisation_id=1,
        name="SPL-110 Community Forum",
        status="confirmed",
    )
    now = datetime(2026, 10, 21, 9, 0, tzinfo=SINGAPORE)
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.event_notes = "Internal coordinator handover — never expose."
        if configured_registration:
            event.registration_opens_at = datetime(2026, 11, 1, 9, 0, tzinfo=SINGAPORE)
            event.registration_closes_at = datetime(2026, 12, 3, 18, 0, tzinfo=SINGAPORE)
            event.registration_capacity = 75
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event_id,
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=ORGANISER_ONE,
                assigned_at=now,
            )
        )
        harbour = Venue(
            name="Harbour Hall",
            location="8 Marina Way",
            operating_slots=["AM", "PM"],
        )
        studio = Venue(
            name="Studio One",
            location="21 River Road",
            operating_slots=["AM", "PM"],
        )
        archived = Venue(name="Old Hall", location="1 Old Road", operating_slots=["AM"])
        session.add_all([harbour, studio, archived])
        session.flush()
        session.add_all(
            [
                VenueBooking(
                    event_request_id=event_id,
                    venue_id=harbour.id,
                    status="approved",
                    booking_date=date(2026, 12, 4),
                    event_slots=["AM"],
                    approval_note="Venue Staff internal note — never expose.",
                ),
                VenueBooking(
                    event_request_id=event_id,
                    venue_id=studio.id,
                    status="requested",
                    requires_review=True,
                    booking_date=date(2026, 12, 4),
                    event_slots=["AM"],
                ),
                VenueBooking(
                    event_request_id=event_id,
                    venue_id=archived.id,
                    status="withdrawn",
                    booking_date=date(2026, 12, 4),
                    event_slots=["AM"],
                ),
            ]
        )
        equipment_type = EquipmentType(
            name="Wireless Microphone",
            normalised_name="wireless microphone",
            total_stock=20,
        )
        session.add(equipment_type)
        session.flush()
        microphone = EquipmentRequirement(
            event_request_id=event_id,
            equipment_type="Microphones",
            equipment_type_id=equipment_type.id,
            quantity=4,
            status="reserved",
            essentiality="essential",
            notes="Internal equipment note — never expose.",
        )
        projector = EquipmentRequirement(
            event_request_id=event_id,
            equipment_type="Projector",
            quantity=2,
            status="unavailable",
            essentiality="non_essential",
        )
        removed = EquipmentRequirement(
            event_request_id=event_id,
            equipment_type="Removed item",
            quantity=1,
            status="removed",
            essentiality="non_essential",
        )
        session.add_all([microphone, projector, removed])
        session.flush()
        session.add(
            EquipmentReservation(
                event_request_id=event_id,
                equipment_requirement_id=microphone.id,
                equipment_type_id=equipment_type.id,
                commitment_start_date=date(2026, 12, 4),
                commitment_end_date=date(2026, 12, 4),
                quantity=4,
                reserved_by_account_id=COORDINATOR,
                reserved_at=now,
            )
        )
        session.commit()
        return event_id


# SPL-45 AC-1,2,3,4 Test-01
# SPL-45 AC-6 Test-03
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


# SPL-45 AC-5 Test-02
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
            "coordinator": None,
            "venue_arrangements": [],
            "equipment_arrangements": [],
            "registration_settings": {
                "enabled": False,
                "capacity": None,
                "opens_at": None,
                "closes_at": None,
            },
            "clarifications": [],
        }
    }


# SPL-45 AC-6,7 Test-03
# SPL-45 AC-2 Test-04
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


# SPL-45 AC-8 Test-05
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


# SPL-45 AC-9 Test-06
def test_tc_cs_e01_s3_05_empty_organisation_is_a_success(client):
    response = client.get("/api/organisation/events", headers=headers("other-organiser"))

    assert response.status_code == 200
    assert response.json == {"events": []}


# SPL-45 AC-1 Test-07
@pytest.mark.parametrize("identity", ["coordinator", "unassigned-organiser"])
def test_tc_cs_e01_s3_06_requires_the_role_and_trusted_membership(client, identity):
    response = client.get("/api/organisation/events", headers=headers(identity))

    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}


def test_tc_spl_110_001_same_organisation_sees_status_and_coordinator(organisation_app, client):
    event_id = seed_spl110_arrangements(organisation_app)

    response = client.get(f"/api/organisation/events/{event_id}", headers=headers())

    assert response.status_code == 200
    assert response.json["event"]["status_label"] == "Confirmed"
    assert response.json["event"]["coordinator"] == {
        "id": COORDINATOR,
        "name": "Casey Lim",
    }


def test_tc_spl_110_002_cross_organisation_and_private_drafts_stay_hidden(organisation_app, client):
    other_event = seed_event(
        organisation_app,
        organiser=OTHER_ORGANISER,
        organisation_id=2,
        name="Other organisation",
    )
    colleague_draft = seed_event(
        organisation_app,
        organiser=ORGANISER_TWO,
        organisation_id=1,
        name="Colleague private draft",
        status="draft",
    )

    for event_id in (other_event, colleague_draft):
        response = client.get(f"/api/organisation/events/{event_id}", headers=headers())
        assert response.status_code == 404
        assert response.json == {"error": "Event not found."}


def test_tc_spl_110_003_returns_configured_venues_equipment_and_registration(
    organisation_app, client
):
    event_id = seed_spl110_arrangements(organisation_app)

    event = client.get(f"/api/organisation/events/{event_id}", headers=headers()).json["event"]

    assert event["venue_arrangements"][0] == {
        "booking_id": event["venue_arrangements"][0]["booking_id"],
        "venue": "Harbour Hall",
        "location": "8 Marina Way",
        "date": "2026-12-04",
        "start_time": "09:30",
        "end_time": "12:00",
        "status": "approved",
        "status_label": "Approved",
    }
    assert event["equipment_arrangements"][0] == {
        "requirement_id": event["equipment_arrangements"][0]["requirement_id"],
        "equipment": "Wireless Microphone",
        "required_quantity": 4,
        "reserved_quantity": 4,
        "status": "reserved",
        "status_label": "Reserved",
        "essentiality": "essential",
        "essentiality_label": "Essential",
    }
    assert event["registration_settings"] == {
        "enabled": True,
        "capacity": 75,
        "opens_at": "2026-11-01T09:00:00+08:00",
        "closes_at": "2026-12-03T18:00:00+08:00",
    }


def test_tc_spl_110_004_reports_missing_configuration_without_fabricating_values(
    organisation_app, client
):
    event_id = seed_event(
        organisation_app,
        organiser=ORGANISER_TWO,
        organisation_id=1,
        name="No arrangements yet",
        status="planning",
    )

    event = client.get(f"/api/organisation/events/{event_id}", headers=headers()).json["event"]

    assert event["coordinator"] is None
    assert event["venue_arrangements"] == []
    assert event["equipment_arrangements"] == []
    assert event["registration_settings"] == {
        "enabled": False,
        "capacity": None,
        "opens_at": None,
        "closes_at": None,
    }


def test_tc_spl_110_005_labels_pending_review_and_unavailable_arrangements(
    organisation_app, client
):
    event_id = seed_spl110_arrangements(organisation_app)

    event = client.get(f"/api/organisation/events/{event_id}", headers=headers()).json["event"]

    assert [(item["venue"], item["status_label"]) for item in event["venue_arrangements"]] == [
        ("Harbour Hall", "Approved"),
        ("Studio One", "Review required"),
    ]
    equipment_states = [
        (item["equipment"], item["status_label"]) for item in event["equipment_arrangements"]
    ]
    assert equipment_states == [
        ("Wireless Microphone", "Reserved"),
        ("Projector", "Unavailable"),
    ]


def test_tc_spl_110_006_excludes_internal_event_equipment_and_venue_notes(organisation_app, client):
    event_id = seed_spl110_arrangements(organisation_app)

    response = client.get(f"/api/organisation/events/{event_id}", headers=headers())
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    for private_field in ("event_notes", "approval_note", "notes"):
        assert private_field not in response.json["event"]
    for private_value in (
        "Internal coordinator handover",
        "Venue Staff internal note",
        "Internal equipment note",
    ):
        assert private_value not in body


def test_tc_spl_110_007_get_is_read_only_and_creates_no_arrangement_state(organisation_app, client):
    event_id = seed_event(
        organisation_app,
        organiser=ORGANISER_TWO,
        organisation_id=1,
        name="Read only",
        status="planning",
    )

    response = client.get(f"/api/organisation/events/{event_id}", headers=headers())

    assert response.status_code == 200
    with Session(organisation_app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assert event.coordinator_assignment is None
        assert event.venue_bookings == []
        assert event.equipment_requirements == []
        assert event.registration_opens_at is None
        assert event.registration_closes_at is None
        assert event.registration_capacity is None


def test_tc_spl_110_008_reload_reflects_the_latest_saved_state(organisation_app, client):
    event_id = seed_spl110_arrangements(organisation_app, configured_registration=False)
    path = f"/api/organisation/events/{event_id}"

    before = client.get(path, headers=headers()).json["event"]
    with Session(organisation_app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.registration_opens_at = datetime(2026, 11, 2, 9, 0, tzinfo=SINGAPORE)
        event.registration_closes_at = datetime(2026, 12, 2, 18, 0, tzinfo=SINGAPORE)
        event.registration_capacity = 60
        session.commit()
    after = client.get(path, headers=headers()).json["event"]

    assert before["registration_settings"]["enabled"] is False
    assert after["registration_settings"] == {
        "enabled": True,
        "capacity": 60,
        "opens_at": "2026-11-02T09:00:00+08:00",
        "closes_at": "2026-12-02T18:00:00+08:00",
    }
