"""Concurrency proofs for SPL-60 and SPL-61 against disposable PostgreSQL.

Each test interleaves two real transactions, which SQLite cannot express, so they run only
under `npm run integration`. Cases: first assignment wins, and reassignment loses to a
concurrent transition into a terminal status.
"""

import os
import subprocess
import sys
import uuid
from datetime import UTC, date, datetime, time

import pytest
from app.coordinator_assignment import (
    NON_REASSIGNABLE_STATUSES,
    SUBMITTED,
    UNDER_REVIEW,
    _reassignment_statement,
)
from app.models import (
    Account,
    AccountRole,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import create_engine, delete, inspect, update
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
