"""PostgreSQL proofs for SPL-134 (QA-SPL-134-06x), run only under `npm run integration`.

They drive the real Flask routes against a disposable PostgreSQL database, so the transactional
guarantees the SQLite suite cannot show are measured: real concurrent requests, row-level locking
and the notification uniqueness constraint.
"""

import os
import subprocess
import sys
import threading
import uuid
from datetime import UTC, date, datetime, time

import pytest
from app import create_app
from app.models import (
    Account,
    AccountRole,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Notification,
    Organisation,
    Role,
)
from sqlalchemy import create_engine, delete, func, inspect, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)


@pytest.fixture(scope="module")
def engine():
    url = os.environ["INTEGRATION_DATABASE_URL"]
    engine = create_engine(url)
    try:
        if not inspect(engine).has_table("notifications"):
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                check=True,
                env={**os.environ, "DATABASE_URL": url},
            )
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def world(engine):
    ids = {name: str(uuid.uuid4()) for name in ("lead", "organiser", "alice", "bob", "carol")}
    roles = {
        "lead": Role.EVENT_OPERATIONS_MANAGER,
        "organiser": Role.EVENT_ORGANISER,
        "alice": Role.EVENT_COORDINATOR,
        "bob": Role.EVENT_COORDINATOR,
        "carol": Role.EVENT_COORDINATOR,
    }
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-134 Client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for name, account_id in ids.items():
            session.add(Account(id=account_id, display_name=name.title()))
            session.add(AccountRole(account_id=account_id, role=roles[name].value))
        event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation.id,
            name="SPL-134 Summit",
            purpose="PostgreSQL proof",
            proposed_date=date(2026, 10, 12),
            start_time=time(9, 0),
            end_time=time(12, 0),
            expected_attendance=50,
            status="submitted",
            submitted_at=datetime.now(UTC),
        )
        session.add(event)
        session.commit()
        event_id, organisation_id = event.id, organisation.id

    tokens = {f"token-{name}": account_id for name, account_id in ids.items()}
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": os.environ["INTEGRATION_DATABASE_URL"],
            "IDENTITY_VERIFIER": tokens.__getitem__,
        }
    )
    yield {"app": app, "event_id": event_id, "ids": ids}

    app.extensions["engine"].dispose()
    with Session(engine) as session:
        session.execute(delete(Notification).where(Notification.event_request_id == event_id))
        session.execute(
            delete(EventCoordinatorHistory).where(
                EventCoordinatorHistory.event_request_id == event_id
            )
        )
        session.execute(
            delete(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event_id
            )
        )
        session.execute(delete(EventRequest).where(EventRequest.id == event_id))
        session.execute(delete(AccountRole).where(AccountRole.account_id.in_(ids.values())))
        session.execute(delete(Account).where(Account.id.in_(ids.values())))
        session.execute(delete(Organisation).where(Organisation.id == organisation_id))
        session.commit()


def _call(app, method, path, body=None, token="token-lead"):
    client = app.test_client()
    return getattr(client, method)(path, json=body, headers={"Authorization": f"Bearer {token}"})


def _notice_count(engine, event_id):
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.event_request_id == event_id)
        )


def _history_count(engine, event_id):
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(EventCoordinatorHistory)
            .where(EventCoordinatorHistory.event_request_id == event_id)
        )


def _race(app, calls):
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(index, call):
        barrier.wait()
        results[index] = call()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return [response.status_code for response in results]


# QA-SPL-134-061 | AC1,AC2,AC3,AC5 | BB: the whole flow on PostgreSQL
def test_qa_spl_134_061_assign_supervise_and_reassign_end_to_end(engine, world):
    app, event_id, ids = world["app"], world["event_id"], world["ids"]
    path = f"/api/event-requests/{event_id}/coordinator"

    assert _call(app, "post", path, {"coordinator_account_id": ids["alice"]}).status_code == 201
    seen = _call(app, "get", "/api/event-requests/supervision").get_json()["events"]
    assert [(e["id"], e["coordinator"]["name"]) for e in seen if e["id"] == event_id] == [
        (event_id, "Alice")
    ]
    assert _notice_count(engine, event_id) == 2

    assert _call(app, "put", path, {"coordinator_account_id": ids["bob"]}).status_code == 200
    assert _notice_count(engine, event_id) == 5
    assert _history_count(engine, event_id) == 2
    with Session(engine) as session:
        recipients = sorted(
            session.scalars(
                select(Notification.recipient_account_id).where(
                    Notification.event_request_id == event_id
                )
            )
        )
    assert recipients == sorted([ids["alice"]] * 2 + [ids["bob"]] + [ids["organiser"]] * 2)


# QA-SPL-134-062 | AC3,AC5 | WB: a reassignment that read stale state is refused, no notices
def test_qa_spl_134_062_a_stale_reassignment_is_refused_and_notifies_nobody(
    engine, world, monkeypatch
):
    from app import coordinator_assignment

    app, event_id, ids = world["app"], world["event_id"], world["ids"]
    path = f"/api/event-requests/{event_id}/coordinator"
    assert _call(app, "post", path, {"coordinator_account_id": ids["alice"]}).status_code == 201
    before = _notice_count(engine, event_id)

    original = coordinator_assignment._chosen_coordinator
    stale_has_read = threading.Event()
    rival_done = threading.Event()

    def chosen(session, coordinator_id, **kwargs):
        account = original(session, coordinator_id, **kwargs)
        if coordinator_id == ids["bob"]:
            # Alice -> Bob has read "current coordinator is Alice"; hold it until Carol's wins.
            stale_has_read.set()
            assert rival_done.wait(timeout=30)
        return account

    monkeypatch.setattr(coordinator_assignment, "_chosen_coordinator", chosen)
    outcome = {}

    def stale():
        outcome["stale"] = _call(app, "put", path, {"coordinator_account_id": ids["bob"]})

    thread = threading.Thread(target=stale)
    thread.start()
    assert stale_has_read.wait(timeout=30)
    rival = _call(app, "put", path, {"coordinator_account_id": ids["carol"]})
    rival_done.set()
    thread.join(timeout=30)

    assert rival.status_code == 200
    assert outcome["stale"].status_code == 409
    assert _notice_count(engine, event_id) == before + 3  # only the winner's three
    assert _history_count(engine, event_id) == 2
    with Session(engine) as session:
        held = session.get(EventCoordinatorAssignment, event_id).coordinator_account_id
    assert held == ids["carol"]


# QA-SPL-134-064 | AC3,AC5 | BB: free-running concurrent reassignments keep one notice per change
def test_qa_spl_134_064_racing_reassignments_never_notify_more_than_once_per_change(engine, world):
    app, event_id, ids = world["app"], world["event_id"], world["ids"]
    path = f"/api/event-requests/{event_id}/coordinator"
    assert _call(app, "post", path, {"coordinator_account_id": ids["alice"]}).status_code == 201
    before = _notice_count(engine, event_id)

    statuses = _race(
        app,
        [
            lambda: _call(app, "put", path, {"coordinator_account_id": ids["bob"]}),
            lambda: _call(app, "put", path, {"coordinator_account_id": ids["carol"]}),
        ],
    )

    won = statuses.count(200)
    assert won >= 1 and set(statuses) <= {200, 409}
    assert _notice_count(engine, event_id) == before + 3 * won
    assert _history_count(engine, event_id) == 1 + won


# QA-SPL-134-063 | AC1,AC5 | BB: two Leads assign at once; one wins, two notices
def test_qa_spl_134_063_concurrent_assignments_notify_once(engine, world):
    app, event_id, ids = world["app"], world["event_id"], world["ids"]
    path = f"/api/event-requests/{event_id}/coordinator"

    statuses = _race(
        app,
        [
            lambda: _call(app, "post", path, {"coordinator_account_id": ids["alice"]}),
            lambda: _call(app, "post", path, {"coordinator_account_id": ids["bob"]}),
        ],
    )

    assert sorted(statuses) == [201, 409]
    assert _notice_count(engine, event_id) == 2
    assert _history_count(engine, event_id) == 1
