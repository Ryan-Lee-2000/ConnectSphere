"""PostgreSQL evidence for SPL-96: two people taking the last usable unit out of service.

SQLite cannot run two transactions against each other, so these cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), on a throw-away PostgreSQL database built with
the real Alembic migrations.

What is proved here, and what is not
------------------------------------
TC-SPL-96-07 as published races *marking a unit unavailable* against *reserving it*. This file
races two concurrent **recordings** against the same equipment type instead, which is the
invariant AC1 states — the unavailable total never exceeds total stock — and the one that a
missing row lock would silently break.

The marking-against-reserving direction is deliberately not raced here. Both operations take a
row lock on the same ``equipment_types`` row — SPL-97's reserve route through
``_locked_reservable_requirement``, and this story through ``_apply_change`` — so what such a race
would demonstrate is SPL-97's lock rather than this story's. Two recordings is the pairing only
this story can get wrong.

What this story's own AC2 and AC3 need from reservations is proved on SQLite in
test_equipment_unavailability.py (TC-SPL-96-04 reserves against reduced stock; TC-SPL-96-01 and
-05 flag the lines that no longer fit), because neither needs two simultaneous transactions.

TC-SPL-96-11 is new, added during implementation: it applies the migration against data and
checks the database itself, not just the route, refuses a total outside 0..total_stock.

How the race is staged
----------------------
``ordered_race`` (shared with SPL-137/138 and SPL-118) holds the first request immediately before
it commits and *proves* the second is waiting on a PostgreSQL lock before releasing the first.
Without ``with_for_update()`` the second would not wait, both would read "one unit still usable",
and the total would end up above stock.
"""

import os
import subprocess
import sys
import uuid
from datetime import datetime

import pytest
from app import create_app
from app import equipment_unavailability as unavailability_module
from app.event_requests import SINGAPORE
from app.models import Account, AccountRole, EquipmentType, Role
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

NOW = datetime(2026, 10, 10, 9, 30, tzinfo=SINGAPORE)


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl96_{uuid.uuid4().hex[:12]}"
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
    """Two Technical Support accounts and one equipment type with a single usable unit left."""

    monkeypatch.setattr(unavailability_module, "_now", lambda: NOW)
    tokens = {"first": str(uuid.uuid4()), "second": str(uuid.uuid4())}
    engine = create_engine(pg_url)
    with Session(engine) as session:
        for label, account_id in tokens.items():
            session.add(Account(id=account_id, display_name=f"Technical {label}"))
            session.add(AccountRole(account_id=account_id, role=Role.TECHNICAL_SUPPORT_STAFF.value))
        equipment_type = EquipmentType(
            name=f"Portable Stage Light {uuid.uuid4().hex[:6]}",
            normalised_name=f"portable stage light {uuid.uuid4().hex[:6]}",
            location="Technical Store B",
            total_stock=4,
            # Three of the four are already out of service, so exactly one is still usable.
            unavailable_units=3,
        )
        session.add(equipment_type)
        session.commit()
        type_id = equipment_type.id
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": pg_url,
            "IDENTITY_VERIFIER": tokens.__getitem__,
        }
    )
    monkeypatch.setattr(unavailability_module, "_now", lambda: NOW)
    yield app, engine, type_id
    app.extensions["engine"].dispose()
    engine.dispose()


# TC-SPL-96-07
# SPL-96 AC-1 Test-07 (the half that does not need SPL-97's reservation route)
def test_tc_spl_96_07_two_recordings_cannot_exceed_total_stock(scenario):
    from test_exact_venue_bookings_postgres import ordered_race

    app, engine, type_id = scenario

    def record(label):
        def call(client):
            return client.post(
                f"/api/equipment-types/{type_id}/unavailable-units",
                headers={"Authorization": f"Bearer {label}"},
                json={"quantity": 1, "reason": f"Taken out of service by {label}."},
            )

        return call

    # ordered_race asserts the second request really waited on a database lock.
    first, second = ordered_race(app, record("first"), record("second"))

    # Exactly one of the two took the last usable unit; the other was refused with a 400.
    assert sorted([first[0], second[0]]) == [201, 400]
    refused = first if first[0] == 400 else second
    assert "still usable" in refused[1]["error"]

    with Session(engine) as session:
        equipment_type = session.get(EquipmentType, type_id)
        # The invariant AC1 states: never above total stock.
        assert equipment_type.unavailable_units == 4
        assert equipment_type.unavailable_units <= equipment_type.total_stock
        # And only the successful recording left a history entry behind.
        written = session.scalar(
            select(func.count())
            .select_from(text("equipment_unavailability_records"))
            .where(text(f"equipment_type_id = {type_id}"))
        )
        assert written == 1


# TC-SPL-96-11
# SPL-96 AC-1 Test-11 (added during implementation; see this file's docstring)
def test_tc_spl_96_11_migration_keeps_stock_and_refuses_an_impossible_total(scenario, pg_url):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy.exc import IntegrityError

    app, engine, type_id = scenario
    app.extensions["engine"].dispose()
    engine.dispose()

    # Roll the migration back to its parent and forward again with an equipment type in place.
    # The parent is read from the migration itself, so this keeps working when it is re-pointed.
    parent = (
        ScriptDirectory.from_config(Config("alembic.ini"))
        .get_revision("s3_equipment_unavailable_units")
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
    row = text("SELECT total_stock, unavailable_units FROM equipment_types WHERE id = :id")
    with engine.connect() as connection:
        # Going down drops the column, so coming back up reads as "all stock usable" from the
        # server default. The type itself and its stock survive.
        assert tuple(connection.execute(row, {"id": type_id}).one()) == (4, 0)

    # The database itself refuses a total above stock...
    for impossible in (5, -1):
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE equipment_types SET unavailable_units = :n WHERE id = :id"),
                    {"n": impossible, "id": type_id},
                )
    # ...and accepts every total within the bounds, including both ends.
    for allowed in (0, 4):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE equipment_types SET unavailable_units = :n WHERE id = :id"),
                {"n": allowed, "id": type_id},
            )
    engine.dispose()
