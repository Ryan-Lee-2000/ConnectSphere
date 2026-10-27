"""Create realistic local-only SPL-136 UAT fixtures."""

import os
import sys
import uuid
from datetime import date, datetime, time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
load_dotenv(ROOT / ".env")

from app.event_requests import SINGAPORE  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    AccountRole,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Role,
    SafetyReview,
    Venue,
    VenueBooking,
)
from app.safety_reviews import _fingerprint  # noqa: E402

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-136 fixtures are local-only and refuse a non-local database.")
try:
    run_id = str(uuid.UUID(os.environ["SPL136_E2E_RUN_ID"]))
except (KeyError, ValueError):
    raise SystemExit("A valid SPL136_E2E_RUN_ID is required for isolated fixtures.") from None


def account(session: Session, email: str, role: Role) -> Account:
    account_id = session.scalar(
        text("SELECT id FROM auth.users WHERE email = :email"), {"email": email}
    )
    row = session.get(Account, str(account_id)) if account_id else None
    if (
        row is None
        or session.scalar(
            select(AccountRole.account_id).where(
                AccountRole.account_id == row.id, AccountRole.role == role.value
            )
        )
        is None
    ):
        raise SystemExit(f"Run npm run setup first: {role.value} fixture is missing.")
    return row


def plan(crowd_movement: str) -> dict:
    return {
        "emergency_access": {
            "value": "Keep the marked fire exit clear and brief the event ushers.",
            "not_applicable_reason": None,
        },
        "equipment_placement": {
            "value": "Route presentation cables behind the marked stage line.",
            "not_applicable_reason": None,
        },
        "crowd_movement": {"value": crowd_movement, "not_applicable_reason": None},
        "venue_restrictions": {
            "value": "No open flame and no blocked exits.",
            "not_applicable_reason": None,
        },
    }


def add_event(
    session: Session,
    *,
    name: str,
    status: str,
    day: date,
    coordinator: Account,
    organiser: Account,
    manager: Account,
    technical: Account,
    venue: Venue,
    equipment: EquipmentType,
    safety: Account,
    reviewed: bool,
) -> EventRequest:
    """Seed one complete arrangement so UAT exercises real safety and readiness data."""

    now = datetime.now(SINGAPORE)
    layout = venue.layouts[0]
    event = EventRequest(
        organiser_account_id=organiser.id,
        organisation_id=organiser.organisation_id,
        name=name,
        purpose=(
            "Community leadership workshop with a facilitated discussion and presentation segment."
        ),
        proposed_date=day,
        start_time=time(10),
        end_time=time(12),
        expected_attendance=min(35, layout.capacity),
        accessibility_needs=["Step-free access"],
        venue_notes="Keep emergency exits clear and maintain an accessible route to seating.",
        status=status,
    )
    session.add(event)
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
            layout=layout.layout,
            expected_attendance=event.expected_attendance,
            booking_date=day,
            event_slots=["AM"],
            requested_by_account_id=coordinator.id,
            requested_at=now,
            approved_by_account_id=manager.id,
            approved_at=now,
        )
    )
    requirement = EquipmentRequirement(
        event_request_id=event.id,
        equipment_type=equipment.name,
        equipment_type_id=equipment.id,
        quantity=1,
        required_start_date=day,
        required_end_date=day,
        status="reserved",
        essentiality="essential",
    )
    session.add(requirement)
    session.flush()
    session.add(
        EquipmentReservation(
            event_request_id=event.id,
            equipment_requirement_id=requirement.id,
            equipment_type_id=equipment.id,
            commitment_start_date=day,
            commitment_end_date=day,
            quantity=1,
            reserved_by_account_id=technical.id,
            reserved_at=now,
        )
    )
    session.flush()
    if reviewed:
        session.add(
            SafetyReview(
                event_request_id=event.id,
                plan=plan("Use separate entry and exit queues with two volunteer ushers."),
                arrangement_fingerprint=_fingerprint(event),
                status="approved",
                submitted_by_account_id=coordinator.id,
                submitted_at=now,
                decided_by_account_id=safety.id,
                decided_at=now,
            )
        )
    return event


engine = create_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        coordinator = account(
            session,
            os.getenv(
                "VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL",
                "event.coordinator@example.test",
            ),
            Role.EVENT_COORDINATOR,
        )
        manager = account(
            session,
            os.getenv(
                "VITE_LOCAL_DEMO_OPERATIONS_MANAGER_EMAIL",
                "operations.manager@example.test",
            ),
            Role.EVENT_OPERATIONS_MANAGER,
        )
        organiser = account(
            session,
            os.getenv("VITE_LOCAL_DEMO_EMAIL", "developer@example.test"),
            Role.EVENT_ORGANISER,
        )
        technical = account(
            session,
            os.getenv(
                "VITE_LOCAL_DEMO_TECHNICAL_SUPPORT_EMAIL",
                "technical.support@example.test",
            ),
            Role.TECHNICAL_SUPPORT_STAFF,
        )
        safety = account(
            session,
            os.getenv("VITE_LOCAL_DEMO_SAFETY_OFFICER_EMAIL", "safety.officer@example.test"),
            Role.SAFETY_OFFICER,
        )
        venue = session.scalar(select(Venue).where(Venue.layouts.any()).order_by(Venue.id))
        equipment = session.scalar(select(EquipmentType).order_by(EquipmentType.id))
        if venue is None or equipment is None or not venue.layouts:
            raise SystemExit(
                "Run npm run setup first: venue layouts and catalogue equipment are required."
            )

        add_event(
            session,
            name=f"E2E SPL-136 {run_id} Harbour Futures Leadership Forum",
            status="confirmed",
            day=date(2031, 2, 12),
            coordinator=coordinator,
            organiser=organiser,
            manager=manager,
            technical=technical,
            venue=venue,
            equipment=equipment,
            safety=safety,
            reviewed=True,
        )
        add_event(
            session,
            name=f"E2E SPL-136 {run_id} Community Access Briefing",
            status="confirmed",
            day=date(2031, 2, 19),
            coordinator=coordinator,
            organiser=organiser,
            manager=manager,
            technical=technical,
            venue=venue,
            equipment=equipment,
            safety=safety,
            reviewed=False,
        )
        add_event(
            session,
            name=f"E2E SPL-136 {run_id} Community Capacity Update",
            status="confirmed",
            day=date(2031, 2, 22),
            coordinator=coordinator,
            organiser=organiser,
            manager=manager,
            technical=technical,
            venue=venue,
            equipment=equipment,
            safety=safety,
            reviewed=False,
        )
        add_event(
            session,
            name=f"E2E SPL-136 {run_id} Volunteer Operations Briefing",
            status="preparing",
            day=date(2031, 2, 26),
            coordinator=coordinator,
            organiser=organiser,
            manager=manager,
            technical=technical,
            venue=venue,
            equipment=equipment,
            safety=safety,
            reviewed=True,
        )
finally:
    engine.dispose()
