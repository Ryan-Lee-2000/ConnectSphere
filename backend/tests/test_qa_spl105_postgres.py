"""PostgreSQL evidence for SPL-105: concurrent completion and the migration.

SQLite serialises writes, so it cannot show a race. These cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), reusing SPL-85's throw-away database fixture,
seeded event and race harness. Seeded events end in the past, so the real clock is after the end.
"""

import os
import subprocess
import sys
from datetime import date, timedelta

import pytest
import test_event_confirmation_postgres as spl85
from app.models import EventRequest, EventStatusHistory
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3
pg_url, engine = spl85.pg_url, spl85.engine


def _complete(event_id, note=None):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/complete",
        json={"note": note},
        headers={"Authorization": "Bearer coordinator"},
    )


def _ended_preparing_event(engine, ids, organisation_id, venue_id, type_id, day):
    event_id, _ = spl85._seed_ready_event(engine, ids, organisation_id, venue_id, type_id, day)
    with Session(engine) as session:
        session.execute(
            update(EventRequest).where(EventRequest.id == event_id).values(status="preparing")
        )
        session.commit()
    return event_id


# QA-SPL-105-080 | AC2/AC4 | BB
def test_qa_spl_105_080_concurrent_completions_complete_once(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2026, 9, 2) + timedelta(days=run)
            event_id = _ended_preparing_event(engine, ids, organisation_id, venue_id, type_id, day)

            results = spl85._race(
                app, [_complete(event_id, "First note."), _complete(event_id, "Second note.")]
            )

            assert sorted(status for status, _ in results) == [200, 409], results
            refused = next(body for status, body in results if status == 409)
            assert refused["error"] == "This event is already completed."
            winner = next(body for status, body in results if status == 200)
            with Session(engine) as session:
                stored = session.get(EventRequest, event_id)
                assert stored.status == "completed"
                assert stored.completion_note == winner["event"]["completion_note"]
                assert (
                    session.scalar(
                        select(func.count(EventStatusHistory.id)).where(
                            EventStatusHistory.event_request_id == event_id,
                            EventStatusHistory.action == "complete",
                        )
                    )
                    == 1
                )
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-105-081 | AC4 | WB
def test_qa_spl_105_081_migration_adds_paired_completion_columns(engine):
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("event_requests")}
    for name in ("completed_by_account_id", "completed_at", "completion_note"):
        assert columns[name]["nullable"] is True
    assert any(
        foreign_key["constrained_columns"] == ["completed_by_account_id"]
        and foreign_key["referred_table"] == "accounts"
        for foreign_key in inspector.get_foreign_keys("event_requests")
    )
    checks = {check["name"] for check in inspector.get_check_constraints("event_requests")}
    assert "ck_event_requests_completion_recorded" in checks
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "s4_event_completion"
        )


# QA-SPL-105-082 | AC4 | WB
def test_qa_spl_105_082_postgres_refuses_a_note_without_an_actor(engine):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    event_id = _ended_preparing_event(
        engine, ids, organisation_id, venue_id, type_id, date(2026, 9, 10)
    )
    with Session(engine) as session, pytest.raises(IntegrityError) as refused:
        session.execute(
            update(EventRequest)
            .where(EventRequest.id == event_id)
            .values(completion_note="Orphan note")
        )
    assert "ck_event_requests_completion_recorded" in str(refused.value)


# QA-SPL-105-083 | AC4 | WB
def test_qa_spl_105_083_migration_downgrades_and_upgrades_cleanly(engine, pg_url):
    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": pg_url},
        )

    down = alembic("downgrade", "s4_safety_reviews")
    assert down.returncode == 0, down.stderr
    names = {column["name"] for column in inspect(engine).get_columns("event_requests")}
    assert not names & {"completed_by_account_id", "completed_at", "completion_note"}

    up = alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    names = {column["name"] for column in inspect(engine).get_columns("event_requests")}
    assert {"completed_by_account_id", "completed_at", "completion_note"} <= names
