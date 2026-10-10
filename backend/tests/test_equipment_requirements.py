"""SPL-90 API and boundary tests for coordinator equipment planning."""

from datetime import date, datetime

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy.orm import Session

ORGANISER = "00000000-0000-0000-0000-000000000901"
COORDINATOR = "00000000-0000-0000-0000-000000000902"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000903"
TECHNICAL_SUPPORT = "00000000-0000-0000-0000-000000000904"
ATTENDEE = "00000000-0000-0000-0000-000000000905"
EVENT_DATE = date(2026, 10, 14)


@pytest.fixture
def app(tmp_path):
    """Create one assigned Planning event with legacy organiser equipment wording."""
    tokens = {
        "organiser": ORGANISER,
        "coordinator": COORDINATOR,
        "other-coordinator": OTHER_COORDINATOR,
        "technical": TECHNICAL_SUPPORT,
        "attendee": ATTENDEE,
    }
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/equipment-requirements.db",
            "IDENTITY_VERIFIER": tokens.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        session.add(organisation)
        session.flush()
        session.add_all(
            [
                Account(
                    id=ORGANISER,
                    display_name="Olivia Organiser",
                    organisation_id=organisation.id,
                ),
                Account(id=COORDINATOR, display_name="Casey Coordinator"),
                Account(id=OTHER_COORDINATOR, display_name="Devon Coordinator"),
                Account(id=TECHNICAL_SUPPORT, display_name="Taylor Technical"),
                Account(id=ATTENDEE, display_name="Avery Attendee"),
            ]
        )
        session.add_all(
            [
                AccountRole(account_id=ORGANISER, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=COORDINATOR, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=OTHER_COORDINATOR, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=TECHNICAL_SUPPORT, role=Role.TECHNICAL_SUPPORT_STAFF.value),
                AccountRole(account_id=ATTENDEE, role=Role.ATTENDEE.value),
            ]
        )
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=organisation.id,
            name="Northstar Innovation Forum",
            purpose="Share the annual innovation plan",
            proposed_date=EVENT_DATE,
            start_time=datetime.strptime("09:00", "%H:%M").time(),
            end_time=datetime.strptime("12:00", "%H:%M").time(),
            expected_attendance=100,
            status="planning",
            required_facilities=[],
            accessibility_needs=[],
            registration_required=False,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=COORDINATOR,
                assigned_at=datetime(2026, 10, 1, 9, tzinfo=SINGAPORE),
            )
        )
        session.add_all(
            [
                EquipmentRequirement(
                    event_request_id=event.id,
                    equipment_type="Wireless microphone",
                    quantity=4,
                    notes="For panel discussion.",
                    required_start_date=EVENT_DATE,
                    required_end_date=EVENT_DATE,
                ),
                EquipmentType(
                    name="Wireless Microphone",
                    normalised_name="wireless microphone",
                    description="Handheld microphone with receiver.",
                    location="Technical Store A",
                    total_stock=12,
                ),
            ]
        )
        session.commit()
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"}


def endpoint(requirement_id: int | None = None):
    path = "/api/event-requests/1/equipment-requirements"
    return f"{path}/{requirement_id}" if requirement_id is not None else path


def valid_payload(**overrides):
    """Provide one valid catalogue-backed requirement for concise boundary tests."""
    payload = {
        "equipment_type_id": 1,
        "quantity": 4,
        "notes": "For panel discussion.",
        "required_start_date": EVENT_DATE.isoformat(),
        "required_end_date": EVENT_DATE.isoformat(),
        "essentiality": "undecided",
    }
    payload.update(overrides)
    return payload


# SPL-90 AC-1 / TC-SPL-90-001: the assigned coordinator sees retained organiser wording once.
def test_tc_spl_90_001_lists_retained_organiser_requirements_and_catalogue_choices(client):
    response = client.get(endpoint(), headers=headers())

    assert response.status_code == 200
    assert response.json["event"] == {
        "id": 1,
        "name": "Northstar Innovation Forum",
        "proposed_date": "2026-10-14",
        "status": "planning",
    }
    assert response.json["requirements"][0]["organiser_equipment_text"] == "Wireless microphone"
    assert response.json["requirements"][0]["status"] == "unmapped"
    assert response.json["equipment_types"][0]["name"] == "Wireless Microphone"


# SPL-90 AC-1 / TC-SPL-90-002: mapping preserves original wording and safely derives D-1.
def test_tc_spl_90_002_maps_legacy_wording_without_creating_a_duplicate(client):
    response = client.patch(endpoint(1), json=valid_payload(), headers=headers())

    assert response.status_code == 200
    requirement = response.json["requirement"]
    assert requirement["organiser_equipment_text"] == "Wireless microphone"
    assert requirement["equipment_type"]["name"] == "Wireless Microphone"
    assert requirement["status"] == "requested"
    assert requirement["collection_date"] == "2026-10-13"
    assert requirement["planned_return_date"] == "2026-10-14"
    reopened = client.get(endpoint(), headers=headers())
    assert len(reopened.json["requirements"]) == 1


# SPL-90 AC-2 / TC-SPL-90-003: a coordinator can record an additional catalogue requirement.
def test_tc_spl_90_003_adds_a_catalogue_backed_requirement(client):
    response = client.post(
        endpoint(),
        json=valid_payload(quantity=2, notes="For registration desk."),
        headers=headers(),
    )

    assert response.status_code == 201
    assert response.json["requirement"]["status"] == "requested"
    assert response.json["requirement"]["organiser_equipment_text"] == "Wireless Microphone"
    assert response.json["requirement"]["quantity"] == 2


# SPL-90 AC-2 / TC-SPL-90-004: quantities and dates reject invalid/boundary input at the API.
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("quantity", 0, "Quantity must be a positive whole number."),
        ("quantity", 1.5, "Quantity must be a positive whole number."),
        ("quantity", True, "Quantity must be a positive whole number."),
        (
            "required_start_date",
            "2026-10-13",
            "Equipment requirement dates must fall within this event's recorded date.",
        ),
        ("equipment_type_id", 999, "Choose an equipment type from the catalogue."),
    ],
)
def test_tc_spl_90_004_rejects_invalid_requirement_boundaries(client, field, value, message):
    response = client.post(endpoint(), json=valid_payload(**{field: value}), headers=headers())

    assert response.status_code == 400
    assert response.json["error"] == message


# SPL-90 AC-3 / TC-SPL-90-005: Essential decisions retain consultation, note, actor and time.
def test_tc_spl_90_005_records_an_essentiality_decision_after_technical_consultation(client):
    response = client.patch(
        endpoint(1),
        json=valid_payload(
            essentiality="essential",
            consulted_technical_support_account_id=TECHNICAL_SUPPORT,
            essentiality_decision_note="Microphones are needed for every panel speaker.",
        ),
        headers=headers(),
    )

    assert response.status_code == 200
    requirement = response.json["requirement"]
    assert requirement["essentiality"] == "essential"
    assert requirement["consulted_technical_support"] == {
        "id": TECHNICAL_SUPPORT,
        "name": "Taylor Technical",
    }
    assert (
        requirement["essentiality_decision_note"]
        == "Microphones are needed for every panel speaker."
    )
    assert requirement["essentiality_decided_by"]["id"] == COORDINATOR
    assert requirement["essentiality_decided_at"] is not None


# SPL-90 AC-3 / TC-SPL-90-006: a criticality decision cannot be forged without real consultation.
@pytest.mark.parametrize(
    "overrides",
    [
        {"essentiality": "essential"},
        {
            "essentiality": "essential",
            "consulted_technical_support_account_id": ATTENDEE,
            "essentiality_decision_note": "Needed.",
        },
        {
            "essentiality": "non_essential",
            "consulted_technical_support_account_id": TECHNICAL_SUPPORT,
            "essentiality_decision_note": "   ",
        },
    ],
)
def test_tc_spl_90_006_requires_valid_consultation_evidence(client, overrides):
    response = client.patch(endpoint(1), json=valid_payload(**overrides), headers=headers())

    assert response.status_code == 400


# SPL-90 AC-4 / TC-SPL-90-007: removal is soft so the requirement remains visible as history.
def test_tc_spl_90_007_soft_removes_an_unreserved_requirement_with_audit_timestamp(client):
    response = client.delete(endpoint(1), headers=headers())

    assert response.status_code == 200
    assert response.json["requirement"]["status"] == "removed"
    assert response.json["requirement"]["removed_at"] is not None
    reopened = client.get(endpoint(), headers=headers())
    assert reopened.json["requirements"] == []
    assert (
        reopened.json["removed_requirements"][0]["organiser_equipment_text"]
        == "Wireless microphone"
    )


# TC-SPL-97-14 — coordinator edits and removals recheck the line after stock work is committed.
def test_tc_spl_97_14_reserved_requirement_cannot_be_edited_or_removed(client):
    """Regression: a coordinator cannot overwrite or remove a line once reservation work exists."""

    assert client.patch(endpoint(1), json=valid_payload(), headers=headers()).status_code == 200
    with Session(client.application.extensions["engine"]) as session:
        session.get(EquipmentRequirement, 1).status = "partially_reserved"
        session.commit()

    edit = client.patch(endpoint(1), json={"quantity": 1}, headers=headers())
    remove = client.delete(endpoint(1), headers=headers())

    assert edit.status_code == 409
    assert remove.status_code == 409
    assert "unreserved" in edit.json["error"]
    assert "unreserved" in remove.json["error"]


# SPL-90 AC-4 / TC-SPL-90-008: only the assigned coordinator can read or change this event.
@pytest.mark.parametrize(
    "token, expected",
    [("organiser", 403), ("attendee", 403), ("other-coordinator", 404)],
)
def test_tc_spl_90_008_denies_untrusted_or_unassigned_callers(client, token, expected):
    response = client.get(endpoint(), headers=headers(token))

    assert response.status_code == expected
