"""PostgreSQL proofs for SPL-125 (QA-SPL-125-16x), run only under `npm run integration`.

They measure what SQLite cannot: row locking between two delivery workers, a pending retry picked
up by a new app instance, the role backfill in the real migration, the database checks, the
foreign key that keeps email records, and row-level security with no browser grants.
"""

import os
import subprocess
import sys
import threading
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from app import create_app, email_delivery
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    EmailDelivery,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Notification,
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

SHARED_ADDRESS = "shared.inbox@connectsphere.test"


class Outbox:
    def __init__(self, fail=False, hold: threading.Event | None = None):
        self.messages = []
        self.fail = fail
        self.hold = hold
        self.lock = threading.Lock()

    def __call__(self, message):
        with self.lock:
            self.messages.append(message)
        if self.hold:
            self.hold.wait(5)
        if self.fail:
            raise ConnectionRefusedError("mail server unreachable")
        return f"gmail-{uuid.uuid4().hex[:8]}"


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
    ids = {name: str(uuid.uuid4()) for name in ("lead", "organiser", "alice")}
    names = {"lead": "Lee Lead", "organiser": "Olivia Organiser", "alice": "Alice Tan"}
    roles = {
        "lead": Role.EVENT_OPERATIONS_MANAGER,
        "organiser": Role.EVENT_ORGANISER,
        "alice": Role.EVENT_COORDINATOR,
    }
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-125 Client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for key, account_id in ids.items():
            session.add(Account(id=account_id, display_name=names[key]))
            session.add(AccountRole(account_id=account_id, role=roles[key].value))
        event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation.id,
            name="SPL-125 Summit",
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

    outbox = Outbox()
    tokens = {f"token-{key}": account_id for key, account_id in ids.items()}
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": os.environ["INTEGRATION_DATABASE_URL"],
            "IDENTITY_VERIFIER": tokens.__getitem__,
            "EMAIL_SENDER": outbox,
            "NOTIFICATION_EMAIL_TO": SHARED_ADDRESS,
            "APP_BASE_URL": "https://app.connectsphere.test",
        }
    )
    yield {"app": app, "event_id": event_id, "ids": ids, "outbox": outbox}

    app.extensions["engine"].dispose()
    with Session(engine) as session:
        notice_ids = select(Notification.id).where(Notification.event_request_id == event_id)
        session.execute(delete(EmailDelivery).where(EmailDelivery.notification_id.in_(notice_ids)))
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


def _assign(world):
    return (
        world["app"]
        .test_client()
        .post(
            f"/api/event-requests/{world['event_id']}/coordinator",
            json={"coordinator_account_id": world["ids"]["alice"]},
            headers={"Authorization": "Bearer token-lead"},
        )
    )


def _add_notice(world, key="spl125_pg:1"):
    with Session(world["app"].extensions["engine"]) as session:
        notice = Notification(
            recipient_account_id=world["ids"]["alice"],
            recipient_role=Role.EVENT_COORDINATOR,
            event_request_id=world["event_id"],
            message="Something changed.",
            dedupe_key=key,
            created_at=datetime.now(SINGAPORE),
        )
        session.add(notice)
        session.commit()
        return notice.id


def _email(engine, notice_id):
    with Session(engine) as session:
        return session.scalars(
            select(EmailDelivery).where(EmailDelivery.notification_id == notice_id)
        ).one()


def _make_pending(world, notice_id):
    """The first attempt failed, so the email waits for its retry."""

    with world["app"].extensions["engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE email_deliveries SET status = 'pending', sent_at = NULL, attempts = 1, "
                "provider_message_id = NULL, next_attempt_at = now() - interval '1 second' "
                "WHERE notification_id = :n"
            ),
            {"n": notice_id},
        )


# QA-SPL-125-160 | AC1/AC2 | BB real route on PostgreSQL
def test_qa_spl_125_160_an_assignment_on_postgresql_emails_each_notice_once(engine, world):
    assert _assign(world).status_code == 201

    with Session(engine) as session:
        notices = session.scalars(
            select(Notification).where(Notification.event_request_id == world["event_id"])
        ).all()
        emails = session.scalars(
            select(EmailDelivery).where(EmailDelivery.notification_id.in_([n.id for n in notices]))
        ).all()
    assert len(notices) == 2 and len(emails) == 2
    assert {e.status for e in emails} == {"sent"}
    assert {e.recipient_role for e in emails} == {"event_coordinator", "event_organiser"}
    assert len(world["outbox"].messages) == 2


# QA-SPL-125-161 | AC9/AC10 | WB concurrency (two workers, one due email)
def test_qa_spl_125_161_two_workers_never_send_the_same_email_twice(engine, world):
    notice_id = _add_notice(world)
    _make_pending(world, notice_id)
    message_id = f"<connectsphere-email-{_email(engine, notice_id).id}@connectsphere.local>"
    release = threading.Event()
    first, second = Outbox(hold=release), Outbox()
    results = {}

    def run(name, sender):
        results[name] = email_delivery.process_due_emails(engine, sender)

    one = threading.Thread(target=run, args=("one", first))
    one.start()
    assert _wait_for(lambda: first.messages)  # worker one holds the row lock mid-send
    two = threading.Thread(target=run, args=("two", second))
    two.start()
    two.join(10)
    release.set()
    one.join(10)

    sends = [m for m in first.messages + second.messages if m["Message-ID"] == message_id]
    assert len(sends) == 1
    email = _email(engine, notice_id)
    assert (email.status, email.attempts) == ("sent", 2)


# QA-SPL-125-162 | AC10 | WB restart picks up the pending retry
def test_qa_spl_125_162_a_new_app_instance_sends_a_pending_retry_once(engine, world):
    notice_id = _add_notice(world, "spl125_pg:restart")
    _make_pending(world, notice_id)
    world["app"].extensions["engine"].dispose()

    restarted_outbox = Outbox()
    restarted = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": os.environ["INTEGRATION_DATABASE_URL"],
            "EMAIL_SENDER": restarted_outbox,
            "NOTIFICATION_EMAIL_TO": SHARED_ADDRESS,
            "APP_BASE_URL": "https://app.connectsphere.test",
        }
    )
    try:
        restarted.extensions["process_due_emails"]()
        restarted.extensions["process_due_emails"]()
    finally:
        restarted.extensions["engine"].dispose()

    message_id = f"<connectsphere-email-{_email(engine, notice_id).id}@connectsphere.local>"
    assert [m["Message-ID"] for m in restarted_outbox.messages].count(message_id) == 1
    email = _email(engine, notice_id)
    assert (email.status, email.attempts) == ("sent", 2)
    assert "retried, attempt 2" in restarted_outbox.messages[0]["X-Tags"]


# QA-SPL-125-163 | AC10 | WB a retry that is not yet due waits
def test_qa_spl_125_163_a_retry_is_not_sent_before_it_is_due(engine, world):
    notice_id = _add_notice(world, "spl125_pg:later")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE email_deliveries SET status = 'pending', sent_at = NULL, attempts = 1, "
                "next_attempt_at = now() + interval '1 minute' WHERE notification_id = :n"
            ),
            {"n": notice_id},
        )
    outbox = Outbox()
    email_delivery.process_due_emails(engine, outbox)
    message_id = f"<connectsphere-email-{_email(engine, notice_id).id}@connectsphere.local>"
    assert message_id not in [m["Message-ID"] for m in outbox.messages]

    email_delivery.process_due_emails(
        engine, outbox, now=datetime.now(SINGAPORE) + timedelta(minutes=1, seconds=5)
    )
    assert [m["Message-ID"] for m in outbox.messages].count(message_id) == 1


# QA-SPL-125-164 | AC11 | WB records block deleting their notice
def test_qa_spl_125_164_a_notice_with_an_email_record_cannot_be_deleted(engine, world):
    notice_id = _add_notice(world, "spl125_pg:keep")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM notifications WHERE id = :n"), {"n": notice_id})
    assert _email(engine, notice_id).notification_id == notice_id


# QA-SPL-125-165 | AC3a/AC3b/AC8 | WB database checks
@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("UPDATE notifications SET recipient_role = NULL WHERE id = :n", "recipient_role"),
        ("UPDATE notifications SET recipient_role = 'admin' WHERE id = :n", "known_role"),
        (
            "UPDATE email_deliveries SET recipient_role = 'admin' WHERE notification_id = :n",
            "known_role",
        ),
        ("UPDATE email_deliveries SET status = 'bounced' WHERE notification_id = :n", "status"),
        ("UPDATE email_deliveries SET sent_at = NULL WHERE notification_id = :n", "outcome"),
    ],
)
def test_qa_spl_125_165_postgresql_enforces_role_and_outcome_rules(
    engine, world, statement, constraint
):
    notice_id = _add_notice(world, f"spl125_pg:{constraint}:{uuid.uuid4().hex[:6]}")

    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(text(statement), {"n": notice_id})
    assert constraint in str(refused.value)


# QA-SPL-125-166 | AC11 | WB security (row-level security, no browser grants)
def test_qa_spl_125_166_browser_roles_cannot_read_email_records(engine):
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT relrowsecurity FROM pg_class WHERE relname = 'email_deliveries'")
        )
        for role in ("anon", "authenticated"):
            exists = connection.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            )
            if not exists:
                continue
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege(:r, 'email_deliveries', :p)"),
                    {"r": role, "p": privilege},
                ), (role, privilege)


# QA-SPL-125-167 | AC5 | BB refused action on PostgreSQL
def test_qa_spl_125_167_a_refused_action_on_postgresql_leaves_no_email(engine, world):
    response = (
        world["app"]
        .test_client()
        .post(
            f"/api/event-requests/{world['event_id']}/coordinator",
            json={"coordinator_account_id": world["ids"]["alice"]},
            headers={"Authorization": "Bearer token-alice"},
        )
    )

    assert response.status_code == 403
    with Session(engine) as session:
        assert not session.scalars(
            select(Notification).where(Notification.event_request_id == world["event_id"])
        ).all()
    assert world["outbox"].messages == []


def _wait_for(predicate, seconds=5.0):
    import time as clock

    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        if predicate():
            return True
        clock.sleep(0.02)
    return False


# --- Migration (fresh database per case) -----------------------------------------------------


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
    name = f"spl125_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


KINDS = {
    "coordinator_assigned:1": "event_coordinator",
    "coordinator_removed:2": "event_coordinator",
    "clarification_answered:3": "event_coordinator",
    "change_request_submitted:4": "event_coordinator",
    "safety_decision:5": "event_coordinator",
    "organiser_coordinator_changed:6": "event_organiser",
    "organiser_approved:7": "event_organiser",
    "arrangement_booking_approved:8": "event_coordinator",
    "technical_requirement_added:9": "technical_support_staff",
    "venue_booking_requested:10": "venue_staff",
    "attendee_cancelled:11": "attendee",
}


def _seed_legacy_notices(url, keys):
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
                        "INSERT INTO notifications (recipient_account_id, event_request_id, "
                        "message, dedupe_key, created_at) VALUES (:a, :e, 'Old notice', :k, now())"
                    ),
                    {"a": account, "e": event, "k": key},
                )
    finally:
        legacy.dispose()


# QA-SPL-125-170 | AC3d | WB migration backfill
def test_qa_spl_125_170_existing_notices_are_given_their_role(fresh_url):
    assert _alembic(fresh_url, "upgrade", "s4_hold_expiry").returncode == 0
    _seed_legacy_notices(fresh_url, KINDS)

    upgraded = _alembic(fresh_url, "upgrade", "head")

    assert upgraded.returncode == 0, upgraded.stderr
    current = create_engine(fresh_url)
    try:
        with current.connect() as connection:
            stored = dict(
                connection.execute(
                    text("SELECT dedupe_key, recipient_role FROM notifications")
                ).all()
            )
            assert connection.scalar(text("SELECT count(*) FROM email_deliveries")) == 0
            nullable = connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'notifications' AND column_name = 'recipient_role'"
                )
            )
            default = connection.scalar(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name = 'notifications' AND column_name = 'recipient_role'"
                )
            )
    finally:
        current.dispose()
    assert stored == KINDS
    assert nullable == "NO" and default is None


# QA-SPL-125-171 | AC3d | WB negative (unknown kind stops the migration)
def test_qa_spl_125_171_an_unknown_notice_kind_stops_the_migration(fresh_url):
    assert _alembic(fresh_url, "upgrade", "s4_hold_expiry").returncode == 0
    _seed_legacy_notices(fresh_url, ["coordinator_assigned:1", "mystery_kind:2"])

    refused = _alembic(fresh_url, "upgrade", "head")

    assert refused.returncode != 0
    assert "No role is known for notice kind 'mystery_kind'" in refused.stderr
    check = create_engine(fresh_url)
    try:
        with check.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "s4_hold_expiry"
            )
            assert not inspect(connection).has_table("email_deliveries")
            columns = {c["name"] for c in inspect(connection).get_columns("notifications")}
            assert "recipient_role" not in columns
    finally:
        check.dispose()


# QA-SPL-125-172 | AC3d/AC11 | WB migration round trip
def test_qa_spl_125_172_the_migration_downgrades_and_upgrades_cleanly(fresh_url):
    assert _alembic(fresh_url, "upgrade", "head").returncode == 0
    down = _alembic(fresh_url, "downgrade", "s4_hold_expiry")
    assert down.returncode == 0, down.stderr
    check = create_engine(fresh_url)
    try:
        with check.connect() as connection:
            assert not inspect(connection).has_table("email_deliveries")
    finally:
        check.dispose()
    up = _alembic(fresh_url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
