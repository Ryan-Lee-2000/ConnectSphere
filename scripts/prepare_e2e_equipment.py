"""Prepare repeatable local-only equipment states for the SPL-97 browser walkthrough.

The application has no user action that creates a ``review_required`` line: it is a state left by
an earlier stock review.  These clearly labelled, disposable rows let the browser test demonstrate
both successful and refused revalidation without adding a production-only shortcut.
"""

import os
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import (  # noqa: E402
    Account,
    AccountRole,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventRequest,
    Role,
)

load_dotenv(ROOT / ".env")
database_url = os.environ["DATABASE_URL"]
if urlparse(database_url).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("E2E fixture preparation is local-only and refuses a non-local database.")

engine = create_engine(database_url)


def account_with_role(session: Session, role: Role) -> Account:
    """Return a locally seeded actor whose server-owned role can own the fixture."""

    account = session.scalar(
        select(Account).join(AccountRole).where(AccountRole.role == role.value).order_by(Account.id)
    )
    if account is None:
        raise SystemExit(f"Run npm run setup first: no local {role.value} account exists.")
    return account


with Session(engine) as session, session.begin():
    organiser = account_with_role(session, Role.EVENT_ORGANISER)
    technician = account_with_role(session, Role.TECHNICAL_SUPPORT_STAFF)
    if organiser.organisation_id is None:
        raise SystemExit("Local Event Organiser fixture needs an organisation.")

    # Re-running a browser suite replaces only its own clearly marked fixture rows.
    for event in session.scalars(
        select(EventRequest).where(EventRequest.name.like("E2E SPL-97 %"))
    ):
        session.delete(event)
    session.flush()
    for equipment_type in session.scalars(
        select(EquipmentType).where(EquipmentType.name.like("E2E SPL-97 %"))
    ):
        session.delete(equipment_type)
    session.flush()

    feasible_type = EquipmentType(
        name="E2E SPL-97 Feasible Microphone",
        normalised_name="e2e spl-97 feasible microphone",
        total_stock=5,
        location="Equipment Store",
    )
    infeasible_type = EquipmentType(
        name="E2E SPL-97 Infeasible Presentation Kit",
        normalised_name="e2e spl-97 infeasible presentation kit",
        total_stock=4,
        location="Equipment Store",
    )
    partial_type = EquipmentType(
        name="E2E SPL-97 Partial Display Plinth",
        normalised_name="e2e spl-97 partial display plinth",
        total_stock=10,
        location="Civic Store",
    )
    session.add_all([feasible_type, infeasible_type, partial_type])
    session.flush()

    def add_requirement(
        name: str,
        equipment_type: EquipmentType,
        quantity: int,
        status: str,
        reserved: int = 0,
    ):
        """Create one planning event and its mapped line, optionally with retained units."""

        event = EventRequest(
            organiser_account_id=organiser.id,
            organisation_id=organiser.organisation_id,
            name=name,
            purpose="Local browser evidence only",
            proposed_date=date(2030, 10, 20),
            start_time=time(9),
            end_time=time(12),
            expected_attendance=20,
            status="planning",
        )
        session.add(event)
        session.flush()
        requirement = EquipmentRequirement(
            event_request_id=event.id,
            equipment_type=equipment_type.name,
            equipment_type_id=equipment_type.id,
            quantity=quantity,
            required_start_date=date(2030, 10, 20),
            required_end_date=date(2030, 10, 20),
            status=status,
            notes="E2E SPL-97 browser evidence fixture",
        )
        session.add(requirement)
        session.flush()
        if reserved:
            session.add(
                EquipmentReservation(
                    event_request_id=event.id,
                    equipment_requirement_id=requirement.id,
                    equipment_type_id=equipment_type.id,
                    commitment_start_date=date(2030, 10, 20),
                    commitment_end_date=date(2030, 10, 20),
                    quantity=reserved,
                    reserved_by_account_id=technician.id,
                    reserved_at=datetime.now(timezone.utc),
                )
            )

    add_requirement("E2E SPL-97 Feasible review", feasible_type, 5, "review_required", reserved=5)
    add_requirement(
        "E2E SPL-97 Infeasible review", infeasible_type, 5, "review_required", reserved=5
    )
    add_requirement("E2E SPL-97 Partial reservation", partial_type, 12, "requested")

engine.dispose()
