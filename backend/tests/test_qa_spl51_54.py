"""QA acceptance test scripts for SPL-51..SPL-54 (CS-E03-S1..S4).

Each function below is the automated evidence for one QA test case ID in the
QA-SPL-51 / QA-SPL-52 / QA-SPL-53 / QA-SPL-54 Confluence reports (QA SPACE).
Function names embed the test case ID so a reader can jump from the report
straight to the exact assertion. This file only holds cases that had no
existing automated coverage; the QA reports also cite pre-existing tests in
test_event_requests.py, test_event_request_submission.py, test_slots.py and
EventRequestForm.test.tsx directly where that coverage already existed.

Fixtures and helpers are reused from test_event_requests.py rather than
duplicated. `client`/`event_app` are not imported here: they're re-exported from
conftest.py so pytest resolves them by fixture name without ruff flagging a
parameter-name/import shadow (F811).
"""

from datetime import date

from app.models import EventRequest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_event_requests import create_event, event_payload, headers

# ---------------------------------------------------------------------------
# QA-SPL-51 (CS-E03-S1 — core event request details)
# ---------------------------------------------------------------------------


def test_qa_spl51_006_proposed_date_of_today_is_the_accepted_lower_boundary(client):
    """QA-SPL-51-006 [Boundary Testing] AC3: today is not 'in the past'."""

    created = create_event(client, proposed_date=date.today().isoformat())

    assert created["proposed_date"] == date.today().isoformat()


def test_qa_spl51_008_smallest_valid_expected_attendance_is_accepted(client):
    """QA-SPL-51-008 [Boundary Testing] AC4: 1 is the lower valid boundary."""

    created = create_event(client, expected_attendance=1)

    assert created["expected_attendance"] == 1


# ---------------------------------------------------------------------------
# QA-SPL-52 (CS-E03-S2 — venue requirements)
# ---------------------------------------------------------------------------


def test_qa_spl52_001_every_venue_requirement_field_round_trips_exactly(client):
    """QA-SPL-52-001 [Happy Flow] AC1: every venue field is stored and echoed back."""

    created = create_event(
        client,
        preferred_room_layout="Theatre",
        required_facilities=["Projector", "Step-free access"],
        facilities_notes="Two wireless microphones",
        accessibility_needs="Reserved wheelchair spaces",
        location_preference="Central",
        venue_notes="Near public transport",
    )

    assert created["preferred_room_layout"] == "Theatre"
    assert created["required_facilities"] == ["Projector", "Step-free access"]
    assert created["facilities_notes"] == "Two wireless microphones"
    assert created["accessibility_needs"] == "Reserved wheelchair spaces"
    assert created["location_preference"] == "Central"
    assert created["venue_notes"] == "Near public transport"


def test_qa_spl52_007_every_venue_requirement_field_is_optional_at_creation(client):
    """QA-SPL-52-007 [Boundary Testing] AC3: only the 6 mandatory core fields sent."""

    payload = event_payload()
    for field in (
        "preferred_room_layout",
        "required_facilities",
        "facilities_notes",
        "accessibility_needs",
        "location_preference",
        "venue_notes",
        "venue_id",
    ):
        payload.pop(field, None)

    response = client.post("/api/event-requests", json=payload, headers=headers())

    assert response.status_code == 201
    created = response.json["event_request"]
    assert created["preferred_room_layout"] is None
    assert created["required_facilities"] == []
    assert created["facilities_notes"] is None
    assert created["accessibility_needs"] is None
    assert created["location_preference"] is None
    assert created["venue_notes"] is None
    assert created["venue_id"] is None


def test_qa_spl52_009_coordinator_sees_the_same_venue_fields_as_the_organiser(client):
    """QA-SPL-52-009 [Cross Cut Quality Expectations] AC4: visible to coordinator."""

    created = create_event(
        client,
        preferred_room_layout="Boardroom",
        required_facilities=["Whiteboard"],
        location_preference="Riverside",
    )

    seen_by_coordinator = client.get(
        f"/api/event-requests/{created['id']}", headers=headers("coordinator")
    )

    assert seen_by_coordinator.status_code == 200
    body = seen_by_coordinator.json["event_request"]
    assert body["preferred_room_layout"] == "Boardroom"
    assert body["required_facilities"] == ["Whiteboard"]
    assert body["location_preference"] == "Riverside"


# ---------------------------------------------------------------------------
# QA-SPL-53 (CS-E03-S3 — equipment requirements)
# ---------------------------------------------------------------------------


def test_qa_spl53_001_zero_equipment_lines_is_valid(client):
    """QA-SPL-53-001 [Boundary Testing] AC1/AC4: an explicit empty list is accepted."""

    created = create_event(client, equipment_requirements=[])

    assert created["equipment_requirements"] == []


def test_qa_spl53_003_blank_equipment_type_is_rejected(client, event_app):
    """QA-SPL-53-003 [Negative Testing] AC1: whitespace-only equipment_type is refused."""

    response = client.post(
        "/api/event-requests",
        json=event_payload(equipment_requirements=[{"equipment_type": "   ", "quantity": 1}]),
        headers=headers(),
    )

    assert response.status_code == 400
    assert response.json == {"error": "Equipment requirement 1 type is required."}
    with Session(event_app.extensions["engine"]) as session:
        assert session.scalars(select(EventRequest)).all() == []


def test_qa_spl53_006_non_integer_equipment_quantity_is_rejected(client):
    """QA-SPL-53-006 [Negative Testing] AC2: a decimal quantity is refused."""

    response = client.post(
        "/api/event-requests",
        json=event_payload(equipment_requirements=[{"equipment_type": "Lectern", "quantity": 1.5}]),
        headers=headers(),
    )

    assert response.status_code == 400
    assert response.json == {
        "error": "Equipment requirement 1 quantity must be a positive whole number."
    }


def test_qa_spl53_007_equipment_type_outside_any_catalogue_is_accepted(client):
    """QA-SPL-53-007 [Happy Flow] AC3: equipment_type is free text, by design.

    AC3 was corrected on the Jira ticket (no concrete customer requirement for a
    Technical Support Staff catalogue exists) to describe this free-text
    behaviour directly, so an arbitrary descriptive string being accepted is the
    expected, correct outcome rather than a gap pending a future catalogue.
    """

    equipment_type = "Not a real catalogue item xyz123"
    created = create_event(
        client,
        equipment_requirements=[{"equipment_type": equipment_type, "quantity": 1}],
    )

    assert created["equipment_requirements"][0]["equipment_type"] == equipment_type


def test_qa_spl53_008_regression_equipment_requirements_matches_the_live_frontend_contract(client):
    """QA-SPL-53-008 [Regression] Re-verifies a former release-blocking defect is fixed.

    Previously (QA-CS-E03-S3 / commit-level state before this branch) the live
    EventRequestForm.tsx submitted equipment lines under the key
    'equipment_lines' while the backend only accepted 'equipment_requirements',
    so every real submission with equipment failed with a 400. The frontend has
    since been changed to send 'equipment_requirements' (see
    frontend/src/EventRequestForm.tsx submit handler); this proves the backend
    now accepts that exact shape end to end.
    """

    equipment_line = {"equipment_type": "Lectern", "quantity": 1, "notes": None}
    response = client.post(
        "/api/event-requests",
        json=event_payload(equipment_requirements=[equipment_line]),
        headers=headers(),
    )

    assert response.status_code == 201
    created_line = response.json["event_request"]["equipment_requirements"][0]
    assert created_line["equipment_type"] == "Lectern"


def test_qa_spl53_009_omitting_equipment_requirements_entirely_defaults_to_an_empty_list(client):
    """QA-SPL-53-009 [Boundary Testing] AC4: the key can be left out entirely, not just empty."""

    payload = event_payload()
    payload.pop("equipment_requirements")

    response = client.post("/api/event-requests", json=payload, headers=headers())

    assert response.status_code == 201
    assert response.json["event_request"]["equipment_requirements"] == []


# ---------------------------------------------------------------------------
# QA-SPL-54 (CS-E03-S4 — registration needs)
# ---------------------------------------------------------------------------


def test_qa_spl54_001_registration_required_defaults_to_false_when_omitted(client):
    """QA-SPL-54-001 [Boundary Testing] AC1: the key can be left out entirely."""

    payload = event_payload()
    payload.pop("registration_required")
    payload.pop("registration_notes", None)

    response = client.post("/api/event-requests", json=payload, headers=headers())

    assert response.status_code == 201
    assert response.json["event_request"]["registration_required"] is False


def test_qa_spl54_002_registration_required_true_with_notes_round_trips(client):
    """QA-SPL-54-002 [Happy Flow] AC1/AC2: explicit true plus free-text notes."""

    created = create_event(
        client, registration_required=True, registration_notes="Collect name and email"
    )

    assert created["registration_required"] is True
    assert created["registration_notes"] == "Collect name and email"


def test_qa_spl54_004_registration_notes_stay_null_when_false_and_omitted(client):
    """QA-SPL-54-004 [Boundary Testing] AC2: notes are not force-set when registration is off."""

    payload = event_payload(registration_required=False)
    payload.pop("registration_notes", None)

    response = client.post("/api/event-requests", json=payload, headers=headers())

    assert response.status_code == 201
    assert response.json["event_request"]["registration_notes"] is None


def test_qa_spl54_005_coordinator_sees_registration_fields(client):
    """QA-SPL-54-005 [Cross Cut Quality Expectations] AC3: visible to the Event Coordinator."""

    created = create_event(client, registration_required=True, registration_notes="Bring photo ID")

    seen_by_coordinator = client.get(
        f"/api/event-requests/{created['id']}", headers=headers("coordinator")
    )

    assert seen_by_coordinator.status_code == 200
    body = seen_by_coordinator.json["event_request"]
    assert body["registration_required"] is True
    assert body["registration_notes"] == "Bring photo ID"
