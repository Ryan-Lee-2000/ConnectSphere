"""QA coverage for SPL-125, Receive notifications by email.

Case IDs (QA-SPL-125-NNN) match the QA-SPL-125 Confluence page. BB = black-box (HTTP API and the
email that leaves the app), WB = white-box (stored rows, session hooks, the retry loop, start-up).

Every case runs with a recording sender injected through EMAIL_SENDER, so no email is sent. The
PostgreSQL cases (locking, migration, row-level security) are in test_qa_spl125_postgres.py.
"""

import ast
import importlib.util
import inspect
import logging
import os
import re
import subprocess
import sys
import threading
import time as clock
from datetime import UTC, date, datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path

import httpx
import pytest
from app import create_app, email_delivery, models, notifications
from app.email_delivery import MAX_ATTEMPTS, GmailSender, SmtpSender, log_sender
from app.event_requests import SINGAPORE
from app.models import (
    ROLE_DISPLAY_NAMES,
    ROLE_VALUES,
    Account,
    AccountRole,
    Base,
    EmailDelivery,
    EventRequest,
    Notification,
    Organisation,
    Role,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_coordinator_assignment import (
    ALICE,
    BOB,
    INACTIVE_COORDINATOR,
    MANAGER,
    MANAGER_AND_ORGANISER,
    ORGANISER,
    TOKENS,
    VENUE_STAFF,
    headers,
)

SHARED_ADDRESS = "shared.inbox@connectsphere.test"
BASE_URL = "https://app.connectsphere.test"
BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations/versions/s4_email_deliveries.py"
ACCOUNTS = [
    (MANAGER, "Morgan Manager", True, [Role.EVENT_OPERATIONS_MANAGER]),
    (ORGANISER, "Olivia Organiser", True, [Role.EVENT_ORGANISER]),
    (ALICE, "Alice Tan", True, [Role.EVENT_COORDINATOR]),
    (BOB, "Bob Lim", True, [Role.EVENT_COORDINATOR]),
    (INACTIVE_COORDINATOR, "Ivan Inactive", False, [Role.EVENT_COORDINATOR]),
    (VENUE_STAFF, "Vera Venue", True, [Role.VENUE_STAFF]),
    (
        MANAGER_AND_ORGANISER,
        "Mina Multi",
        True,
        [Role.EVENT_OPERATIONS_MANAGER, Role.EVENT_ORGANISER],
    ),
]


class Outbox:
    """Records every message handed to the mail backend; can be told to fail."""

    def __init__(self):
        self.messages: list[EmailMessage] = []
        self.fail_next = 0
        self.always_fail = False
        self.error: Exception = ConnectionRefusedError("mail server unreachable")
        self.on_send = None

    def __call__(self, message: EmailMessage) -> str:
        self.messages.append(message)
        if self.on_send:
            self.on_send(message)
        if self.always_fail or self.fail_next:
            self.fail_next = max(0, self.fail_next - 1)
            raise self.error
        return f"gmail-{len(self.messages)}"


@pytest.fixture
def outbox():
    return Outbox()


@pytest.fixture
def app(tmp_path, outbox):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/spl125.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
            "EMAIL_SENDER": outbox,
            "NOTIFICATION_EMAIL_TO": SHARED_ADDRESS,
            "APP_BASE_URL": BASE_URL + "/",
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        session.add(organisation)
        session.flush()
        for account_id, name, active, roles in ACCOUNTS:
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    is_active=active,
                    organisation_id=organisation.id,
                )
            )
            session.add_all(AccountRole(account_id=account_id, role=role.value) for role in roles)
        session.commit()
        app.config["TEST_ORGANISATION_ID"] = organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def add_event(app, name="Harbour Summit", organiser=ORGANISER):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=organiser,
            organisation_id=app.config["TEST_ORGANISATION_ID"],
            name=name,
            purpose="Client showcase",
            proposed_date=date(2026, 10, 12),
            start_time=time(9, 0),
            end_time=time(12, 0),
            expected_attendance=120,
            status="submitted",
            submitted_at=datetime(2026, 9, 1, 9, 0, tzinfo=SINGAPORE),
        )
        session.add(event)
        session.commit()
        return event.id


def assign(client, event_id, coordinator=ALICE, token="manager"):
    return client.post(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": coordinator},
        headers=headers(token),
    )


def reassign(client, event_id, coordinator=BOB, token="manager"):
    return client.put(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": coordinator},
        headers=headers(token),
    )


def notices(app):
    with Session(app.extensions["engine"]) as session:
        return list(session.scalars(select(Notification).order_by(Notification.id)))


def deliveries(app):
    with Session(app.extensions["engine"]) as session:
        return list(session.scalars(select(EmailDelivery).order_by(EmailDelivery.id)))


def delivery_for(app, recipient):
    return next(d for d in deliveries(app) if d.recipient_account_id == recipient)


def add_notice(
    app, *, role=Role.EVENT_COORDINATOR, recipient=ALICE, kind="coordinator_assigned", **extra
):
    """Adds a notice directly, as a future notification type would, and commits it."""

    event_id = extra.pop("event_id", None) or add_event(app, extra.pop("event_name", "Gala"))
    with Session(app.extensions["engine"]) as session:
        notice = Notification(
            recipient_account_id=recipient,
            recipient_role=role,
            event_request_id=event_id,
            message=extra.pop("message", "Something changed."),
            dedupe_key=f"{kind}:{extra.pop('source', 1)}",
            created_at=extra.pop("created_at", datetime.now(SINGAPORE)),
        )
        session.add(notice)
        session.commit()
        return notice.id


def run_due(app, outbox, *, after: timedelta, start: datetime | None = None) -> int:
    moment = (start or datetime.now(SINGAPORE)) + after
    return email_delivery.process_due_emails(app.extensions["engine"], outbox, now=moment)


def plain_body(message: EmailMessage) -> str:
    return message.get_body(("plain",)).get_content()


def html_body(message: EmailMessage) -> str:
    return message.get_body(("html",)).get_content()


# =============================================================================================
# AC1  Every in-app notice also produces exactly one email; later types need no email work
# =============================================================================================


# QA-SPL-125-001 | AC1 | BB happy path
def test_qa_spl_125_001_an_assignment_notice_produces_exactly_one_email(app, client, outbox):
    event_id = add_event(app)

    assert assign(client, event_id).status_code == 201

    stored = notices(app)
    emails = deliveries(app)
    assert len(stored) >= 1
    assert sorted(d.notification_id for d in emails) == [n.id for n in stored]
    assert len(outbox.messages) == len(stored)
    alice = delivery_for(app, ALICE)
    assert alice.status == "sent" and alice.attempts == 1


# QA-SPL-125-002 | AC1 | BB multi-recipient
def test_qa_spl_125_002_a_reassignment_emails_every_notified_account_once(app, client, outbox):
    event_id = add_event(app)
    assign(client, event_id)
    before = {n.id for n in notices(app)}

    assert reassign(client, event_id, BOB).status_code == 200

    new = [n for n in notices(app) if n.id not in before]
    assert {n.recipient_account_id for n in new} == {ALICE, BOB, ORGANISER}
    emails = {d.notification_id: d for d in deliveries(app)}
    assert all(n.id in emails for n in new)
    assert len(emails) == len(notices(app)) == len(outbox.messages)


# QA-SPL-125-003 | AC1 | WB future type
def test_qa_spl_125_003_a_notice_type_added_later_is_emailed_without_email_work(app, outbox):
    notice_id = add_notice(app, role=Role.SAFETY_OFFICER, kind="safety_decision")

    [email] = deliveries(app)
    assert email.notification_id == notice_id
    assert email.status == "sent"
    assert "(Safety Officer)" in email.subject
    assert len(outbox.messages) == 1


# QA-SPL-125-004 | AC1 | WB boundary (many notices in one action)
def test_qa_spl_125_004_many_notices_in_one_commit_get_one_email_each(app, outbox):
    event_id = add_event(app)
    with Session(app.extensions["engine"]) as session:
        session.add_all(
            Notification(
                recipient_account_id=ALICE,
                recipient_role=Role.EVENT_COORDINATOR,
                event_request_id=event_id,
                message=f"Change {i}",
                dedupe_key=f"coordinator_assigned:{i}",
                created_at=datetime.now(SINGAPORE),
            )
            for i in range(25)
        )
        session.commit()

    emails = deliveries(app)
    assert len(emails) == 25
    assert len({d.notification_id for d in emails}) == 25
    assert len(outbox.messages) == 25
    # AC2: no digest. Each message carries one change only.
    assert all(plain_body(m).count("What changed:") == 1 for m in outbox.messages)


# QA-SPL-125-005 | AC1 | BB negative (reading is not a notice)
def test_qa_spl_125_005_reading_and_marking_notices_sends_nothing(app, client, outbox):
    event_id = add_event(app)
    assign(client, event_id)
    sent = len(outbox.messages)
    notice_id = notices(app)[0].id

    alice = notices(app)[0].recipient_account_id
    token = next(name for name, account in TOKENS.items() if account == alice)
    assert client.get("/api/notifications", headers=headers(token)).status_code == 200
    client.post(f"/api/notifications/{notice_id}/read", headers=headers(token))
    client.post("/api/notifications/read-all", headers=headers(token))

    assert len(outbox.messages) == sent
    assert len(deliveries(app)) == len(notices(app))


# QA-SPL-125-006 | AC1 | WB every helper
def test_qa_spl_125_006_every_notice_helper_on_main_names_a_role(app):
    # Every helper that builds a Notification passes recipient_role; a helper that forgot would
    # be refused at flush (AC3a). The static check keeps the list complete as helpers are added.
    tree = ast.parse(Path(notifications.__file__).read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Notification"
    ]
    assert len(calls) >= 11
    for call in calls:
        keywords = {kw.arg for kw in call.keywords}
        assert "recipient_role" in keywords, ast.unparse(call)[:120]


# =============================================================================================
# AC2  The first attempt follows the save immediately; no batching
# =============================================================================================


# QA-SPL-125-010 | AC2 | WB timing
def test_qa_spl_125_010_the_first_attempt_runs_before_the_request_returns(app, client, outbox):
    event_id = add_event(app)
    response = assign(client, event_id)

    assert response.status_code == 201
    # Nothing drove the retry loop; the attempt already happened as part of the action.
    assert all(d.attempts == 1 and d.status == "sent" for d in deliveries(app))
    assert len(outbox.messages) == len(notices(app))


# QA-SPL-125-011 | AC2 | WB ordering (after commit)
def test_qa_spl_125_011_the_send_starts_only_after_the_action_is_saved(app, client, outbox):
    event_id = add_event(app)
    seen = []

    def check_saved(message):
        # A separate connection can already see the committed assignment and notice.
        with Session(app.extensions["engine"]) as session:
            seen.append(
                (
                    session.scalar(select(func.count()).select_from(Notification)),
                    session.get(EventRequest, event_id) is not None,
                )
            )

    outbox.on_send = check_saved
    assign(client, event_id)

    assert seen and all(count >= 1 and found for count, found in seen)


# QA-SPL-125-012 | AC2 | WB no batching
def test_qa_spl_125_012_separate_actions_send_separately_and_immediately(app, outbox):
    add_notice(app, kind="clarification_answered", event_name="First Event")
    assert len(outbox.messages) == 1
    add_notice(app, kind="change_request_submitted", event_name="Second Event")
    assert len(outbox.messages) == 2
    assert "First Event" in outbox.messages[0]["Subject"]
    assert "Second Event" in outbox.messages[1]["Subject"]


# QA-SPL-125-013 | AC2 | WB runtime worker wakes at once
def test_qa_spl_125_013_the_runtime_worker_runs_as_soon_as_it_is_woken():
    ran = threading.Event()
    calls = []

    def deliver():
        calls.append(clock.monotonic())
        if len(calls) >= 2:
            ran.set()
        return 0

    worker = email_delivery._Worker(deliver)
    worker.start()
    assert _wait(lambda: len(calls) >= 1)  # the boot run
    woken = clock.monotonic()
    worker.wake()

    assert ran.wait(2), "wake() did not run delivery promptly"
    assert calls[1] - woken < email_delivery.POLL_SECONDS


# QA-SPL-125-014 | AC2 | WB no due-date delay
def test_qa_spl_125_014_a_new_email_is_due_at_the_moment_of_its_notice(app, outbox):
    outbox.always_fail = True
    created = datetime(2026, 10, 28, 9, 30, tzinfo=SINGAPORE)
    add_notice(app, created_at=created)

    [email] = deliveries(app)
    assert email.created_at.replace(tzinfo=None) == created.replace(tzinfo=None)
    # The first attempt was due immediately; the next is a minute after that attempt.
    assert email.attempts == 1


def _wait(predicate, seconds=3.0):
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        if predicate():
            return True
        clock.sleep(0.02)
    return predicate()


# =============================================================================================
# AC3  One shared address; subject and first line name the recipient and the role
# =============================================================================================


# QA-SPL-125-020 | AC3 | BB happy path
def test_qa_spl_125_020_the_email_names_the_coordinator_and_role(app, client, outbox):
    event_id = add_event(app, "Harbour Summit")
    assign(client, event_id)

    alice = delivery_for(app, ALICE)
    message = next(m for m in outbox.messages if "Alice Tan" in m["Subject"])
    assert message["To"] == SHARED_ADDRESS
    assert SHARED_ADDRESS in message["From"]
    assert alice.to_address == SHARED_ADDRESS
    assert message["Subject"] == "[ConnectSphere] For Alice Tan (Event Coordinator): Harbour Summit"
    assert plain_body(message).splitlines()[0] == "For Alice Tan (Event Coordinator)"
    assert alice.recipient_name == "Alice Tan"
    assert alice.recipient_role == "event_coordinator"


# QA-SPL-125-021 | AC3 | BB second role
def test_qa_spl_125_021_the_organiser_email_names_the_organiser_role(app, client, outbox):
    event_id = add_event(app, "Harbour Summit")
    assign(client, event_id)

    organiser = delivery_for(app, ORGANISER)
    assert organiser.subject == (
        "[ConnectSphere] For Olivia Organiser (Event Organiser): Harbour Summit"
    )
    assert organiser.body_text.splitlines()[0] == "For Olivia Organiser (Event Organiser)"
    assert organiser.to_address == SHARED_ADDRESS


# QA-SPL-125-022 | AC3 | WB multi-role account
def test_qa_spl_125_022_a_multi_role_account_is_named_with_the_role_the_notice_was_for(
    app, client, outbox
):
    # Mina holds Operations Manager and Organiser; her event's notice was sent to her as organiser.
    event_id = add_event(app, "Mina's Launch", organiser=MANAGER_AND_ORGANISER)
    assign(client, event_id)

    mina = delivery_for(app, MANAGER_AND_ORGANISER)
    assert "For Mina Multi (Event Organiser)" in mina.subject
    assert "Operations Manager" not in mina.subject


# QA-SPL-125-023 | AC3 | WB security (header injection)
def test_qa_spl_125_023_line_breaks_in_names_cannot_add_email_headers(app, outbox):
    with Session(app.extensions["engine"]) as session:
        session.get(Account, ALICE).display_name = "Alice\r\nBcc: attacker@example.test"
        session.commit()
    add_notice(app, event_name="Gala\r\nBcc: attacker@example.test")

    [message] = outbox.messages
    assert message["Bcc"] is None
    assert "\n" not in message["Subject"] and "\r" not in message["Subject"]
    assert message["To"] == SHARED_ADDRESS
    assert message["Subject"].startswith("[ConnectSphere] For Alice Bcc: attacker@example.test (")


# QA-SPL-125-024 | AC3 | WB security (HTML)
def test_qa_spl_125_024_html_in_names_and_messages_is_escaped(app, outbox):
    with Session(app.extensions["engine"]) as session:
        session.get(Account, ALICE).display_name = "<b>Alice</b>"
        session.commit()
    add_notice(app, event_name="<script>alert(1)</script>", message="<img src=x onerror=1>")

    html = html_body(outbox.messages[0])
    assert "<script>" not in html and "<img" not in html and "<b>Alice" not in html
    assert "&lt;script&gt;" in html and "&lt;img src=x onerror=1&gt;" in html


# QA-SPL-125-025 | AC3 | WB config
def test_qa_spl_125_025_every_email_goes_to_the_configured_shared_address(app, outbox):
    for role, recipient, kind in (
        (Role.EVENT_COORDINATOR, ALICE, "coordinator_assigned"),
        (Role.VENUE_STAFF, VENUE_STAFF, "venue_booking_requested"),
        (Role.EVENT_ORGANISER, ORGANISER, "organiser_decision"),
    ):
        add_notice(app, role=role, recipient=recipient, kind=kind)

    assert {m["To"] for m in outbox.messages} == {SHARED_ADDRESS}
    assert {d.to_address for d in deliveries(app)} == {SHARED_ADDRESS}


# =============================================================================================
# AC3a  A notice must name its role; there is no default
# =============================================================================================


def _bare_notice(event_id, **overrides):
    values = dict(
        recipient_account_id=ALICE,
        event_request_id=event_id,
        message="x",
        dedupe_key="coordinator_removed:1",
        created_at=datetime.now(SINGAPORE),
    )
    values.update(overrides)
    return Notification(**values)


# QA-SPL-125-030 | AC3a | WB negative (role omitted)
def test_qa_spl_125_030_a_notice_without_a_role_is_refused(app, outbox):
    event_id = add_event(app)
    with Session(app.extensions["engine"]) as session:
        session.add(_bare_notice(event_id))
        with pytest.raises(ValueError, match="must name the role"):
            session.commit()

    assert notices(app) == [] and deliveries(app) == [] and outbox.messages == []


# QA-SPL-125-031 | AC3a | WB negative (None)
def test_qa_spl_125_031_an_explicit_null_role_is_refused(app):
    event_id = add_event(app)
    with pytest.raises(ValueError):
        _bare_notice(event_id, recipient_role=None)


# QA-SPL-125-032 | AC3a | WB boundary (empty)
def test_qa_spl_125_032_an_empty_role_is_refused(app):
    event_id = add_event(app)
    with pytest.raises(ValueError):
        _bare_notice(event_id, recipient_role="")


# QA-SPL-125-033 | AC3a | WB schema
def test_qa_spl_125_033_the_role_column_is_required_with_no_default():
    column = Notification.__table__.c.recipient_role
    assert column.nullable is False
    assert column.default is None and column.server_default is None


# QA-SPL-125-034 | AC3a | WB database
def test_qa_spl_125_034_the_database_refuses_a_notice_without_a_role(app):
    event_id = add_event(app)
    with app.extensions["engine"].begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO notifications (recipient_account_id, event_request_id, message, "
                "dedupe_key, created_at) VALUES (:a, :e, 'x', 'raw:1', '2026-10-28 09:00:00')"
            ),
            {"a": ALICE, "e": event_id},
        )


# =============================================================================================
# AC3b  The role must be a defined role
# =============================================================================================


# QA-SPL-125-040 | AC3b | WB negative
@pytest.mark.parametrize(
    "value", ["admin", "coordinator", "Event Coordinator", "EVENT_COORDINATOR"]
)
def test_qa_spl_125_040_an_undefined_role_is_refused(app, value):
    event_id = add_event(app)
    with pytest.raises(ValueError, match="Unknown notification role"):
        _bare_notice(event_id, recipient_role=value)


# QA-SPL-125-041 | AC3b | WB happy path (every defined role)
@pytest.mark.parametrize("role", list(Role))
def test_qa_spl_125_041_every_defined_role_is_accepted(app, outbox, role):
    add_notice(app, role=role)

    [email] = deliveries(app)
    assert email.recipient_role == role.value
    assert f"({ROLE_DISPLAY_NAMES[role]})" in email.subject


# QA-SPL-125-042 | AC3b | WB database (validator bypassed)
def test_qa_spl_125_042_the_database_refuses_an_undefined_role(app):
    event_id = add_event(app)
    with app.extensions["engine"].begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO notifications (recipient_account_id, recipient_role, "
                "event_request_id, message, dedupe_key, created_at) "
                "VALUES (:a, 'admin', :e, 'x', 'raw:2', '2026-10-28 09:00:00')"
            ),
            {"a": ALICE, "e": event_id},
        )


# QA-SPL-125-043 | AC3b | WB database (email record)
def test_qa_spl_125_043_an_email_record_with_an_undefined_role_is_refused(app, outbox):
    notice_id = add_notice(app)
    with app.extensions["engine"].begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text("UPDATE email_deliveries SET recipient_role = 'admin' WHERE notification_id = :n"),
            {"n": notice_id},
        )


# QA-SPL-125-044 | AC3b | WB drift (model vs migration)
def test_qa_spl_125_044_the_migration_allows_exactly_the_defined_roles():
    migration = _load(MIGRATION, "spl125_migration_044")
    allowed = set(re.findall(r"'([a-z_]+)'", migration.KNOWN_ROLE))
    assert allowed == set(ROLE_VALUES)
    assert set(re.findall(r"'([a-z_]+)'", models.KNOWN_NOTIFICATION_ROLE)) == set(ROLE_VALUES)


# =============================================================================================
# AC3c  Every defined role has a display name; a role added without one fails the checks
# =============================================================================================


def _load(path: Path, name: str, replace: tuple[str, str] | None = None):
    source = path.read_text()
    if replace:
        assert replace[0] in source
        source = source.replace(replace[0], replace[1])
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    finally:
        sys.modules.pop(name, None)
    return module


# QA-SPL-125-050 | AC3c | WB happy path
def test_qa_spl_125_050_every_defined_role_has_a_readable_display_name():
    assert set(ROLE_DISPLAY_NAMES) == set(Role)
    assert all(name.strip() for name in ROLE_DISPLAY_NAMES.values())
    assert ROLE_DISPLAY_NAMES[Role.VENUE_STAFF] == "Venue Staff"


# QA-SPL-125-051 | AC3c | WB negative (new role without a name)
def test_qa_spl_125_051_a_role_added_without_a_display_name_stops_loading():
    with pytest.raises(RuntimeError, match="Roles without an email display name"):
        _load(
            Path(models.__file__),
            "spl125_models_051",
            ('    ATTENDEE = "attendee"\n', '    ATTENDEE = "attendee"\n    AUDITOR = "auditor"\n'),
        )


# QA-SPL-125-052 | AC3c | WB negative (name removed)
def test_qa_spl_125_052_a_role_whose_display_name_is_removed_stops_loading():
    with pytest.raises(RuntimeError, match="attendee"):
        _load(Path(models.__file__), "spl125_models_052", ('    Role.ATTENDEE: "Attendee",\n', ""))


# QA-SPL-125-053 | AC3c | WB boundary (blank name)
def test_qa_spl_125_053_a_blank_display_name_stops_loading():
    with pytest.raises(RuntimeError, match="venue_staff"):
        _load(
            Path(models.__file__),
            "spl125_models_053",
            ('Role.VENUE_STAFF: "Venue Staff"', 'Role.VENUE_STAFF: "   "'),
        )


# QA-SPL-125-054 | AC3c | WB control (unchanged source loads)
def test_qa_spl_125_054_the_unchanged_models_module_loads():
    loaded = _load(Path(models.__file__), "spl125_models_054")
    assert set(loaded.ROLE_DISPLAY_NAMES) == set(loaded.Role)


# =============================================================================================
# AC3d  Existing notices are given their correct role (migration map; PostgreSQL runs it)
# =============================================================================================


def _helper_kinds():
    """(dedupe-key prefix, role) for every Notification built in notifications.py."""

    tree = ast.parse(Path(notifications.__file__).read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Notification":
            keywords = {kw.arg: kw.value for kw in node.keywords}
            key = keywords["dedupe_key"]
            prefix = ast.unparse(key).split(":", 1)[0].lstrip("f'\"")
            found.append((prefix, ast.unparse(keywords["recipient_role"])))
    return found


# QA-SPL-125-060 | AC3d | WB drift (migration map vs helpers)
def test_qa_spl_125_060_the_backfill_gives_each_helper_kind_the_role_the_helper_names():
    migration = _load(MIGRATION, "spl125_migration_060")
    literal = {
        "Role.EVENT_COORDINATOR": "event_coordinator",
        "Role.EVENT_ORGANISER": "event_organiser",
        "Role.TECHNICAL_SUPPORT_STAFF": "technical_support_staff",
        "Role.VENUE_STAFF": "venue_staff",
        "Role.ATTENDEE": "attendee",
    }

    def backfilled(kind):
        return migration.ROLE_BY_KIND.get(kind) or next(
            (r for p, r in migration.ROLE_BY_PREFIX.items() if kind.startswith(p)), None
        )

    checked = 0
    for prefix, role in _helper_kinds():
        if role == "role":
            continue  # the helper's notify(...) passes each role explicitly; checked below
        kind = prefix.replace("{kind}", "x")
        assert backfilled(kind) == literal[role], (prefix, role)
        checked += 1
    assert checked >= 10
    assert backfilled("coordinator_removed") == "event_coordinator"
    assert backfilled("organiser_coordinator_changed") == "event_organiser"


# QA-SPL-125-061 | AC3d | WB negative (unknown kind stops)
def test_qa_spl_125_061_an_unknown_kind_stops_the_backfill(monkeypatch):
    migration = _load(MIGRATION, "spl125_migration_061")

    class Bind:
        def execute(self, statement, params=None):
            class Result:
                def all(self):
                    return [(7, "mystery_kind:3")]

            return Result()

    monkeypatch.setattr(migration.op, "get_bind", lambda: Bind(), raising=False)
    with pytest.raises(RuntimeError, match="mystery_kind"):
        migration._backfill_roles()


# QA-SPL-125-062 | AC3d | WB every existing kind
@pytest.mark.parametrize(
    ("dedupe_key", "role"),
    [
        ("coordinator_assigned:1", "event_coordinator"),
        ("coordinator_removed:1", "event_coordinator"),
        ("clarification_answered:1", "event_coordinator"),
        ("change_request_submitted:1", "event_coordinator"),
        ("safety_decision:1", "event_coordinator"),
        ("organiser_coordinator_changed:1", "event_organiser"),
        ("organiser_approved:1", "event_organiser"),
        ("arrangement_booking_approved:1", "event_coordinator"),
        ("technical_requirement_added:1", "technical_support_staff"),
        ("venue_booking_requested:1", "venue_staff"),
        ("attendee_cancelled:1", "attendee"),
    ],
)
def test_qa_spl_125_062_each_existing_kind_maps_to_its_role(monkeypatch, dedupe_key, role):
    migration = _load(MIGRATION, "spl125_migration_062")
    updates = []

    class Bind:
        def execute(self, statement, params=None):
            if params:
                updates.append(params)

            class Result:
                def all(self):
                    return [(1, dedupe_key)]

            return Result()

    monkeypatch.setattr(migration.op, "get_bind", lambda: Bind(), raising=False)
    migration._backfill_roles()
    assert updates == [{"role": role, "id": 1}]


# =============================================================================================
# AC4  Event name, same wording as in-app, Singapore time, link to the same page
# =============================================================================================


# QA-SPL-125-070 | AC4 | BB happy path (matches the in-app notice)
def test_qa_spl_125_070_the_email_repeats_the_in_app_notice(app, client, outbox):
    event_id = add_event(app, "Harbour Summit")
    assign(client, event_id)

    [in_app] = client.get("/api/notifications", headers=headers("coordinator")).json[
        "notifications"
    ]
    message = next(m for m in outbox.messages if "Alice Tan" in m["Subject"])
    body = plain_body(message)
    assert "Event: Harbour Summit" in body
    assert f"What changed: {in_app['message']}" in body
    assert f"Open: {BASE_URL}{in_app['link']}" in body
    created = datetime.fromisoformat(in_app["created_at"]).astimezone(SINGAPORE)
    assert f"When: {created:%a} {created.day} {created:%b %Y}, {created:%H:%M} SGT" in body


# QA-SPL-125-071 | AC4 | WB boundary (UTC instant across midnight)
def test_qa_spl_125_071_the_time_is_shown_in_singapore_time(app, outbox):
    add_notice(app, created_at=datetime(2026, 10, 27, 16, 30, tzinfo=UTC))

    assert "When: Wed 28 Oct 2026, 00:30 SGT" in plain_body(outbox.messages[0])


# QA-SPL-125-072 | AC4 | WB every link family
@pytest.mark.parametrize(
    ("kind", "role", "path"),
    [
        ("coordinator_assigned", Role.EVENT_COORDINATOR, "/workspace/assigned-events/{id}"),
        ("organiser_decision", Role.EVENT_ORGANISER, "/workspace/organisation-events/{id}"),
        (
            "technical_requirement_recorded",
            Role.TECHNICAL_SUPPORT_STAFF,
            "/workspace/equipment-review-queue",
        ),
        ("venue_booking_requested", Role.VENUE_STAFF, "/workspace/booking-requests"),
        ("attendee_event_cancelled", Role.ATTENDEE, "/workspace/my-registrations"),
    ],
)
def test_qa_spl_125_072_the_link_opens_the_same_page_as_the_notice(app, outbox, kind, role, path):
    event_id = add_event(app)
    add_notice(app, role=role, kind=kind, event_id=event_id)

    expected = BASE_URL + path.format(id=event_id)
    [message] = outbox.messages
    assert f"Open: {expected}" in plain_body(message)
    assert f'href="{expected}"' in html_body(message)
    # No double slash although APP_BASE_URL was configured with a trailing slash.
    assert "//workspace" not in plain_body(message)


# QA-SPL-125-073 | AC4 | WB html part
def test_qa_spl_125_073_the_html_part_holds_the_same_details(app, outbox):
    add_notice(app, event_name="Gala Night", message="Your booking was approved.")

    html = html_body(outbox.messages[0])
    assert "Event: Gala Night" in html
    assert "What changed: Your booking was approved." in html
    assert " SGT" in html
    assert "Open in ConnectSphere" in html


# QA-SPL-125-074 | AC4 | WB stored body equals sent body
def test_qa_spl_125_074_the_stored_body_is_the_body_that_was_sent(app, outbox):
    add_notice(app)

    [email] = deliveries(app)
    [message] = outbox.messages
    assert plain_body(message).strip() == email.body_text.strip()
    assert message["Subject"] == email.subject


# =============================================================================================
# AC5  A refused or rolled-back action sends no email
# =============================================================================================


# QA-SPL-125-080 | AC5 | BB refused (inactive coordinator)
def test_qa_spl_125_080_a_refused_assignment_sends_nothing(app, client, outbox):
    event_id = add_event(app)

    response = assign(client, event_id, INACTIVE_COORDINATOR)

    assert response.status_code >= 400
    assert notices(app) == [] and deliveries(app) == [] and outbox.messages == []


# QA-SPL-125-081 | AC5 | BB security (wrong role)
@pytest.mark.parametrize("token", ["organiser", "coordinator", "venue-staff"])
def test_qa_spl_125_081_an_unauthorised_assignment_sends_nothing(app, client, outbox, token):
    event_id = add_event(app)

    assert assign(client, event_id, token=token).status_code == 403
    assert notices(app) == [] and deliveries(app) == [] and outbox.messages == []


# QA-SPL-125-082 | AC5 | WB rollback after the notice was flushed
def test_qa_spl_125_082_a_rolled_back_action_leaves_no_notice_or_email(app, outbox):
    event_id = add_event(app)
    with Session(app.extensions["engine"]) as session:
        session.add(_bare_notice(event_id, recipient_role=Role.EVENT_COORDINATOR))
        session.flush()  # the email row is written in the same flush
        assert session.scalar(select(func.count()).select_from(EmailDelivery)) == 1
        session.rollback()

    assert notices(app) == [] and deliveries(app) == [] and outbox.messages == []


# QA-SPL-125-083 | AC5 | WB failed commit (duplicate notice)
def test_qa_spl_125_083_an_action_that_fails_on_commit_sends_nothing_more(app, outbox):
    notice_id = add_notice(app, kind="coordinator_removed", source=1)
    event_id = notices(app)[0].event_request_id
    with Session(app.extensions["engine"]) as session:
        session.add(
            _bare_notice(
                event_id, recipient_role="event_coordinator", dedupe_key="coordinator_removed:1"
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    assert [n.id for n in notices(app)] == [notice_id]
    assert len(deliveries(app)) == 1 and len(outbox.messages) == 1


# QA-SPL-125-084 | AC5 | WB queued flag cleared on rollback
def test_qa_spl_125_084_after_a_rollback_a_later_commit_does_not_dispatch(app, outbox, monkeypatch):
    event_id = add_event(app)
    dispatched = []
    settings = email_delivery._settings[app.extensions["engine"]]
    monkeypatch.setitem(
        email_delivery._settings,
        app.extensions["engine"],
        email_delivery.EmailSettings(
            settings.to_address, settings.base_url, lambda: dispatched.append(1)
        ),
    )
    with Session(app.extensions["engine"]) as session:
        session.add(_bare_notice(event_id, recipient_role=Role.EVENT_COORDINATOR))
        session.flush()
        session.rollback()
        session.get(EventRequest, event_id).name = "Renamed"
        session.commit()

    assert dispatched == []


# =============================================================================================
# AC6  A failed send never blocks or undoes the action
# =============================================================================================


# QA-SPL-125-090 | AC6 | BB failing mail server
def test_qa_spl_125_090_the_action_is_saved_when_every_send_fails(app, client, outbox):
    outbox.always_fail = True
    event_id = add_event(app)

    response = assign(client, event_id)

    assert response.status_code == 201
    with Session(app.extensions["engine"]) as session:
        alice_notices = select(func.count()).select_from(Notification)
        alice_notices = alice_notices.where(Notification.recipient_account_id == ALICE)
        assert session.scalar(alice_notices) == 1
    alice = delivery_for(app, ALICE)
    assert alice.status == "pending" and alice.attempts == 1
    assert "mail server unreachable" in alice.last_error
    in_app = client.get("/api/notifications", headers=headers("coordinator")).json
    assert len(in_app["notifications"]) == 1


# QA-SPL-125-091 | AC6 | WB dispatch itself raises
def test_qa_spl_125_091_a_dispatch_error_is_logged_and_the_action_stays(
    app, client, monkeypatch, caplog
):
    engine = app.extensions["engine"]
    settings = email_delivery._settings[engine]

    def broken():
        raise RuntimeError("worker gone")

    monkeypatch.setitem(
        email_delivery._settings,
        engine,
        email_delivery.EmailSettings(settings.to_address, settings.base_url, broken),
    )
    event_id = add_event(app)
    with caplog.at_level(logging.ERROR, logger="app.email_delivery"):
        response = assign(client, event_id)

    assert response.status_code == 201
    assert "Email dispatch failed" in caplog.text
    assert len([n for n in notices(app) if n.recipient_account_id == ALICE]) == 1
    assert all(d.status == "pending" and d.attempts == 0 for d in deliveries(app))


# QA-SPL-125-092 | AC6 | WB timeout
def test_qa_spl_125_092_a_timeout_is_recorded_as_an_error(app, outbox):
    outbox.always_fail = True
    outbox.error = TimeoutError("timed out")
    add_notice(app)

    [email] = deliveries(app)
    assert email.last_error == "TimeoutError: timed out"
    assert len(notices(app)) == 1


# QA-SPL-125-093 | AC6 | WB boundary (long error)
def test_qa_spl_125_093_a_very_long_error_is_kept_to_2000_characters(app, outbox):
    outbox.always_fail = True
    outbox.error = RuntimeError("x" * 5000)
    add_notice(app)

    assert len(deliveries(app)[0].last_error) == 2000


# QA-SPL-125-094 | AC6 | BB repeat after a failed send
def test_qa_spl_125_094_repeating_the_action_after_a_failed_send_adds_no_notice(
    app, client, outbox
):
    outbox.always_fail = True
    event_id = add_event(app)
    assign(client, event_id)
    count = len(notices(app))

    assert assign(client, event_id).status_code == 409
    assert len(notices(app)) == count == len(deliveries(app))


# =============================================================================================
# AC7  Tests and CI never send; local development sends only to Mailpit
# =============================================================================================


# QA-SPL-125-100 | AC7 | WB tests ignore any configured backend
@pytest.mark.parametrize("backend", ["gmail_api", "smtp"])
def test_qa_spl_125_100_a_test_app_never_uses_a_real_backend(tmp_path, monkeypatch, backend):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a test tried to reach a real mail backend")

    monkeypatch.setattr(httpx, "post", forbidden)
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", forbidden)
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/ac7.db",
            "EMAIL_BACKEND": backend,
            "GMAIL_CLIENT_ID": "id",
            "GMAIL_CLIENT_SECRET": "secret",
            "GMAIL_REFRESH_TOKEN": "token",
            "NOTIFICATION_EMAIL_TO": SHARED_ADDRESS,
            "APP_BASE_URL": BASE_URL,
        }
    )
    Base.metadata.create_all(app.extensions["engine"])
    with Session(app.extensions["engine"]) as session:
        organisation = Organisation(name="Org")
        session.add(organisation)
        session.flush()
        session.add(Account(id=ALICE, display_name="Alice Tan", organisation_id=organisation.id))
        session.commit()
        app.config["TEST_ORGANISATION_ID"] = organisation.id
    add_notice(app)

    [email] = deliveries(app)
    assert email.status == "sent" and email.provider_message_id is None
    app.extensions["engine"].dispose()


# QA-SPL-125-101 | AC7 | WB the log backend writes the whole email to the log
def test_qa_spl_125_101_the_log_backend_writes_the_email_to_the_log(caplog):
    message = EmailMessage()
    message["Subject"] = "[ConnectSphere] For Alice Tan (Event Coordinator): Gala"
    message.set_content("For Alice Tan (Event Coordinator)")
    with caplog.at_level(logging.INFO, logger="app.email_delivery"):
        assert log_sender(message) is None

    assert "Email not sent (log backend)" in caplog.text
    assert "For Alice Tan (Event Coordinator): Gala" in caplog.text


def _runtime_app(tmp_path, **config):
    values = {
        "DATABASE_URL": f"sqlite:///{tmp_path}/runtime.db",
        "EMAIL_BACKEND": "smtp",
        "NOTIFICATION_EMAIL_TO": SHARED_ADDRESS,
        "APP_BASE_URL": BASE_URL,
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": "1",
        "GMAIL_CLIENT_ID": "",
        "GMAIL_CLIENT_SECRET": "",
        "GMAIL_REFRESH_TOKEN": "",
        "RENDER": "",
    }
    values.update(config)
    return create_app(values)


# QA-SPL-125-102 | AC7 | WB start-up refusals
@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"EMAIL_BACKEND": "log"}, "EMAIL_BACKEND must be smtp"),
        ({"EMAIL_BACKEND": ""}, "EMAIL_BACKEND must be smtp"),
        ({"EMAIL_BACKEND": "sendgrid"}, "EMAIL_BACKEND must be smtp"),
        ({"EMAIL_BACKEND": "smtp", "RENDER": "true"}, "must be gmail_api on Render"),
        ({"EMAIL_BACKEND": "gmail_api"}, "GMAIL_CLIENT_ID"),
        ({"NOTIFICATION_EMAIL_TO": ""}, "NOTIFICATION_EMAIL_TO"),
        ({"APP_BASE_URL": ""}, "APP_BASE_URL"),
        ({"SMTP_PORT": "1"}, "Mailpit is not reachable"),
    ],
)
def test_qa_spl_125_102_the_app_refuses_to_start_when_email_is_misconfigured(
    tmp_path, config, message
):
    with pytest.raises(RuntimeError, match=message):
        _runtime_app(tmp_path, **config)


# QA-SPL-125-103 | AC7 | WB smtp goes only to the configured local server
def test_qa_spl_125_103_smtp_sends_to_the_configured_local_server(monkeypatch):
    used = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            used.append((host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def send_message(self, message):
            used.append(message["To"])

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSMTP)
    message = EmailMessage()
    message["To"] = SHARED_ADDRESS
    message.set_content("x")
    SmtpSender("127.0.0.1", 54325)(message)

    assert used == [("127.0.0.1", 54325, email_delivery.SEND_TIMEOUT_SECONDS), SHARED_ADDRESS]


# QA-SPL-125-104 | AC7 | WB a valid local runtime starts with smtp
def test_qa_spl_125_104_a_local_runtime_with_a_reachable_server_starts(tmp_path, monkeypatch):
    class Probe:
        def close(self):
            pass

    monkeypatch.setattr(email_delivery.socket, "create_connection", lambda *_a, **_k: Probe())
    started = []
    monkeypatch.setattr(email_delivery._Worker, "start", lambda self: started.append(self))

    app = _runtime_app(tmp_path, SMTP_PORT="54325")

    assert started, "the background worker was not started"
    settings = email_delivery._settings[app.extensions["engine"]]
    assert settings.to_address == SHARED_ADDRESS
    app.extensions["engine"].dispose()


# QA-SPL-125-105 | AC7 | WB Render uses the Gmail API
def test_qa_spl_125_105_render_with_gmail_settings_uses_the_gmail_api(tmp_path, monkeypatch):
    monkeypatch.setattr(email_delivery._Worker, "start", lambda self: None)
    captured = {}
    original = email_delivery._runtime_sender

    def spy(config):
        captured["sender"] = original(config)
        return captured["sender"]

    monkeypatch.setattr(email_delivery, "_runtime_sender", spy)
    app = _runtime_app(
        tmp_path,
        EMAIL_BACKEND="gmail_api",
        RENDER="true",
        GMAIL_CLIENT_ID="id",
        GMAIL_CLIENT_SECRET="secret",
        GMAIL_REFRESH_TOKEN="token",
    )

    assert isinstance(captured["sender"], GmailSender)
    app.extensions["engine"].dispose()


# =============================================================================================
# AC8  Up to 4 attempts a minute apart; one outcome; retries are not separate emails
# =============================================================================================


# QA-SPL-125-110 | AC8 | WB always failing
def test_qa_spl_125_110_an_email_that_always_fails_is_tried_4_times_then_failed(app, outbox):
    outbox.always_fail = True
    start = datetime.now(SINGAPORE)
    add_notice(app)

    assert run_due(app, outbox, start=start, after=timedelta(seconds=50)) == 0  # not yet due
    for minute in (1, 2, 3):
        assert run_due(app, outbox, start=start, after=timedelta(minutes=minute, seconds=5)) == 1
    assert run_due(app, outbox, start=start, after=timedelta(hours=1)) == 0

    [email] = deliveries(app)
    assert email.attempts == MAX_ATTEMPTS == 4
    assert email.status == "failed"
    assert email.failed_at is not None and email.sent_at is None
    assert email.next_attempt_at is None
    assert len(outbox.messages) == 4  # every attempt failed, so nothing was delivered


# QA-SPL-125-111 | AC8 | WB fail then succeed
def test_qa_spl_125_111_a_retry_that_succeeds_ends_sent_and_is_tagged(app, outbox):
    outbox.fail_next = 1
    start = datetime.now(SINGAPORE)
    add_notice(app, role=Role.VENUE_STAFF, recipient=VENUE_STAFF)

    assert run_due(app, outbox, start=start, after=timedelta(seconds=30)) == 0
    assert run_due(app, outbox, start=start, after=timedelta(minutes=1, seconds=1)) == 1

    [email] = deliveries(app)
    assert (email.status, email.attempts, email.last_error) == ("sent", 2, None)
    assert email.sent_at is not None and email.failed_at is None
    assert outbox.messages[0]["X-Tags"] == "Venue Staff"
    assert outbox.messages[1]["X-Tags"] == "Venue Staff, retried, attempt 2"


# QA-SPL-125-112 | AC8 | WB retry spacing
def test_qa_spl_125_112_each_retry_is_due_one_minute_after_the_previous_attempt(app, outbox):
    outbox.always_fail = True
    start = datetime.now(SINGAPORE)
    add_notice(app)
    first = deliveries(app)[0].next_attempt_at

    attempt_two = start.replace(tzinfo=None) + timedelta(minutes=1, seconds=5)
    run_due(app, outbox, start=start, after=timedelta(minutes=1, seconds=5))
    second = deliveries(app)[0].next_attempt_at

    assert timedelta(seconds=55) <= first - start.replace(tzinfo=None) <= timedelta(seconds=65)
    assert second - attempt_two == timedelta(minutes=1)


# QA-SPL-125-113 | AC8 | WB one record across retries
def test_qa_spl_125_113_retries_are_never_counted_as_separate_emails(app, outbox):
    outbox.fail_next = 3
    start = datetime.now(SINGAPORE)
    add_notice(app)
    for minute in (1, 2, 3):
        run_due(app, outbox, start=start, after=timedelta(minutes=minute, seconds=5))

    emails = deliveries(app)
    assert len(emails) == 1
    assert (emails[0].status, emails[0].attempts) == ("sent", 4)
    assert outbox.messages[-1]["X-Tags"].endswith("retried, attempt 4")


# QA-SPL-125-114 | AC8 | WB database outcome rule
@pytest.mark.parametrize(
    "assignment",
    [
        "status = 'sent', sent_at = NULL",
        "status = 'failed', failed_at = NULL",
        "status = 'sent', failed_at = '2026-10-28 09:00:00'",
        "status = 'pending', sent_at = '2026-10-28 09:00:00'",
        "status = 'bounced'",
    ],
)
def test_qa_spl_125_114_an_email_has_exactly_one_recorded_outcome(app, outbox, assignment):
    add_notice(app)
    with app.extensions["engine"].begin() as connection, pytest.raises(IntegrityError):
        connection.execute(text(f"UPDATE email_deliveries SET {assignment}"))


# QA-SPL-125-115 | AC8 | WB a first-time success is not tagged as retried
def test_qa_spl_125_115_a_first_time_success_is_not_tagged_retried(app, outbox):
    add_notice(app)

    assert outbox.messages[0]["X-Tags"] == "Event Coordinator"


# =============================================================================================
# AC9  A retry never adds a notice and never resends a sent email
# =============================================================================================


# QA-SPL-125-120 | AC9 | WB no second notice
def test_qa_spl_125_120_a_retry_never_creates_a_second_notice(app, outbox):
    outbox.fail_next = 2
    start = datetime.now(SINGAPORE)
    add_notice(app)
    for minute in (1, 2):
        run_due(app, outbox, start=start, after=timedelta(minutes=minute, seconds=5))

    assert len(notices(app)) == 1
    assert deliveries(app)[0].status == "sent"


# QA-SPL-125-121 | AC9 | WB a sent email is never resent
def test_qa_spl_125_121_a_sent_email_is_never_picked_up_again(app, outbox):
    add_notice(app)
    for hours in (1, 24, 24 * 30):
        assert run_due(app, outbox, after=timedelta(hours=hours)) == 0

    assert len(outbox.messages) == 1


# QA-SPL-125-122 | AC9 | WB every attempt is the same message
def test_qa_spl_125_122_every_attempt_carries_the_same_message_id(app, outbox):
    outbox.fail_next = 2
    start = datetime.now(SINGAPORE)
    add_notice(app)
    for minute in (1, 2):
        run_due(app, outbox, start=start, after=timedelta(minutes=minute, seconds=5))

    ids = {m["Message-ID"] for m in outbox.messages}
    assert len(outbox.messages) == 3 and len(ids) == 1


# QA-SPL-125-123 | AC9 | WB database uniqueness
def test_qa_spl_125_123_a_notice_cannot_gain_a_second_email_record(app, outbox):
    add_notice(app)
    [email] = deliveries(app)
    with Session(app.extensions["engine"]) as session:
        session.add(
            EmailDelivery(
                notification_id=email.notification_id,
                recipient_account_id=email.recipient_account_id,
                recipient_name=email.recipient_name,
                recipient_role=email.recipient_role,
                to_address=email.to_address,
                subject=email.subject,
                body_text=email.body_text,
                body_html=email.body_html,
                status="pending",
                attempts=0,
                created_at=email.created_at,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


# QA-SPL-125-124 | AC9 | WB a failed email is never retried again
def test_qa_spl_125_124_a_failed_email_is_never_tried_again(app, outbox):
    outbox.always_fail = True
    start = datetime.now(SINGAPORE)
    add_notice(app)
    for minute in (1, 2, 3):
        run_due(app, outbox, start=start, after=timedelta(minutes=minute, seconds=5))
    outbox.always_fail = False

    assert run_due(app, outbox, start=start, after=timedelta(days=1)) == 0
    assert len(outbox.messages) == 4 and deliveries(app)[0].status == "failed"


# =============================================================================================
# AC10  A pending retry survives a restart (PostgreSQL proofs in the _postgres file)
# =============================================================================================


# QA-SPL-125-130 | AC10 | WB a new app instance picks up a pending retry
def test_qa_spl_125_130_a_restarted_app_sends_a_pending_retry_once(tmp_path, app, outbox):
    outbox.fail_next = 1
    start = datetime.now(SINGAPORE)
    add_notice(app)
    app.extensions["engine"].dispose()  # the first instance goes away

    second = Outbox()
    restarted = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": app.config["DATABASE_URL"],
            "EMAIL_SENDER": second,
            "NOTIFICATION_EMAIL_TO": SHARED_ADDRESS,
            "APP_BASE_URL": BASE_URL,
        }
    )
    engine = restarted.extensions["engine"]
    assert email_delivery.process_due_emails(engine, second, now=start) == 0  # not due yet
    later = start + timedelta(minutes=1, seconds=5)
    assert email_delivery.process_due_emails(engine, second, now=later) == 1
    assert email_delivery.process_due_emails(engine, second, now=later) == 0

    assert len(second.messages) == 1
    with Session(engine) as session:
        email = session.scalars(select(EmailDelivery)).one()
    assert (email.status, email.attempts) == ("sent", 2)
    engine.dispose()


# QA-SPL-125-131 | AC10 | WB the worker runs once at boot
def test_qa_spl_125_131_the_worker_runs_pending_emails_straight_after_start():
    calls = []
    worker = email_delivery._Worker(lambda: calls.append(1) or 0)
    started = clock.monotonic()
    worker.start()

    assert _wait(lambda: calls, 2)
    assert clock.monotonic() - started < email_delivery.POLL_SECONDS


# QA-SPL-125-132 | AC10 | WB the loop survives a failing run
def test_qa_spl_125_132_the_worker_keeps_running_after_a_failed_run(caplog):
    calls = []

    def deliver():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database asleep")
        return 0

    worker = email_delivery._Worker(deliver)
    with caplog.at_level(logging.ERROR, logger="app.email_delivery"):
        worker.start()
        assert _wait(lambda: calls)
        worker.wake()
        assert _wait(lambda: len(calls) >= 2)

    assert "Email delivery loop failed" in caplog.text


# QA-SPL-125-133 | AC10 | WB an email interrupted mid-attempt is retried
def test_qa_spl_125_133_an_attempt_that_never_committed_is_tried_again(app, outbox):
    # A crash during the send rolls the row back to pending with its previous attempt count.
    outbox.always_fail = True
    add_notice(app)
    before = deliveries(app)[0]
    engine = app.extensions["engine"]
    with Session(engine) as session:
        row = session.get(EmailDelivery, before.id)
        email_delivery._attempt(row, Outbox(), datetime.now(SINGAPORE))
        session.rollback()  # the process died before commit

    after = deliveries(app)[0]
    assert (after.status, after.attempts) == ("pending", before.attempts)


# =============================================================================================
# AC11  One record per email with every required field
# =============================================================================================


# QA-SPL-125-140 | AC11 | WB sent record
def test_qa_spl_125_140_a_sent_email_record_holds_every_required_field(app, client, outbox):
    event_id = add_event(app, "Harbour Summit")
    assign(client, event_id)

    alice = delivery_for(app, ALICE)
    notice = next(n for n in notices(app) if n.recipient_account_id == ALICE)
    assert alice.notification_id == notice.id
    assert (alice.recipient_name, alice.recipient_role) == ("Alice Tan", "event_coordinator")
    assert alice.to_address == SHARED_ADDRESS
    assert alice.subject.startswith("[ConnectSphere] For Alice Tan")
    assert notice.message in alice.body_text and "Harbour Summit" in alice.body_html
    assert (alice.status, alice.attempts) == ("sent", 1)
    assert alice.sent_at is not None and alice.failed_at is None
    assert alice.provider_message_id and alice.provider_message_id.startswith("gmail-")
    assert alice.last_error is None


# QA-SPL-125-141 | AC11 | WB failed record
def test_qa_spl_125_141_a_failed_email_record_holds_the_last_error(app, outbox):
    outbox.always_fail = True
    start = datetime.now(SINGAPORE)
    add_notice(app)
    outbox.error = ConnectionResetError("final failure")
    for minute in (1, 2, 3):
        run_due(app, outbox, start=start, after=timedelta(minutes=minute, seconds=5))

    [email] = deliveries(app)
    assert email.status == "failed" and email.attempts == 4
    assert email.failed_at is not None and email.sent_at is None
    assert email.last_error == "ConnectionResetError: final failure"
    assert email.provider_message_id is None
    assert email.body_text and email.body_html and email.subject


# QA-SPL-125-142 | AC11 | WB Gmail message id
def test_qa_spl_125_142_the_gmail_sender_returns_the_gmail_message_id(monkeypatch):
    calls = []

    class Response:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("bad", request=None, response=None)

        def json(self):
            return self._body

    def post(url, **kwargs):
        calls.append(url)
        if url == email_delivery.GMAIL_TOKEN_URL:
            return Response(200, {"access_token": "access", "expires_in": 3600})
        assert kwargs["headers"]["Authorization"] == "Bearer access"
        return Response(200, {"id": "18c0ffee"})

    monkeypatch.setattr(httpx, "post", post)
    sender = GmailSender("id", "secret", "refresh")
    message = EmailMessage()
    message.set_content("x")

    assert sender(message) == "18c0ffee"
    assert sender(message) == "18c0ffee"
    # The access token is reused until it expires.
    assert calls.count(email_delivery.GMAIL_TOKEN_URL) == 1


# QA-SPL-125-143 | AC11 | WB a rejected token is fetched again
def test_qa_spl_125_143_a_401_from_gmail_fails_the_attempt_and_renews_the_token(monkeypatch):
    calls = []

    class Response:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "unauthorised", request=httpx.Request("POST", "x"), response=None
                )

        def json(self):
            return self._body

    def post(url, **_kwargs):
        calls.append(url)
        if url == email_delivery.GMAIL_TOKEN_URL:
            return Response(200, {"access_token": f"t{len(calls)}", "expires_in": 3600})
        return Response(401 if calls.count(url) == 1 else 200, {"id": "ok"})

    monkeypatch.setattr(httpx, "post", post)
    sender = GmailSender("id", "secret", "refresh")
    message = EmailMessage()
    message.set_content("x")

    with pytest.raises(httpx.HTTPStatusError):
        sender(message)
    assert sender(message) == "ok"
    assert calls.count(email_delivery.GMAIL_TOKEN_URL) == 2


# QA-SPL-125-144 | AC11 | WB records are never deleted
def test_qa_spl_125_144_no_application_code_deletes_an_email_record():
    for path in (BACKEND / "app").glob("*.py"):
        source = path.read_text()
        assert not re.search(r"delete\(\s*EmailDelivery", source), path.name
        assert "DELETE FROM email_deliveries" not in source.upper().replace("  ", " "), path.name
    column = EmailDelivery.__table__.c.notification_id
    [foreign_key] = column.foreign_keys
    # No cascade: deleting the notice is blocked rather than taking its email record with it.
    assert foreign_key.ondelete is None


# QA-SPL-125-145 | AC11 | WB one record per notice (field list)
def test_qa_spl_125_145_the_record_has_the_columns_ac11_lists():
    columns = set(EmailDelivery.__table__.c.keys())
    assert {
        "notification_id",
        "recipient_account_id",
        "recipient_name",
        "recipient_role",
        "to_address",
        "subject",
        "body_text",
        "body_html",
        "status",
        "attempts",
        "sent_at",
        "failed_at",
        "provider_message_id",
        "last_error",
    } <= columns
    assert EmailDelivery.__table__.c.notification_id.unique


# =============================================================================================
# Cross-cutting
# =============================================================================================


# QA-SPL-125-150 | AC1/AC7 | WB the module documents no hidden send path
def test_qa_spl_125_150_only_the_three_backends_exist():
    source = inspect.getsource(email_delivery._runtime_sender)
    assert email_delivery.RUNTIME_BACKENDS == ("smtp", "gmail_api")
    assert "log" not in email_delivery.RUNTIME_BACKENDS
    assert "RENDER" in source


# QA-SPL-125-106 | AC7 | WB setup writes the local Mailpit settings
def test_qa_spl_125_106_setup_points_local_email_at_mailpit(tmp_path):
    from scripts import dev

    written = dev.email_env(tmp_path / ".env")

    assert written.splitlines() == [
        "EMAIL_BACKEND=smtp",
        "NOTIFICATION_EMAIL_TO=connectsphere.notices@gmail.com",
        "APP_BASE_URL=http://127.0.0.1:5173",
    ]


# QA-SPL-125-107 | AC7 | WB setup keeps email settings added by hand
def test_qa_spl_125_107_rerunning_setup_keeps_existing_email_settings(tmp_path):
    from scripts import dev

    target = tmp_path / ".env"
    target.write_text(
        "DATABASE_URL=postgresql://local\nEMAIL_BACKEND=gmail_api\nGMAIL_CLIENT_ID=fixture-id\n"
        "GMAIL_CLIENT_SECRET=\nNOTIFICATION_EMAIL_TO=other@example.test\n"
    )

    written = dict(line.split("=", 1) for line in dev.email_env(target).splitlines())

    assert written["EMAIL_BACKEND"] == "gmail_api"
    assert written["GMAIL_CLIENT_ID"] == "fixture-id"
    assert written["NOTIFICATION_EMAIL_TO"] == "other@example.test"
    assert "GMAIL_CLIENT_SECRET" not in written  # a blank value is not copied
    assert "DATABASE_URL" not in written  # only email settings are carried over


# QA-SPL-125-015 | AC2 | WB regression for D1: the app loaded as backend.app (npm start)
def test_qa_spl_125_015_the_first_attempt_is_immediate_when_loaded_as_backend_app(tmp_path):
    # npm start loads backend.app:create_app, so app.email_delivery is imported a second time and
    # both copies hook the session. The email must still go out as the action commits.
    script = f"""
import importlib
from datetime import datetime
from app.models import Account, Base, EventRequest, Notification, Organisation, Role
from app.event_requests import SINGAPORE
from sqlalchemy.orm import Session
sent = []
create_app = importlib.import_module("backend.app").create_app
app = create_app({{"TESTING": True, "DATABASE_URL": "sqlite:///{tmp_path.as_posix()}/d1.db",
                  "EMAIL_SENDER": lambda message: sent.append(message["Subject"])}})
import sys
assert "backend.app.email_delivery" in sys.modules and "app.email_delivery" in sys.modules
engine = app.extensions["engine"]
Base.metadata.create_all(engine)
with Session(engine) as session:
    org = Organisation(name="Org"); session.add(org); session.flush()
    session.add(Account(id="{ALICE}", display_name="Alice Tan", organisation_id=org.id))
    event = EventRequest(organiser_account_id="{ALICE}", organisation_id=org.id, name="Gala",
        purpose="x", proposed_date=datetime(2026, 12, 1).date(),
        start_time=datetime(2026, 12, 1, 9).time(), end_time=datetime(2026, 12, 1, 11).time(),
        expected_attendance=10, status="submitted")
    session.add(event); session.flush()
    session.add(Notification(recipient_account_id="{ALICE}", recipient_role=Role.EVENT_COORDINATOR,
        event_request_id=event.id, message="m", dedupe_key="coordinator_assigned:1",
        created_at=datetime.now(SINGAPORE)))
    session.commit()
print("SENT", len(sent))
"""
    root = BACKEND.parent
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={**os.environ, "PYTHONPATH": f"{root / 'backend'}{os.pathsep}{root}"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "SENT 1" in result.stdout


def _flushed_notice(session, event_id, key):
    session.add(
        _bare_notice(
            event_id,
            recipient_role=Role.EVENT_COORDINATOR,
            dedupe_key=f"coordinator_assigned:{key}",
        )
    )
    session.flush()


# QA-SPL-125-016 | AC2 | WB review round 1: a savepoint commit does not consume the dispatch
def test_qa_spl_125_016_a_savepoint_commit_keeps_the_send_for_the_outer_commit(app, outbox):
    event_id = add_event(app)
    with Session(app.extensions["engine"]) as session:
        _flushed_notice(session, event_id, "savepoint_commit")
        session.begin_nested().commit()
        assert outbox.messages == []  # nothing is sent while the outer transaction is open
        session.commit()

    assert len(outbox.messages) == 1
    assert deliveries(app)[0].status == "sent"


# QA-SPL-125-017 | AC2 | WB review round 1: a savepoint rollback does not drop the dispatch
def test_qa_spl_125_017_a_savepoint_rollback_keeps_the_send_for_the_outer_commit(app, outbox):
    event_id = add_event(app)
    with Session(app.extensions["engine"]) as session:
        _flushed_notice(session, event_id, "savepoint_rollback")
        session.begin_nested().rollback()
        session.commit()

    assert len(outbox.messages) == 1
    assert deliveries(app)[0].status == "sent"


# QA-SPL-125-018 | AC5 | WB review round 1: a notice rolled back with its savepoint is not sent
def test_qa_spl_125_018_a_notice_inside_a_rolled_back_savepoint_sends_nothing(app, outbox):
    event_id = add_event(app)
    with Session(app.extensions["engine"]) as session:
        nested = session.begin_nested()
        _flushed_notice(session, event_id, "inside_savepoint")
        nested.rollback()
        session.commit()

    assert notices(app) == [] and deliveries(app) == [] and outbox.messages == []
