"""Create disposable local-only SPL-135 browser-evidence fixtures."""
# ruff: noqa: E501, E702

import os
import sys
from datetime import date, datetime, time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
load_dotenv(ROOT / ".env")

from app.event_requests import SINGAPORE  # noqa: E402
from app.models import (  # noqa: E402
    Account,
    AccountRole,
    EmailDelivery,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    Role,
    Venue,
    VenueBooking,
)

database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("SPL-135 fixtures are local-only and refuse a non-local database.")


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


engine = create_engine(database_url)
try:
    with Session(engine) as session, session.begin():
        coordinator = account(
            session,
            os.getenv("VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL", "event.coordinator@example.test"),
            Role.EVENT_COORDINATOR,
        )
        manager = account(
            session,
            os.getenv(
                "VITE_LOCAL_DEMO_OPERATIONS_MANAGER_EMAIL", "operations.manager@example.test"
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
            os.getenv("VITE_LOCAL_DEMO_TECHNICAL_SUPPORT_EMAIL", "technical.support@example.test"),
            Role.TECHNICAL_SUPPORT_STAFF,
        )
        account(
            session,
            os.getenv("VITE_LOCAL_DEMO_SAFETY_OFFICER_EMAIL", "safety.officer@example.test"),
            Role.SAFETY_OFFICER,
        )
        # SPL-125: email records block deleting their notices, which the event delete cascades to.
        session.execute(
            delete(EmailDelivery).where(
                EmailDelivery.notification_id.in_(
                    select(Notification.id)
                    .join(EventRequest, Notification.event_request_id == EventRequest.id)
                    .where(EventRequest.name.like("E2E SPL-135 %"))
                )
            )
        )
        for event in session.scalars(
            select(EventRequest).where(EventRequest.name.like("E2E SPL-135 %"))
        ).all():
            session.delete(event)
        venue = session.scalar(select(Venue).where(Venue.layouts.any()).order_by(Venue.id))
        equipment = session.scalar(select(EquipmentType).order_by(EquipmentType.id))
        if venue is None or equipment is None or not venue.layouts:
            raise SystemExit(
                "Run npm run setup first: a venue with a layout and catalogue equipment are required."
            )
        layout = venue.layouts[0]
        now = datetime.now(SINGAPORE)
        for name in ("E2E SPL-135 Safety approval", "E2E SPL-135 Safety changes"):
            event = EventRequest(
                organiser_account_id=organiser.id,
                organisation_id=organiser.organisation_id,
                name=name,
                purpose="Disposable safety-review evidence event",
                proposed_date=date(2031, 1, 22),
                start_time=time(10),
                end_time=time(12),
                expected_attendance=min(20, layout.capacity),
                accessibility_needs=["Step-free access"],
                venue_notes="Keep all emergency exits clear.",
                status="confirmed",
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
                    expected_attendance=min(20, layout.capacity),
                    booking_date=event.proposed_date,
                    event_slots=["AM"],
                    requested_by_account_id=coordinator.id,
                    requested_at=now,
                    approved_by_account_id=manager.id,
                    approved_at=now,
                )
            )
            line = EquipmentRequirement(
                event_request_id=event.id,
                equipment_type=equipment.name,
                equipment_type_id=equipment.id,
                quantity=1,
                required_start_date=event.proposed_date,
                required_end_date=event.proposed_date,
                status="reserved",
                essentiality="essential",
            )
            session.add(line)
            session.flush()
            session.add(
                EquipmentReservation(
                    event_request_id=event.id,
                    equipment_requirement_id=line.id,
                    equipment_type_id=equipment.id,
                    commitment_start_date=event.proposed_date,
                    commitment_end_date=event.proposed_date,
                    quantity=1,
                    reserved_by_account_id=technical.id,
                    reserved_at=now,
                )
            )
finally:
    engine.dispose()
