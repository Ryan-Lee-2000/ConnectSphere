"""SPL-124 QA on PostgreSQL: racing actions leave exactly one notice each (AC4).

Case IDs are QA-SPL-124-NNN (see the QA-SPL-124 report). Reuses SPL-116's disposable database
and scenario (one Confirmed event with open registration, two attendee tokens "first" and
"second"); runs only under ``npm run integration``.
"""

import threading
import uuid
from datetime import datetime

import test_event_registrations_postgres as pg
from app.event_requests import SINGAPORE
from app.models import Account, AccountRole, EventCoordinatorAssignment, Notification, Role
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_event_registrations_postgres import race

pytestmark = pg.pytestmark
pg_url = pg.pg_url
scenario = pg.scenario

DETAILS = {"name": "Attendee", "email": "a@b.co", "contact_number": "91234567"}


def together(app, calls):
    """Run each (method, path, token, body) at the same instant; return the status codes."""

    barrier = threading.Barrier(len(calls))
    codes = [None] * len(calls)

    def attempt(index, method, path, token, body):
        client = app.test_client()
        barrier.wait()
        codes[index] = getattr(client, method)(
            path, json=body, headers={"Authorization": f"Bearer {token}"}
        ).status_code

    threads = [
        threading.Thread(target=attempt, args=(index, *call)) for index, call in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return sorted(codes)


def count(engine, key_prefix):
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.dedupe_key.like(f"{key_prefix}%"))
        )


def tokens(app):
    return app.config["IDENTITY_VERIFIER"].__self__


def register(app, event_id, token="first"):
    response = app.test_client().post(
        f"/api/event-requests/{event_id}/registrations",
        json=DETAILS,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.json
    return response.json["registration"]["id"]


# QA-SPL-124-070 | AC3 AC4 | WB concurrency
def test_qa_spl_124_070_one_attendee_registering_twice_at_once_is_acknowledged_once(scenario):
    app, engine, event_id = scenario
    assert race(app, event_id, ["first", "first"]) == [201, 409]
    assert count(engine, "attendee_registered:") == 1


# QA-SPL-124-071 | AC3 AC4 | WB concurrency
def test_qa_spl_124_071_two_simultaneous_withdrawals_are_acknowledged_once(scenario):
    app, engine, event_id = scenario
    registration = register(app, event_id)
    path = f"/api/registrations/{registration}/withdraw"
    assert together(app, [("post", path, "first", {}), ("post", path, "first", {})]) == [200, 409]
    assert count(engine, "attendee_withdrawn:") == 1


# QA-SPL-124-072 | AC2 AC4 | WB concurrency
def test_qa_spl_124_072_two_simultaneous_cancellations_notify_once(scenario):
    app, engine, event_id = scenario
    register(app, event_id)
    coordinator = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Account(id=coordinator, display_name="Casey Lim"))
        session.flush()
        session.add(AccountRole(account_id=coordinator, role=Role.EVENT_COORDINATOR.value))
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event_id,
                coordinator_account_id=coordinator,
                assigned_by_account_id=coordinator,
                assigned_at=datetime.now(SINGAPORE),
            )
        )
        session.commit()
    tokens(app)["coordinator"] = coordinator
    path = f"/api/event-requests/{event_id}/cancel"
    body = {"reason": "Typhoon warning issued"}
    codes = together(app, [("post", path, "coordinator", body)] * 2)
    assert codes == [200, 409]
    assert count(engine, "attendee_event_cancelled:") == 1
