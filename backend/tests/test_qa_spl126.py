"""QA coverage for SPL-126, Choose which notification types I receive.

Case IDs (QA-SPL-126-NNN) match the QA-SPL-126 Confluence page. BB = black-box (HTTP API and the
email that leaves the app), WB = white-box (stored rows, the session hook, the type map).

Every case runs with a recording sender injected through EMAIL_SENDER, so no email is sent. The
PostgreSQL cases (migration backfill, concurrency, constraints) are in test_qa_spl126_postgres.py;
the screen is covered in frontend/src/NotificationSettings.test.tsx.
"""

import ast
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
from app import create_app, email_delivery, models, notification_settings
from app.event_requests import SINGAPORE
from app.models import (
    NOTIFICATION_TYPE_BY_KIND,
    NOTIFICATION_TYPE_ROLES,
    Account,
    AccountRole,
    Base,
    EmailDelivery,
    EventRequest,
    Notification,
    NotificationEmailOptOut,
    NotificationType,
    Organisation,
    Role,
    notification_type_for,
)
from app.notifications import add_change_request_submitted_notice, add_technical_support_notices
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_coordinator_assignment import (
    ALICE,
    BOB,
    INACTIVE_COORDINATOR,
    MANAGER,
    MANAGER_AND_ORGANISER,
    ORGANISER,
    VENUE_STAFF,
    add_request,
    assign,
    headers,
    reassign,
)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations/versions/s4_notification_types.py"
URL = "/api/notification-settings"
TECH_A = "00000000-0000-0000-0000-000000000126"
TECH_B = "00000000-0000-0000-0000-000000000127"
SAFETY = "00000000-0000-0000-0000-000000000128"
ATTENDEE = "00000000-0000-0000-0000-000000000129"
COORDINATOR_ATTENDEE = "00000000-0000-0000-0000-000000000130"
TOKENS = {
    "manager": MANAGER,
    "organiser": ORGANISER,
    "coordinator": ALICE,
    "coordinator-b": BOB,
    "inactive": INACTIVE_COORDINATOR,
    "venue-staff": VENUE_STAFF,
    "manager-and-organiser": MANAGER_AND_ORGANISER,
    "tech-a": TECH_A,
    "tech-b": TECH_B,
    "safety": SAFETY,
    "attendee": ATTENDEE,
    "coordinator-attendee": COORDINATOR_ATTENDEE,
}
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
    (TECH_A, "Tara Tech", True, [Role.TECHNICAL_SUPPORT_STAFF]),
    (TECH_B, "Theo Tech", True, [Role.TECHNICAL_SUPPORT_STAFF]),
    (SAFETY, "Sam Safety", True, [Role.SAFETY_OFFICER]),
    (ATTENDEE, "Ada Attendee", True, [Role.ATTENDEE]),
    (COORDINATOR_ATTENDEE, "Cleo Both", True, [Role.EVENT_COORDINATOR, Role.ATTENDEE]),
]
COORDINATOR_TYPES = [
    "coordinator_assignment",
    "coordinator_requests",
    "coordinator_arrangements",
    "coordinator_hold_deadlines",
    "coordinator_safety",
]
ORGANISER_TYPES = ["organiser_review", "organiser_coordinator", "organiser_confirmation"]
ATTENDEE_TYPES = ["attendee_registration", "attendee_event_changes"]


class Outbox:
    def __init__(self):
        self.messages = []
        self.fail_next = 0

    def __call__(self, message):
        if self.fail_next:
            self.fail_next -= 1
            raise ConnectionRefusedError("mail server unreachable")
        self.messages.append(message)
        return f"gmail-{len(self.messages)}"


@pytest.fixture
def outbox():
    return Outbox()


@pytest.fixture
def app(tmp_path, outbox):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/spl126.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
            "EMAIL_SENDER": outbox,
            "NOTIFICATION_EMAIL_TO": "shared.inbox@connectsphere.test",
            "APP_BASE_URL": "https://app.connectsphere.test",
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


def settings(client, token):
    response = client.get(URL, headers=headers(token))
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["types"]


def emails_on(client, token):
    return {item["type"]: item["email"] for item in settings(client, token)}


def change(client, token, kind, body):
    return client.put(f"{URL}/{kind}", headers=headers(token), json=body)


def turn_off(client, token, kind):
    response = change(client, token, kind, {"email": False})
    assert response.status_code == 200, response.get_data(as_text=True)


def rows(app, model, *where):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(select(model).where(*where)).all()


def opt_outs(app):
    with Session(app.extensions["engine"]) as session:
        return set(
            session.execute(
                select(
                    NotificationEmailOptOut.account_id, NotificationEmailOptOut.notification_type
                )
            ).tuples()
        )


def notice_for(app, recipient, kind_prefix):
    [notice] = rows(
        app,
        Notification,
        Notification.recipient_account_id == recipient,
        Notification.dedupe_key.startswith(f"{kind_prefix}:"),
    )
    return notice


def emailed(app, notice):
    return bool(rows(app, EmailDelivery, EmailDelivery.notification_id == notice.id))


def subjects(outbox):
    return [message["Subject"] for message in outbox.messages]


def add_raw_notice(app, dedupe_key, recipient=ALICE, event_id=None, **extra):
    event_id = event_id or add_request(app, f"Raw {dedupe_key}")
    with Session(app.extensions["engine"]) as session:
        notice = Notification(
            recipient_account_id=recipient,
            recipient_role=extra.pop("role", Role.EVENT_COORDINATOR),
            event_request_id=event_id,
            message="Something changed.",
            dedupe_key=dedupe_key,
            created_at=datetime.now(SINGAPORE),
            **extra,
        )
        session.add(notice)
        session.commit()
        return notice.id


def _load_migration():
    spec = importlib.util.spec_from_file_location("s4_notification_types", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =============================================================================================
# AC1  Every notification records its type from one fixed list
# =============================================================================================


# QA-SPL-126-001 | AC1 | WB fixed list
def test_qa_spl_126_001_the_type_list_is_fixed_and_every_type_has_a_role_and_label():
    assert [kind.value for kind in NotificationType] == [
        *COORDINATOR_TYPES,
        *ORGANISER_TYPES,
        "technical_equipment",
        "venue_booking_requests",
        *ATTENDEE_TYPES,
    ]
    assert set(NOTIFICATION_TYPE_ROLES) == set(NotificationType)
    assert set(notification_settings.TYPE_LABELS) == set(NotificationType)
    for label, description in notification_settings.TYPE_LABELS.values():
        assert label.strip() and description.strip()
    # Every type is reachable: some notice kind maps to it.
    assert set(NOTIFICATION_TYPE_BY_KIND.values()) == set(NotificationType)


# QA-SPL-126-002 | AC1 | WB model and migration agree
def test_qa_spl_126_002_the_migration_backfills_with_the_same_map_the_app_uses():
    migration = _load_migration()
    assert migration.TYPE_BY_KIND == {
        kind: t.value for kind, t in NOTIFICATION_TYPE_BY_KIND.items()
    }
    for kind in NotificationType:
        assert f"'{kind.value}'" in migration.KNOWN_TYPE
    assert migration.down_revision == "s4_replacement_bookings"


# QA-SPL-126-003 | AC1 | WB every notice kind written on main has a type, and no type is dead
def test_qa_spl_126_003_the_kinds_in_the_source_are_exactly_the_mapped_kinds():
    """Rebuilds every dedupe-key kind from the backend source and compares it with the map."""

    prefixes = {
        "add_organiser_notice": "organiser_",
        "add_review_outcome_notice": "organiser_",
        "add_arrangement_notice": "arrangement_",
        "add_technical_support_notices": "technical_",
        "add_attendee_notices": "attendee_",
        "add_venue_booking_notices": "venue_booking_",
    }
    found = set()
    for path in sorted((BACKEND / "app").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in prefixes:
                    for keyword in node.keywords:
                        if keyword.arg == "kind":
                            found |= {prefixes[name] + c for c in _constants(keyword.value)}
                if name == "_notify_technical_support" and len(node.args) >= 3:
                    found |= {"technical_" + c for c in _constants(node.args[2])}
                if name == "notify" and len(node.args) >= 3:
                    found |= _constants(node.args[2])
            if isinstance(node, ast.keyword) and node.arg == "dedupe_key":
                head = node.value.values[0] if isinstance(node.value, ast.JoinedStr) else None
                if isinstance(head, ast.Constant) and ":" in head.value:
                    found.add(head.value.split(":", 1)[0])
        if path.name == "notifications.py":
            # add_registration_notice picks its kind in the function body.
            function = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "add_registration_notice"
            )
            found |= {
                "attendee_" + c
                for n in ast.walk(function)
                if isinstance(n, ast.Assign)
                for c in _constants(n.value)
                if c in ("registered", "withdrawn")
            }
        if path.name == "equipment_requirements.py":
            # _notify_technical_support also receives its kind through a variable.
            function = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_notify_technical_support"
            )
            action = next(n for n in ast.walk(function) if isinstance(n, ast.Dict))
            found |= {"technical_" + c for k in action.keys for c in _constants(k)}

    assert found == set(NOTIFICATION_TYPE_BY_KIND), (
        sorted(found - set(NOTIFICATION_TYPE_BY_KIND)),
        sorted(set(NOTIFICATION_TYPE_BY_KIND) - found),
    )


def _constants(node):
    return {
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


# QA-SPL-126-004 | AC1 | WB every kind stores its type
@pytest.mark.parametrize("kind", sorted(NOTIFICATION_TYPE_BY_KIND))
def test_qa_spl_126_004_each_kind_is_saved_with_its_type(app, kind):
    notice_id = add_raw_notice(app, f"{kind}:1")
    [notice] = rows(app, Notification, Notification.id == notice_id)
    assert notice.notification_type == NOTIFICATION_TYPE_BY_KIND[kind].value


# QA-SPL-126-005 | AC1 | BB happy path (real assignment)
def test_qa_spl_126_005_a_real_action_records_each_notice_type(app, client):
    event_id = add_request(app)
    assert assign(client, event_id).status_code == 201
    assert notice_for(app, ALICE, "coordinator_assigned").notification_type == (
        "coordinator_assignment"
    )
    assert notice_for(app, ORGANISER, "organiser_coordinator_changed").notification_type == (
        "organiser_coordinator"
    )
    assert reassign(client, event_id).status_code == 200
    assert notice_for(app, ALICE, "coordinator_removed").notification_type == (
        "coordinator_assignment"
    )
    with Session(app.extensions["engine"]) as session:
        assert (
            session.scalar(select(func.count()).where(Notification.notification_type.is_(None)))
            == 0
        )


# QA-SPL-126-006 | AC1 | WB negative (a kind with no type is refused with its action)
def test_qa_spl_126_006_a_notice_kind_with_no_type_cannot_be_saved(app, outbox):
    event_id = add_request(app)
    with Session(app.extensions["engine"]) as session:
        session.add(
            Notification(
                recipient_account_id=ALICE,
                recipient_role=Role.EVENT_COORDINATOR,
                event_request_id=event_id,
                message="A future trigger.",
                dedupe_key="spl999_future_kind:1",
                created_at=datetime.now(SINGAPORE),
            )
        )
        with pytest.raises(ValueError, match="spl999_future_kind"):
            session.commit()
    assert rows(app, Notification) == []
    assert rows(app, EmailDelivery) == []
    assert outbox.messages == []


# QA-SPL-126-007 | AC1 | WB negative (the whole action rolls back, not only the notice)
def test_qa_spl_126_007_an_action_writing_an_unmapped_kind_is_refused_whole(
    app, client, monkeypatch
):
    from app import notifications

    original = notifications.add_coordinator_assigned_notice

    def untyped(session, event, coordinator_id, history_id):
        original(session, event, coordinator_id, history_id)
        [notice] = [obj for obj in session.new if isinstance(obj, Notification)]
        notice.dedupe_key = f"untyped_kind:{history_id}"

    monkeypatch.setattr("app.coordinator_assignment.add_coordinator_assigned_notice", untyped)
    client.application.config["PROPAGATE_EXCEPTIONS"] = False
    event_id = add_request(app)
    response = assign(client, event_id)

    assert response.status_code == 500
    assert rows(app, Notification) == []
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(text("SELECT count(*) FROM event_coordinator_assignments")) == 0


# QA-SPL-126-008 | AC1 | WB boundary (exact kind, not a prefix or a near match)
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("coordinator_assigned", "coordinator_assignment"),
        ("coordinator_assigned:1:extra", "coordinator_assignment"),
        ("arrangement_hold_expired:9", "coordinator_hold_deadlines"),
        ("arrangement_booking_flagged:9", "coordinator_arrangements"),
        ("coordinator_assignedx:1", None),
        ("Coordinator_assigned:1", None),
        ("organiser_:1", None),
        ("arrangement_hold:1", None),
        (":1", None),
        ("", None),
    ],
)
def test_qa_spl_126_008_the_type_comes_from_the_exact_kind(key, expected):
    if expected is None:
        with pytest.raises(ValueError):
            notification_type_for(key)
    else:
        assert notification_type_for(key).value == expected


# QA-SPL-126-009 | AC1 | WB a caller cannot store a wrong type
def test_qa_spl_126_009_the_stored_type_always_follows_the_kind(app):
    notice_id = add_raw_notice(
        app, "coordinator_assigned:1", notification_type="attendee_registration"
    )
    [notice] = rows(app, Notification, Notification.id == notice_id)
    assert notice.notification_type == "coordinator_assignment"


# QA-SPL-126-010 | AC1 | WB the database refuses an unknown type
def test_qa_spl_126_010_the_database_refuses_a_type_outside_the_list(app):
    notice_id = add_raw_notice(app, "coordinator_assigned:1")
    with pytest.raises(IntegrityError), app.extensions["engine"].begin() as connection:
        connection.execute(
            text("UPDATE notifications SET notification_type = 'marketing' WHERE id = :id"),
            {"id": notice_id},
        )
    with pytest.raises(IntegrityError), app.extensions["engine"].begin() as connection:
        connection.execute(
            text("UPDATE notifications SET notification_type = NULL WHERE id = :id"),
            {"id": notice_id},
        )


# =============================================================================================
# AC2  The settings list each notification type with an email on/off toggle
# =============================================================================================


# QA-SPL-126-011 | AC2 | BB happy path
def test_qa_spl_126_011_a_coordinator_sees_each_of_their_types_with_its_toggle(client):
    items = settings(client, "coordinator")
    assert [item["type"] for item in items] == COORDINATOR_TYPES
    for item in items:
        assert set(item) == {"type", "label", "description", "role", "role_label", "email"}
        assert item["role"] == "event_coordinator"
        assert item["role_label"] == "Event Coordinator"
        assert item["email"] is True
        assert item["label"] and item["description"]
    labels = {item["type"]: item["label"] for item in items}
    assert labels["coordinator_hold_deadlines"] == "Venue hold deadlines"


# QA-SPL-126-012 | AC2 | BB every role's list
@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("organiser", ORGANISER_TYPES),
        ("tech-a", ["technical_equipment"]),
        ("venue-staff", ["venue_booking_requests"]),
        ("attendee", ATTENDEE_TYPES),
        ("coordinator-attendee", [*COORDINATOR_TYPES, *ATTENDEE_TYPES]),
        ("manager-and-organiser", ORGANISER_TYPES),
        ("safety", []),
        ("manager", []),
    ],
)
def test_qa_spl_126_012_each_role_lists_exactly_its_own_types(client, token, expected):
    assert [item["type"] for item in settings(client, token)] == expected


# QA-SPL-126-013 | AC2 | BB the toggle round-trips
def test_qa_spl_126_013_a_toggle_change_is_returned_and_listed(client):
    response = change(client, "coordinator", "coordinator_safety", {"email": False})
    assert response.status_code == 200
    assert response.get_json() == {
        "type": "coordinator_safety",
        "label": "Safety decisions",
        "description": notification_settings.TYPE_LABELS[NotificationType.COORDINATOR_SAFETY][1],
        "role": "event_coordinator",
        "role_label": "Event Coordinator",
        "email": False,
    }
    assert emails_on(client, "coordinator")["coordinator_safety"] is False
    assert sum(not on for on in emails_on(client, "coordinator").values()) == 1


# QA-SPL-126-014 | AC2 | WB every type is listed for some role
def test_qa_spl_126_014_every_type_is_listed_for_an_account_holding_its_role(app, client):
    with Session(app.extensions["engine"]) as session:
        session.add_all(
            AccountRole(account_id=SAFETY, role=role.value)
            for role in Role
            if role != Role.SAFETY_OFFICER
        )
        session.commit()
    assert [item["type"] for item in settings(client, "safety")] == [
        kind.value for kind in NotificationType
    ]


# QA-SPL-126-015 | AC2 | WB the list reads once (no query per type)
def test_qa_spl_126_015_listing_costs_the_same_queries_with_or_without_choices(app, client):
    def count_selects():
        selects = []

        def listen(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        engine = app.extensions["engine"]
        event.listen(engine, "before_cursor_execute", listen)
        try:
            settings(client, "coordinator-attendee")
        finally:
            event.remove(engine, "before_cursor_execute", listen)
        return len(selects)

    before = count_selects()
    for kind in [*COORDINATOR_TYPES, *ATTENDEE_TYPES]:
        turn_off(client, "coordinator-attendee", kind)
    assert count_selects() == before


# =============================================================================================
# AC3  All toggles default to on
# =============================================================================================


# QA-SPL-126-020 | AC3 | BB happy path (a new account)
@pytest.mark.parametrize("token", ["coordinator", "organiser", "tech-a", "venue-staff", "attendee"])
def test_qa_spl_126_020_a_new_account_has_every_type_on(client, token):
    assert all(item["email"] for item in settings(client, token))


# QA-SPL-126-021 | AC3 | WB reading the defaults writes nothing
def test_qa_spl_126_021_defaults_need_no_stored_rows(app, client):
    for token in TOKENS:
        if token != "inactive":
            settings(client, token)
    assert opt_outs(app) == set()


# QA-SPL-126-022 | AC3 | BB an account that never opened the screen gets every email
def test_qa_spl_126_022_without_any_choice_every_notice_is_emailed(app, client, outbox):
    event_id = add_request(app)
    assign(client, event_id)
    reassign(client, event_id)
    notices = rows(app, Notification)
    assert len(notices) == 5
    assert all(emailed(app, notice) for notice in notices)
    assert len(outbox.messages) == 5


# QA-SPL-126-023 | AC3 | BB boundary (back on returns to the default)
def test_qa_spl_126_023_turning_a_type_back_on_restores_the_default(app, client):
    turn_off(client, "coordinator", "coordinator_assignment")
    assert opt_outs(app) == {(ALICE, "coordinator_assignment")}
    assert (
        change(client, "coordinator", "coordinator_assignment", {"email": True}).status_code == 200
    )
    assert opt_outs(app) == set()
    assert all(emails_on(client, "coordinator").values())


# QA-SPL-126-024 | AC3 | WB a role added later starts with its types on
def test_qa_spl_126_024_a_role_added_later_starts_with_every_type_on(app, client):
    turn_off(client, "attendee", "attendee_registration")
    with Session(app.extensions["engine"]) as session:
        session.add(AccountRole(account_id=ATTENDEE, role=Role.VENUE_STAFF.value))
        session.commit()
    assert emails_on(client, "attendee") == {
        "venue_booking_requests": True,
        "attendee_registration": False,
        "attendee_event_changes": True,
    }


# QA-SPL-126-025 | AC3 | WB a choice survives losing and regaining the role
def test_qa_spl_126_025_a_choice_is_kept_while_its_role_is_removed(app, client):
    turn_off(client, "coordinator-attendee", "coordinator_requests")
    with Session(app.extensions["engine"]) as session:
        session.execute(
            delete(AccountRole).where(
                AccountRole.account_id == COORDINATOR_ATTENDEE,
                AccountRole.role == Role.EVENT_COORDINATOR.value,
            )
        )
        session.commit()
    assert [item["type"] for item in settings(client, "coordinator-attendee")] == ATTENDEE_TYPES
    with Session(app.extensions["engine"]) as session:
        session.add(AccountRole(account_id=COORDINATOR_ATTENDEE, role=Role.EVENT_COORDINATOR.value))
        session.commit()
    assert emails_on(client, "coordinator-attendee")["coordinator_requests"] is False


# =============================================================================================
# AC4  Turning a type off stops emails of that type only; in-app cannot be disabled
# =============================================================================================


# QA-SPL-126-030 | AC4 | BB happy path
def test_qa_spl_126_030_a_type_turned_off_gets_no_email_but_keeps_its_notice(app, client, outbox):
    turn_off(client, "coordinator", "coordinator_assignment")
    event_id = add_request(app)
    assert assign(client, event_id).status_code == 201

    mine = notice_for(app, ALICE, "coordinator_assigned")
    assert not emailed(app, mine)
    assert emailed(app, notice_for(app, ORGANISER, "organiser_coordinator_changed"))
    assert subjects(outbox) == [
        "[ConnectSphere] For Olivia Organiser (Event Organiser): Harbour Summit"
    ]
    inbox = client.get("/api/notifications", headers=headers("coordinator")).get_json()
    assert [n["message"] for n in inbox["notifications"]] == [
        "You have been assigned to Harbour Summit."
    ]
    assert inbox["unread_count"] == 1


# QA-SPL-126-031 | AC4 | BB only that type: the account's other types still email
def test_qa_spl_126_031_the_accounts_other_types_still_email(app, client, outbox):
    turn_off(client, "coordinator", "coordinator_assignment")
    event_id = add_request(app)
    assign(client, event_id)
    with Session(app.extensions["engine"]) as session:
        add_change_request_submitted_notice(
            session, session.get(EventRequest, event_id), change_request_id=1, field_labels=["Date"]
        )
        session.commit()
    request_notice = notice_for(app, ALICE, "change_request_submitted")
    assert request_notice.notification_type == "coordinator_requests"
    assert emailed(app, request_notice)
    assert not emailed(app, notice_for(app, ALICE, "coordinator_assigned"))


# QA-SPL-126-032 | AC4 | BB only that account: another account's same type still emails
def test_qa_spl_126_032_the_same_type_still_emails_other_accounts(app, client, outbox):
    turn_off(client, "coordinator", "coordinator_assignment")
    event_id = add_request(app)
    assign(client, event_id)
    reassign(client, event_id)  # Alice removed (muted), Bob assigned (not muted)

    assert not emailed(app, notice_for(app, ALICE, "coordinator_removed"))
    assert emailed(app, notice_for(app, BOB, "coordinator_assigned"))
    assert len(rows(app, Notification)) == 5
    assert len(rows(app, EmailDelivery)) == 3
    assert not [s for s in subjects(outbox) if "Alice Tan" in s]


# QA-SPL-126-033 | AC4 | WB boundary (one flush, several recipients of one type)
def test_qa_spl_126_033_one_action_emails_only_the_recipients_who_kept_it_on(app, client, outbox):
    turn_off(client, "tech-b", "technical_equipment")
    event_id = add_request(app)
    with Session(app.extensions["engine"]) as session:
        add_technical_support_notices(
            session,
            session.get(EventRequest, event_id),
            kind="event_cancelled",
            source_id=1,
            message="Cancelled.",
        )
        session.commit()
    notices = {n.recipient_account_id: n for n in rows(app, Notification)}
    assert set(notices) == {TECH_A, TECH_B}
    assert emailed(app, notices[TECH_A]) and not emailed(app, notices[TECH_B])
    assert len(outbox.messages) == 1


# QA-SPL-126-034 | AC4 | BB negative (in-app cannot be disabled)
@pytest.mark.parametrize(
    "body",
    [{"in_app": False}, {"email": False, "in_app": False}, {"channel": "in_app", "email": False}],
)
def test_qa_spl_126_034_there_is_no_way_to_turn_in_app_notices_off(app, client, body):
    response = change(client, "coordinator", "coordinator_assignment", body)
    assert response.status_code == 400
    assert opt_outs(app) == set()
    assert all("in_app" not in item for item in settings(client, "coordinator"))


# QA-SPL-126-035 | AC4 | BB every type off: every notice still arrives in-app
def test_qa_spl_126_035_with_every_type_off_the_inbox_still_fills(app, client, outbox):
    for kind in COORDINATOR_TYPES:
        turn_off(client, "coordinator", kind)
    for kind in ORGANISER_TYPES:
        turn_off(client, "organiser", kind)
    event_id = add_request(app)
    assign(client, event_id)
    for token in ("coordinator", "organiser"):
        inbox = client.get("/api/notifications", headers=headers(token)).get_json()
        assert len(inbox["notifications"]) == 1
    assert rows(app, EmailDelivery) == []
    assert outbox.messages == []


# QA-SPL-126-036 | AC4 | WB a choice changes only later emails
def test_qa_spl_126_036_an_email_already_queued_is_still_sent_after_turning_off(
    app, client, outbox
):
    outbox.fail_next = 2  # both first attempts fail, so both emails wait for a retry
    event_id = add_request(app)
    assign(client, event_id)
    assert {d.status for d in rows(app, EmailDelivery)} == {"pending"}
    turn_off(client, "coordinator", "coordinator_assignment")

    later = datetime.now(SINGAPORE) + email_delivery.RETRY_DELAY * 2
    assert email_delivery.process_due_emails(app.extensions["engine"], outbox, now=later) == 2
    assert {d.status for d in rows(app, EmailDelivery)} == {"sent"}


# =============================================================================================
# AC5  Every role; only the signed-in user can read or change their own settings
# =============================================================================================


# QA-SPL-126-040 | AC5 | BB security (sign-in required)
@pytest.mark.parametrize(
    ("method", "path"),
    [("get", URL), ("put", f"{URL}/coordinator_assignment")],
)
def test_qa_spl_126_040_settings_need_a_signed_in_account(client, method, path):
    response = getattr(client, method)(path, json={"email": False})
    assert response.status_code == 401


# QA-SPL-126-041 | AC5 | BB every role's account can read and change its own settings
@pytest.mark.parametrize(
    ("token", "kind"),
    [
        ("organiser", "organiser_review"),
        ("coordinator", "coordinator_requests"),
        ("venue-staff", "venue_booking_requests"),
        ("tech-a", "technical_equipment"),
        ("attendee", "attendee_event_changes"),
        ("safety", None),
        ("manager", None),
    ],
)
def test_qa_spl_126_041_every_role_reaches_its_own_settings(app, client, token, kind):
    assert client.get(URL, headers=headers(token)).status_code == 200
    if kind:
        turn_off(client, token, kind)
        assert opt_outs(app) == {(TOKENS[token], kind)}


# QA-SPL-126-042 | AC5 | BB security (another user cannot read them)
def test_qa_spl_126_042_one_accounts_choice_is_invisible_to_another(app, client):
    turn_off(client, "coordinator", "coordinator_safety")
    assert all(emails_on(client, "coordinator-b").values())
    assert all(emails_on(client, "coordinator-attendee").values())
    assert emails_on(client, "coordinator")["coordinator_safety"] is False


# QA-SPL-126-043 | AC5 | BB security (another user cannot change them)
@pytest.mark.parametrize(
    ("query", "body"),
    [
        (f"?account_id={ALICE}", {"email": False}),
        ("", {"email": False, "account_id": ALICE}),
        ("", {"email": False, "recipient_account_id": ALICE}),
        (f"?user_id={ALICE}&role=event_coordinator", {"email": False}),
    ],
)
def test_qa_spl_126_043_a_submitted_account_id_never_selects_whose_settings_change(
    app, client, query, body
):
    response = client.put(
        f"{URL}/coordinator_safety{query}", headers=headers("coordinator-b"), json=body
    )
    assert response.status_code in (200, 400)
    assert (ALICE, "coordinator_safety") not in opt_outs(app)
    assert all(emails_on(client, "coordinator").values())
    if response.status_code == 200:
        assert opt_outs(app) == {(BOB, "coordinator_safety")}


# QA-SPL-126-044 | AC5 | BB security (a type for a role not held is refused like an unknown one)
@pytest.mark.parametrize(
    ("token", "kind"),
    [
        ("organiser", "coordinator_assignment"),
        ("coordinator", "attendee_registration"),
        ("safety", "coordinator_safety"),
        ("manager", "organiser_review"),
        ("coordinator", "not_a_type"),
        ("coordinator", "COORDINATOR_ASSIGNMENT"),
        ("coordinator", "coordinator_assignment%20"),
        ("coordinator", "x" * 500),
    ],
)
def test_qa_spl_126_044_a_type_outside_the_accounts_roles_is_not_found(app, client, token, kind):
    response = change(client, token, kind, {"email": False})
    assert response.status_code == 404
    assert response.get_json() == {"error": "Notification type not found."}
    assert opt_outs(app) == set()


# QA-SPL-126-045 | AC5 | BB security (an inactive account holds no roles)
def test_qa_spl_126_045_an_inactive_account_is_refused(client):
    assert client.get(URL, headers=headers("inactive")).status_code == 403
    assert change(client, "inactive", "coordinator_assignment", {"email": False}).status_code == 403


# QA-SPL-126-046 | AC5 | BB negative (malformed requests)
@pytest.mark.parametrize(
    "body",
    [None, [], "false", {"email": "false"}, {"email": 0}, {"email": None}, {}, {"Email": False}],
)
def test_qa_spl_126_046_a_malformed_change_is_refused_and_stores_nothing(app, client, body):
    if body is None:
        response = client.put(
            f"{URL}/coordinator_assignment", headers=headers("coordinator"), data="not json"
        )
    else:
        response = change(client, "coordinator", "coordinator_assignment", body)
    assert response.status_code == 400
    assert opt_outs(app) == set()


# QA-SPL-126-047 | AC5 | BB negative (no other methods)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", URL),
        ("delete", URL),
        ("post", f"{URL}/coordinator_assignment"),
        ("delete", f"{URL}/coordinator_assignment"),
        ("get", f"{URL}/coordinator_assignment"),
        ("patch", f"{URL}/coordinator_assignment"),
    ],
)
def test_qa_spl_126_047_only_read_and_change_are_offered(app, client, method, path):
    response = getattr(client, method)(path, headers=headers("coordinator"), json={"email": False})
    # The app's default-deny policy refuses an unrouted method before routing reports 405.
    assert response.status_code in (403, 405)
    assert opt_outs(app) == set()


# QA-SPL-126-048 | AC5 | WB access after a state change (role removed)
def test_qa_spl_126_048_losing_a_role_stops_changes_to_its_types(app, client):
    with Session(app.extensions["engine"]) as session:
        session.execute(
            delete(AccountRole).where(
                AccountRole.account_id == COORDINATOR_ATTENDEE,
                AccountRole.role == Role.EVENT_COORDINATOR.value,
            )
        )
        session.commit()
    response = change(client, "coordinator-attendee", "coordinator_assignment", {"email": False})
    assert response.status_code == 404
    turn_off(client, "coordinator-attendee", "attendee_registration")


# QA-SPL-126-049 | AC5 | BB repeats and duplicates
def test_qa_spl_126_049_repeating_a_change_is_harmless(app, client):
    for _ in range(3):
        turn_off(client, "coordinator", "coordinator_assignment")
    assert opt_outs(app) == {(ALICE, "coordinator_assignment")}
    for _ in range(3):
        assert change(client, "coordinator", "coordinator_assignment", {"email": True}).get_json()[
            "email"
        ]
    assert opt_outs(app) == set()


# QA-SPL-126-050 | AC5 | WB a concurrent duplicate insert answers as success
def test_qa_spl_126_050_a_racing_duplicate_turn_off_still_succeeds(app, client, monkeypatch):
    """Simulates the other request committing first: the existence check misses its row."""

    with Session(app.extensions["engine"]) as session:
        session.add(
            NotificationEmailOptOut(
                account_id=ALICE,
                notification_type="coordinator_assignment",
                created_at=datetime.now(SINGAPORE),
            )
        )
        session.commit()
    monkeypatch.setattr(Session, "get", lambda self, *args, **kwargs: None)

    response = change(client, "coordinator", "coordinator_assignment", {"email": False})
    assert response.status_code == 200
    assert response.get_json()["email"] is False
    assert opt_outs(app) == {(ALICE, "coordinator_assignment")}


# QA-SPL-126-051 | AC5 | WB deleting an account removes its settings
def test_qa_spl_126_051_settings_belong_to_the_account(app, client):
    turn_off(client, "attendee", "attendee_registration")
    # SQLite enforces foreign keys only when asked, before the transaction starts.
    with app.extensions["engine"].connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        connection.execute(delete(AccountRole).where(AccountRole.account_id == ATTENDEE))
        connection.execute(delete(Account).where(Account.id == ATTENDEE))
        connection.commit()
    assert opt_outs(app) == set()


# =============================================================================================
# AC6  SPL-125 checks these settings before sending an email
# =============================================================================================


# QA-SPL-126-060 | AC6 | WB the check is made before the email exists
def test_qa_spl_126_060_a_muted_notice_never_gets_an_email_record(app, client, outbox):
    turn_off(client, "coordinator", "coordinator_assignment")
    event_id = add_request(app)
    seen = []

    @event.listens_for(Session, "after_flush")
    def capture(session, _context):
        seen.extend(
            obj.recipient_account_id for obj in session.new if isinstance(obj, EmailDelivery)
        )

    try:
        assign(client, event_id)
    finally:
        event.remove(Session, "after_flush", capture)
    assert seen == [ORGANISER]
    assert [d.recipient_account_id for d in rows(app, EmailDelivery)] == [ORGANISER]


# QA-SPL-126-061 | AC6 | WB one settings read per flush, however many notices
def test_qa_spl_126_061_the_check_reads_settings_once_per_save(app):
    event_id = add_request(app)
    reads = []

    def listen(_conn, _cursor, statement, *_args):
        if "notification_email_opt_outs" in statement:
            reads.append(statement)

    engine = app.extensions["engine"]
    event.listen(engine, "before_cursor_execute", listen)
    try:
        with Session(engine) as session:
            session.add_all(
                Notification(
                    recipient_account_id=[ALICE, BOB, ORGANISER][i % 3],
                    recipient_role=Role.EVENT_COORDINATOR,
                    event_request_id=event_id,
                    message=f"Change {i}",
                    dedupe_key=f"coordinator_assigned:{i}",
                    created_at=datetime.now(SINGAPORE),
                )
                for i in range(60)
            )
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", listen)
    assert len(reads) == 1
    assert len(rows(app, EmailDelivery)) == 60


# QA-SPL-126-062 | AC6 | WB the check is per recipient and type, not per type or per recipient
def test_qa_spl_126_062_the_check_matches_recipient_and_type_together(app, client):
    turn_off(client, "coordinator", "coordinator_requests")
    turn_off(client, "coordinator-b", "coordinator_assignment")
    event_id = add_request(app)
    ids = {
        (ALICE, "coordinator_assigned:1"): True,
        (ALICE, "change_request_submitted:1"): False,
        (BOB, "coordinator_assigned:1"): False,
        (BOB, "change_request_submitted:1"): True,
    }
    for (recipient, key), _ in ids.items():
        add_raw_notice(app, key, recipient=recipient, event_id=event_id)
    for (recipient, key), expected in ids.items():
        [notice] = rows(
            app,
            Notification,
            Notification.recipient_account_id == recipient,
            Notification.dedupe_key == key,
        )
        assert emailed(app, notice) is expected, (recipient, key)


# QA-SPL-126-063 | AC6 | WB a save where every notice is muted starts no delivery
def test_qa_spl_126_063_an_all_muted_save_does_not_wake_delivery(app, client):
    turn_off(client, "coordinator", "coordinator_assignment")
    event_id = add_request(app)
    with Session(app.extensions["engine"]) as session:
        session.add(
            Notification(
                recipient_account_id=ALICE,
                recipient_role=Role.EVENT_COORDINATOR,
                event_request_id=event_id,
                message="Muted.",
                dedupe_key="coordinator_assigned:1",
                created_at=datetime.now(SINGAPORE),
            )
        )
        session.flush()
        assert "spl125_email_dispatch" not in session.info
        session.add(
            Notification(
                recipient_account_id=BOB,
                recipient_role=Role.EVENT_COORDINATOR,
                event_request_id=event_id,
                message="Not muted.",
                dedupe_key="coordinator_assigned:2",
                created_at=datetime.now(SINGAPORE),
            )
        )
        session.flush()
        assert "spl125_email_dispatch" in session.info
        session.commit()
    assert [d.recipient_account_id for d in rows(app, EmailDelivery)] == [BOB]


# QA-SPL-126-064 | AC6 | BB turning a type back on resumes its email from the next notice
def test_qa_spl_126_064_email_resumes_after_turning_back_on(app, client, outbox):
    turn_off(client, "coordinator", "coordinator_assignment")
    first = add_request(app, "First Event")
    assign(client, first)
    change(client, "coordinator", "coordinator_assignment", {"email": True})
    second = add_request(app, "Second Event")
    assign(client, second)
    alice = [s for s in subjects(outbox) if "Alice Tan" in s]
    assert alice == ["[ConnectSphere] For Alice Tan (Event Coordinator): Second Event"]


# QA-SPL-126-065 | AC6 | WB a rolled-back save with a muted recipient leaves nothing behind
def test_qa_spl_126_065_a_rolled_back_action_leaves_no_notice_email_or_dispatch(app, client):
    turn_off(client, "coordinator", "coordinator_assignment")
    event_id = add_request(app)
    with Session(app.extensions["engine"]) as session:
        for recipient in (ALICE, BOB):
            session.add(
                Notification(
                    recipient_account_id=recipient,
                    recipient_role=Role.EVENT_COORDINATOR,
                    event_request_id=event_id,
                    message="x",
                    dedupe_key="coordinator_assigned:1",
                    created_at=datetime.now(SINGAPORE),
                )
            )
        session.flush()
        assert "spl125_email_dispatch" in session.info  # Bob's email was queued
        session.rollback()
        assert "spl125_email_dispatch" not in session.info
    assert rows(app, Notification) == [] and rows(app, EmailDelivery) == []


# QA-SPL-126-066 | AC1, AC2 | WB a type added without a role or a label stops the app loading
@pytest.mark.parametrize(
    ("module", "mapping", "message"),
    [
        ("models", "NOTIFICATION_TYPE_ROLES", "Notification types without a role"),
        ("notification_settings", "TYPE_LABELS", "Notification types without a label"),
    ],
)
def test_qa_spl_126_066_an_incomplete_type_list_refuses_to_load(module, mapping, message):
    path = BACKEND / "app" / f"{module}.py"
    tree = ast.parse(path.read_text())
    [guard] = [
        node for node in tree.body if isinstance(node, ast.If) and mapping in ast.unparse(node.test)
    ]
    source = getattr(models if module == "models" else notification_settings, mapping)
    namespace = {
        "NotificationType": NotificationType,
        mapping: {k: v for k, v in source.items() if k != NotificationType.COORDINATOR_SAFETY},
    }
    with pytest.raises(RuntimeError, match=message):
        exec(compile(ast.Module([guard], type_ignores=[]), str(path), "exec"), namespace)
