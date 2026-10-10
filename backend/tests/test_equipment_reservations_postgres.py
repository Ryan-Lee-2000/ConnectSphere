"""PostgreSQL concurrency evidence for SPL-97 equipment reservations.

SQLite accepts ``FOR UPDATE`` syntax but does not enforce row locks.  This focused test uses
separate PostgreSQL connections to prove that a coordinator edit and a Technical Support
reservation cannot both validate an obsolete requirement quantity.
"""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest
from app import create_app
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
)
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000000971"
TECHNICAL_SUPPORT = "00000000-0000-0000-0000-000000000972"
ORGANISER = "00000000-0000-0000-0000-000000000973"

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)


@pytest.fixture()
def postgres_app():
    """Create an isolated current-schema PostgreSQL database for concurrent API requests."""

    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    database_name = f"spl97_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    database_url = server.set(database=database_name).render_as_string(hide_password=False)
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": database_url,
            "IDENTITY_VERIFIER": lambda token: token,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            organisation = Organisation(id=97, name="SPL-97 concurrency organisation")
            coordinator = Account(id=COORDINATOR, display_name="Casey Coordinator")
            technical_support = Account(id=TECHNICAL_SUPPORT, display_name="Taylor Technical")
            organiser = Account(id=ORGANISER, display_name="Olivia Organiser")
            session.add_all([organisation, coordinator, technical_support, organiser])
            # AccountRole has only foreign-key ids, so flush accounts before adding those rows.
            session.flush()
            event = EventRequest(
                id=97,
                organiser_account_id=ORGANISER,
                organisation_id=organisation.id,
                name="SPL-97 concurrent equipment event",
                proposed_date=date(2026, 10, 20),
                status="planning",
            )
            equipment_type = EquipmentType(
                id=97,
                name="SPL-97 wireless microphone",
                normalised_name="spl-97 wireless microphone",
                total_stock=10,
            )
            requirement = EquipmentRequirement(
                id=97,
                event_request_id=event.id,
                equipment_type="Wireless microphone",
                equipment_type_id=equipment_type.id,
                quantity=6,
                required_start_date=date(2026, 10, 20),
                required_end_date=date(2026, 10, 20),
                status="requested",
            )
            session.add_all(
                [
                    AccountRole(account_id=COORDINATOR, role=Role.EVENT_COORDINATOR.value),
                    AccountRole(
                        account_id=TECHNICAL_SUPPORT,
                        role=Role.TECHNICAL_SUPPORT_STAFF.value,
                    ),
                    event,
                    equipment_type,
                    requirement,
                    EventCoordinatorAssignment(
                        event_request_id=event.id,
                        coordinator_account_id=COORDINATOR,
                        assigned_by_account_id=COORDINATOR,
                        assigned_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                    ),
                ]
            )
            session.commit()
        yield application
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        admin.dispose()


# TC-SPL-97-13 — a reservation waits for an in-progress coordinator edit, then rechecks the line.
def test_tc_spl_97_13_coordinator_quantity_change_and_reservation_cannot_both_succeed(postgres_app):
    """AC1/AC2 concurrency: three units cannot be reserved after the line becomes one unit."""

    barrier = threading.Barrier(2, timeout=10)

    def edit_requirement():
        with postgres_app.test_client() as client:
            barrier.wait()
            return client.patch(
                "/api/event-requests/97/equipment-requirements/97",
                headers={"Authorization": f"Bearer {COORDINATOR}"},
                json={"quantity": 1},
            ).status_code

    def reserve_equipment():
        with postgres_app.test_client() as client:
            barrier.wait()
            return client.post(
                "/api/equipment-requirements/97/reservations",
                headers={"Authorization": f"Bearer {TECHNICAL_SUPPORT}"},
                json={"quantity": 3},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(
            executor.map(lambda operation: operation(), [edit_requirement, reserve_equipment])
        )

    # Either operation may win the race: a successful edit returns 200, while a successful
    # reservation creates its audit row and returns 201.  The loser must be refused.
    assert statuses in ([200, 409], [201, 409])
    with Session(postgres_app.extensions["engine"]) as session:
        requirement = session.get(EquipmentRequirement, 97)
        reservations = session.query(EquipmentReservation).all()
        assert (requirement.quantity, sum(row.quantity for row in reservations)) in {(1, 0), (6, 3)}
