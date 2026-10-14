"""SPL-93 lifecycle races use real PostgreSQL event row locks."""

import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from app import equipment_requirement_unavailability as unavailability
from app.models import EquipmentRequirement, EquipmentReservation, EventRequest
from sqlalchemy import create_engine, select, text
from sqlalchemy import event as sql_event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from test_equipment_requirement_unavailability import app as app
from test_equipment_requirement_unavailability import client as client
from test_equipment_requirement_unavailability import headers, mark
from test_exact_venue_bookings_postgres import ordered_race

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)


@pytest.fixture
def database_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl93_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    try:
        migrated = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        assert migrated.returncode == 0, migrated.stderr
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# TC-SPL-93-012 — a decision waiting for event closure must observe the committed lifecycle.
@pytest.mark.parametrize("event_status", ["cancelled", "completed"])
@pytest.mark.parametrize("action", ["mark-unavailable", "restore-requested"])
@pytest.mark.parametrize("closure_first", [True, False])
def test_event_closure_and_availability_decision_share_a_transaction_boundary(
    app, client, event_status, action, closure_first
):
    if action == "restore-requested":
        assert mark(client, reason="Supplier recall").status_code == 201
    with Session(app.extensions["engine"]) as session:
        before = [
            unavailability.serialize_record(row) for row in unavailability.history_for(session, 1)
        ]
        original_status = session.get(EquipmentRequirement, 1).status

    def close_event(_client):
        # Represents the database write made by an event lifecycle transition. PostgreSQL UPDATE
        # takes the same event row lock; no test-only product endpoint or auth bypass is added.
        with Session(app.extensions["engine"]) as session, session.begin():
            event = session.scalar(
                select(EventRequest).where(EventRequest.id == 1).with_for_update()
            )
            event.status = event_status
        return SimpleNamespace(status_code=200, json={})

    def decide(client):
        return client.post(
            f"/api/equipment-requirements/1/{action}",
            headers=headers(),
            json={"reason": "New decision"} if action == "mark-unavailable" else None,
        )

    first, second = ordered_race(
        app,
        close_event if closure_first else decide,
        decide if closure_first else close_event,
    )
    decision = second if closure_first else first
    assert decision[0] == (409 if closure_first else 201 if action == "mark-unavailable" else 200)
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, 1).status == event_status
        history = [
            unavailability.serialize_record(row) for row in unavailability.history_for(session, 1)
        ]
        if closure_first:
            assert session.get(EquipmentRequirement, 1).status == original_status
            assert history == before
        else:
            assert session.get(EquipmentRequirement, 1).status == (
                "unavailable" if action == "mark-unavailable" else "requested"
            )
            assert history[: len(before)] == before
            assert len(history) == len(before) + 1


# TC-SPL-93-013 — reservation inserts and decisions serialize without an event/stock deadlock.
def test_reservation_insert_and_unavailability_decision_serialize_without_deadlock(app):
    engine = app.extensions["engine"]
    reservation_locked = threading.Event()
    release_reservation = threading.Event()
    event_locked = threading.Event()
    thread_ids = {}
    decision_pid = {}

    def after_cursor_execute(conn, cursor, statement, params, context, many):
        normalised = " ".join(statement.lower().split())
        current = threading.get_ident()
        if (
            current == thread_ids.get("reservation")
            and "from equipment_requirements" in normalised
            and "for update" in normalised
        ):
            reservation_locked.set()
            assert release_reservation.wait(10), "Race driver did not resume the reservation"
        if (
            current == thread_ids.get("decision")
            and "from event_requests" in normalised
            and "for " in normalised
        ):
            event_locked.set()

    def before_cursor_execute(conn, cursor, statement, params, context, many):
        normalised = " ".join(statement.lower().split())
        if (
            threading.get_ident() == thread_ids.get("decision")
            and "from equipment_types" in normalised
            and "for update" in normalised
        ):
            decision_pid["value"] = conn.connection.driver_connection.info.backend_pid

    def reserve():
        thread_ids["reservation"] = threading.get_ident()
        return app.test_client().post(
            "/api/equipment-requirements/1/reservations",
            headers=headers(),
            json={"quantity": 1},
        )

    def decide():
        thread_ids["decision"] = threading.get_ident()
        return app.test_client().post(
            "/api/equipment-requirements/1/mark-unavailable",
            headers=headers(),
            json={"reason": "Supplier recall"},
        )

    sql_event.listen(engine, "after_cursor_execute", after_cursor_execute)
    sql_event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reservation = pool.submit(reserve)
            assert reservation_locked.wait(10), "Reservation never acquired its row locks"
            decision = pool.submit(decide)
            assert event_locked.wait(10), "Decision never acquired its event row lock"
            deadline = monotonic() + 8
            blocked = False
            while monotonic() < deadline:
                if "value" in decision_pid:
                    with engine.connect() as connection:
                        blocked = bool(
                            connection.scalar(
                                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                {"pid": decision_pid["value"]},
                            )
                        )
                    if blocked:
                        break
                sleep(0.01)
            assert blocked, "Decision did not wait for the reservation's stock-pool lock"
            release_reservation.set()
            reservation_response = reservation.result(timeout=10)
            decision_response = decision.result(timeout=10)
    finally:
        release_reservation.set()
        sql_event.remove(engine, "after_cursor_execute", after_cursor_execute)
        sql_event.remove(engine, "before_cursor_execute", before_cursor_execute)

    assert reservation_response.status_code == 201
    assert decision_response.status_code == 409
    with Session(engine) as session:
        line = session.get(EquipmentRequirement, 1)
        reservations = session.scalars(
            select(EquipmentReservation).where(
                EquipmentReservation.equipment_requirement_id == line.id
            )
        ).all()
        assert line.status == "partially_reserved"
        assert [(row.quantity, row.event_request_id) for row in reservations] == [(1, 1)]
        assert unavailability.history_for(session, line.id) == []
