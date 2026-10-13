"""Acceptance coverage for SPL-93: unavailable event requirement decisions."""

from datetime import date, datetime, time

import pytest
from app import create_app
from app import equipment_requirement_unavailability as unavailability
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentRequirementUnavailabilityRecord,
    EquipmentReservation,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

TECHNICAL_SUPPORT = "00000000-0000-0000-0000-000000000931"
COORDINATOR = "00000000-0000-0000-0000-000000000932"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000933"
ORGANISER = "00000000-0000-0000-0000-000000000934"
NOW = datetime(2026, 10, 12, 10, 15, tzinfo=unavailability.SINGAPORE)


@pytest.fixture
def database_url(tmp_path):
    return f"sqlite:///{tmp_path}/requirement-unavailability.db"


@pytest.fixture
def app(database_url, monkeypatch):
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organisation(id=931, name="Northstar Community Partners"))
        session.add_all(
            [
                Account(id=TECHNICAL_SUPPORT, display_name="Taylor Technical", is_active=True),
                Account(id=COORDINATOR, display_name="Casey Coordinator", is_active=True),
                Account(id=OTHER_COORDINATOR, display_name="Jordan Coordinator", is_active=True),
                Account(id=ORGANISER, display_name="Olivia Organiser", is_active=True),
            ]
        )
        session.flush()
        session.add_all(
            [
                AccountRole(account_id=TECHNICAL_SUPPORT, role=Role.TECHNICAL_SUPPORT_STAFF.value),
                AccountRole(account_id=COORDINATOR, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=OTHER_COORDINATOR, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=ORGANISER, role=Role.EVENT_ORGANISER.value),
            ]
        )
        session.add(
            EquipmentType(
                id=1,
                name="Wireless Microphone",
                normalised_name="wireless microphone",
                total_stock=12,
            )
        )
        event = EventRequest(
            id=1,
            organiser_account_id=ORGANISER,
            organisation_id=931,
            name="Community Leadership Forum",
            purpose="Annual leadership programme",
            proposed_date=date(2026, 11, 20),
            start_time=time(14),
            end_time=time(17),
            expected_attendance=80,
            status="planning",
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=1,
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=ORGANISER,
                assigned_at=NOW,
            )
        )
        session.add_all(
            [
                EquipmentRequirement(
                    id=1,
                    event_request_id=1,
                    equipment_type="Wireless microphones",
                    quantity=4,
                    equipment_type_id=1,
                    required_start_date=date(2026, 11, 20),
                    required_end_date=date(2026, 11, 21),
                    status="requested",
                ),
                EquipmentRequirement(
                    id=2,
                    event_request_id=1,
                    equipment_type="Spare microphones",
                    quantity=2,
                    equipment_type_id=1,
                    required_start_date=date(2026, 11, 20),
                    required_end_date=date(2026, 11, 21),
                    status="requested",
                ),
            ]
        )
        session.flush()
        session.add(
            EquipmentReservation(
                event_request_id=1,
                equipment_requirement_id=2,
                equipment_type_id=1,
                commitment_start_date=date(2026, 11, 19),
                commitment_end_date=date(2026, 11, 21),
                quantity=1,
                reserved_by_account_id=TECHNICAL_SUPPORT,
                reserved_at=NOW,
            )
        )
        session.commit()
    application = create_app(
        {"TESTING": True, "DATABASE_URL": database_url, "IDENTITY_VERIFIER": lambda token: token}
    )
    monkeypatch.setattr(unavailability, "_now", lambda: NOW)
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(identity=TECHNICAL_SUPPORT):
    return {"Authorization": f"Bearer {identity}"}


def mark(client, requirement_id=1, identity=TECHNICAL_SUPPORT, **payload):
    return client.post(
        f"/api/equipment-requirements/{requirement_id}/mark-unavailable",
        headers=headers(identity),
        json=payload,
    )


# TC-SPL-93-001 — AC1: an unheld Requested line receives a required reason and optional suggestion.
def test_tc_spl_93_001_marks_an_unheld_requested_line_unavailable_with_auditable_reason(
    app, client
):
    response = mark(
        client, reason="Supplier recall", alternative_suggestion="Use wired microphones"
    )

    assert response.status_code == 201
    assert response.json["requirement"] == {"id": 1, "status": "unavailable"}
    assert response.json["record"]["reason"] == "Supplier recall"
    assert response.json["record"]["alternative_suggestion"] == "Use wired microphones"
    assert response.json["record"]["recorded_at"].startswith("2026-10-12T10:15")
    with Session(app.extensions["engine"]) as session:
        assert session.get(EquipmentRequirement, 1).status == "unavailable"
        record = session.scalar(select(EquipmentRequirementUnavailabilityRecord))
        assert (record.action, record.recorded_by_account_id) == (
            "marked_unavailable",
            TECHNICAL_SUPPORT,
        )


# TC-SPL-93-002 — AC1: a blank reason or wrong state never changes the line.
@pytest.mark.parametrize(
    "payload, requirement_id",
    [
        ({"reason": "   "}, 1),
        ({"reason": "Valid reason", "unexpected": True}, 1),
        ({"reason": "Already held"}, 2),
    ],
)
def test_tc_spl_93_002_refuses_invalid_or_reserved_marking_without_mutation(
    app, client, payload, requirement_id
):
    response = mark(client, requirement_id, **payload)

    assert response.status_code in (400, 409)
    with Session(app.extensions["engine"]) as session:
        assert session.get(EquipmentRequirement, requirement_id).status == "requested"
        assert session.query(EquipmentRequirementUnavailabilityRecord).count() == 0
        assert session.query(EquipmentReservation).count() == 1


# TC-SPL-93-003 — AC2: the assigned coordinator sees status, reason and suggestion on that line.
def test_tc_spl_93_003_coordinator_sees_the_unavailable_decision_without_other_line_changes(
    app, client
):
    assert (
        mark(
            client, reason="Supplier recall", alternative_suggestion="Use wired microphones"
        ).status_code
        == 201
    )

    response = client.get(
        "/api/event-requests/1/equipment-requirements", headers=headers(COORDINATOR)
    )

    assert response.status_code == 200
    affected = next(line for line in response.json["requirements"] if line["id"] == 1)
    unaffected = next(line for line in response.json["requirements"] if line["id"] == 2)
    assert affected["status"] == "unavailable"
    assert len(affected["unavailability_history"]) == 1
    history = affected["unavailability_history"][0]
    assert history["id"] == 1
    assert history["action"] == "marked_unavailable"
    assert history["reason"] == "Supplier recall"
    assert history["alternative_suggestion"] == "Use wired microphones"
    assert history["recorded_by"] == {"id": TECHNICAL_SUPPORT, "name": "Taylor Technical"}
    # SQLite stores the same clock time without its offset; PostgreSQL preserves the offset.
    assert history["recorded_at"].startswith("2026-10-12T10:15")
    assert (unaffected["status"], unaffected["unavailability_history"]) == ("requested", [])


# TC-SPL-93-004 — AC2: a non-Technical Support caller cannot change a line or its reservations.
@pytest.mark.parametrize("identity", [COORDINATOR, OTHER_COORDINATOR, ORGANISER])
def test_tc_spl_93_004_only_technical_support_can_mark_a_requirement(app, client, identity):
    response = mark(client, identity=identity, reason="Unauthorised change")

    assert response.status_code == 403
    with Session(app.extensions["engine"]) as session:
        assert session.get(EquipmentRequirement, 1).status == "requested"
        assert session.query(EquipmentReservation).count() == 1
        assert session.query(EquipmentRequirementUnavailabilityRecord).count() == 0


# TC-SPL-93-005 — AC3: restore returns the line to Requested but keeps both audit entries.
def test_tc_spl_93_005_restores_unavailable_to_requested_and_retains_original_reason(app, client):
    assert (
        mark(
            client, reason="Supplier recall", alternative_suggestion="Use wired microphones"
        ).status_code
        == 201
    )
    response = client.post("/api/equipment-requirements/1/restore-requested", headers=headers())

    assert response.status_code == 200
    assert response.json["requirement"] == {"id": 1, "status": "requested"}
    with Session(app.extensions["engine"]) as session:
        history = session.scalars(
            select(EquipmentRequirementUnavailabilityRecord).order_by(
                EquipmentRequirementUnavailabilityRecord.id
            )
        ).all()
        assert [
            (entry.action, entry.reason, entry.recorded_by_account_id) for entry in history
        ] == [
            ("marked_unavailable", "Supplier recall", TECHNICAL_SUPPORT),
            ("restored_to_requested", None, TECHNICAL_SUPPORT),
        ]


# TC-SPL-93-006 — AC3: restore is a guarded transition and does not erase history on refusal.
def test_tc_spl_93_006_restore_rejects_wrong_state_or_role_without_erasing_history(app, client):
    assert (
        client.post(
            "/api/equipment-requirements/1/restore-requested", headers=headers()
        ).status_code
        == 409
    )
    assert mark(client, reason="Supplier recall").status_code == 201
    assert (
        client.post(
            "/api/equipment-requirements/1/restore-requested", headers=headers(COORDINATOR)
        ).status_code
        == 403
    )
    with Session(app.extensions["engine"]) as session:
        assert session.get(EquipmentRequirement, 1).status == "unavailable"
        assert [
            (entry.action, entry.reason)
            for entry in session.scalars(select(EquipmentRequirementUnavailabilityRecord))
        ] == [("marked_unavailable", "Supplier recall")]


# TC-SPL-93-010/011 — closed or pre-planning events cannot acquire availability decisions.
@pytest.mark.parametrize(
    "event_status",
    [
        "cancelled",
        "completed",
        "draft",
        "submitted",
        "under_review",
        "returned_for_clarification",
        "approved",
        "rejected",
        "withdrawn",
    ],
)
@pytest.mark.parametrize("action", ["mark-unavailable", "restore-requested"])
def test_closed_or_inactive_event_refuses_decision_without_mutating_history(
    app, client, event_status, action
):
    if action == "restore-requested":
        assert (
            mark(client, reason="Supplier recall", alternative_suggestion="Use wired").status_code
            == 201
        )
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, 1).status = event_status
        session.commit()
        previous = [
            unavailability.serialize_record(record)
            for record in unavailability.history_for(session, 1)
        ]
        line_status = session.get(EquipmentRequirement, 1).status
    response = client.post(
        f"/api/equipment-requirements/1/{action}",
        headers=headers(),
        json={"reason": "New decision"} if action == "mark-unavailable" else None,
    )
    assert response.status_code == 409
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, 1).status == event_status
        assert session.get(EquipmentRequirement, 1).status == line_status
        assert [
            unavailability.serialize_record(record)
            for record in unavailability.history_for(session, 1)
        ] == previous
        assert session.get(EquipmentRequirement, 2).status == "requested"
        assert session.query(EquipmentReservation).count() == 1


@pytest.mark.parametrize("event_status", ["planning", "confirmed", "postponed"])
def test_active_event_allows_mark_and_restore(app, client, event_status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, 1).status = event_status
        session.commit()
    assert mark(client, reason="Supplier recall").status_code == 201
    assert (
        client.post(
            "/api/equipment-requirements/1/restore-requested", headers=headers()
        ).status_code
        == 200
    )
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, 1).status == event_status
        assert session.get(EquipmentRequirement, 1).status == "requested"
        assert len(unavailability.history_for(session, 1)) == 2
