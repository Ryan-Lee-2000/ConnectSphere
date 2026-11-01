"""PostgreSQL proofs for SPL-126 (QA-SPL-126-15x), run only under `npm run integration`.

They measure what SQLite cannot: the type backfill in the real migration and its refusal of an
unknown kind, a real unique-key race between two turn-off requests, the database checks, the
foreign key cascade, row-level security with no browser grants, and the email check on PostgreSQL.
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
    NOTIFICATION_TYPE_BY_KIND,
    Account,
    AccountRole,
    EmailDelivery,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Notification,
    NotificationEmailOptOut,
    Organisation,
    Role,
)
from sqlalchemy import create_engine, delete, inspect, make_url, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

BEFORE = "s4_replacement_bookings"


class Outbox:
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def __call__(self, message):
        with self.lock:
            self.messages.append(message)
        return f"gmail-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def engine():
    url = os.environ["INTEGRATION_DATABASE_URL"]
    engine = create_engine(url)
    try:
        if not inspect(engine).has_table("notification_email_opt_outs"):
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
    ids = {name: str(uuid.uuid4()) for name in ("lead", "organiser", "alice")}
    roles = {
        "lead": Role.EVENT_OPERATIONS_MANAGER,
        "organiser": Role.EVENT_ORGANISER,
        "alice": Role.EVENT_COORDINATOR,
    }
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-126 Client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for key, account_id in ids.items():
            session.add(Account(id=account_id, display_name=f"SPL-126 {key}"))
            session.add(AccountRole(account_id=account_id, role=roles[key].value))
        event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation.id,
            name="SPL-126 Summit",
            purpose="PostgreSQL proof",
            proposed_date=date(2026, 12, 12),
            start_time=time(9, 0),
            end_time=time(12, 0),
            expected_attendance=50,
            status="submitted",
            submitted_at=datetime.now(UTC),
        )
        session.add(event)
        session.commit()
        event_id, organisation_id = event.id, organisation.id

    outbox = Outbox()
    tokens = {f"token-{key}": account_id for key, account_id in ids.items()}
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": os.environ["INTEGRATION_DATABASE_URL"],
            "IDENTITY_VERIFIER": tokens.__getitem__,
            "EMAIL_SENDER": outbox,
            "NOTIFICATION_EMAIL_TO": "shared.inbox@connectsphere.test",
            "APP_BASE_URL": "https://app.connectsphere.test",
        }
    )
    yield {"app": app, "event_id": event_id, "ids": ids, "outbox": outbox}

    app.extensions["engine"].dispose()
    with Session(engine) as session:
        notice_ids = select(Notification.id).where(Notification.event_request_id == event_id)
        session.execute(delete(EmailDelivery).where(EmailDelivery.notification_id.in_(notice_ids)))
        session.execute(delete(Notification).where(Notification.event_request_id == event_id))
        for model in (EventCoordinatorHistory, EventCoordinatorAssignment):
            session.execute(delete(model).where(model.event_request_id == event_id))
        session.execute(delete(EventRequest).where(EventRequest.id == event_id))
        session.execute(
            delete(NotificationEmailOptOut).where(
                NotificationEmailOptOut.account_id.in_(ids.values())
            )
        )
        session.execute(delete(AccountRole).where(AccountRole.account_id.in_(ids.values())))
        session.execute(delete(Account).where(Account.id.in_(ids.values())))
        session.execute(delete(Organisation).where(Organisation.id == organisation_id))
        session.commit()


def _client(world):
    return world["app"].test_client()


def _put(world, token, kind, email=False):
    return _client(world).put(
        f"/api/notification-settings/{kind}",
        json={"email": email},
        headers={"Authorization": f"Bearer token-{token}"},
    )


def _alembic(url, *args):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )


@pytest.fixture
def fresh_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl126_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _seed_notices(url, keys):
    legacy = create_engine(url)
    try:
        with legacy.begin() as connection:
            organisation = connection.scalar(
                text("INSERT INTO organisations (name) VALUES ('Legacy client') RETURNING id")
            )
            account = str(uuid.uuid4())
            connection.execute(
                text(
                    "INSERT INTO accounts (id, display_name, organisation_id, is_active) "
                    "VALUES (:id, 'Legacy', :org, true)"
                ),
                {"id": account, "org": organisation},
            )
            event = connection.scalar(
                text(
                    "INSERT INTO event_requests (organiser_account_id, organisation_id, name, "
                    "status, proposed_date, start_time, end_time, expected_attendance, "
                    "required_facilities, accessibility_needs, registration_required, "
                    "submitted_at) VALUES (:account, :org, 'Legacy', 'planning', '2026-12-01', "
                    "'09:00', '11:00', 50, '[]', '[]', false, now()) RETURNING id"
                ),
                {"account": account, "org": organisation},
            )
            for key in keys:
                connection.execute(
                    text(
                        "INSERT INTO notifications (recipient_account_id, recipient_role, "
                        "event_request_id, message, dedupe_key, created_at) VALUES "
                        "(:a, 'event_coordinator', :e, 'Old notice', :k, now())"
                    ),
                    {"a": account, "e": event, "k": key},
                )
    finally:
        legacy.dispose()


def _stored_types(url):
    current = create_engine(url)
    try:
        with current.connect() as connection:
            return dict(
                connection.execute(
                    text("SELECT dedupe_key, notification_type FROM notifications")
                ).all()
            )
    finally:
        current.dispose()


ALL_KINDS = {
    f"{kind}:{i}": t.value for i, (kind, t) in enumerate(NOTIFICATION_TYPE_BY_KIND.items())
}


# QA-SPL-126-150 | AC1 | WB migration backfill of every kind on main
def test_qa_spl_126_150_existing_notices_are_given_their_type(fresh_url):
    assert _alembic(fresh_url, "upgrade", BEFORE).returncode == 0
    _seed_notices(fresh_url, ALL_KINDS)

    upgraded = _alembic(fresh_url, "upgrade", "head")

    assert upgraded.returncode == 0, upgraded.stderr
    assert _stored_types(fresh_url) == ALL_KINDS
    check = create_engine(fresh_url)
    try:
        with check.connect() as connection:
            column = connection.execute(
                text(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_name = 'notifications' AND column_name = 'notification_type'"
                )
            ).one()
            assert tuple(column) == ("NO", None)
            assert connection.scalar(text("SELECT count(*) FROM notification_email_opt_outs")) == 0
            assert connection.scalar(text("SELECT count(*) FROM email_deliveries")) == 0
    finally:
        check.dispose()


# QA-SPL-126-151 | AC1 | WB negative (an unknown kind stops the migration, nothing changes)
def test_qa_spl_126_151_an_unknown_kind_stops_the_migration(fresh_url):
    assert _alembic(fresh_url, "upgrade", BEFORE).returncode == 0
    _seed_notices(fresh_url, ["coordinator_assigned:1", "d1probe:2"])

    refused = _alembic(fresh_url, "upgrade", "head")

    assert refused.returncode != 0
    assert "No type is known for notice kind 'd1probe'" in refused.stderr
    check = create_engine(fresh_url)
    try:
        with check.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == BEFORE
            assert not inspect(connection).has_table("notification_email_opt_outs")
            columns = {c["name"] for c in inspect(connection).get_columns("notifications")}
            assert "notification_type" not in columns
    finally:
        check.dispose()


# QA-SPL-126-152 | AC1 | WB the migration downgrades and upgrades cleanly with data
def test_qa_spl_126_152_the_migration_round_trips(fresh_url):
    assert _alembic(fresh_url, "upgrade", BEFORE).returncode == 0
    _seed_notices(fresh_url, ["organiser_decision:1", "attendee_venue_added:2"])
    assert _alembic(fresh_url, "upgrade", "head").returncode == 0

    down = _alembic(fresh_url, "downgrade", BEFORE)
    assert down.returncode == 0, down.stderr
    check = create_engine(fresh_url)
    try:
        with check.connect() as connection:
            assert not inspect(connection).has_table("notification_email_opt_outs")
    finally:
        check.dispose()
    up = _alembic(fresh_url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert _stored_types(fresh_url) == {
        "organiser_decision:1": "organiser_review",
        "attendee_venue_added:2": "attendee_event_changes",
    }


# QA-SPL-126-153 | AC5 | WB concurrency (two turn-offs race on the unique key)
def test_qa_spl_126_153_two_racing_turn_offs_both_succeed_with_one_row(engine, world, monkeypatch):
    barrier = threading.Barrier(2)
    real_get = Session.get

    def get_then_wait(self, *args, **kwargs):
        found = real_get(self, *args, **kwargs)
        if args and args[0] is NotificationEmailOptOut:
            barrier.wait(5)  # both requests have checked; neither has inserted yet
        return found

    monkeypatch.setattr(Session, "get", get_then_wait)
    results = []

    def turn_off():
        results.append(_put(world, "alice", "coordinator_assignment").status_code)

    threads = [threading.Thread(target=turn_off) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert results == [200, 200]
    with Session(engine) as session:
        assert session.scalars(
            select(NotificationEmailOptOut.notification_type).where(
                NotificationEmailOptOut.account_id == world["ids"]["alice"]
            )
        ).all() == ["coordinator_assignment"]


# QA-SPL-126-154 | AC1, AC5 | WB PostgreSQL checks
@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "INSERT INTO notification_email_opt_outs VALUES (:a, 'marketing', now())",
            "ck_notification_email_opt_outs_known_type",
        ),
        (
            "INSERT INTO notification_email_opt_outs VALUES (:a, 'coordinator_safety', now()), "
            "(:a, 'coordinator_safety', now())",
            "notification_email_opt_outs_pkey",
        ),
        (
            "INSERT INTO notification_email_opt_outs VALUES "
            "('00000000-0000-0000-0000-00000000dead', 'coordinator_safety', now())",
            "notification_email_opt_outs_account_id_fkey",
        ),
        (
            "UPDATE notifications SET notification_type = 'marketing' "
            "WHERE recipient_account_id = :a",
            "ck_notifications_known_type",
        ),
        (
            "UPDATE notifications SET notification_type = NULL WHERE recipient_account_id = :a",
            "notification_type",
        ),
    ],
)
def test_qa_spl_126_154_postgresql_enforces_the_type_and_setting_rules(
    engine, world, statement, constraint
):
    assert (
        _client(world)
        .post(
            f"/api/event-requests/{world['event_id']}/coordinator",
            json={"coordinator_account_id": world["ids"]["alice"]},
            headers={"Authorization": "Bearer token-lead"},
        )
        .status_code
        == 201
    )
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(text(statement), {"a": world["ids"]["alice"]})
    assert constraint in str(refused.value)


# QA-SPL-126-155 | AC5 | WB security (row-level security, no browser grants)
def test_qa_spl_126_155_browser_roles_cannot_read_or_change_settings(engine):
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT relrowsecurity FROM pg_class WHERE relname = 'notification_email_opt_outs'"
            )
        )
        for role in ("anon", "authenticated"):
            if not connection.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            ):
                continue
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege(:r, 'notification_email_opt_outs', :p)"),
                    {"r": role, "p": privilege},
                ), (role, privilege)


# QA-SPL-126-156 | AC5 | WB settings are removed with their account
def test_qa_spl_126_156_deleting_an_account_deletes_its_settings(engine, world):
    assert _put(world, "alice", "coordinator_safety").status_code == 200
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM account_roles WHERE account_id = :a"), {"a": world["ids"]["alice"]}
        )
        connection.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": world["ids"]["alice"]})
        assert (
            connection.scalar(
                text("SELECT count(*) FROM notification_email_opt_outs WHERE account_id = :a"),
                {"a": world["ids"]["alice"]},
            )
            == 0
        )


# QA-SPL-126-157 | AC4, AC6 | BB the email check on PostgreSQL
def test_qa_spl_126_157_a_muted_type_gets_no_email_on_postgresql(engine, world):
    assert _put(world, "alice", "coordinator_assignment").status_code == 200
    response = _client(world).post(
        f"/api/event-requests/{world['event_id']}/coordinator",
        json={"coordinator_account_id": world["ids"]["alice"]},
        headers={"Authorization": "Bearer token-lead"},
    )
    assert response.status_code == 201
    with Session(engine) as session:
        notices = session.scalars(
            select(Notification).where(Notification.event_request_id == world["event_id"])
        ).all()
        by_recipient = {n.recipient_account_id: n for n in notices}
        assert by_recipient[world["ids"]["alice"]].notification_type == "coordinator_assignment"
        emailed = set(
            session.scalars(
                select(EmailDelivery.recipient_account_id).where(
                    EmailDelivery.notification_id.in_([n.id for n in notices])
                )
            ).all()
        )
    assert emailed == {world["ids"]["organiser"]}
    assert len(world["outbox"].messages) == 1
