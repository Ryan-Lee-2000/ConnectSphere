"""PostgreSQL QA scripts for SPL-67 (CS-E06-S4 — approve an event request).

Evidence for QA-SPL-67-080 to QA-SPL-67-086. These cases need a real PostgreSQL server, so they
run only under `npm run integration` (INTEGRATION_DATABASE_URL). Each test builds its own
throw-away database on that server, migrates it with Alembic, and drops it afterwards.
"""

import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, time

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.event_review import APPROVE, InvalidStatusTransition, transition_event_status
from app.models import (
    Account,
    AccountRole,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Organisation,
    Role,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

PREVIOUS_HEAD = "s2_clarification_requests"


def _alembic(url: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )


@pytest.fixture
def server():
    return make_url(os.environ["INTEGRATION_DATABASE_URL"])


@pytest.fixture
def fresh_database(server):
    """An empty database, dropped when the test ends. Yields its URL."""

    name = f"qa67_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def pg_url(fresh_database):
    upgraded = _alembic(fresh_database, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    return fresh_database


@pytest.fixture
def engine(pg_url):
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


def _seed(engine, status="under_review"):
    manager, alice, bob, owner = (str(uuid.uuid4()) for _ in range(4))
    with Session(engine) as session:
        organisation = Organisation(name="Postgres Client")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (manager, "Morgan Manager", Role.EVENT_OPERATIONS_MANAGER),
            (alice, "Alice Tan", Role.EVENT_COORDINATOR),
            (bob, "Bob Lim", Role.EVENT_COORDINATOR),
            (owner, "Olivia Owner", Role.EVENT_ORGANISER),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    organisation_id=organisation.id if role == Role.EVENT_ORGANISER else None,
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        event = EventRequest(
            organiser_account_id=owner,
            organisation_id=organisation.id,
            name="Postgres Forum",
            purpose="Proving the PostgreSQL behaviour",
            proposed_date=date(2026, 12, 4),
            start_time=time(9, 0),
            end_time=time(12, 0),
            expected_attendance=80,
            status=status,
            submitted_at=datetime(2026, 9, 20, 9, tzinfo=SINGAPORE),
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=alice,
                assigned_by_account_id=manager,
                assigned_at=datetime(2026, 9, 21, 9, tzinfo=SINGAPORE),
            )
        )
        session.commit()
        return {"event": event.id, "manager": manager, "alice": alice, "bob": bob, "owner": owner}


def _app(pg_url, ids):
    tokens = {name: ids[name] for name in ("alice", "bob", "owner", "manager")}
    return create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": tokens.__getitem__}
    )


def _auth(who):
    return {"Authorization": f"Bearer {who}"}


def test_qa_spl67_080_migration_adds_two_nullable_typed_columns_with_a_foreign_key(engine):
    """QA-SPL-67-080 [White-box / Migration] AC3: uuid and timestamptz columns, FK to accounts."""

    with engine.connect() as connection:
        columns = {
            row.column_name: (row.data_type, row.is_nullable)
            for row in connection.execute(
                text(
                    "select column_name, data_type, is_nullable from information_schema.columns "
                    "where table_name = 'event_requests' "
                    "and column_name in ('approved_by_account_id', 'approved_at')"
                )
            )
        }
        references = (
            connection.execute(
                text(
                    "select ccu.table_name from information_schema.table_constraints tc "
                    "join information_schema.key_column_usage kcu "
                    "  on tc.constraint_name = kcu.constraint_name "
                    "join information_schema.constraint_column_usage ccu "
                    "  on tc.constraint_name = ccu.constraint_name "
                    "where tc.constraint_type = 'FOREIGN KEY' "
                    "and tc.table_name = 'event_requests' "
                    "and kcu.column_name = 'approved_by_account_id'"
                )
            )
            .scalars()
            .all()
        )
    assert columns == {
        "approved_by_account_id": ("uuid", "YES"),
        "approved_at": ("timestamp with time zone", "YES"),
    }
    assert references == ["accounts"]


def test_qa_spl67_081_the_database_refuses_an_unknown_approver(engine):
    """QA-SPL-67-081 [White-box] AC3: an approval cannot name an account that does not exist."""

    ids = _seed(engine)
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text("update event_requests set approved_by_account_id = :who where id = :i"),
                {"who": str(uuid.uuid4()), "i": ids["event"]},
            )
        session.rollback()


def test_qa_spl67_082_existing_requests_survive_the_upgrade_with_no_decision(fresh_database):
    """QA-SPL-67-082 [Migration] AC3,6: rows created before the migration keep every value."""

    assert _alembic(fresh_database, "upgrade", PREVIOUS_HEAD).returncode == 0
    engine = create_engine(fresh_database)
    try:
        with engine.begin() as connection:
            organisation = connection.execute(
                text("insert into organisations (name) values ('Old client') returning id")
            ).scalar_one()
            owner = str(uuid.uuid4())
            connection.execute(
                text(
                    "insert into accounts (id, display_name, organisation_id, is_active) "
                    "values (:id, 'Old organiser', :org, true)"
                ),
                {"id": owner, "org": organisation},
            )
            event = connection.execute(
                text(
                    "insert into event_requests (organiser_account_id, organisation_id, name, "
                    "status, required_facilities, accessibility_needs, registration_required) "
                    "values (:owner, :org, 'Old draft', 'draft', '[]', '[]', false) returning id"
                ),
                {"owner": owner, "org": organisation},
            ).scalar_one()
        upgraded = _alembic(fresh_database, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "select name, status, approved_by_account_id, approved_at "
                    "from event_requests where id = :i"
                ),
                {"i": event},
            ).one()
        assert tuple(row) == ("Old draft", "draft", None, None)
    finally:
        engine.dispose()


def test_qa_spl67_083_downgrade_removes_the_columns_and_upgrade_restores_them(pg_url):
    """QA-SPL-67-083 [Migration] AC3: the migration reverses cleanly and can be re-applied."""

    downgraded = _alembic(pg_url, "downgrade", PREVIOUS_HEAD)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(pg_url)
    try:
        query = text(
            "select count(*) from information_schema.columns where table_name = 'event_requests' "
            "and column_name in ('approved_by_account_id', 'approved_at')"
        )
        with engine.connect() as connection:
            assert connection.execute(query).scalar_one() == 0
        assert _alembic(pg_url, "upgrade", "head").returncode == 0
        with engine.connect() as connection:
            assert connection.execute(query).scalar_one() == 2
    finally:
        engine.dispose()


def test_qa_spl67_084_approval_end_to_end_on_postgres(engine, pg_url):
    """QA-SPL-67-084 [UAT] AC1,3,4: approve, then the organiser reads a timezone-aware outcome."""

    ids = _seed(engine)
    app = _app(pg_url, ids)
    client = app.test_client()
    url = f"/api/event-requests/{ids['event']}/approve"

    assert client.post(url, headers=_auth("bob")).status_code == 404
    approved = client.post(url, headers=_auth("alice"))
    assert approved.status_code == 200
    assert approved.json["event"]["status"] == "planning"
    outcome = client.get(f"/api/event-requests/{ids['event']}", headers=_auth("owner")).json[
        "event_request"
    ]
    assert outcome["approved_by"] == {"id": ids["alice"], "name": "Alice Tan"}
    assert outcome["approved_at"].endswith("+08:00")
    assert client.post(url, headers=_auth("alice")).status_code == 409
    with Session(engine) as session:
        assert session.get(EventRequest, ids["event"]).approved_at.tzinfo is not None
    app.extensions["engine"].dispose()


def test_qa_spl67_085_two_simultaneous_approvals_produce_one_decision(engine, pg_url):
    """QA-SPL-67-085 [Concurrency] AC1,6: a real row-lock race; exactly one approval wins."""

    ids = _seed(engine)
    outcome = {}
    first_holds_the_row = threading.Event()

    def second_request():
        first_holds_the_row.wait(5)
        with Session(engine) as session:
            try:
                transition_event_status(
                    session,
                    event_request_id=ids["event"],
                    action=APPROVE,
                    actor_account_id=ids["alice"],
                    changed_at=datetime.now(SINGAPORE),
                )
                session.commit()
                outcome["second"] = "won"
            except InvalidStatusTransition:
                session.rollback()
                outcome["second"] = "refused"

    with Session(engine) as first:
        transition_event_status(
            first,
            event_request_id=ids["event"],
            action=APPROVE,
            actor_account_id=ids["alice"],
            changed_at=datetime.now(SINGAPORE),
        )
        worker = threading.Thread(target=second_request)
        worker.start()
        first_holds_the_row.set()
        worker.join(0.5)  # the second transaction is now blocked on the first one's row lock
        first.commit()
    worker.join(10)

    assert outcome == {"second": "refused"}
    with Session(engine) as session:
        rows = session.query(EventStatusHistory).filter_by(action=APPROVE).all()
        assert len(rows) == 1


def test_qa_spl67_086_the_status_constraint_still_rejects_unknown_statuses(engine):
    """QA-SPL-67-086 [White-box] AC5,6: approval added no status; the constraint is unchanged."""

    ids = _seed(engine)
    with Session(engine) as session:
        session.execute(
            text("update event_requests set status = 'planning' where id = :i"),
            {"i": ids["event"]},
        )
        session.commit()
        with pytest.raises(IntegrityError):
            session.execute(
                text("update event_requests set status = 'approved_pending' where id = :i"),
                {"i": ids["event"]},
            )
        session.rollback()
