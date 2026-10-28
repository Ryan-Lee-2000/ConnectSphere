"""Coordinator assignment and editing concurrency proofs against disposable PostgreSQL.

Each test interleaves two real transactions, which SQLite cannot express, so they run only
under `npm run integration`. Cases cover competing assignments, terminal transitions and the
shared SPL-108 event/assignment lock boundary.
"""

import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time
from time import monotonic, sleep

import pytest
from app import create_app
from app.coordinator_assignment import (
    NON_REASSIGNABLE_STATUSES,
    SUBMITTED,
    UNDER_REVIEW,
    _reassignment_statement,
)
from app.models import (
    Account,
    AccountRole,
    EmailDelivery,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventDetailChange,
    EventRequest,
    Notification,
    Organisation,
    Role,
)
from sqlalchemy import (
    create_engine,
    delete,
    func,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy import (
    event as sql_event,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)


def _transition(session, event_request_id, status):
    session.execute(
        update(EventRequest)
        .where(EventRequest.id == event_request_id)
        .values(status=status)
        .execution_options(synchronize_session=False)
    )


@pytest.fixture(scope="module")
def engine():
    url = os.environ["INTEGRATION_DATABASE_URL"]
    engine = create_engine(url)
    try:
        if not inspect(engine).has_table("event_coordinator_assignments"):
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                check=True,
                env={**os.environ, "DATABASE_URL": url},
            )
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def scenario(engine):
    """One submitted request, one manager and two active coordinators, removed afterwards."""

    manager, alice, bob = (str(uuid.uuid4()) for _ in range(3))
    with Session(engine) as session:
        organisation = Organisation(name=f"Concurrency Client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        organisation_id = organisation.id
        session.add_all(
            [
                Account(id=manager, display_name="Morgan Manager"),
                Account(id=alice, display_name="Alice Tan"),
                Account(id=bob, display_name="Bob Lim"),
            ]
        )
        session.add_all(
            [
                AccountRole(account_id=manager, role=Role.EVENT_OPERATIONS_MANAGER.value),
                AccountRole(account_id=alice, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=bob, role=Role.EVENT_COORDINATOR.value),
            ]
        )
        event = EventRequest(
            organiser_account_id=manager,
            organisation_id=organisation_id,
            name="Concurrency Summit",
            purpose="Proving interleaved transactions",
            proposed_date=date(2026, 10, 12),
            start_time=time(9, 0),
            end_time=time(12, 0),
            expected_attendance=120,
            status=SUBMITTED,
        )
        session.add(event)
        session.commit()
        event_request_id = event.id

    yield {"event_request_id": event_request_id, "manager": manager, "alice": alice, "bob": bob}

    accounts = [manager, alice, bob]
    with Session(engine) as session:
        session.execute(
            delete(EventCoordinatorHistory).where(
                EventCoordinatorHistory.event_request_id == event_request_id
            )
        )
        session.execute(
            delete(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event_request_id
            )
        )
        # SPL-125: email records block deleting their notices, so they go first.
        session.execute(
            delete(EmailDelivery).where(
                EmailDelivery.notification_id.in_(
                    select(Notification.id).where(Notification.event_request_id == event_request_id)
                )
            )
        )
        session.execute(delete(EventRequest).where(EventRequest.id == event_request_id))
        session.execute(delete(AccountRole).where(AccountRole.account_id.in_(accounts)))
        session.execute(delete(Account).where(Account.id.in_(accounts)))
        session.execute(delete(Organisation).where(Organisation.id == organisation_id))
        session.commit()


def _assign(session, scenario, coordinator_id):
    session.add(
        EventCoordinatorAssignment(
            event_request_id=scenario["event_request_id"],
            coordinator_account_id=coordinator_id,
            assigned_by_account_id=scenario["manager"],
            assigned_at=datetime.now(UTC),
        )
    )


# SPL-60 AC-3 Test-04
def test_tc_e05_s2_04_first_assignment_wins_when_two_managers_assign_at_once(engine, scenario):
    event_request_id = scenario["event_request_id"]

    with Session(engine) as loser, Session(engine) as winner:
        # The losing request reads an unassigned, submitted request before the winner commits.
        assert loser.get(EventCoordinatorAssignment, event_request_id) is None
        assert loser.get(EventRequest, event_request_id).status == SUBMITTED

        _assign(winner, scenario, scenario["alice"])
        winner.commit()

        _assign(loser, scenario, scenario["bob"])
        with pytest.raises(IntegrityError):
            loser.commit()
        loser.rollback()

    with Session(engine) as session:
        assignment = session.get(EventCoordinatorAssignment, event_request_id)
        assert assignment.coordinator_account_id == scenario["alice"]
        assert session.get(EventRequest, event_request_id).status == SUBMITTED


# SPL-61 AC-2 Test-02
def test_tc_e05_s3_02_reassignment_loses_to_a_concurrent_terminal_transition(engine, scenario):
    event_request_id = scenario["event_request_id"]
    assert "cancelled" in NON_REASSIGNABLE_STATUSES
    with Session(engine) as session:
        _assign(session, scenario, scenario["alice"])
        _transition(session, event_request_id, UNDER_REVIEW)
        session.commit()

    with Session(engine) as reassigner, Session(engine) as canceller:
        # The manager reads a reassignable request held by Alice ...
        assert reassigner.get(EventRequest, event_request_id).status == UNDER_REVIEW
        assignment = reassigner.get(EventCoordinatorAssignment, event_request_id)
        assert assignment.coordinator_account_id == scenario["alice"]
        # ... which another transaction cancels before the reassignment lands.
        _transition(canceller, event_request_id, "cancelled")
        canceller.commit()

        refused = reassigner.execute(
            _reassignment_statement(
                event_request_id,
                previous_id=scenario["alice"],
                coordinator_id=scenario["bob"],
                actor_id=scenario["manager"],
                now=datetime.now(UTC),
            )
        )
        assert refused.rowcount == 0
        reassigner.rollback()

    with Session(engine) as session:
        assignment = session.get(EventCoordinatorAssignment, event_request_id)
        assert assignment.coordinator_account_id == scenario["alice"]


# SPL-61 AC-2 Test-Supporting
def test_reassignment_applies_while_the_request_is_still_reassignable(engine, scenario):
    event_request_id = scenario["event_request_id"]
    with Session(engine) as session:
        _assign(session, scenario, scenario["alice"])
        _transition(session, event_request_id, UNDER_REVIEW)
        session.commit()

    with Session(engine) as session:
        applied = session.execute(
            _reassignment_statement(
                event_request_id,
                previous_id=scenario["alice"],
                coordinator_id=scenario["bob"],
                actor_id=scenario["manager"],
                now=datetime.now(UTC),
            )
        )
        assert applied.rowcount == 1
        session.commit()

    with Session(engine) as session:
        assignment = session.get(EventCoordinatorAssignment, event_request_id)
        assert assignment.coordinator_account_id == scenario["bob"]
        assert session.get(EventRequest, event_request_id).status == UNDER_REVIEW


# SPL-108 AC4: coordinator edits and reassignment share one event-then-assignment lock order.
def test_tc_spl_108_013_reassignment_wins_without_deadlocking_a_stale_edit(engine, scenario):
    event_request_id = scenario["event_request_id"]
    with Session(engine) as session:
        _assign(session, scenario, scenario["alice"])
        session.commit()

    identities = {
        "manager": scenario["manager"],
        "alice": scenario["alice"],
    }
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": os.environ["INTEGRATION_DATABASE_URL"],
            "IDENTITY_VERIFIER": identities.__getitem__,
        }
    )
    route_engine = app.extensions["engine"]
    assignment_held = threading.Event()
    release_reassignment = threading.Event()
    edit_reached_assignment = threading.Event()
    thread_ids = {}
    editor_pid = {}

    def hold_reassignment(conn, cursor, statement, params, context, many):
        normalized = " ".join(statement.lower().split())
        if threading.get_ident() == thread_ids.get("reassign") and normalized.startswith(
            "update event_coordinator_assignments"
        ):
            assignment_held.set()
            assert release_reassignment.wait(10), "Edit never reached the assignment lock"

    def observe_edit(conn, cursor, statement, params, context, many):
        normalized = " ".join(statement.lower().split())
        if (
            threading.get_ident() == thread_ids.get("edit")
            and normalized.startswith("select")
            and "event_coordinator_assignments" in normalized
            and "for update" in normalized
        ):
            editor_pid["value"] = conn.connection.driver_connection.info.backend_pid
            edit_reached_assignment.set()

    def call(label, method, path, *, token, body):
        thread_ids[label] = threading.get_ident()
        client = app.test_client()
        return getattr(client, method)(
            path,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )

    assignment_path = f"/api/event-requests/{event_request_id}/coordinator"
    edit_path = f"/api/event-requests/assigned/{event_request_id}/event-information"
    sql_event.listen(route_engine, "after_cursor_execute", hold_reassignment)
    sql_event.listen(route_engine, "before_cursor_execute", observe_edit)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reassign = pool.submit(
                call,
                "reassign",
                "put",
                assignment_path,
                token="manager",
                body={"coordinator_account_id": scenario["bob"]},
            )
            assert assignment_held.wait(10), "Reassignment never held the assignment row"
            edit = pool.submit(
                call,
                "edit",
                "patch",
                edit_path,
                token="alice",
                body={"purpose": "Stale coordinator edit"},
            )
            assert edit_reached_assignment.wait(10), "Edit never requested the assignment lock"

            deadline = monotonic() + 8
            blocked = False
            while monotonic() < deadline:
                with engine.connect() as connection:
                    blocked = bool(
                        connection.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                            {"pid": editor_pid["value"]},
                        )
                    )
                if blocked:
                    break
                sleep(0.01)
            assert blocked, "Edit did not wait for the reassignment boundary"
            release_reassignment.set()

            reassignment_response = reassign.result(timeout=10)
            edit_response = edit.result(timeout=10)
    finally:
        release_reassignment.set()
        sql_event.remove(route_engine, "after_cursor_execute", hold_reassignment)
        sql_event.remove(route_engine, "before_cursor_execute", observe_edit)
        route_engine.dispose()

    assert reassignment_response.status_code == 200
    assert edit_response.status_code == 404
    assert edit_response.json == {"error": "Assigned event not found."}
    with Session(engine) as session:
        assignment = session.get(EventCoordinatorAssignment, event_request_id)
        assert assignment.coordinator_account_id == scenario["bob"]
        assert (
            session.get(EventRequest, event_request_id).purpose
            == "Proving interleaved transactions"
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(EventDetailChange)
                .where(EventDetailChange.event_request_id == event_request_id)
            )
            == 0
        )
