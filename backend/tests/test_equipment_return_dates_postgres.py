"""PostgreSQL evidence for SPL-100: extending a commitment races a new reservation.

SQLite cannot run two transactions against each other, so these cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), on a throw-away PostgreSQL database built with
the real Alembic migrations.

Why this race is the one that matters
-------------------------------------
Extending a planned return date and reserving units are two different routes, in two different
modules, both competing for the same shared pool. They serialise only because **both** take a row
lock on the same ``equipment_types`` row: SPL-97's ``_locked_reservable_requirement`` and this
story's own lock. If either dropped it, two transactions could each read the day as free and both
commit, putting more units on that day than exist.

``ordered_race`` (shared with SPL-137/138, SPL-118 and SPL-96) holds the first request immediately
before it commits and *proves* the second is waiting on a PostgreSQL lock before releasing the
first.
"""

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, time, timedelta

import pytest
from app import create_app
from app import equipment_return_dates as return_dates_module
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

NOW = datetime(2026, 10, 11, 10, 0, tzinfo=SINGAPORE)
CONTESTED_DAY = date(2026, 10, 15)


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl100_{uuid.uuid4().hex[:12]}"
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
    """Stock 3, all three held to 14 Oct, and a second line wanting one unit across 15 Oct.

    Either the extension takes 15 Oct or the new reservation does; both cannot fit.
    """

    monkeypatch.setattr(return_dates_module, "_now", lambda: NOW)
    tokens = {"first": str(uuid.uuid4()), "second": str(uuid.uuid4())}
    engine = create_engine(pg_url)
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-100 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for label, account_id in tokens.items():
            session.add(Account(id=account_id, display_name=f"Technical {label}"))
            session.add(AccountRole(account_id=account_id, role=Role.TECHNICAL_SUPPORT_STAFF.value))
        session.flush()

        equipment_type = EquipmentType(
            name=f"Stage Monitor {uuid.uuid4().hex[:6]}",
            normalised_name=f"stage monitor {uuid.uuid4().hex[:6]}",
            location="Technical Store C",
            total_stock=3,
        )
        session.add(equipment_type)
        session.flush()

        def add_event(name, proposed):
            event = EventRequest(
                organiser_account_id=tokens["first"],
                organisation_id=organisation.id,
                name=name,
                purpose="Annual programme",
                proposed_date=proposed,
                start_time=time(14, 0),
                end_time=time(17, 0),
                expected_attendance=50,
                status="planning",
                submitted_at=NOW,
            )
            session.add(event)
            session.flush()
            return event

        # The reservation to be extended: all three units, ending 14 Oct.
        held_event = add_event("Held Event", date(2026, 10, 13))
        held_line = EquipmentRequirement(
            event_request_id=held_event.id,
            equipment_type="Stage monitors",
            quantity=3,
            equipment_type_id=equipment_type.id,
            required_start_date=date(2026, 10, 13),
            required_end_date=date(2026, 10, 14),
            status="reserved",
        )
        session.add(held_line)
        session.flush()
        reservation = EquipmentReservation(
            event_request_id=held_event.id,
            equipment_requirement_id=held_line.id,
            equipment_type_id=equipment_type.id,
            commitment_start_date=date(2026, 10, 12),
            commitment_end_date=date(2026, 10, 14),
            quantity=3,
            reserved_by_account_id=tokens["first"],
            reserved_at=NOW,
        )
        session.add(reservation)

        # The contender: required 16 Oct, so it collects on 15 Oct — the contested day.
        rival_event = add_event("Rival Event", date(2026, 10, 16))
        rival_line = EquipmentRequirement(
            event_request_id=rival_event.id,
            equipment_type="Stage monitors",
            quantity=1,
            equipment_type_id=equipment_type.id,
            required_start_date=date(2026, 10, 16),
            required_end_date=date(2026, 10, 16),
            status="requested",
        )
        session.add(rival_line)
        session.commit()
        ids = (reservation.id, rival_line.id, equipment_type.id)

    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": tokens.__getitem__}
    )
    monkeypatch.setattr(return_dates_module, "_now", lambda: NOW)
    yield app, engine, ids
    app.extensions["engine"].dispose()
    engine.dispose()


def committed_on(engine, equipment_type_id, day):
    """Units promised on one day by every reservation of this type."""

    with Session(engine) as session:
        reservations = session.scalars(
            select(EquipmentReservation).where(
                EquipmentReservation.equipment_type_id == equipment_type_id
            )
        ).all()
        return sum(
            reservation.quantity
            for reservation in reservations
            if reservation.commitment_start_date <= day <= reservation.commitment_end_date
        )


# TC-SPL-100-07
# SPL-100 AC-3 Test-07
def test_tc_spl_100_07_extending_races_a_new_reservation_for_the_last_unit(scenario):
    from test_exact_venue_bookings_postgres import ordered_race

    app, engine, (reservation_id, rival_line_id, type_id) = scenario
    assert committed_on(engine, type_id, CONTESTED_DAY) == 0

    def extend(client):
        return client.patch(
            f"/api/equipment-reservations/{reservation_id}/planned-return-date",
            headers={"Authorization": "Bearer first"},
            json={"planned_return_date": CONTESTED_DAY.isoformat()},
        )

    def reserve(client):
        return client.post(
            f"/api/equipment-requirements/{rival_line_id}/reservations",
            headers={"Authorization": "Bearer second"},
            json={"quantity": 1},
        )

    # ordered_race asserts the second request really waited on a database lock.
    first, second = ordered_race(app, extend, reserve)

    # Exactly one of the two took the contested day; the other was refused with a conflict.
    statuses = sorted([first[0], second[0]])
    assert statuses == [200, 409] or statuses == [201, 409], statuses

    # Whichever won, the day never holds more units than exist.
    assert committed_on(engine, type_id, CONTESTED_DAY) <= 3
    assert committed_on(engine, type_id, CONTESTED_DAY) >= 1


# TC-SPL-100-12
# SPL-100 AC-1 / AC-3 Test-12 (added during implementation)
def test_tc_spl_100_12_migration_keeps_reservations_and_leaves_them_unedited(scenario, pg_url):
    """The two audit columns are additive: an existing reservation reads as never edited."""

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    app, engine, (reservation_id, _, _) = scenario
    app.extensions["engine"].dispose()
    engine.dispose()

    # Roll back to this migration's parent and forward again with a reservation in the table.
    # The parent is read from the migration itself, so this keeps working when it is re-pointed.
    parent = (
        ScriptDirectory.from_config(Config("alembic.ini"))
        .get_revision("s3_equipment_return_dates")
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
    row = text(
        "SELECT commitment_end_date, quantity, return_date_changed_by_account_id, "
        "return_date_changed_at FROM equipment_reservations WHERE id = :id"
    )
    with engine.connect() as connection:
        end_date, quantity, changed_by, changed_at = connection.execute(
            row, {"id": reservation_id}
        ).one()
    # The commitment survives untouched, and the reservation reads as never edited rather than
    # as edited by whoever created it.
    assert end_date == date(2026, 10, 14)
    assert quantity == 3
    assert changed_by is None
    assert changed_at is None
    engine.dispose()


def test_commitment_days_are_inclusive_of_the_planned_return_date(scenario):
    """AC2 in one line: the planned return day itself is committed, the next day is not."""

    _, engine, (_, _, type_id) = scenario
    assert committed_on(engine, type_id, date(2026, 10, 14)) == 3
    assert committed_on(engine, type_id, date(2026, 10, 15)) == 0
    assert committed_on(engine, type_id, date(2026, 10, 12) - timedelta(days=1)) == 0
