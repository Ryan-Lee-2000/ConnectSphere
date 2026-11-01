"""SPL-112 PostgreSQL lock boundary, constraints and migration safety."""

import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest
import test_event_change_requests_postgres as pg
import test_qa_spl112 as qa
from app.models import Account, AccountRole, EventCoordinatorAssignment, EventDetailChange, Role
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_exact_venue_bookings_postgres import ordered_race

pytestmark = pg.pytestmark
pg_url = pg.pg_url
scenario = pg.scenario


@pytest.fixture
def prepared(scenario):
    app, engine, event, organiser = scenario
    coordinator = qa.base.COORDINATOR
    with Session(engine) as s:
        s.add(Account(id=coordinator, display_name="QA coordinator"))
        s.add(AccountRole(account_id=coordinator, role=Role.EVENT_COORDINATOR.value))
        s.add(
            EventCoordinatorAssignment(
                event_request_id=event,
                coordinator_account_id=coordinator,
                assigned_by_account_id=coordinator,
                assigned_at=datetime.now(timezone.utc),
            )
        )
        s.commit()
    app.config["IDENTITY_VERIFIER"] = {"organiser": organiser, "coordinator": coordinator}.get
    client = app.test_client()
    req = qa.request(client, event)
    return app, engine, event, req


# QA-SPL-112-060 | AC3/AC5 | WB
def test_qa_spl_112_060_concurrent_save_once(prepared):
    app, engine, event, req = prepared
    decisions = qa.choices(req)
    token = qa.preview(app.test_client(), event, req, decisions).json["preview_token"]

    def call(client):
        return client.post(
            qa.url(event, req),
            json={"decisions": decisions, "preview_token": token},
            headers=qa.base.headers("coordinator"),
        )

    first, second = ordered_race(app, call, call)
    assert first[0] == 200 and second[0] == 409
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(EventDetailChange)) == 1
        assert s.scalar(text("SELECT status FROM event_change_requests")) == "closed"


@pytest.mark.parametrize(
    "values",
    [
        "decision='accepted'",
        "decision='declined'",
        "decided_at=now()",
        "decision='unknown'",
        "decline_reason='reason'",
    ],
)
# QA-SPL-112-061 | AC1/AC4 | WB
def test_qa_spl_112_061_incomplete_decision_constraint(prepared, values):
    _, engine, _, req = prepared
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(f"UPDATE event_change_request_items SET {values} WHERE id=:id"),
            {"id": req["items"][0]["id"]},
        )
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT decision FROM event_change_request_items")) is None


# QA-SPL-112-062 | AC4/AC5 | WB
def test_qa_spl_112_062_downgrade_preserves_decisions(prepared, pg_url):
    app, engine, event, req = prepared
    assert qa.save(app.test_client(), event, req, qa.choices(req)).status_code == 200
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "s4_equipment_request_ids"],
        env={**os.environ, "DATABASE_URL": pg_url},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Cannot downgrade SPL-112 after decisions" in result.stderr
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT decision FROM event_change_request_items")) == "accepted"
        assert (
            conn.scalar(text("SELECT version_num FROM alembic_version"))
            # SPL-126 is the current head. A refused downgrade must preserve that head.
            == "s4_notification_types"
        )


# QA-SPL-112-063 | AC4 | WB
def test_qa_spl_112_063_upgrade_preserves_pending(prepared, pg_url):
    _, engine, _, req = prepared
    for target in ["s4_equipment_request_ids", "head"]:
        direction = "upgrade" if target == "head" else "downgrade"
        result = subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            env={**os.environ, "DATABASE_URL": pg_url},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id,decision,decided_at FROM event_change_request_items")
        ).one()
        assert tuple(row) == (req["items"][0]["id"], None, None)
