"""PostgreSQL QA scripts for SPL-68 (CS-E06-S5 - reject an event request).

Evidence for QA-SPL-68-094 to QA-SPL-68-103. These cases need a real PostgreSQL server, so they
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
from app.event_review import APPROVE, REJECT, InvalidStatusTransition, transition_event_status
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

PREVIOUS_HEAD = "s2_event_approval"


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

    name = f"qa68_{uuid.uuid4().hex[:12]}"
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


def _decision_columns(engine):
    with engine.connect() as connection:
        return {
            row.column_name: (row.data_type, row.is_nullable)
            for row in connection.execute(
                text(
                    "select column_name, data_type, is_nullable from information_schema.columns "
                    "where table_name = 'event_requests' and column_name in "
                    "('rejected_by_account_id', 'rejected_at', 'rejection_reason')"
                )
            )
        }


def test_qa_spl68_094_migration_adds_three_nullable_typed_columns_with_a_foreign_key(engine):
    """QA-SPL-68-094 [White-box / Migration] AC3: uuid, timestamptz and text, FK to accounts."""

    assert _decision_columns(engine) == {
        "rejected_by_account_id": ("uuid", "YES"),
        "rejected_at": ("timestamp with time zone", "YES"),
        "rejection_reason": ("text", "YES"),
    }
    with engine.connect() as connection:
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
                    "and kcu.column_name = 'rejected_by_account_id'"
                )
            )
            .scalars()
            .all()
        )
    assert references == ["accounts"]


def test_qa_spl68_095_the_database_refuses_an_unknown_decision_maker(engine):
    """QA-SPL-68-095 [White-box] AC3: a rejection cannot name an account that does not exist."""

    ids = _seed(engine)
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "update event_requests set rejected_by_account_id = :who, "
                    "rejected_at = now(), rejection_reason = 'x' where id = :i"
                ),
                {"who": str(uuid.uuid4()), "i": ids["event"]},
            )
        session.rollback()


@pytest.mark.parametrize(
    "assignment",
    [
        "rejected_by_account_id = :who",
        "rejected_at = now()",
        "rejection_reason = 'only a reason'",
        "rejected_by_account_id = :who, rejected_at = now()",
        "rejected_by_account_id = :who, rejection_reason = 'no time'",
        "rejected_at = now(), rejection_reason = 'no decision-maker'",
    ],
)
def test_qa_spl68_096_the_check_constraint_refuses_a_partial_record(engine, assignment):
    """QA-SPL-68-096 [White-box] AC3,6: PostgreSQL enforces all-three-or-none."""

    ids = _seed(engine)
    with Session(engine) as session:
        with pytest.raises(IntegrityError, match="ck_event_requests_rejection_complete"):
            session.execute(
                text(f"update event_requests set {assignment} where id = :i"),
                {"who": ids["alice"], "i": ids["event"]},
            )
        session.rollback()


def test_qa_spl68_097_the_check_constraint_accepts_a_complete_or_empty_record(engine):
    """QA-SPL-68-097 [White-box] AC3: a full record and a cleared record are both valid."""

    ids = _seed(engine)
    with Session(engine) as session:
        session.execute(
            text(
                "update event_requests set rejected_by_account_id = :who, "
                "rejected_at = now(), rejection_reason = 'Complete' where id = :i"
            ),
            {"who": ids["alice"], "i": ids["event"]},
        )
        session.commit()
        session.execute(
            text(
                "update event_requests set rejected_by_account_id = null, "
                "rejected_at = null, rejection_reason = null where id = :i"
            ),
            {"i": ids["event"]},
        )
        session.commit()


def test_qa_spl68_098_existing_requests_survive_the_upgrade_with_no_decision(fresh_database):
    """QA-SPL-68-098 [Migration] AC3,6: rows created before the migration keep every value."""

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
                    "select name, status, rejected_by_account_id, rejected_at, rejection_reason "
                    "from event_requests where id = :i"
                ),
                {"i": event},
            ).one()
        assert tuple(row) == ("Old draft", "draft", None, None, None)
    finally:
        engine.dispose()


def test_qa_spl68_099_downgrade_removes_the_columns_and_upgrade_restores_them(pg_url):
    """QA-SPL-68-099 [Migration] AC3: the migration reverses cleanly and can be re-applied."""

    downgraded = _alembic(pg_url, "downgrade", PREVIOUS_HEAD)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(pg_url)
    try:
        assert _decision_columns(engine) == {}
        with engine.connect() as connection:
            constraint = text(
                "select count(*) from pg_constraint "
                "where conname = 'ck_event_requests_rejection_complete'"
            )
            assert connection.execute(constraint).scalar_one() == 0
        assert _alembic(pg_url, "upgrade", "head").returncode == 0
        assert len(_decision_columns(engine)) == 3
        with engine.connect() as connection:
            assert connection.execute(constraint).scalar_one() == 1
    finally:
        engine.dispose()


def test_qa_spl68_100_rejection_end_to_end_on_postgres(engine, pg_url):
    """QA-SPL-68-100 [UAT] AC1,2,3,4: reject, then the organiser reads a timezone-aware outcome."""

    ids = _seed(engine)
    app = _app(pg_url, ids)
    client = app.test_client()
    url = f"/api/event-requests/{ids['event']}/reject"
    body = {"reason": "  Not workable on PostgreSQL.  "}

    assert client.post(url, json=body, headers=_auth("bob")).status_code == 404
    assert client.post(url, json={"reason": " "}, headers=_auth("alice")).status_code == 400
    rejected = client.post(url, json=body, headers=_auth("alice"))
    assert rejected.status_code == 200
    assert rejected.json["event"]["status"] == "rejected"
    outcome = client.get(f"/api/event-requests/{ids['event']}", headers=_auth("owner")).json[
        "event_request"
    ]
    assert outcome["rejected_by"] == {"id": ids["alice"], "name": "Alice Tan"}
    assert outcome["rejected_at"].endswith("+08:00")
    assert outcome["rejection_reason"] == "Not workable on PostgreSQL."
    assert client.post(url, json=body, headers=_auth("alice")).status_code == 409
    with Session(engine) as session:
        assert session.get(EventRequest, ids["event"]).rejected_at.tzinfo is not None
    app.extensions["engine"].dispose()


def test_qa_spl68_101_two_simultaneous_rejections_produce_one_decision(engine):
    """QA-SPL-68-101 [Concurrency] AC1,6: a real row-lock race; exactly one rejection wins."""

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
                    action=REJECT,
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
            action=REJECT,
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
        assert len(session.query(EventStatusHistory).filter_by(action=REJECT).all()) == 1


def test_qa_spl68_102_a_rejection_racing_an_approval_leaves_exactly_one_decision(engine):
    """QA-SPL-68-102 [Concurrency] AC1,5,6: approve and reject cannot both win on the same event."""

    ids = _seed(engine)
    results = {}
    approval_holds_the_row = threading.Event()

    def rejection():
        approval_holds_the_row.wait(5)
        with Session(engine) as session:
            try:
                transition_event_status(
                    session,
                    event_request_id=ids["event"],
                    action=REJECT,
                    actor_account_id=ids["alice"],
                    changed_at=datetime.now(SINGAPORE),
                )
                session.commit()
                results["reject"] = "won"
            except InvalidStatusTransition:
                session.rollback()
                results["reject"] = "refused"

    with Session(engine) as approval:
        transition_event_status(
            approval,
            event_request_id=ids["event"],
            action=APPROVE,
            actor_account_id=ids["alice"],
            changed_at=datetime.now(SINGAPORE),
        )
        worker = threading.Thread(target=rejection)
        worker.start()
        approval_holds_the_row.set()
        worker.join(0.5)
        approval.commit()
    worker.join(10)

    assert results == {"reject": "refused"}
    with Session(engine) as session:
        actions = [row.action for row in session.query(EventStatusHistory)]
        assert actions == [APPROVE]
        assert session.get(EventRequest, ids["event"]).status == "planning"


def test_qa_spl68_103_the_status_constraint_still_stores_rejected_and_refuses_unknowns(engine):
    """QA-SPL-68-103 [White-box] AC3,5: rejected is storable; the vocabulary gained nothing new."""

    ids = _seed(engine)
    with Session(engine) as session:
        session.execute(
            text(
                "update event_requests set status = 'rejected', rejected_by_account_id = :who, "
                "rejected_at = now(), rejection_reason = 'x' where id = :i"
            ),
            {"who": ids["alice"], "i": ids["event"]},
        )
        session.commit()
        with pytest.raises(IntegrityError):
            session.execute(
                text("update event_requests set status = 'rejected_pending' where id = :i"),
                {"i": ids["event"]},
            )
        session.rollback()
