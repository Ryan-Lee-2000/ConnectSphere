"""Owned, disposable equipment scenarios shared by the local browser suite."""

from datetime import date, datetime, time, timedelta, timezone

from app.models import (
    Account,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Venue,
    VenueBooking,
    VenueLayout,
)
from sqlalchemy import delete
from sqlalchemy.orm import Session

FIXTURE_DATE = date(2030, 10, 20)
NORTHSTAR = "E2E SPL-90 Northstar Leadership Retreat"
STUDIO = "E2E SPL-95 Civic Arts Open Studio"
# Exact names identify our rows. Ordinary demonstration events and catalogue stock stay untouched.
SCENARIOS = (
    (NORTHSTAR, "E2E SPL-95 Wireless Microphone", 6, 6, "requested", 0),
    (STUDIO, "E2E SPL-95 Display Plinth Set", 10, 12, "partially_reserved", 10),
    ("E2E SPL-97 Feasible review", "E2E SPL-97 Feasible Microphone", 5, 5, "review_required", 5),
    (
        "E2E SPL-97 Infeasible review",
        "E2E SPL-97 Infeasible Presentation Kit",
        4,
        5,
        "review_required",
        5,
    ),
    ("E2E SPL-97 Partial reservation", "E2E SPL-97 Partial Display Plinth", 10, 12, "requested", 0),
)


# SPL-85 recorded UAT: a Planning event with an Approved booking and an Essential line one unit
# short, so the journey shows a blocker, Technical Support clears it, and the coordinator confirms.
CONFIRMATION_EVENT = "E2E SPL-85 Confirmation Showcase"
CONFIRMATION_TYPE = "E2E SPL-85 Stage Microphone"
CONFIRMATION_VENUE = "E2E SPL-85 Harbour Hall"


def remove_equipment_fixtures(session: Session) -> None:
    """Delete parents first; database cascades retain no dangling assignments or reservations."""
    session.execute(
        delete(EventRequest).where(
            EventRequest.name.in_([row[0] for row in SCENARIOS] + [CONFIRMATION_EVENT])
        )
    )
    session.execute(
        delete(EquipmentType).where(
            EquipmentType.name.in_([row[1] for row in SCENARIOS] + [CONFIRMATION_TYPE])
        )
    )
    # The event (and so its booking) is gone, so the owned venue can be removed safely.
    session.execute(delete(Venue).where(Venue.name == CONFIRMATION_VENUE))


def prepare_confirmation_fixture(
    session: Session,
    *,
    organiser: Account,
    technician: Account,
    coordinator: Account,
    manager: Account,
    venue_staff: Account,
) -> None:
    """Reset the SPL-85 scenario: Approved booking, Essential line reserved 3 of 4."""
    now = datetime.now(timezone.utc)
    venue = Venue(
        name=CONFIRMATION_VENUE,
        location="E2E Test Location",
        operating_slots=["AM", "PM", "NIGHT"],
        setup_buffer_slots=0,
        turnaround_buffer_slots=0,
    )
    venue.layouts = [VenueLayout(layout="theatre", capacity=150)]
    equipment_type = EquipmentType(
        name=CONFIRMATION_TYPE,
        normalised_name=CONFIRMATION_TYPE.lower(),
        total_stock=10,
        location="Equipment E2E Store",
    )
    event = EventRequest(
        organiser_account_id=organiser.id,
        organisation_id=organiser.organisation_id,
        name=CONFIRMATION_EVENT,
        purpose="Local browser evidence only",
        proposed_date=FIXTURE_DATE,
        start_time=time(14),
        end_time=time(17),
        expected_attendance=80,
        preferred_room_layout="theatre",
        registration_required=True,
        status="planning",
    )
    session.add_all([venue, equipment_type, event])
    session.flush()
    session.add(
        EventCoordinatorAssignment(
            event_request_id=event.id,
            coordinator_account_id=coordinator.id,
            assigned_by_account_id=manager.id,
            assigned_at=now,
        )
    )
    session.add(
        VenueBooking(
            event_request_id=event.id,
            venue_id=venue.id,
            status="approved",
            layout="theatre",
            expected_attendance=80,
            booking_date=FIXTURE_DATE,
            event_slots=["PM"],
            requested_by_account_id=coordinator.id,
            requested_at=now,
            approved_by_account_id=venue_staff.id,
            approved_at=now,
        )
    )
    requirement = EquipmentRequirement(
        event_request_id=event.id,
        equipment_type=CONFIRMATION_TYPE,
        equipment_type_id=equipment_type.id,
        quantity=4,
        required_start_date=FIXTURE_DATE,
        required_end_date=FIXTURE_DATE,
        status="partially_reserved",
        essentiality="essential",
        notes="SPL-85 confirmation E2E fixture",
    )
    session.add(requirement)
    session.flush()
    session.add(
        EquipmentReservation(
            event_request_id=event.id,
            equipment_requirement_id=requirement.id,
            equipment_type_id=equipment_type.id,
            quantity=3,
            commitment_start_date=FIXTURE_DATE - timedelta(days=1),
            commitment_end_date=FIXTURE_DATE,
            reserved_by_account_id=technician.id,
            reserved_at=now,
        )
    )


def prepare_equipment_fixtures(
    session: Session,
    *,
    organiser: Account,
    technician: Account,
    coordinator: Account,
    manager: Account,
) -> None:
    """Reset owned scenarios with separate stock pools for independent browser journeys."""
    remove_equipment_fixtures(session)
    now = datetime.now(timezone.utc)
    for event_name, type_name, stock, quantity, status, reserved in SCENARIOS:
        equipment_type = EquipmentType(
            name=type_name,
            normalised_name=type_name.lower(),
            total_stock=stock,
            location="Equipment E2E Store",
        )
        event = EventRequest(
            organiser_account_id=organiser.id,
            organisation_id=organiser.organisation_id,
            name=event_name,
            purpose="Local browser evidence only",
            proposed_date=FIXTURE_DATE,
            start_time=time(9),
            end_time=time(12),
            expected_attendance=20,
            status="planning",
        )
        session.add_all([equipment_type, event])
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=coordinator.id,
                assigned_by_account_id=manager.id,
                assigned_at=now,
            )
        )
        requirement = EquipmentRequirement(
            event_request_id=event.id,
            equipment_type=type_name,
            equipment_type_id=equipment_type.id,
            quantity=quantity,
            required_start_date=FIXTURE_DATE,
            required_end_date=FIXTURE_DATE,
            status=status,
            notes="Shared equipment E2E fixture",
        )
        session.add(requirement)
        session.flush()
        if reserved:
            session.add(
                EquipmentReservation(
                    event_request_id=event.id,
                    equipment_requirement_id=requirement.id,
                    equipment_type_id=equipment_type.id,
                    quantity=reserved,
                    commitment_start_date=FIXTURE_DATE - timedelta(days=1),
                    commitment_end_date=FIXTURE_DATE,
                    reserved_by_account_id=technician.id,
                    reserved_at=now,
                )
            )
