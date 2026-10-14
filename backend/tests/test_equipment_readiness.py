"""Acceptance coverage for SPL-99: coordinator equipment readiness."""

from datetime import date, datetime, time

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentRequirementUnavailabilityRecord,
    EquipmentReservation,
    EquipmentReservationRelease,
    EquipmentReviewNote,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000000991"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000000992"
TECHNICAL = "00000000-0000-0000-0000-000000000993"
ORGANISER = "00000000-0000-0000-0000-000000000994"
NOW = datetime(2026, 10, 14, 9, 30, tzinfo=SINGAPORE)
EVENT_DATE = date(2026, 11, 20)


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/equipment-readiness.db",
            "IDENTITY_VERIFIER": {
                "coordinator": COORDINATOR,
                "other-coordinator": OTHER_COORDINATOR,
                "technical": TECHNICAL,
                "organiser": ORGANISER,
            }.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organisation(id=99, name="Northstar Community Partners"))
        accounts = [
            (COORDINATOR, "Casey Coordinator", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Jordan Coordinator", Role.EVENT_COORDINATOR),
            (TECHNICAL, "Taylor Technical", Role.TECHNICAL_SUPPORT_STAFF),
            (ORGANISER, "Olivia Organiser", Role.EVENT_ORGANISER),
        ]
        for account_id, name, role in accounts:
            session.add(Account(id=account_id, display_name=name, is_active=True))
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.add(
            EquipmentType(
                id=1,
                name="Wireless Microphone",
                normalised_name="wireless microphone",
                total_stock=12,
            )
        )
        session.commit()
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(identity="coordinator"):
    return {} if identity is None else {"Authorization": f"Bearer {identity}"}


def add_event(app, *, status="planning", assigned=True):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=99,
            name="Community Leadership Forum",
            purpose="Annual leadership programme",
            proposed_date=EVENT_DATE,
            start_time=time(14),
            end_time=time(17),
            expected_attendance=80,
            status=status,
            submitted_at=NOW,
        )
        session.add(event)
        session.flush()
        if assigned:
            session.add(
                EventCoordinatorAssignment(
                    event_request_id=event.id,
                    coordinator_account_id=COORDINATOR,
                    assigned_by_account_id=ORGANISER,
                    assigned_at=NOW,
                )
            )
        session.commit()
        return event.id


def add_line(
    app,
    event_id,
    *,
    quantity=4,
    status="requested",
    essentiality="undecided",
    mapped=True,
    review_reason=None,
    text="Wireless microphones",
):
    with Session(app.extensions["engine"]) as session:
        line = EquipmentRequirement(
            event_request_id=event_id,
            equipment_type=text,
            equipment_type_id=1 if mapped else None,
            quantity=quantity,
            notes="Use the main stage sockets.",
            required_start_date=EVENT_DATE,
            required_end_date=EVENT_DATE,
            status=status,
            essentiality=essentiality,
            review_reason=review_reason,
            review_flagged_at=NOW if review_reason else None,
        )
        session.add(line)
        session.commit()
        return line.id


def add_reservation(app, event_id, line_id, quantity, return_date, *, released=0):
    with Session(app.extensions["engine"]) as session:
        reservation = EquipmentReservation(
            event_request_id=event_id,
            equipment_requirement_id=line_id,
            equipment_type_id=1,
            commitment_start_date=date(2026, 11, 19),
            commitment_end_date=return_date,
            quantity=quantity,
            reserved_by_account_id=TECHNICAL,
            reserved_at=NOW,
        )
        session.add(reservation)
        session.flush()
        if released:
            session.add(
                EquipmentReservationRelease(
                    reservation_id=reservation.id,
                    quantity=released,
                    reason="Units returned early.",
                    released_by_account_id=TECHNICAL,
                    released_at=NOW,
                )
            )
        session.commit()
        return reservation.id


def detail(client, event_id, identity="coordinator"):
    return client.get(f"/api/event-requests/assigned/{event_id}", headers=headers(identity))


# TC-SPL-99-001 — AC1: every operational field and reason reaches the assigned coordinator.
def test_tc_spl_99_001_serializes_quantities_return_date_notes_and_reasons(app, client):
    event_id = add_event(app)
    line_id = add_line(
        app,
        event_id,
        status="review_required",
        essentiality="essential",
        review_reason="Dates changed after reservation.",
    )
    add_reservation(app, event_id, line_id, 2, date(2026, 11, 21), released=1)
    add_reservation(app, event_id, line_id, 2, date(2026, 11, 23))
    with Session(app.extensions["engine"]) as session:
        session.add(
            EquipmentReviewNote(
                equipment_requirement_id=line_id,
                note="Confirm the replacement frequency.",
                author_account_id=TECHNICAL,
                created_at=NOW,
            )
        )
        session.add(
            EquipmentRequirementUnavailabilityRecord(
                equipment_requirement_id=line_id,
                action="marked_unavailable",
                reason="Supplier recall",
                alternative_suggestion="Use wired microphones",
                recorded_by_account_id=TECHNICAL,
                recorded_at=NOW,
            )
        )
        session.commit()

    response = detail(client, event_id)

    assert response.status_code == 200
    line = response.json["event"]["equipment_requirements"][0]
    assert (line["required_quantity"], line["reserved_quantity"]) == (4, 3)
    assert line["status"] == "review_required"
    assert line["planned_return_date"] == "2026-11-23"
    assert line["technical_support_notes"][0]["note"] == "Confirm the replacement frequency."
    assert line["technical_support_notes"][0]["author"]["name"] == "Taylor Technical"
    assert line["unavailability_history"][0]["reason"] == "Supplier recall"
    assert line["outstanding_review_reasons"] == ["Dates changed after reservation."]


# TC-SPL-99-002 — AC1: fully released reservations do not inflate the current line state.
def test_tc_spl_99_002_uses_only_retained_reservation_quantities_and_dates(app, client):
    event_id = add_event(app)
    line_id = add_line(app, event_id, quantity=3, essentiality="non_essential")
    add_reservation(app, event_id, line_id, 2, date(2026, 11, 25), released=2)

    line = detail(client, event_id).json["event"]["equipment_requirements"][0]

    assert line["reserved_quantity"] == 0
    assert line["planned_return_date"] is None
    assert line["active_reservations"] == []


# TC-SPL-99-003 — AC2: essential completion decides readiness; non-essential shortfalls do not.
def test_tc_spl_99_003_ready_when_essential_lines_are_complete_and_decisions_exist(app, client):
    event_id = add_event(app)
    essential_id = add_line(app, event_id, quantity=2, status="reserved", essentiality="essential")
    add_reservation(app, event_id, essential_id, 2, date(2026, 11, 21))
    add_line(app, event_id, quantity=5, essentiality="non_essential", text="Decorative lights")

    readiness = detail(client, event_id).json["event"]["equipment_readiness"]

    assert readiness == {
        "ready": True,
        "has_equipment_blocker": False,
        "active_requirement_count": 2,
        "blockers": [],
    }


# TC-SPL-99-004 — AC2: every failed readiness rule returns a reusable blocker code.
def test_tc_spl_99_004_lists_undecided_unmapped_shortfall_and_review_blockers(app, client):
    event_id = add_event(app)
    add_line(app, event_id, mapped=False)
    essential_id = add_line(
        app,
        event_id,
        quantity=4,
        status="review_required",
        essentiality="essential",
        review_reason="Technical Support must re-check the changed dates.",
    )
    add_reservation(app, event_id, essential_id, 2, date(2026, 11, 21))

    readiness = detail(client, event_id).json["event"]["equipment_readiness"]
    codes = [blocker["code"] for blocker in readiness["blockers"]]

    assert readiness["ready"] is False
    assert readiness["has_equipment_blocker"] is True
    assert codes == [
        "essentiality_undecided",
        "legacy_requirement_unmapped",
        "essential_not_fully_reserved",
        "essential_review_outstanding",
    ]
    assert {blocker["requirement_id"] for blocker in readiness["blockers"]} == {
        1,
        2,
    }


# TC-SPL-99-005 — AC3: an event with no requirements has no equipment blocker.
def test_tc_spl_99_005_no_requirements_means_no_equipment_blocker(app, client):
    event_id = add_event(app, status="confirmed")

    event = detail(client, event_id).json["event"]

    assert event["status"] == "confirmed"
    assert event["equipment_requirements"] == []
    assert event["equipment_readiness"] == {
        "ready": True,
        "has_equipment_blocker": False,
        "active_requirement_count": 0,
        "blockers": [],
    }


# TC-SPL-99-006 — AC3: removed history is visible but does not create an active blocker.
def test_tc_spl_99_006_removed_lines_do_not_block_or_change_the_event(app, client):
    event_id = add_event(app, status="planning")
    add_line(app, event_id, status="removed", mapped=False)

    event = detail(client, event_id).json["event"]

    assert event["status"] == "planning"
    assert event["equipment_requirements"][0]["status"] == "removed"
    assert event["equipment_readiness"]["active_requirement_count"] == 0
    assert event["equipment_readiness"]["has_equipment_blocker"] is False


# TC-SPL-99-007 — AC4: only the assigned coordinator can read this result.
def test_tc_spl_99_007_enforces_assigned_coordinator_scope(app, client):
    event_id = add_event(app)
    add_line(app, event_id)

    assert detail(client, event_id).status_code == 200
    assert detail(client, event_id, "other-coordinator").status_code == 404
    assert detail(client, event_id, "technical").status_code == 403
    assert detail(client, event_id, "organiser").status_code == 403
    assert detail(client, event_id, None).status_code == 401


# TC-SPL-99-008 — AC4: repeated reads create no business or audit mutation.
def test_tc_spl_99_008_readiness_is_read_only(app, client):
    event_id = add_event(app)
    line_id = add_line(app, event_id, essentiality="essential")
    before = _stored_state(app, event_id, line_id)

    first = detail(client, event_id)
    second = detail(client, event_id)

    assert first.status_code == second.status_code == 200
    assert first.json["event"]["equipment_readiness"] == second.json["event"]["equipment_readiness"]
    assert _stored_state(app, event_id, line_id) == before


def _stored_state(app, event_id, line_id):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        line = session.get(EquipmentRequirement, line_id)
        audit_rows = sum(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                EquipmentReviewNote,
                EquipmentRequirementUnavailabilityRecord,
                EquipmentReservation,
                EquipmentReservationRelease,
            )
        )
        return event.status, line.status, line.essentiality, audit_rows
