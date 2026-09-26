"""PostgreSQL QA scripts for SPL-65 (CS-E06-S2 — request clarification).

Evidence for QA-SPL-65-063 to QA-SPL-65-071. These cases need a real PostgreSQL server, so they
run only under `npm run integration` (INTEGRATION_DATABASE_URL). Each test builds its own
throw-away database on that server, migrates it with Alembic, and drops it afterwards, so it
never touches or depends on the data in the integration database itself.
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
from app.event_review import REQUEST_CLARIFICATION, InvalidStatusTransition, transition_event_status
from app.models import (
    Account,
    AccountRole,
    ClarificationRequest,
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

PREVIOUS_HEAD = "s2_accessibility_needs_list"


def _alembic(url: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )


@pytest.fixture
def pg_url():
    """A brand-new, fully migrated database, dropped when the test ends."""

    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"qa65_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def engine(pg_url):
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


def _seed(engine):
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
            status="under_review",
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
        return {
            "event": event.id,
            "manager": manager,
            "alice": alice,
            "bob": bob,
            "owner": owner,
        }


# QA-SPL-65-063
def test_qa_spl65_063_migration_creates_the_locked_down_clarification_table(engine):
    """QA-SPL-65-063 [White-box / Migration] AC3,6: columns, index and row-level security."""

    with engine.connect() as connection:
        columns = {
            row.column_name: (row.data_type, row.is_nullable)
            for row in connection.execute(
                text(
                    "select column_name, data_type, is_nullable from information_schema.columns "
                    "where table_name = 'clarification_requests'"
                )
            )
        }
        indexes = (
            connection.execute(
                text("select indexname from pg_indexes where tablename = 'clarification_requests'")
            )
            .scalars()
            .all()
        )
        rls = connection.execute(
            text("select relrowsecurity from pg_class where relname = 'clarification_requests'")
        ).scalar_one()
        public_grants = connection.execute(
            text(
                "select count(*) from information_schema.role_table_grants "
                "where table_name = 'clarification_requests' and grantee = 'PUBLIC'"
            )
        ).scalar_one()

    assert columns == {
        "id": ("integer", "NO"),
        "event_request_id": ("integer", "NO"),
        "message": ("text", "NO"),
        "author_account_id": ("uuid", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
    }
    assert "ix_clarification_requests_event_request_id" in indexes
    assert rls is True
    assert public_grants == 0


# QA-SPL-65-064
def test_qa_spl65_064_database_constraint_accepts_the_new_status_and_rejects_others(engine):
    """QA-SPL-65-064 [White-box / Migration] AC4,7: the widened check constraint on PostgreSQL."""

    ids = _seed(engine)
    with Session(engine) as session:
        session.execute(
            text("update event_requests set status = 'returned_for_clarification' where id = :i"),
            {"i": ids["event"]},
        )
        session.commit()
        with pytest.raises(IntegrityError):
            session.execute(
                text("update event_requests set status = 'returned' where id = :i"),
                {"i": ids["event"]},
            )
        session.rollback()


# QA-SPL-65-065
def test_qa_spl65_065_foreign_keys_and_not_null_protect_the_record(engine):
    """QA-SPL-65-065 [White-box] AC3: no orphan, anonymous or empty clarification can exist."""

    ids = _seed(engine)
    moment = datetime(2026, 9, 27, 9, tzinfo=SINGAPORE)
    bad_rows = [
        {"event_request_id": 999999, "message": "x", "author_account_id": ids["alice"]},
        {"event_request_id": ids["event"], "message": "x", "author_account_id": str(uuid.uuid4())},
        {"event_request_id": ids["event"], "message": None, "author_account_id": ids["alice"]},
    ]
    for row in bad_rows:
        with Session(engine) as session:
            session.add(ClarificationRequest(created_at=moment, **row))
            with pytest.raises(IntegrityError):
                session.commit()


# QA-SPL-65-066
def test_qa_spl65_066_deleting_an_event_cascades_to_its_clarifications_in_the_database(engine):
    """QA-SPL-65-066 [White-box] AC6: ON DELETE CASCADE, independent of the ORM."""

    ids = _seed(engine)
    with Session(engine) as session:
        session.add(
            ClarificationRequest(
                event_request_id=ids["event"],
                message="Will be removed",
                author_account_id=ids["alice"],
                created_at=datetime(2026, 9, 27, 9, tzinfo=SINGAPORE),
            )
        )
        session.commit()
        session.execute(text("delete from event_coordinator_assignments"))
        session.execute(text("delete from event_requests where id = :i"), {"i": ids["event"]})
        session.commit()
        assert session.execute(text("select count(*) from clarification_requests")).scalar() == 0


# QA-SPL-65-067
def test_qa_spl65_067_downgrade_is_refused_while_an_event_is_returned_then_succeeds(pg_url, engine):
    """QA-SPL-65-067 [White-box / Migration] AC4: the migration is reversible without data loss."""

    ids = _seed(engine)
    with Session(engine) as session:
        session.execute(
            text("update event_requests set status = 'returned_for_clarification' where id = :i"),
            {"i": ids["event"]},
        )
        session.commit()

    refused = _alembic(pg_url, "downgrade", PREVIOUS_HEAD)
    assert refused.returncode != 0
    assert "Returned for clarification" in refused.stderr

    with Session(engine) as session:
        session.execute(
            text("update event_requests set status = 'under_review' where id = :i"),
            {"i": ids["event"]},
        )
        session.commit()
    downgraded = _alembic(pg_url, "downgrade", PREVIOUS_HEAD)
    assert downgraded.returncode == 0, downgraded.stderr
    with engine.connect() as connection:
        assert (
            connection.execute(text("select to_regclass('clarification_requests')")).scalar()
            is None
        )
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(text("update event_requests set status = 'returned_for_clarification'"))

    restored = _alembic(pg_url, "upgrade", "head")
    assert restored.returncode == 0, restored.stderr
    with engine.connect() as connection:
        assert connection.execute(text("select to_regclass('clarification_requests')")).scalar()


# QA-SPL-65-068
def test_qa_spl65_068_two_simultaneous_requests_record_exactly_one_clarification(engine):
    """QA-SPL-65-068 [Concurrency] AC7: the race is settled by the conditional UPDATE."""

    ids = _seed(engine)
    outcome: dict[str, str] = {}
    first_holds_the_row = threading.Event()
    second_has_started = threading.Event()

    def second_request():
        first_holds_the_row.wait(5)
        with Session(engine) as session:
            second_has_started.set()
            try:
                transition_event_status(
                    session,
                    event_request_id=ids["event"],
                    action=REQUEST_CLARIFICATION,
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
            action=REQUEST_CLARIFICATION,
            actor_account_id=ids["alice"],
            changed_at=datetime.now(SINGAPORE),
        )
        first.add(
            ClarificationRequest(
                event_request_id=ids["event"],
                message="Winner",
                author_account_id=ids["alice"],
                created_at=datetime.now(SINGAPORE),
            )
        )
        thread = threading.Thread(target=second_request)
        thread.start()
        first_holds_the_row.set()
        second_has_started.wait(5)
        first.commit()
        thread.join(10)

    assert outcome == {"second": "refused"}
    with Session(engine) as session:
        assert session.query(ClarificationRequest).count() == 1
        assert (
            session.query(EventStatusHistory).filter_by(action=REQUEST_CLARIFICATION).count() == 1
        )


# QA-SPL-65-069
def test_qa_spl65_069_full_api_flow_runs_against_postgresql(pg_url, engine):
    """QA-SPL-65-069 [UAT / API] AC1-6: the real routes on the real database."""

    ids = _seed(engine)
    tokens = {name: ids[name] for name in ("alice", "bob", "owner", "manager")}
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": tokens.__getitem__}
    )
    client = app.test_client()
    auth = lambda who: {"Authorization": f"Bearer {who}"}  # noqa: E731
    url = f"/api/event-requests/{ids['event']}/request-clarification"

    assert client.post(url, json={"message": "  First  "}, headers=auth("alice")).status_code == 200
    assert client.post(url, json={"message": "again"}, headers=auth("alice")).status_code == 409
    with Session(engine) as session:
        session.execute(text("update event_requests set status = 'under_review'"))
        session.commit()
    assert client.post(url, json={"message": "Second"}, headers=auth("alice")).status_code == 200

    seen = client.get(f"/api/event-requests/{ids['event']}", headers=auth("owner")).json
    history = seen["event_request"]["clarifications"]
    assert [c["message"] for c in history] == ["Second", "First"]
    assert history[0]["created_at"].endswith("+08:00")
    assert seen["event_request"]["status"] == "returned_for_clarification"
    app.extensions["engine"].dispose()


# QA-SPL-65-070
@pytest.mark.parametrize("event_id", [2**31, 2**40, 2**63])
def test_qa_spl65_070_out_of_range_event_ids_answer_404_not_500(pg_url, engine, event_id):
    """QA-SPL-65-070 [Boundary / Negative] AC1: ids are 32-bit; overflow is a 404."""

    ids = _seed(engine)
    tokens = {"alice": ids["alice"]}
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": tokens.__getitem__}
    )

    response = app.test_client().post(
        f"/api/event-requests/{event_id}/request-clarification",
        json={"message": "hello"},
        headers={"Authorization": "Bearer alice"},
    )

    assert response.status_code == 404
    app.extensions["engine"].dispose()


# QA-SPL-65-071
def test_qa_spl65_071_a_message_at_the_limit_is_stored_without_truncation(pg_url, engine):
    """QA-SPL-65-071 [Boundary] AC2,3: PostgreSQL returns all 2000 characters unchanged."""

    ids = _seed(engine)
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": pg_url,
            "IDENTITY_VERIFIER": {"alice": ids["alice"]}.__getitem__,
        }
    )
    message = ("é✓" * 1000)[:2000]

    response = app.test_client().post(
        f"/api/event-requests/{ids['event']}/request-clarification",
        json={"message": message},
        headers={"Authorization": "Bearer alice"},
    )

    assert response.status_code == 200
    with Session(engine) as session:
        assert session.query(ClarificationRequest).one().message == message
    app.extensions["engine"].dispose()
