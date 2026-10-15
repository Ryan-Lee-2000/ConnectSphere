"""PostgreSQL evidence for SPL-111: simultaneous submissions, the partial unique index and grants.

SQLite cannot run two transactions against each other, so these cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), on a throw-away PostgreSQL database built with
the real Alembic migrations. Case IDs continue the QA-SPL-111 numbering used in
test_event_change_requests.py.

How the race is staged
----------------------
Both submissions use ``ordered_race`` (shared with SPL-118/137/138): the first request is held just
before it commits, and the test *proves* the second one is waiting on a PostgreSQL lock before
releasing the first. Without the row lock on the event, the second would not wait and the test
fails; with it, the second then sees the first Pending and is refused.
"""

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, time

import pytest
from app import create_app
from app.models import (
    Account,
    AccountRole,
    EventChangeRequest,
    EventChangeRequestItem,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

ITEM = {"field": "expected_attendance", "requested_value": 50, "reason": "More guests."}


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl111_{uuid.uuid4().hex[:12]}"
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
def scenario(pg_url):
    organiser = str(uuid.uuid4())
    engine = create_engine(pg_url)
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-111 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        session.add(Account(id=organiser, display_name="Erin Goh", organisation_id=organisation.id))
        session.add(AccountRole(account_id=organiser, role=Role.EVENT_ORGANISER.value))
        event = EventRequest(
            organiser_account_id=organiser,
            organisation_id=organisation.id,
            name="Harbour Lights Gala",
            purpose="Annual fundraiser",
            proposed_date=date(2026, 12, 5),
            start_time=time(18),
            end_time=time(22),
            expected_attendance=150,
            status="planning",
        )
        session.add(event)
        session.commit()
        event_id = event.id
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": {"organiser": organiser}.get}
    )
    yield app, engine, event_id, organiser
    app.extensions["engine"].dispose()
    engine.dispose()


def _submit_call(event_id, item=ITEM):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/change-requests",
        json={"items": [item]},
        headers={"Authorization": "Bearer organiser"},
    )


def _counts(engine):
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(EventChangeRequest)),
            session.scalar(select(func.count()).select_from(EventChangeRequestItem)),
        )


# QA-SPL-111-060 | AC4 | WB/PG
def test_qa_spl_111_060_ac4_pg_two_simultaneous_submissions_save_exactly_one(scenario):
    from test_exact_venue_bookings_postgres import ordered_race

    app, engine, event_id, _ = scenario
    other = {**ITEM, "field": "name", "requested_value": "A different name"}
    first, second = ordered_race(app, _submit_call(event_id), _submit_call(event_id, other))

    assert first[0] == 201
    assert second[0] == 409
    assert "already has a pending change request" in second[1]["error"]
    # Exactly one request with its single item; the loser left nothing behind.
    assert _counts(engine) == (1, 1)
    with Session(engine) as session:
        assert session.scalar(select(EventChangeRequestItem.field)) == "expected_attendance"


# QA-SPL-111-061 | AC4 | WB/PG
def test_qa_spl_111_061_ac4_pg_the_partial_unique_index_is_the_backstop(scenario):
    _, engine, event_id, organiser = scenario
    with Session(engine) as session:
        for _ in range(2):
            session.add(
                EventChangeRequest(
                    event_request_id=event_id,
                    status="pending",
                    submitted_by_account_id=organiser,
                    submitted_at=datetime(2026, 10, 20, 12),
                )
            )
        with pytest.raises(IntegrityError):
            session.commit()
    with engine.connect() as connection:
        definition = connection.scalar(
            text(
                "select indexdef from pg_indexes "
                "where indexname = 'uq_event_change_requests_one_pending'"
            )
        )
    assert "UNIQUE" in definition and "status" in definition and "pending" in definition


# QA-SPL-111-062 | AC2 | WB/PG
def test_qa_spl_111_062_ac2_pg_database_refuses_an_unknown_status_and_a_repeated_field(scenario):
    _, engine, event_id, organiser = scenario
    with Session(engine) as session:
        session.add(
            EventChangeRequest(
                event_request_id=event_id,
                status="resolved",
                submitted_by_account_id=organiser,
                submitted_at=datetime(2026, 10, 20, 12),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    with Session(engine) as session:
        request = EventChangeRequest(
            event_request_id=event_id,
            status="pending",
            submitted_by_account_id=organiser,
            submitted_at=datetime(2026, 10, 20, 12),
            items=[
                EventChangeRequestItem(field="name", requested_value="a", reason="r"),
                EventChangeRequestItem(field="name", requested_value="b", reason="r"),
            ],
        )
        session.add(request)
        with pytest.raises(IntegrityError):
            session.commit()


# QA-SPL-111-063 | AC3 | BB/PG
def test_qa_spl_111_063_ac3_pg_the_stored_time_is_the_real_instant(scenario):
    app, engine, event_id, _ = scenario
    response = _submit_call(event_id)(app.test_client())
    assert response.status_code == 201
    shown = response.get_json()["change_request"]["submitted_at"]
    assert shown.endswith("+08:00")
    with Session(engine) as session:
        stored = session.scalar(select(EventChangeRequest.submitted_at))
        assert stored.tzinfo is not None
        assert abs((stored - datetime.fromisoformat(shown)).total_seconds()) < 1


# QA-SPL-111-064 | AC2/AC5 | WB/PG (security: no browser access to the new tables)
def test_qa_spl_111_064_pg_browser_roles_have_no_access_and_rls_is_on(scenario, pg_url):
    _, engine, _, _ = scenario
    tables = ("event_change_requests", "event_change_request_items")
    with engine.connect() as connection:
        for table in tables:
            assert connection.scalar(
                text("select relrowsecurity from pg_class where relname = :t"), {"t": table}
            )
            for role in ("anon", "authenticated"):
                exists = connection.scalar(
                    text("select count(*) from pg_roles where rolname = :r"), {"r": role}
                )
                if not exists:
                    continue
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not connection.scalar(
                        text("select has_table_privilege(:r, :t, :p)"),
                        {"r": role, "t": table, "p": privilege},
                    ), (role, table, privilege)


# QA-SPL-111-065 | AC5 | WB/PG
def test_qa_spl_111_065_pg_deleting_the_event_removes_its_requests_and_items(scenario):
    app, engine, event_id, _ = scenario
    assert _submit_call(event_id)(app.test_client()).status_code == 201
    with Session(engine) as session:
        session.delete(session.get(EventRequest, event_id))
        session.commit()
    assert _counts(engine) == (0, 0)


# QA-SPL-111-066 | AC2 | WB/PG: the migration downgrades and upgrades again cleanly.
def test_qa_spl_111_066_pg_migration_downgrades_and_upgrades_again(pg_url):
    environment = {**os.environ, "DATABASE_URL": pg_url}
    for command in (["downgrade", "s3_requirement_unavailability"], ["upgrade", "head"]):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            capture_output=True,
            text=True,
            env=environment,
        )
        assert result.returncode == 0, result.stderr
    engine = create_engine(pg_url)
    with engine.connect() as connection:
        assert connection.scalar(text("select count(*) from event_change_requests")) == 0
    engine.dispose()
