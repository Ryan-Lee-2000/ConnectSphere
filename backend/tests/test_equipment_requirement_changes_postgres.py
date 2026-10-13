"""PostgreSQL evidence for SPL-91: simultaneous changes never release the same units twice.

SQLite cannot run two transactions against each other, so these cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), on a throw-away PostgreSQL database built with
the real Alembic migrations.

What AC4 promises here
----------------------
"Failed or simultaneous conflicting changes never leave a stale reservation or release the same
units twice." Two things make that true:

1. Every stock-changing route takes the same two row locks in the same order — the equipment type,
   then the requirement line — so two requests on one line run one after the other.
2. The waiting request re-reads the line once it gets the lock, and recomputes what is still held.
   So a second change finds nothing left to release, and a removal that lost the race finds the
   line already gone and stops before any release.

``ordered_race`` (shared with SPL-96, SPL-100, SPL-118 and SPL-137/138) holds the first request
immediately before it commits and *proves* the second is waiting on a PostgreSQL lock before
releasing the first. Without the lock the second would not wait, and the case fails.
"""

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, time, timedelta

import pytest
from app import create_app
from app import equipment_requirements as requirements_module
from app.equipment_reservation_state import remaining_quantity
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EquipmentRequirement,
    EquipmentRequirementChange,
    EquipmentReservation,
    EquipmentReservationRelease,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

NOW = datetime(2026, 10, 13, 10, 0, tzinfo=SINGAPORE)
EVENT_DATE = date(2026, 11, 20)


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl91_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    try:
        upgraded = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        assert upgraded.returncode == 0, upgraded.stderr
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def scenario(pg_url, monkeypatch):
    """One Planning event, its assigned coordinator, and a line needing 4 with all 4 reserved."""

    coordinator = str(uuid.uuid4())
    technical = str(uuid.uuid4())
    engine = create_engine(pg_url)
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-91 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        session.add_all(
            [
                Account(id=coordinator, display_name="Casey Coordinator"),
                Account(id=technical, display_name="Taylor Technical"),
            ]
        )
        session.flush()
        session.add_all(
            [
                AccountRole(account_id=coordinator, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=technical, role=Role.TECHNICAL_SUPPORT_STAFF.value),
            ]
        )
        equipment_type = EquipmentType(
            name=f"Wireless Microphone {uuid.uuid4().hex[:6]}",
            normalised_name=f"wireless microphone {uuid.uuid4().hex[:6]}",
            location="Technical Store A",
            total_stock=10,
        )
        session.add(equipment_type)
        event = EventRequest(
            organiser_account_id=coordinator,
            organisation_id=organisation.id,
            name="Community Leadership Forum",
            purpose="Annual programme",
            proposed_date=EVENT_DATE,
            start_time=time(14, 0),
            end_time=time(17, 0),
            expected_attendance=80,
            status="planning",
            submitted_at=NOW,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=coordinator,
                assigned_by_account_id=coordinator,
                assigned_at=NOW,
            )
        )
        line = EquipmentRequirement(
            event_request_id=event.id,
            equipment_type="Wireless microphones",
            quantity=4,
            notes="Panel.",
            equipment_type_id=equipment_type.id,
            required_start_date=EVENT_DATE,
            required_end_date=EVENT_DATE,
            status="reserved",
        )
        session.add(line)
        session.flush()
        session.add(
            EquipmentReservation(
                event_request_id=event.id,
                equipment_requirement_id=line.id,
                equipment_type_id=equipment_type.id,
                commitment_start_date=EVENT_DATE - timedelta(days=1),
                commitment_end_date=EVENT_DATE,
                quantity=4,
                reserved_by_account_id=technical,
                reserved_at=NOW,
            )
        )
        session.commit()
        ids = (event.id, line.id)

    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": pg_url,
            "IDENTITY_VERIFIER": {"coordinator": coordinator}.__getitem__,
        }
    )
    monkeypatch.setattr(requirements_module, "_now", lambda: NOW)
    yield app, engine, ids
    app.extensions["engine"].dispose()
    engine.dispose()


def released_total(engine, line_id):
    with Session(engine) as session:
        return (
            session.scalar(
                select(func.coalesce(func.sum(EquipmentReservationRelease.quantity), 0))
                .join(EquipmentReservation)
                .where(EquipmentReservation.equipment_requirement_id == line_id)
            )
            or 0
        )


def still_held(engine, line_id):
    with Session(engine) as session:
        reservations = session.scalars(
            select(EquipmentReservation).where(
                EquipmentReservation.equipment_requirement_id == line_id
            )
        ).all()
        return sum(remaining_quantity(item) for item in reservations)


def history_count(engine, line_id):
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(EquipmentRequirementChange)
            .where(EquipmentRequirementChange.equipment_requirement_id == line_id)
        )


def url(event_id, line_id):
    return f"/api/event-requests/{event_id}/equipment-requirements/{line_id}"


AUTH = {"Authorization": "Bearer coordinator"}


# TC-SPL-91-04
# SPL-91 AC-4 Test-04 — two simultaneous changes to the same reserved line
def test_tc_spl_91_04_two_simultaneous_changes_release_the_units_once(scenario):
    from test_exact_venue_bookings_postgres import ordered_race

    app, engine, (event_id, line_id) = scenario

    def change_to(quantity):
        def call(client):
            return client.patch(url(event_id, line_id), headers=AUTH, json={"quantity": quantity})

        return call

    # ordered_race asserts the second change really waited on a database lock.
    first, second = ordered_race(app, change_to(5), change_to(6))

    # Both are accepted actions: the second ran after the first, saw the line as it now stood,
    # and changed it again. Neither was lost.
    assert (first[0], second[0]) == (200, 200)
    # The four units were released exactly once — by the first change. The second found nothing
    # left to release, because it recomputed what was held once it had the lock.
    assert released_total(engine, line_id) == 4
    assert (first[1]["released_quantity"], second[1]["released_quantity"]) == (4, 0)
    # No reservation is left consuming stock for values the line no longer has.
    assert still_held(engine, line_id) == 0
    # One history entry per accepted action.
    assert history_count(engine, line_id) == 2

    # The second change was computed against the line *as the first left it* (quantity 5), not
    # against the stale value it would have read without the lock (4). Without this, the history
    # would claim 4 -> 6 and silently lose the first change.
    #
    # Note what this assertion is for: the release count above is ALSO protected by SPL-98's own
    # row lock on the reservation rows, so removing this story's lock alone does not double-
    # release. This line is what proves this story's lock is doing its own job.
    with Session(engine) as session:
        entries = session.scalars(
            select(EquipmentRequirementChange)
            .where(EquipmentRequirementChange.equipment_requirement_id == line_id)
            .order_by(EquipmentRequirementChange.id)
        ).all()
        assert [(e.old_values["quantity"], e.new_values["quantity"]) for e in entries] == [
            (4, 5),
            (5, 6),
        ]


# TC-SPL-91-04
# SPL-91 AC-3 / AC-4 Test-04 — a change racing a removal
def test_tc_spl_91_04_a_change_racing_a_removal_releases_the_units_once(scenario):
    from test_exact_venue_bookings_postgres import ordered_race

    app, engine, (event_id, line_id) = scenario

    def change(client):
        return client.patch(url(event_id, line_id), headers=AUTH, json={"quantity": 5})

    def remove(client):
        return client.delete(url(event_id, line_id), headers=AUTH)

    first, second = ordered_race(app, remove, change)

    # The removal went first and released the four units. The change waited, re-read the line,
    # found it removed, and was refused before it could reach any release.
    assert first[0] == 200
    assert first[1]["released_quantity"] == 4
    assert second[0] == 409
    assert released_total(engine, line_id) == 4
    assert still_held(engine, line_id) == 0
    # Only the accepted action is in the history.
    assert history_count(engine, line_id) == 1


# TC-SPL-91-13
# SPL-91 AC-4 Test-13 (added during implementation)
def test_tc_spl_91_13_migration_keeps_lines_and_the_history_table_refuses_bad_rows(
    scenario, pg_url
):
    """The new table is additive: existing lines survive a rollback and re-apply, and the
    database itself refuses an action the history does not know."""

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy.exc import IntegrityError

    app, engine, (_, line_id) = scenario
    app.extensions["engine"].dispose()
    engine.dispose()

    # The parent is read from the migration itself, so this keeps working if it is re-pointed.
    parent = (
        ScriptDirectory.from_config(Config("alembic.ini"))
        .get_revision("s3_equipment_requirement_changes")
        .down_revision
    )
    for command in (["downgrade", parent], ["upgrade", "head"]):
        moved = subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": pg_url},
        )
        assert moved.returncode == 0, moved.stderr

    engine = create_engine(pg_url)
    with engine.connect() as connection:
        quantity = connection.execute(
            text("SELECT quantity FROM equipment_requirements WHERE id = :id"), {"id": line_id}
        ).scalar_one()
        assert quantity == 4
        account = connection.execute(
            text("SELECT coordinator_account_id FROM event_coordinator_assignments LIMIT 1")
        ).scalar_one()

    insert = text(
        "INSERT INTO equipment_requirement_changes "
        "(equipment_requirement_id, action, old_values, new_values, released_quantity, "
        "changed_by_account_id, changed_at) "
        "VALUES (:line, :action, '{}', '{}', :released, :account, now())"
    )
    for action, released in (("deleted", 0), ("changed", -1)):
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    insert,
                    {"line": line_id, "action": action, "released": released, "account": account},
                )
    # And a well-formed row is accepted.
    with engine.begin() as connection:
        connection.execute(
            insert, {"line": line_id, "action": "changed", "released": 0, "account": account}
        )
    engine.dispose()
