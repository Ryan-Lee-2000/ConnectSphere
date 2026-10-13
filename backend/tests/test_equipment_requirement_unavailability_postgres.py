"""SPL-93 lifecycle races use real PostgreSQL event row locks."""

import os
import subprocess
import sys
import uuid
from types import SimpleNamespace

import pytest
from app import equipment_requirement_unavailability as unavailability
from app.models import EquipmentRequirement, EventRequest
from sqlalchemy import create_engine, select, text
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
