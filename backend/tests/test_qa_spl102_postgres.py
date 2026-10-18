"""PostgreSQL QA scripts for SPL-102 (CS-E20-S2 — review outcome notifications).

Evidence for QA-SPL-102-070 to QA-SPL-102-072. They need a real PostgreSQL server, so they run only
under `npm run integration` (INTEGRATION_DATABASE_URL). Each test builds its own throw-away
database on that server, migrates it with Alembic, and drops it afterwards.
"""

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, time

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    Organisation,
    Role,
)
from app.notifications import add_review_outcome_notice
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)


@pytest.fixture
def pg_url():
    """A brand-new, fully migrated database, dropped when the test ends."""

    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"qa102_{uuid.uuid4().hex[:12]}"
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
    ids = {name: str(uuid.uuid4()) for name in ("manager", "coordinator", "organiser", "rival")}
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


def _notices(application):
    with Session(application.extensions["engine"]) as session:
        return session.scalars(select(Notification).order_by(Notification.id)).all()


# QA-SPL-102-070
def test_qa_spl_102_070_each_review_action_notifies_only_the_organiser_on_postgres(world):
    """QA-SPL-102-070 [Black-box / PostgreSQL] AC2-5: real routes, real tables, real migration."""

    application, ids = world
    client = application.test_client()
    coordinator = _headers(ids["coordinator"])
    asked = _event(application, ids)
    approved = _event(application, ids)
    rejected = _event(application, ids)
    withdrawn = _event(application, ids)

    assert (
        client.post(
            f"/api/event-requests/{asked}/request-clarification",
            headers=coordinator,
            json={"message": "What is the room layout?"},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/event-requests/{approved}/approve", headers=coordinator).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/event-requests/{rejected}/reject", headers=coordinator, json={"reason": "Clash."}
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/event-requests/{withdrawn}/withdraw", headers=coordinator).status_code
        == 200
    )
    # A repeat of each action is refused and adds nothing.
    assert (
        client.post(f"/api/event-requests/{approved}/approve", headers=coordinator).status_code
        == 409
    )
    assert (
        client.post(f"/api/event-requests/{withdrawn}/withdraw", headers=coordinator).status_code
        == 409
    )

    notices = _notices(application)
    assert len(notices) == 4
    assert {notice.recipient_account_id for notice in notices} == {ids["organiser"]}
    messages = {notice.event_request_id: notice.message for notice in notices}
    assert "What is the room layout?" in messages[asked]
    assert "approved" in messages[approved]
    assert messages[rejected].endswith("Reason: Clash.")
    assert "withdrawal" in messages[withdrawn]
    inbox = client.get("/api/notifications", headers=_headers(ids["organiser"])).get_json()
    assert inbox["unread_count"] == 4
    rival = client.get("/api/notifications", headers=_headers(ids["rival"])).get_json()
    assert rival["notifications"] == []


# QA-SPL-102-071
def test_qa_spl_102_071_the_database_refuses_a_duplicate_notice_for_the_same_action(world):
    """QA-SPL-102-071 [White-box / PostgreSQL] AC5: unique (recipient, dedupe key) constraint."""

    application, ids = world
    event_id = _event(application, ids)
    with Session(application.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        add_review_outcome_notice(session, event, kind="decision", source_id=7, message="first")
        session.commit()
        add_review_outcome_notice(session, event, kind="decision", source_id=7, message="second")
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        # A different action on the same event is a different key and is accepted.
        add_review_outcome_notice(session, event, kind="decision", source_id=8, message="third")
        session.commit()
        count = session.scalar(select(func.count()).select_from(Notification))

    assert count == 2


# QA-SPL-102-072
def test_qa_spl_102_072_a_failed_notice_rolls_back_the_whole_action_on_postgres(world, monkeypatch):
    """QA-SPL-102-072 [White-box / PostgreSQL] AC5: related writes share one transaction."""

    application, ids = world
    client = application.test_client()
    event_id = _event(application, ids)

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_review.add_review_outcome_notice", explode)
    with pytest.raises(RuntimeError):
        client.post(
            f"/api/event-requests/{event_id}/reject",
            headers=_headers(ids["coordinator"]),
            json={"reason": "Clash."},
        )

    with Session(application.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        history = session.execute(
            text("select count(*) from event_status_history where event_request_id = :i"),
            {"i": event_id},
        ).scalar_one()
        assert (event.status, event.rejected_at, event.rejection_reason) == (
            "under_review",
            None,
            None,
        )
    assert history == 0
    assert _notices(application) == []
