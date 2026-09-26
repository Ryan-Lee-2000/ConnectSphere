"""QA acceptance test scripts for SPL-65 (CS-E06-S2 — request clarification).

Each function is the automated evidence for one QA test case ID in the QA-SPL-65 Confluence
report (QA SPACE). The function name embeds the ID, and the docstring carries the ID, the test
category and the acceptance criterion, so a reader can jump from the report to the assertion:

    rg -n "QA-SPL-65-021" backend/tests frontend/src

Black-box cases drive only the public HTTP API. White-box cases call the code under test
(`event_review`, `event_requests.serialize_clarifications`, the models and the migration
constraint) directly. Interface cases are in frontend/src/QaSpl65.test.tsx and the PostgreSQL
cases are in test_qa_spl65_postgres.py.

Acceptance criteria (SPL-65):
  AC1 The assigned Event Coordinator can request clarification while the event is Under Review.
  AC2 A non-blank clarification message is required.
  AC3 The request records its message, author, and date and time.
  AC4 The event moves to Returned for Clarification after the request is recorded.
  AC5 The responsible Event Organiser can retrieve the message with the event request.
  AC6 Clarification history is retained if clarification is requested more than once.
  AC7 Clarification cannot be requested from a status where that action is not permitted.
"""

import time as clock
from datetime import datetime, timedelta, timezone

import pytest
from app import create_app
from app.event_requests import SINGAPORE, serialize_clarifications
from app.event_review import (
    MAX_CLARIFICATION_LENGTH,
    REQUEST_CLARIFICATION,
    TRANSITION_RULES,
    InvalidStatusTransition,
    transition_event_status,
)
from app.event_statuses import (
    EVENT_REQUEST_STATUSES,
    status_check_constraint,
    status_explanation,
    status_label,
)
from app.models import (
    Account,
    AccountRole,
    Base,
    ClarificationRequest,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Organisation,
    Role,
)
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_event_requests import event_payload

MANAGER = "00000000-0000-0000-0000-0000000065a1"
ORG_A_OWNER = "00000000-0000-0000-0000-0000000065a2"
ORG_A_COLLEAGUE = "00000000-0000-0000-0000-0000000065a3"
ORG_B_OWNER = "00000000-0000-0000-0000-0000000065a4"
ALICE = "00000000-0000-0000-0000-0000000065a5"
BOB = "00000000-0000-0000-0000-0000000065a6"
ATTENDEE = "00000000-0000-0000-0000-0000000065a7"
DEAD = "00000000-0000-0000-0000-0000000065a8"
TOKENS = {
    "manager": MANAGER,
    "owner": ORG_A_OWNER,
    "colleague": ORG_A_COLLEAGUE,
    "stranger": ORG_B_OWNER,
    "alice": ALICE,
    "bob": BOB,
    "attendee": ATTENDEE,
    "dead": DEAD,
}
MSG = "Please confirm the expected attendance and the room layout."
ALL_OTHER_STATUSES = sorted(set(EVENT_REQUEST_STATUSES) - {"under_review"})


@pytest.fixture
def world(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/qa65.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        org_a, org_b = Organisation(name="Client A"), Organisation(name="Client B")
        session.add_all([org_a, org_b])
        session.flush()
        people = (
            (MANAGER, "Morgan Manager", Role.EVENT_OPERATIONS_MANAGER, None, True),
            (ORG_A_OWNER, "Olivia Owner", Role.EVENT_ORGANISER, org_a.id, True),
            (ORG_A_COLLEAGUE, "Colin Colleague", Role.EVENT_ORGANISER, org_a.id, True),
            (ORG_B_OWNER, "Sam Stranger", Role.EVENT_ORGANISER, org_b.id, True),
            (ALICE, "Alice Tan", Role.EVENT_COORDINATOR, None, True),
            (BOB, "Bob Lim", Role.EVENT_COORDINATOR, None, True),
            (ATTENDEE, "Ada Attendee", Role.ATTENDEE, None, True),
            (DEAD, "Dee Deactivated", Role.EVENT_COORDINATOR, None, False),
        )
        for account_id, name, role, organisation_id, active in people:
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    organisation_id=organisation_id,
                    is_active=active,
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
    yield app
    engine.dispose()


@pytest.fixture
def client(world):
    return world.test_client()


def h(token="alice"):
    return {"Authorization": f"Bearer {token}"}


def submit_event(client, token="owner", **overrides) -> int:
    response = client.post("/api/event-requests", json=event_payload(**overrides), headers=h(token))
    assert response.status_code == 201, response.json
    return response.json["event_request"]["id"]


def assign(client, event_id, coordinator=ALICE):
    response = client.post(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": coordinator},
        headers=h("manager"),
    )
    assert response.status_code == 201, response.json


def begin_review(client, event_id, token="alice"):
    response = client.post(f"/api/event-requests/{event_id}/begin-review", headers=h(token))
    assert response.status_code == 200, response.json


def review_ready_event(client, **overrides) -> int:
    """A real submitted request, assigned to Alice and already Under Review."""

    event_id = submit_event(client, **overrides)
    assign(client, event_id)
    begin_review(client, event_id)
    return event_id


def ask(client, event_id, message=MSG, token="alice"):
    return client.post(
        f"/api/event-requests/{event_id}/request-clarification",
        json={"message": message},
        headers=h(token),
    )


def ask_raw(client, event_id, token="alice", **kwargs):
    return client.post(
        f"/api/event-requests/{event_id}/request-clarification", headers=h(token), **kwargs
    )


def set_status(app, event_id, status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = status
        session.commit()


def status_of(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return session.get(EventRequest, event_id).status


def rows(app, event_id):
    with Session(app.extensions["engine"]) as session:
        clarifications = session.scalars(
            select(ClarificationRequest)
            .where(ClarificationRequest.event_request_id == event_id)
            .order_by(ClarificationRequest.id)
        ).all()
        audit = session.scalars(
            select(EventStatusHistory)
            .where(
                EventStatusHistory.event_request_id == event_id,
                EventStatusHistory.action == REQUEST_CLARIFICATION,
            )
            .order_by(EventStatusHistory.id)
        ).all()
        session.expunge_all()
        return clarifications, audit


def assert_unchanged(app, event_id, status="under_review"):
    clarifications, audit = rows(app, event_id)
    assert status_of(app, event_id) == status
    assert clarifications == [] and audit == []


def organiser_view(client, event_id, token="owner"):
    return client.get(f"/api/event-requests/{event_id}", headers=h(token)).json["event_request"]


# ===========================================================================================
# AC1 — the assigned Event Coordinator can request clarification while Under Review
# ===========================================================================================


def test_qa_spl65_001_assigned_coordinator_requests_clarification_on_under_review_event(
    world, client
):
    """QA-SPL-65-001 [Happy Flow] AC1: the core success path returns 200 and moves the event."""

    event_id = review_ready_event(client)

    response = ask(client, event_id)

    assert response.status_code == 200
    assert response.is_json
    assert response.json["event"]["status"] == "returned_for_clarification"
    assert status_of(world, event_id) == "returned_for_clarification"


def test_qa_spl65_002_full_lifecycle_through_the_real_routes(world, client):
    """QA-SPL-65-002 [UAT / Visualise Flow] AC1,4,5: submit -> assign -> review -> ask -> read.

    No fixture writes the status directly: every state is reached through the API a real user
    would use, so the whole chain is exercised as one flow.
    """

    event_id = submit_event(client)
    assert organiser_view(client, event_id)["status"] == "submitted"
    assign(client, event_id)
    assert (
        client.get(f"/api/event-requests/assigned/{event_id}", headers=h()).json["event"]["status"]
        == "submitted"
    )
    begin_review(client, event_id)
    assert organiser_view(client, event_id)["status"] == "under_review"

    assert ask(client, event_id).status_code == 200

    seen = organiser_view(client, event_id)
    assert seen["status"] == "returned_for_clarification"
    assert [c["message"] for c in seen["clarifications"]] == [MSG]


def test_qa_spl65_003_unassigned_coordinator_is_refused_without_disclosure(world, client):
    """QA-SPL-65-003 [Negative] AC1: a coordinator who is not assigned gets the same 404."""

    event_id = review_ready_event(client)

    refused = ask(client, event_id, token="bob")
    absent = ask(client, 987654, token="bob")

    assert refused.status_code == 404
    assert (refused.json, absent.status_code) == (absent.json, 404)
    assert_unchanged(world, event_id)


@pytest.mark.parametrize("token", ["manager", "owner", "colleague", "stranger", "attendee"])
def test_qa_spl65_004_every_non_coordinator_role_is_refused(world, client, token):
    """QA-SPL-65-004 [Negative] AC1: manager, organisers and attendee are all forbidden."""

    event_id = review_ready_event(client)

    assert ask(client, event_id, token=token).status_code == 403
    assert_unchanged(world, event_id)


def test_qa_spl65_005_request_without_credentials_is_refused(world, client):
    """QA-SPL-65-005 [Negative] AC1: no bearer token means 401 and nothing is recorded."""

    event_id = review_ready_event(client)

    response = client.post(
        f"/api/event-requests/{event_id}/request-clarification", json={"message": MSG}
    )

    assert response.status_code == 401
    assert_unchanged(world, event_id)


def test_qa_spl65_006_reassignment_moves_the_right_to_ask(world, client):
    """QA-SPL-65-006 [Cross-cut] AC1: only the currently assigned coordinator may ask."""

    event_id = review_ready_event(client)
    reassigned = client.put(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": BOB},
        headers=h("manager"),
    )
    assert reassigned.status_code == 200

    assert ask(client, event_id, token="alice").status_code == 404
    assert_unchanged(world, event_id)
    assert ask(client, event_id, token="bob").status_code == 200


def test_qa_spl65_007_deactivated_coordinator_is_refused(world, client):
    """QA-SPL-65-007 [Negative] AC1: an inactive account holds no roles, even if assigned."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        session.execute(
            EventCoordinatorAssignment.__table__.update()
            .where(EventCoordinatorAssignment.event_request_id == event_id)
            .values(coordinator_account_id=DEAD)
        )
        session.commit()

    assert ask(client, event_id, token="dead").status_code == 403
    assert_unchanged(world, event_id)


@pytest.mark.parametrize("event_id", [0, 999999, 2**31, 2**40])
def test_qa_spl65_008_nonexistent_event_ids_answer_404(world, client, event_id):
    """QA-SPL-65-008 [Boundary] AC1: absent and out-of-range ids are a plain 404."""

    assert ask(client, event_id).status_code == 404


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_qa_spl65_009_only_post_is_supported_on_the_action(world, client, method):
    """QA-SPL-65-009 [Negative / API] AC1,6: the action cannot be read, edited or deleted."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    response = getattr(client, method)(
        f"/api/event-requests/{event_id}/request-clarification", headers=h()
    )

    # The app's default-deny authorisation answers 403 for a method no route declares; a plain
    # router would answer 405. Either way the action is refused and the history is untouched.
    assert response.status_code in (403, 405)
    assert len(rows(world, event_id)[0]) == 1
    assert status_of(world, event_id) == "returned_for_clarification"


# ===========================================================================================
# AC2 — a non-blank clarification message is required
# ===========================================================================================


@pytest.mark.parametrize("blank", ["", " ", "     ", "\t", "\n", " \t\r\n ", " ", " "])
def test_qa_spl65_010_blank_and_whitespace_only_messages_are_refused(world, client, blank):
    """QA-SPL-65-010 [Negative] AC2: nothing visible means nothing is sent."""

    event_id = review_ready_event(client)

    response = ask(client, event_id, blank)

    assert response.status_code == 400
    assert "message" in response.json["error"].lower()
    assert_unchanged(world, event_id)


def test_qa_spl65_011_missing_message_key_is_refused(world, client):
    """QA-SPL-65-011 [Negative] AC2: an empty object is not a message."""

    event_id = review_ready_event(client)

    assert ask_raw(client, event_id, json={}).status_code == 400
    assert_unchanged(world, event_id)


@pytest.mark.parametrize("value", [None, 0, 123, 1.5, True, ["a"], {"a": "b"}])
def test_qa_spl65_012_non_string_messages_are_refused(world, client, value):
    """QA-SPL-65-012 [Negative] AC2: only text can be a message."""

    event_id = review_ready_event(client)

    assert ask(client, event_id, value).status_code == 400
    assert_unchanged(world, event_id)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"data": "message=hello", "content_type": "application/x-www-form-urlencoded"},
        {"data": "{not json", "content_type": "application/json"},
        {"json": ["message"]},
        {"json": "message"},
        {"json": None},
    ],
    ids=["no-body", "form-encoded", "malformed-json", "json-array", "json-string", "json-null"],
)
def test_qa_spl65_013_malformed_request_bodies_are_refused(world, client, kwargs):
    """QA-SPL-65-013 [Negative / API] AC2: only a JSON object with a message is accepted."""

    event_id = review_ready_event(client)

    assert ask_raw(client, event_id, **kwargs).status_code == 400
    assert_unchanged(world, event_id)


def test_qa_spl65_014_shortest_message_is_accepted(world, client):
    """QA-SPL-65-014 [Boundary] AC2: a single character is the lower boundary."""

    event_id = review_ready_event(client)

    assert ask(client, event_id, "?").status_code == 200
    assert rows(world, event_id)[0][0].message == "?"


def test_qa_spl65_015_message_of_exactly_the_maximum_length_is_accepted(world, client):
    """QA-SPL-65-015 [Boundary] AC2: 2000 characters is the upper boundary."""

    event_id = review_ready_event(client)

    assert ask(client, event_id, "x" * MAX_CLARIFICATION_LENGTH).status_code == 200
    assert len(rows(world, event_id)[0][0].message) == 2000


def test_qa_spl65_016_message_one_over_the_maximum_is_refused(world, client):
    """QA-SPL-65-016 [Boundary] AC2: 2001 characters is refused with an explanation."""

    event_id = review_ready_event(client)

    response = ask(client, event_id, "x" * (MAX_CLARIFICATION_LENGTH + 1))

    assert response.status_code == 400
    assert "2000" in response.json["error"]
    assert_unchanged(world, event_id)


def test_qa_spl65_017_length_limit_applies_after_trimming(world, client):
    """QA-SPL-65-017 [Boundary] AC2: padding does not count towards the 2000 characters."""

    event_id = review_ready_event(client)

    response = ask(client, event_id, "   " + "y" * 2000 + "\n\n")

    assert response.status_code == 200
    assert rows(world, event_id)[0][0].message == "y" * 2000


def test_qa_spl65_018_outer_whitespace_is_trimmed_and_inner_layout_is_kept(world, client):
    """QA-SPL-65-018 [Functional] AC2,3: only the ends are trimmed."""

    event_id = review_ready_event(client)

    assert ask(client, event_id, "  Line one\n\n  line   two\t\n").status_code == 200

    assert rows(world, event_id)[0][0].message == "Line one\n\n  line   two"


def test_qa_spl65_019_unicode_and_multiline_text_round_trip_unchanged(world, client):
    """QA-SPL-65-019 [Cross-cut] AC2,3,5: accents, CJK, emoji and newlines survive intact."""

    event_id = review_ready_event(client)
    message = "Café ☕ 会议室 — 3 rooms?\nLayout: théâtre 🎭"

    assert ask(client, event_id, message).status_code == 200

    assert organiser_view(client, event_id)["clarifications"][0]["message"] == message


@pytest.mark.parametrize(
    "message",
    [
        "<script>alert('x')</script>",
        "'; DROP TABLE event_requests; --",
        '"} , "status": "approved',
        "{{7*7}} ${7*7}",
    ],
)
def test_qa_spl65_020_hostile_text_is_stored_as_plain_data(world, client, message):
    """QA-SPL-65-020 [Cross-cut / Security] AC2: markup and SQL are data, never executed."""

    event_id = review_ready_event(client)

    response = ask(client, event_id, message)

    assert response.status_code == 200
    assert response.json["clarifications"][0]["message"] == message
    assert status_of(world, event_id) == "returned_for_clarification"
    assert client.get(f"/api/event-requests/{event_id}", headers=h("owner")).status_code == 200


# ===========================================================================================
# AC3 — the request records its message, author, and date and time
# ===========================================================================================


def test_qa_spl65_021_record_holds_message_author_and_timestamp(world, client):
    """QA-SPL-65-021 [Functional] AC3: all three facts are stored and returned."""

    event_id = review_ready_event(client)
    before = datetime.now(SINGAPORE) - timedelta(seconds=2)

    response = ask(client, event_id)
    after = datetime.now(SINGAPORE) + timedelta(seconds=2)

    [item] = response.json["clarifications"]
    assert item["message"] == MSG
    assert item["author"] == {"id": ALICE, "name": "Alice Tan"}
    stamp = datetime.fromisoformat(item["created_at"])
    assert before <= stamp <= after
    [stored], _ = rows(world, event_id)
    assert (stored.message, stored.author_account_id) == (MSG, ALICE)
    assert stored.created_at is not None


def test_qa_spl65_022_timestamp_is_reported_in_singapore_time(world, client):
    """QA-SPL-65-022 [Cross-cut] AC3: the offset is explicit, so no viewer has to guess."""

    event_id = review_ready_event(client)

    stamp = ask(client, event_id).json["clarifications"][0]["created_at"]

    assert stamp.endswith("+08:00")
    assert datetime.fromisoformat(stamp).utcoffset() == timedelta(hours=8)


def test_qa_spl65_023_one_moment_is_shared_by_record_audit_and_status(world, client):
    """QA-SPL-65-023 [White-box] AC3,4: the three writes use a single transaction timestamp."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    with Session(world.extensions["engine"]) as session:
        clarification = session.scalars(select(ClarificationRequest)).one()
        audit = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.action == REQUEST_CLARIFICATION)
        ).one()
        changed = session.get(EventRequest, event_id).status_changed_at
        assert clarification.created_at == audit.changed_at == changed


@pytest.mark.parametrize(
    "extra",
    [
        {"author": "someone-else"},
        {"author_account_id": BOB},
        {"created_at": "2001-01-01T00:00:00+08:00"},
        {"id": 1},
        {"event_request_id": 999},
    ],
)
def test_qa_spl65_024_client_cannot_choose_author_time_or_ids(world, client, extra):
    """QA-SPL-65-024 [Negative / Security] AC3: server-owned fields cannot be supplied."""

    event_id = review_ready_event(client)

    response = ask_raw(client, event_id, json={"message": MSG, **extra})

    assert response.status_code == 400
    assert_unchanged(world, event_id)


def test_qa_spl65_025_each_clarification_keeps_its_own_author(world, client):
    """QA-SPL-65-025 [Functional] AC3,6: after reassignment the new author is recorded."""

    event_id = review_ready_event(client)
    assert ask(client, event_id, "From Alice").status_code == 200
    set_status(world, event_id, "under_review")
    client.put(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": BOB},
        headers=h("manager"),
    )

    assert ask(client, event_id, "From Bob", token="bob").status_code == 200

    history = organiser_view(client, event_id)["clarifications"]
    assert [(c["message"], c["author"]["name"]) for c in history] == [
        ("From Bob", "Bob Lim"),
        ("From Alice", "Alice Tan"),
    ]


def test_qa_spl65_026_timestamps_never_go_backwards(world, client):
    """QA-SPL-65-026 [Boundary] AC3,6: successive records are ordered in time."""

    event_id = review_ready_event(client)
    for index in range(3):
        assert ask(client, event_id, f"Round {index}").status_code == 200
        set_status(world, event_id, "under_review")

    stamps = [c.created_at for c in rows(world, event_id)[0]]

    assert stamps == sorted(stamps)


# ===========================================================================================
# AC4 — the event moves to Returned for Clarification
# ===========================================================================================


def test_qa_spl65_027_status_label_and_change_time_are_updated(world, client):
    """QA-SPL-65-027 [Functional] AC4: stored value, plain-language label and change time."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        started = session.get(EventRequest, event_id).status_changed_at

    response = ask(client, event_id)

    assert response.json["event"]["status"] == "returned_for_clarification"
    assert response.json["event"]["status_label"] == "Returned for clarification"
    with Session(world.extensions["engine"]) as session:
        moved = session.get(EventRequest, event_id).status_changed_at
    assert moved is not None and moved >= started


def test_qa_spl65_028_nothing_else_about_the_event_changes(world, client):
    """QA-SPL-65-028 [Functional] AC4: content and coordinator assignment are preserved."""

    event_id = review_ready_event(client)
    before = organiser_view(client, event_id)

    assert ask(client, event_id).status_code == 200

    after = organiser_view(client, event_id)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {
        "status",
        "status_label",
        "status_explanation",
        "status_changed_at",
        "clarifications",
    }
    assert after["coordinator"] == before["coordinator"] == {"id": ALICE, "name": "Alice Tan"}


def test_qa_spl65_029_other_events_are_not_touched(world, client):
    """QA-SPL-65-029 [Cross-cut] AC4: the action is scoped to one event."""

    target = review_ready_event(client, name="Target")
    bystander = review_ready_event(client, name="Bystander")

    assert ask(client, target).status_code == 200

    assert status_of(world, bystander) == "under_review"
    assert rows(world, bystander) == ([], [])
    assert len(rows(world, target)[0]) == 1


def test_qa_spl65_030_assigned_list_and_detail_show_the_new_status(world, client):
    """QA-SPL-65-030 [Functional] AC4: the coordinator sees where the event now stands."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    listed = client.get("/api/event-requests/assigned", headers=h()).json["events"]
    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=h()).json["event"]

    assert [e["status_label"] for e in listed] == ["Returned for clarification"]
    assert detail["status"] == "returned_for_clarification"


def test_qa_spl65_031_one_complete_audit_record_is_written(world, client):
    """QA-SPL-65-031 [Functional] AC4: action, before, after, actor and time are all recorded."""

    event_id = review_ready_event(client)
    response = ask(client, event_id)

    [audit] = rows(world, event_id)[1]

    assert (audit.action, audit.previous_status, audit.resulting_status) == (
        "request_clarification",
        "under_review",
        "returned_for_clarification",
    )
    assert audit.actor_account_id == ALICE and audit.changed_at is not None
    assert response.json["transition"]["actor"] == {"id": ALICE, "name": "Alice Tan"}


def test_qa_spl65_032_a_failed_write_leaves_the_status_unchanged(world, client, monkeypatch):
    """QA-SPL-65-032 [White-box] AC4,7: status, audit and message commit together or not at all."""

    event_id = review_ready_event(client)

    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated failure while storing the clarification")

    monkeypatch.setattr("app.event_review.ClarificationRequest", explode)

    with pytest.raises(RuntimeError):
        ask(client, event_id)

    monkeypatch.undo()
    assert_unchanged(world, event_id)


def test_qa_spl65_033_review_history_shows_both_transitions_in_order(world, client):
    """QA-SPL-65-033 [Functional] AC4: begin-review then clarification are both audited."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    with Session(world.extensions["engine"]) as session:
        trail = [
            (a.action, a.previous_status, a.resulting_status)
            for a in session.scalars(
                select(EventStatusHistory)
                .where(EventStatusHistory.event_request_id == event_id)
                .order_by(EventStatusHistory.id)
            )
        ]
    assert trail == [
        ("begin_review", "submitted", "under_review"),
        ("request_clarification", "under_review", "returned_for_clarification"),
    ]


def test_qa_spl65_034_begin_review_is_unaffected_and_refuses_a_returned_event(world, client):
    """QA-SPL-65-034 [Regression] AC4,7: SPL-70 behaviour is unchanged by the new status."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    again = client.post(f"/api/event-requests/{event_id}/begin-review", headers=h())

    assert again.status_code == 409
    assert status_of(world, event_id) == "returned_for_clarification"
    fresh = submit_event(client, name="Fresh")
    assign(client, fresh)
    begin_review(client, fresh)
    assert status_of(world, fresh) == "under_review"


# ===========================================================================================
# AC5 — the responsible Event Organiser can retrieve the message with the event request
# ===========================================================================================


def test_qa_spl65_035_responsible_organiser_retrieves_the_message(world, client):
    """QA-SPL-65-035 [Happy Flow] AC5: the request itself carries the message."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    seen = organiser_view(client, event_id)

    assert seen["status"] == "returned_for_clarification"
    assert seen["status_label"] == "Returned for clarification"
    assert [c["message"] for c in seen["clarifications"]] == [MSG]
    assert seen["clarifications"][0]["author"]["name"] == "Alice Tan"


def test_qa_spl65_036_same_client_colleague_can_read_it_read_only(world, client):
    """QA-SPL-65-036 [Functional] AC5: same-client organisers may view (release rule)."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    seen = client.get(f"/api/organisation/events/{event_id}", headers=h("colleague"))

    assert seen.status_code == 200
    assert seen.json["event"]["status_label"] == "Returned for clarification"
    assert [c["message"] for c in seen.json["event"]["clarifications"]] == [MSG]


def test_qa_spl65_037_another_client_cannot_see_the_event_or_message(world, client):
    """QA-SPL-65-037 [Negative / Security] AC5: unrelated clients get a non-disclosing 404."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    own_route = client.get(f"/api/event-requests/{event_id}", headers=h("stranger"))
    org_route = client.get(f"/api/organisation/events/{event_id}", headers=h("stranger"))

    assert own_route.status_code == 404 and org_route.status_code == 404
    assert MSG not in own_route.get_data(as_text=True) + org_route.get_data(as_text=True)


def test_qa_spl65_038_organiser_list_shows_the_returned_status_and_guidance(world, client):
    """QA-SPL-65-038 [Functional] AC5: the list tells the organiser what to do next."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    [listed] = client.get("/api/event-requests", headers=h("owner")).json["event_requests"]

    assert listed["id"] == event_id
    assert listed["status_label"] == "Returned for clarification"
    assert "update your request" in listed["status_explanation"].lower()


def test_qa_spl65_039_assigned_coordinator_reads_the_history_but_others_cannot(world, client):
    """QA-SPL-65-039 [Functional] AC5,6: coordinator detail carries it; strangers get 404."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    mine = client.get(f"/api/event-requests/assigned/{event_id}", headers=h("alice"))
    theirs = client.get(f"/api/event-requests/assigned/{event_id}", headers=h("bob"))

    assert [c["message"] for c in mine.json["event"]["clarifications"]] == [MSG]
    assert theirs.status_code == 404


def test_qa_spl65_040_clarification_shape_exposes_only_the_intended_fields(world, client):
    """QA-SPL-65-040 [Cross-cut / API] AC5: no internal ids, emails or roles leak."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200

    [item] = organiser_view(client, event_id)["clarifications"]

    assert set(item) == {"id", "message", "author", "created_at"}
    assert set(item["author"]) == {"id", "name"}


@pytest.mark.parametrize("via", ["own", "organisation", "assigned"])
def test_qa_spl65_041_an_event_without_clarifications_returns_an_empty_list(world, client, via):
    """QA-SPL-65-041 [Boundary] AC5,6: zero history is an empty list, never null or missing."""

    event_id = review_ready_event(client)
    url, token = {
        "own": (f"/api/event-requests/{event_id}", "owner"),
        "organisation": (f"/api/organisation/events/{event_id}", "owner"),
        "assigned": (f"/api/event-requests/assigned/{event_id}", "alice"),
    }[via]

    body = client.get(url, headers=h(token)).json
    payload = body.get("event_request") or body["event"]

    assert payload["clarifications"] == []


# ===========================================================================================
# AC6 — clarification history is retained when requested more than once
# ===========================================================================================


def test_qa_spl65_042_second_request_keeps_the_first_newest_first(world, client):
    """QA-SPL-65-042 [Happy Flow] AC6: two requests, two records, latest on top."""

    event_id = review_ready_event(client)
    assert ask(client, event_id, "First question").status_code == 200
    set_status(world, event_id, "under_review")
    assert ask(client, event_id, "Second question").status_code == 200

    history = organiser_view(client, event_id)["clarifications"]

    assert [c["message"] for c in history] == ["Second question", "First question"]
    assert len(rows(world, event_id)[1]) == 2


def test_qa_spl65_043_five_rounds_are_all_retained_in_order(world, client):
    """QA-SPL-65-043 [Boundary] AC6: repeated use stays consistent."""

    event_id = review_ready_event(client)
    for number in range(1, 6):
        assert ask(client, event_id, f"Question {number}").status_code == 200
        set_status(world, event_id, "under_review")

    history = organiser_view(client, event_id)["clarifications"]

    assert [c["message"] for c in history] == [f"Question {n}" for n in range(5, 0, -1)]
    assert len(rows(world, event_id)[1]) == 5


def test_qa_spl65_044_earlier_records_are_never_altered(world, client):
    """QA-SPL-65-044 [Functional] AC6: id, text, author and time of record one stay fixed."""

    event_id = review_ready_event(client)
    assert ask(client, event_id, "First question").status_code == 200
    first = rows(world, event_id)[0][0]
    snapshot = (first.id, first.message, first.author_account_id, first.created_at)
    set_status(world, event_id, "under_review")

    assert ask(client, event_id, "Second question").status_code == 200

    again = rows(world, event_id)[0][0]
    assert (again.id, again.message, again.author_account_id, again.created_at) == snapshot


def test_qa_spl65_045_identical_timestamps_still_sort_newest_first(world, client):
    """QA-SPL-65-045 [White-box] AC6: the id breaks a tie when created_at is equal."""

    event_id = review_ready_event(client)
    moment = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)
    with Session(world.extensions["engine"]) as session:
        for message in ("older", "newer"):
            session.add(
                ClarificationRequest(
                    event_request_id=event_id,
                    message=message,
                    author_account_id=ALICE,
                    created_at=moment,
                )
            )
        session.commit()

    history = organiser_view(client, event_id)["clarifications"]

    assert [c["message"] for c in history] == ["newer", "older"]


def test_qa_spl65_046_deleting_an_event_removes_its_clarifications(world, client):
    """QA-SPL-65-046 [White-box] AC6: no orphan rows are left behind."""

    event_id = review_ready_event(client)
    assert ask(client, event_id).status_code == 200
    with Session(world.extensions["engine"]) as session:
        session.delete(session.get(EventRequest, event_id))
        session.commit()
        assert session.scalars(select(ClarificationRequest)).all() == []


# ===========================================================================================
# AC7 — clarification cannot be requested where the action is not permitted
# ===========================================================================================


@pytest.mark.parametrize("status", ALL_OTHER_STATUSES)
def test_qa_spl65_047_every_status_other_than_under_review_is_refused(world, client, status):
    """QA-SPL-65-047 [Negative] AC7: the full status vocabulary is walked, one at a time."""

    event_id = review_ready_event(client)
    set_status(world, event_id, status)

    response = ask(client, event_id)

    assert response.status_code == 409
    assert "under review" in response.json["error"]
    assert_unchanged(world, event_id, status)


def test_qa_spl65_048_a_repeated_request_is_refused_and_recorded_once(world, client):
    """QA-SPL-65-048 [Negative] AC7: a double click cannot create a second record."""

    event_id = review_ready_event(client)
    assert ask(client, event_id, "Once").status_code == 200

    assert ask(client, event_id, "Twice").status_code == 409

    assert [c.message for c in rows(world, event_id)[0]] == ["Once"]
    assert len(rows(world, event_id)[1]) == 1


def test_qa_spl65_049_a_submitted_event_must_begin_review_first(world, client):
    """QA-SPL-65-049 [Negative] AC7: assignment alone does not allow clarification."""

    event_id = submit_event(client)
    assign(client, event_id)

    assert ask(client, event_id).status_code == 409
    assert_unchanged(world, event_id, "submitted")


def test_qa_spl65_050_refusal_bodies_are_json_with_an_error_message(world, client):
    """QA-SPL-65-050 [API] AC2,7: 400, 403, 404 and 409 all explain themselves in JSON."""

    event_id = review_ready_event(client)
    set_status(world, event_id, "approved")
    responses = [
        ask(client, event_id, ""),
        ask(client, event_id, token="manager"),
        ask(client, event_id, token="bob"),
        ask(client, event_id),
    ]

    assert [r.status_code for r in responses] == [400, 403, 404, 409]
    for response in responses:
        assert response.is_json and response.json["error"]


# ===========================================================================================
# White-box: the code paths themselves
# ===========================================================================================


def test_qa_spl65_051_transition_rule_allows_only_under_review_to_returned(world):
    """QA-SPL-65-051 [White-box] AC4,7: the server-owned rule table is exactly as specified."""

    rule = TRANSITION_RULES[REQUEST_CLARIFICATION]

    assert (rule.previous_status, rule.resulting_status) == (
        "under_review",
        "returned_for_clarification",
    )
    assert set(TRANSITION_RULES) == {"begin_review", "request_clarification"}
    assert TRANSITION_RULES["begin_review"].resulting_status == "under_review"


def test_qa_spl65_052_transition_service_refuses_a_stale_state_without_an_audit_row(world, client):
    """QA-SPL-65-052 [White-box] AC7: the conditional UPDATE is what enforces the rule."""

    event_id = review_ready_event(client)
    set_status(world, event_id, "approved")

    with Session(world.extensions["engine"]) as session:
        with pytest.raises(InvalidStatusTransition):
            transition_event_status(
                session,
                event_request_id=event_id,
                action=REQUEST_CLARIFICATION,
                actor_account_id=ALICE,
                changed_at=datetime.now(SINGAPORE),
            )
        session.rollback()
    assert rows(world, event_id)[1] == []
    assert status_of(world, event_id) == "approved"


def test_qa_spl65_053_transition_service_applies_the_rule_and_returns_evidence(world, client):
    """QA-SPL-65-053 [White-box] AC4: called directly, it moves the row and returns the audit."""

    event_id = review_ready_event(client)
    moment = datetime(2026, 9, 27, 10, 30, tzinfo=SINGAPORE)

    with Session(world.extensions["engine"]) as session:
        audit = transition_event_status(
            session,
            event_request_id=event_id,
            action=REQUEST_CLARIFICATION,
            actor_account_id=ALICE,
            changed_at=moment,
        )
        session.commit()
        assert audit.resulting_status == "returned_for_clarification"
        assert session.get(EventRequest, event_id).status == "returned_for_clarification"


def test_qa_spl65_054_unknown_action_is_a_programming_error_not_a_silent_success(world, client):
    """QA-SPL-65-054 [White-box] AC7: an unregistered action name cannot change anything."""

    event_id = review_ready_event(client)

    with Session(world.extensions["engine"]) as session:
        with pytest.raises(KeyError):
            transition_event_status(
                session,
                event_request_id=event_id,
                action="approve_everything",
                actor_account_id=ALICE,
                changed_at=datetime.now(SINGAPORE),
            )
    assert status_of(world, event_id) == "under_review"


def test_qa_spl65_055_new_status_has_wording_and_a_check_constraint_entry(world):
    """QA-SPL-65-055 [White-box] AC4: vocabulary, wording and DB constraint agree."""

    assert status_label("returned_for_clarification") == "Returned for clarification"
    explanation = status_explanation("returned_for_clarification")
    assert "\n" not in explanation and "_" not in explanation and explanation.strip()
    assert "'returned_for_clarification'" in status_check_constraint()
    assert len(EVENT_REQUEST_STATUSES) == 12


def test_qa_spl65_056_database_accepts_the_new_status_and_rejects_an_unknown_one(world, client):
    """QA-SPL-65-056 [White-box] AC4,7: the check constraint is the last line of defence."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "returned_for_clarification"
        session.commit()
        session.get(EventRequest, event_id).status = "returned"
        with pytest.raises(IntegrityError):
            session.commit()


def test_qa_spl65_057_message_validator_is_exercised_directly(world):
    """QA-SPL-65-057 [White-box] AC2: every branch of the request-body validator."""

    from app.event_review import _clarification_message
    from werkzeug.exceptions import BadRequest

    def run(**kwargs):
        with world.test_request_context("/x", method="POST", **kwargs):
            return _clarification_message()

    assert run(json={"message": "  hi  "}) == "hi"
    assert run(json={"message": "é" * 2000}) == "é" * 2000
    for bad in (
        {"json": {"message": ""}},
        {"json": {"message": "a", "x": 1}},
        {"json": {"msg": "a"}},
        {"json": [1]},
        {"data": "nope", "content_type": "text/plain"},
        {"json": {"message": "z" * 2001}},
    ):
        with pytest.raises(BadRequest):
            run(**bad)


def test_qa_spl65_058_serialiser_reads_every_offset_as_singapore_time(world, client):
    """QA-SPL-65-058 [White-box] AC3,5: naive, UTC and Singapore times all read as +08:00."""

    from types import SimpleNamespace

    def row(number, stamp):
        author = SimpleNamespace(id="a", display_name="Alice Tan")
        return SimpleNamespace(id=number, message=f"m{number}", author=author, created_at=stamp)

    event = SimpleNamespace(
        clarification_requests=[
            row(1, datetime(2026, 9, 27, 9, 0)),  # SQLite: no offset, already Singapore time
            row(2, datetime(2026, 9, 27, 1, 0, tzinfo=timezone.utc)),  # PostgreSQL: UTC
            row(3, datetime(2026, 9, 27, 9, 0, tzinfo=SINGAPORE)),
        ]
    )

    stamps = [item["created_at"] for item in serialize_clarifications(event)]

    assert stamps == ["2026-09-27T09:00:00+08:00"] * 3
    assert serialize_clarifications(SimpleNamespace(clarification_requests=[])) == []


# ===========================================================================================
# Performance, load and API
# ===========================================================================================


def _count_statements(engine, action):
    seen = []

    def record(_conn, _cursor, statement, *_args):
        seen.append(statement)

    sa_event.listen(engine, "before_cursor_execute", record)
    try:
        action()
    finally:
        sa_event.remove(engine, "before_cursor_execute", record)
    return len(seen)


def _add_history(world, event_id, count):
    with Session(world.extensions["engine"]) as session:
        base = datetime(2026, 9, 1, 9, 0, tzinfo=SINGAPORE)
        session.add_all(
            ClarificationRequest(
                event_request_id=event_id,
                message=f"Question {n}",
                author_account_id=ALICE if n % 2 else BOB,
                created_at=base + timedelta(minutes=n),
            )
            for n in range(count)
        )
        session.commit()


@pytest.mark.parametrize("path", ["own", "organisation", "assigned"])
def test_qa_spl65_059_reading_history_costs_the_same_queries_however_long_it_is(
    world, client, path
):
    """QA-SPL-65-059 [Performance / White-box] AC5,6: no N+1 when loading authors."""

    event_id = review_ready_event(client)
    url, token = {
        "own": (f"/api/event-requests/{event_id}", "owner"),
        "organisation": (f"/api/organisation/events/{event_id}", "owner"),
        "assigned": (f"/api/event-requests/assigned/{event_id}", "alice"),
    }[path]
    # Two authors from the start, so both lookups see the same set of accounts (an author who is
    # also the coordinator is served from the session's identity map and would skew the count).
    _add_history(world, event_id, 2)
    engine = world.extensions["engine"]
    client.get(url, headers=h(token))  # warm-up: the first request pays one-off start-up queries
    one = _count_statements(engine, lambda: client.get(url, headers=h(token)))
    _add_history(world, event_id, 60)

    many = _count_statements(engine, lambda: client.get(url, headers=h(token)))

    assert many == one


def test_qa_spl65_060_a_long_history_is_returned_quickly_and_completely(world, client):
    """QA-SPL-65-060 [Performance] AC6: 300 records come back in one fast, ordered response."""

    event_id = review_ready_event(client)
    _add_history(world, event_id, 300)

    started = clock.perf_counter()
    response = client.get(f"/api/event-requests/{event_id}", headers=h("owner"))
    elapsed = clock.perf_counter() - started

    history = response.json["event_request"]["clarifications"]
    assert len(history) == 300
    assert history[0]["message"] == "Question 299" and history[-1]["message"] == "Question 0"
    assert elapsed < 2.0


def test_qa_spl65_061_thirty_events_can_each_be_returned_in_sequence(world, client):
    """QA-SPL-65-061 [Load] AC1,4: repeated use records exactly one clarification per event."""

    ids = [review_ready_event(client, name=f"Event {n}") for n in range(30)]

    started = clock.perf_counter()
    codes = [ask(client, event_id, f"Question for {event_id}").status_code for event_id in ids]
    elapsed = clock.perf_counter() - started

    assert set(codes) == {200}
    assert elapsed < 15.0
    with Session(world.extensions["engine"]) as session:
        assert len(session.scalars(select(ClarificationRequest)).all()) == 30
        assert {e.status for e in session.scalars(select(EventRequest))} == {
            "returned_for_clarification"
        }


def test_qa_spl65_062_success_response_contract(world, client):
    """QA-SPL-65-062 [API] AC1,3,4: the 200 body has exactly the documented top-level keys."""

    event_id = review_ready_event(client)

    response = ask(client, event_id)

    assert response.content_type.startswith("application/json")
    assert set(response.json) == {"event", "transition", "clarifications"}
    assert set(response.json["event"]) == {
        "id",
        "name",
        "status",
        "status_label",
        "proposed_date",
    }
    assert set(response.json["transition"]) == {
        "action",
        "previous_status",
        "resulting_status",
        "actor",
        "changed_at",
    }
