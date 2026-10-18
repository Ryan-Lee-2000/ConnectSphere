"""PostgreSQL QA scripts for SPL-103 (CS-E20-S4 - be notified of new work assigned to me).

Evidence for QA-SPL-103-080 to QA-SPL-103-084. They need a real PostgreSQL server, so they run only
under `npm run integration` (INTEGRATION_DATABASE_URL). Each test builds its own throw-away
database on that server, migrates it with Alembic, and drops it afterwards.
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
from app.models import (
    Account,
    AccountRole,
    ClarificationRequest,
    EventChangeRequest,
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    Organisation,
    Role,
)
from app.notifications import (
    add_change_request_submitted_notice,
    add_clarification_answered_notice,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

ITEM = {"field": "expected_attendance", "requested_value": 150, "reason": "More guests."}


@pytest.fixture
def pg_url():
    """A brand-new, fully migrated database, dropped when the test ends."""

    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"qa103_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    upgraded = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )
    assert upgraded.returncode == 0, upgraded.stderr
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def world(pg_url):
    ids = {
        name: str(uuid.uuid4())
        for name in ("manager", "coordinator", "other", "organiser", "rival")
    }
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": pg_url,
            "IDENTITY_VERIFIER": lambda token: token,
        }
    )
    engine = application.extensions["engine"]
    with Session(engine) as session:
        organisation = Organisation(name="Postgres Client")
        session.add(organisation)
        session.flush()
        for key, name, role in (
            ("manager", "Morgan Manager", Role.EVENT_OPERATIONS_MANAGER),
            ("coordinator", "Alice Tan", Role.EVENT_COORDINATOR),
            ("other", "Bob Lim", Role.EVENT_COORDINATOR),
            ("organiser", "Olivia Organiser", Role.EVENT_ORGANISER),
            ("rival", "Riley Rival", Role.EVENT_ORGANISER),
        ):
            session.add(
                Account(
                    id=ids[key],
                    display_name=name,
                    organisation_id=organisation.id if role == Role.EVENT_ORGANISER else None,
                )
            )
            session.add(AccountRole(account_id=ids[key], role=role.value))
        session.commit()
        ids["organisation"] = organisation.id
    yield application, ids
    engine.dispose()


def _event(application, ids, status="under_review") -> int:
    with Session(application.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=ids["organisation"],
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
                coordinator_account_id=ids["coordinator"],
                assigned_by_account_id=ids["manager"],
                assigned_at=datetime(2026, 9, 21, 9, tzinfo=SINGAPORE),
            )
        )
        session.commit()
        return event.id


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _notices(application, recipient=None):
    with Session(application.extensions["engine"]) as session:
        query = select(Notification).order_by(Notification.id)
        if recipient:
            query = query.where(Notification.recipient_account_id == recipient)
        return session.scalars(query).all()


def _ask(client, ids, event_id) -> int:
    response = client.post(
        f"/api/event-requests/{event_id}/request-clarification",
        headers=_headers(ids["coordinator"]),
        json={"message": "What is the room layout?"},
    )
    assert response.status_code == 200
    return response.get_json()["clarifications"][0]["id"]


def _respond(client, ids, event_id, clarification_id):
    return client.post(
        f"/api/event-requests/{event_id}/clarifications/{clarification_id}/respond",
        headers=_headers(ids["organiser"]),
        json={"response": "Theatre style."},
    )


def _change(client, ids, event_id):
    return client.post(
        f"/api/event-requests/{event_id}/change-requests",
        headers=_headers(ids["organiser"]),
        json={"items": [ITEM]},
    )


# QA-SPL-103-080
def test_qa_spl_103_080_the_answer_and_the_change_request_notify_the_coordinator_on_postgres(world):
    """QA-SPL-103-080 [Black-box / PostgreSQL] AC3-5: real routes, real tables, real migration."""

    application, ids = world
    client = application.test_client()
    answered = _event(application, ids)
    changed = _event(application, ids)
    clarification_id = _ask(client, ids, answered)

    assert _respond(client, ids, answered, clarification_id).status_code == 200
    assert _change(client, ids, changed).status_code == 201
    # A repeat of each action is refused and adds nothing.
    assert _respond(client, ids, answered, clarification_id).status_code == 409
    assert _change(client, ids, changed).status_code == 409

    coordinator = _notices(application, ids["coordinator"])
    assert sorted(n.event_request_id for n in coordinator) == sorted([answered, changed])
    kinds = {n.dedupe_key.split(":", 1)[0] for n in coordinator}
    assert kinds == {"clarification_answered", "change_request_submitted"}
    assert _notices(application, ids["other"]) == []
    inbox = client.get("/api/notifications", headers=_headers(ids["coordinator"])).get_json()
    assert inbox["unread_count"] == 2
    rival = client.get("/api/notifications", headers=_headers(ids["rival"])).get_json()
    assert rival["notifications"] == []


# QA-SPL-103-081
def test_qa_spl_103_081_the_database_refuses_a_duplicate_notice_for_the_same_source(world):
    """QA-SPL-103-081 [White-box / PostgreSQL] AC5: unique (recipient, dedupe key) constraint."""

    application, ids = world
    client = application.test_client()
    event_id = _event(application, ids)
    clarification_id = _ask(client, ids, event_id)
    _respond(client, ids, event_id, clarification_id)
    change_id = _change(client, ids, event_id).get_json()["change_request"]["id"]

    with Session(application.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        add_clarification_answered_notice(
            session, event, author_id=ids["coordinator"], clarification_id=clarification_id
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        add_change_request_submitted_notice(
            session, event, change_request_id=change_id, field_labels=["Purpose"]
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        count = session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.recipient_account_id == ids["coordinator"])
        )

    assert count == 2


# QA-SPL-103-082
def test_qa_spl_103_082_a_failed_notice_rolls_back_the_response_on_postgres(world, monkeypatch):
    """QA-SPL-103-082 [White-box / PostgreSQL] AC3, AC5: related writes share one transaction."""

    application, ids = world
    client = application.test_client()
    event_id = _event(application, ids)
    clarification_id = _ask(client, ids, event_id)
    before = len(_notices(application))

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_review.add_clarification_answered_notice", explode)
    with pytest.raises(RuntimeError):
        _respond(client, ids, event_id, clarification_id)

    with Session(application.extensions["engine"]) as session:
        clarification = session.get(ClarificationRequest, clarification_id)
        status = session.get(EventRequest, event_id).status
        history = session.execute(
            text(
                "select count(*) from event_status_history "
                "where event_request_id = :i and action = 'respond_clarification'"
            ),
            {"i": event_id},
        ).scalar_one()
    assert clarification.response is None and status == "returned_for_clarification"
    assert history == 0
    assert len(_notices(application)) == before


# QA-SPL-103-083
def test_qa_spl_103_083_a_failed_notice_rolls_back_the_change_request_on_postgres(
    world, monkeypatch
):
    """QA-SPL-103-083 [White-box / PostgreSQL] AC4, AC5: request, items and notice are one write."""

    application, ids = world
    client = application.test_client()
    event_id = _event(application, ids)

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_change_requests.add_change_request_submitted_notice", explode)
    with pytest.raises(RuntimeError):
        _change(client, ids, event_id)

    with Session(application.extensions["engine"]) as session:
        requests = session.scalar(select(func.count()).select_from(EventChangeRequest))
        items = session.execute(
            text("select count(*) from event_change_request_items")
        ).scalar_one()
    assert (requests, items) == (0, 0)
    assert _notices(application) == []


# QA-SPL-103-084
def test_qa_spl_103_084_two_simultaneous_change_requests_notify_once(world):
    """QA-SPL-103-084 [Black-box / PostgreSQL] AC4, AC5: the row lock serialises submissions."""

    application, ids = world
    event_id = _event(application, ids)
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def submit():
        client = application.test_client()
        barrier.wait()
        statuses.append(_change(client, ids, event_id).status_code)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [201, 409]
    assert len(_notices(application, ids["coordinator"])) == 1
