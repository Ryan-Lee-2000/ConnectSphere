"""QA acceptance test scripts for SPL-68 (CS-E06-S5 - reject an event request).

Each function is the automated evidence for one QA test case ID in the QA-SPL-68 Confluence
report (QA SPACE). The function name embeds the ID and the docstring carries the ID, the test
category and the acceptance criteria, so a reader can jump from the report to the assertion:

    rg -n "QA-SPL-68-021" backend/tests frontend/src

Black-box cases drive only the public HTTP API with real submitted requests. White-box cases call
the code under test (`event_review`, `event_requests.serialize_rejection`, the models and the
migration chain) directly. Interface cases are in frontend/src/QaSpl68.test.tsx and the
PostgreSQL cases are in test_qa_spl68_postgres.py.

Acceptance criteria (SPL-68):
  AC1 Only the assigned Event Coordinator can reject a request that is Under Review.
  AC2 A non-blank rejection reason is required.
  AC3 Rejection records the reason, decision-maker, and date and time and changes the event to
      Rejected.
  AC4 The responsible Event Organiser can retrieve the rejection outcome and reason.
  AC5 A rejected request cannot undergo further review or planning; proceeding requires a new
      event request.
  AC6 An invalid or unauthorised rejection attempt leaves the event unchanged.
"""

import time as clock
from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app import create_app
from app.event_requests import SINGAPORE, serialize_rejection
from app.event_review import (
    APPROVE,
    BEGIN_REVIEW,
    REJECT,
    REJECTED,
    REQUEST_CLARIFICATION,
    TRANSITION_RULES,
    UNDER_REVIEW,
    InvalidStatusTransition,
    _rejection_reason,
    transition_event_status,
)
from app.event_statuses import EVENT_REQUEST_STATUSES, status_explanation, status_label
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Organisation,
    Role,
    VenueBooking,
)
from sqlalchemy import event as sa_event
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_event_requests import event_payload
from werkzeug.exceptions import BadRequest

MANAGER = "00000000-0000-0000-0000-0000000068a1"
ORG_A_OWNER = "00000000-0000-0000-0000-0000000068a2"
ORG_A_COLLEAGUE = "00000000-0000-0000-0000-0000000068a3"
ORG_B_OWNER = "00000000-0000-0000-0000-0000000068a4"
ALICE = "00000000-0000-0000-0000-0000000068a5"
BOB = "00000000-0000-0000-0000-0000000068a6"
ATTENDEE = "00000000-0000-0000-0000-0000000068a7"
DEAD = "00000000-0000-0000-0000-0000000068a8"
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
REASON = "The requested venue plan is not workable."
SUCCESS_MESSAGE = "Request rejected. The Event Organiser can see your reason."
WRONG_STATUS = "Only an event under review can be rejected."
NOT_ASSIGNED = "Assigned event not found."
BLANK_REASON = "Enter a reason for rejecting the request."
ONLY_REASON = "Send only a rejection reason."
OTHER_STATUSES = sorted(set(EVENT_REQUEST_STATUSES) - {UNDER_REVIEW})
REJECTION_COLUMNS = {
    "status",
    "status_changed_at",
    "rejected_by_account_id",
    "rejected_at",
    "rejection_reason",
}


@pytest.fixture
def world(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/qa68.db",
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


def reassign(client, event_id, coordinator):
    response = client.put(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": coordinator},
        headers=h("manager"),
    )
    assert response.status_code == 200, response.json


def begin_review(client, event_id, token="alice"):
    response = client.post(f"/api/event-requests/{event_id}/begin-review", headers=h(token))
    assert response.status_code == 200, response.json


def review_ready_event(client, **overrides) -> int:
    """A real submitted request, assigned to Alice and already Under Review."""

    event_id = submit_event(client, **overrides)
    assign(client, event_id)
    begin_review(client, event_id)
    return event_id


def reject(client, event_id, token="alice", reason=REASON, **kwargs):
    if "json" not in kwargs and "data" not in kwargs:
        kwargs["json"] = {"reason": reason}
    return client.post(f"/api/event-requests/{event_id}/reject", headers=h(token), **kwargs)


def set_status(app, event_id, status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = status
        session.commit()


def snapshot(app, event_id):
    """Every stored column of the request, plus its audit actions."""

    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        columns = {c.key: getattr(event, c.key) for c in inspect(EventRequest).column_attrs}
        audit = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        return columns, [row.action for row in audit]


def rejections(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return list(
            session.scalars(
                select(EventStatusHistory).where(
                    EventStatusHistory.event_request_id == event_id,
                    EventStatusHistory.action == REJECT,
                )
            )
        )


def assert_untouched(app, event_id, before):
    assert snapshot(app, event_id) == before


def stored_decision(app, event_id):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        return (
            event.status,
            event.rejected_by_account_id,
            event.rejected_at,
            event.rejection_reason,
        )


# ---- AC1: only the assigned Event Coordinator can reject a request that is Under Review ---------


def test_qa_spl68_001_assigned_coordinator_rejects_an_event_under_review(world, client):
    """QA-SPL-68-001 [Functional] AC1,3: the assigned coordinator rejects an Under Review event."""

    event_id = review_ready_event(client)
    response = reject(client, event_id)
    assert response.status_code == 200
    assert response.json["event"]["status"] == "rejected"
    assert stored_decision(world, event_id)[0] == "rejected"


def test_qa_spl68_002_unassigned_coordinator_gets_not_found(world, client):
    """QA-SPL-68-002 [Negative] AC1,6: a coordinator who is not assigned cannot see the event."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, token="bob")
    assert response.status_code == 404
    assert response.json == {"error": NOT_ASSIGNED}
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize("token", ["owner", "colleague", "stranger", "manager", "attendee"])
def test_qa_spl68_003_every_other_role_is_refused(world, client, token):
    """QA-SPL-68-003 [Negative] AC1,6: organisers, manager and attendee cannot reject."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, token=token)
    assert response.status_code == 403
    assert_untouched(world, event_id, before)


def test_qa_spl68_004_no_bearer_token_is_unauthenticated(world, client):
    """QA-SPL-68-004 [Security] AC1,6: an anonymous request is a 401 and changes nothing."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = client.post(f"/api/event-requests/{event_id}/reject", json={"reason": REASON})
    assert response.status_code == 401
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "Basic abc", "alice"])
def test_qa_spl68_005_a_malformed_authorization_header_is_unauthenticated(world, client, header):
    """QA-SPL-68-005 [Security] AC1,6: forged or malformed credentials never reach the rule."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = client.post(
        f"/api/event-requests/{event_id}/reject",
        json={"reason": REASON},
        headers={"Authorization": header},
    )
    assert response.status_code in (401, 403)
    assert_untouched(world, event_id, before)


def test_qa_spl68_006_a_deactivated_coordinator_cannot_reject(world, client):
    """QA-SPL-68-006 [Security] AC1,6: an inactive account is refused even if it was assigned."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        session.query(EventCoordinatorAssignment).filter_by(event_request_id=event_id).update(
            {"coordinator_account_id": DEAD}
        )
        session.commit()
    before = snapshot(world, event_id)
    assert reject(client, event_id, token="dead").status_code in (401, 403)
    assert_untouched(world, event_id, before)


def test_qa_spl68_007_a_coordinator_cannot_reject_a_colleagues_event(world, client):
    """QA-SPL-68-007 [Negative] AC1,6: being assigned elsewhere gives no rights on this event."""

    mine = review_ready_event(client)
    theirs = submit_event(client, token="stranger")
    assign(client, theirs, BOB)
    begin_review(client, theirs, token="bob")
    before_theirs = snapshot(world, theirs)
    assert reject(client, theirs, token="alice").status_code == 404
    assert_untouched(world, theirs, before_theirs)
    assert reject(client, mine, token="alice").status_code == 200


def test_qa_spl68_008_after_reassignment_only_the_new_coordinator_can_reject(world, client):
    """QA-SPL-68-008 [Functional] AC1: authority follows the current assignment."""

    event_id = review_ready_event(client)
    reassign(client, event_id, BOB)
    before = snapshot(world, event_id)
    assert reject(client, event_id, token="alice").status_code == 404
    assert_untouched(world, event_id, before)
    response = reject(client, event_id, token="bob")
    assert response.status_code == 200
    assert response.json["event"]["rejected_by"] == {"id": BOB, "name": "Bob Lim"}


@pytest.mark.parametrize("event_id", [999999, 1, 0])
def test_qa_spl68_009_an_event_that_does_not_exist_is_not_found(client, event_id):
    """QA-SPL-68-009 [Boundary] AC1,6: a missing event id is a 404 with the standard message."""

    response = reject(client, event_id)
    assert response.status_code == 404
    assert response.json == {"error": NOT_ASSIGNED}


def test_qa_spl68_010_an_id_beyond_the_supported_range_is_not_found(client):
    """QA-SPL-68-010 [Boundary] AC1,6: an id larger than any stored id is a clean 404, not a 500."""

    response = reject(client, 2**63)
    assert response.status_code == 404
    assert response.json == {"error": NOT_ASSIGNED}


def test_qa_spl68_011_full_flow_submit_assign_review_reject(world, client):
    """QA-SPL-68-011 [UAT] AC1,3,4: the whole journey, public API only, for the organiser."""

    event_id = submit_event(client)
    assert (
        client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json["event_request"][
            "status"
        ]
        == "submitted"
    )
    assign(client, event_id)
    begin_review(client, event_id)
    assert reject(client, event_id, reason="Not a fit for our venues.").status_code == 200
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert outcome["status"] == "rejected"
    assert outcome["rejection_reason"] == "Not a fit for our venues."


@pytest.mark.parametrize("status", OTHER_STATUSES)
def test_qa_spl68_012_only_an_event_under_review_can_be_rejected(world, client, status):
    """QA-SPL-68-012 [Negative] AC1,6: all 11 other statuses are refused with 409."""

    event_id = review_ready_event(client)
    set_status(world, event_id, status)
    before = snapshot(world, event_id)
    response = reject(client, event_id)
    assert response.status_code == 409
    assert response.json == {"error": WRONG_STATUS}
    assert_untouched(world, event_id, before)


def test_qa_spl68_013_a_submitted_event_must_be_reviewed_before_it_can_be_rejected(world, client):
    """QA-SPL-68-013 [Negative] AC1,5,6: the coordinator cannot skip Begin review."""

    event_id = submit_event(client)
    assign(client, event_id)
    before = snapshot(world, event_id)
    assert reject(client, event_id).status_code == 409
    assert_untouched(world, event_id, before)


def test_qa_spl68_014_a_wrong_role_is_refused_before_the_reason_is_looked_at(world, client):
    """QA-SPL-68-014 [Security] AC1,2: role is checked first, so a blank reason leaks nothing."""

    event_id = review_ready_event(client)
    assert reject(client, event_id, token="owner", json={"reason": ""}).status_code == 403
    assert reject(client, event_id, token="attendee", json={}).status_code == 403


# ---- AC2: a non-blank rejection reason is required  ----


@pytest.mark.parametrize(
    "reason",
    [
        "",
        " ",
        "   ",
        "\n",
        "\t",
        " \n\t ",
        "\u00a0",
        "\u2003\u2003",
        None,
        0,
        12,
        False,
        True,
        [],
        ["a"],
        {},
        {"a": 1},
    ],
)
def test_qa_spl68_015_a_blank_or_non_text_reason_is_refused(world, client, reason):
    """QA-SPL-68-015 [Negative] AC2,6: blank, whitespace-only and non-string reasons are 400."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, json={"reason": reason})
    assert response.status_code == 400
    assert response.json == {"error": BLANK_REASON}
    assert_untouched(world, event_id, before)


def test_qa_spl68_016_a_missing_reason_key_is_refused(world, client):
    """QA-SPL-68-016 [Negative] AC2,6: an empty object has no reason."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, json={})
    assert response.status_code == 400
    assert response.json == {"error": ONLY_REASON}
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize("body", [[], "rejected", 5, None, [{"reason": REASON}], True])
def test_qa_spl68_017_a_body_that_is_not_an_object_is_refused(world, client, body):
    """QA-SPL-68-017 [Negative] AC2,6: lists, strings, numbers and null are not a rejection."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, json=body)
    assert response.status_code == 400
    assert response.json == {"error": ONLY_REASON}
    assert_untouched(world, event_id, before)


def test_qa_spl68_018_no_body_at_all_is_refused(world, client):
    """QA-SPL-68-018 [Negative] AC2,6: a POST without a body is refused."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = client.post(f"/api/event-requests/{event_id}/reject", headers=h())
    assert response.status_code == 400
    assert response.json == {"error": ONLY_REASON}
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize("payload", ["reason=x", "{not json", '{"reason": '])
def test_qa_spl68_019_a_non_json_body_is_refused(world, client, payload):
    """QA-SPL-68-019 [Negative] AC2,6: form-encoded or malformed JSON is not accepted."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, data=payload, content_type="text/plain")
    assert response.status_code == 400
    assert_untouched(world, event_id, before)


def test_qa_spl68_020_malformed_json_with_a_json_content_type_is_refused(world, client):
    """QA-SPL-68-020 [Negative] AC2,6: broken JSON never reaches the rule."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, data='{"reason": "x"', content_type="application/json")
    assert response.status_code == 400
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "planning"},
        {"status": "rejected"},
        {"rejected_by_account_id": BOB},
        {"rejected_by": BOB},
        {"rejected_at": "2020-01-01T00:00:00+08:00"},
        {"actor": BOB},
        {"event_request_id": 1},
    ],
)
def test_qa_spl68_021_a_client_supplied_status_or_decision_maker_is_refused(world, client, extra):
    """QA-SPL-68-021 [Security] AC2,3,6: the server owns status, decision-maker and time."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, json={"reason": REASON, **extra})
    assert response.status_code == 400
    assert response.json == {"error": ONLY_REASON}
    assert_untouched(world, event_id, before)


def test_qa_spl68_022_the_reason_is_trimmed_before_it_is_stored(world, client):
    """QA-SPL-68-022 [Functional] AC2,3: surrounding whitespace is removed, inner text kept."""

    event_id = review_ready_event(client)
    response = reject(client, event_id, reason="  \n Clashes   with exams.\t ")
    assert response.status_code == 200
    assert response.json["event"]["rejection_reason"] == "Clashes   with exams."
    assert stored_decision(world, event_id)[3] == "Clashes   with exams."


def test_qa_spl68_023_a_one_character_reason_is_accepted(world, client):
    """QA-SPL-68-023 [Boundary] AC2: the smallest non-blank reason is valid."""

    event_id = review_ready_event(client)
    assert reject(client, event_id, reason="x").status_code == 200
    assert stored_decision(world, event_id)[3] == "x"


def test_qa_spl68_024_a_reason_of_exactly_the_maximum_length_is_stored_in_full(world, client):
    """QA-SPL-68-024 [Boundary] AC2,3: 2,000 characters is the largest accepted reason."""

    reason = "x" * 2000
    event_id = review_ready_event(client)
    response = reject(client, event_id, reason=reason)
    assert response.status_code == 200
    assert stored_decision(world, event_id)[3] == reason
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert outcome["rejection_reason"] == reason


@pytest.mark.parametrize("length", [2001, 5000, 15000])
def test_qa_spl68_142_a_reason_over_the_maximum_is_refused(world, client, length):
    """QA-SPL-68-142 [Boundary] AC2,6: 2,001+ characters is a 400 and the event is unchanged."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, reason="x" * length)
    assert response.status_code == 400
    assert response.json == {"error": "Keep the reason to 2000 characters or fewer."}
    assert_untouched(world, event_id, before)


def test_qa_spl68_143_the_length_limit_counts_the_trimmed_reason(world, client):
    """QA-SPL-68-143 [Boundary] AC2: padding around a 2,000-character reason does not count."""

    reason = "y" * 2000
    event_id = review_ready_event(client)
    assert reject(client, event_id, reason=f"   {reason}\n\n  ").status_code == 200
    assert stored_decision(world, event_id)[3] == reason


@pytest.mark.parametrize(
    "reason",
    [
        "Line one\nLine two",
        "Emoji \U0001f6ab and accents caf\u00e9 \u4e2d\u6587",
        "<script>alert(1)</script>",
        "Robert'); DROP TABLE event_requests;--",
        '"quoted" & <b>bold</b>',
    ],
)
def test_qa_spl68_025_special_characters_are_stored_verbatim(world, client, reason):
    """QA-SPL-68-025 [Security] AC2,3: newlines, unicode, markup and SQL text are just text."""

    event_id = review_ready_event(client)
    assert reject(client, event_id, reason=reason).status_code == 200
    assert stored_decision(world, event_id)[3] == reason
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert outcome["rejection_reason"] == reason
    with Session(world.extensions["engine"]) as session:
        assert session.scalars(select(EventRequest)).first() is not None


def test_qa_spl68_026_a_wrong_status_with_a_valid_reason_is_a_conflict_not_a_validation_error(
    world, client
):
    """QA-SPL-68-026 [Negative] AC1,6: a well-formed request on the wrong state is 409."""

    event_id = review_ready_event(client)
    set_status(world, event_id, "planning")
    assert reject(client, event_id).status_code == 409


def test_qa_spl68_027_a_blank_reason_on_a_wrong_status_is_reported_as_blank(world, client):
    """QA-SPL-68-027 [Boundary] AC2,6: input is validated before the event is loaded."""

    event_id = review_ready_event(client)
    set_status(world, event_id, "planning")
    before = snapshot(world, event_id)
    assert reject(client, event_id, json={"reason": " "}).status_code == 400
    assert_untouched(world, event_id, before)


# ---- AC3: rejection records reason, decision-maker, date and time, and sets Rejected  ----


def test_qa_spl68_028_the_response_reports_the_new_status_and_label(client):
    """QA-SPL-68-028 [Functional] AC3: status is rejected, shown to people as Not approved."""

    event_id = review_ready_event(client)
    body = reject(client, event_id).json
    assert body["event"]["status"] == "rejected"
    assert body["event"]["status_label"] == "Not approved"
    assert body["message"] == SUCCESS_MESSAGE


def test_qa_spl68_029_the_response_names_the_decision_maker(client):
    """QA-SPL-68-029 [Functional] AC3: rejected_by carries the coordinator's id and name."""

    event_id = review_ready_event(client)
    body = reject(client, event_id).json
    assert body["event"]["rejected_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert body["transition"]["actor"] == {"id": ALICE, "name": "Alice Tan"}


def test_qa_spl68_030_the_decision_time_is_singapore_time_and_current(client):
    """QA-SPL-68-030 [Functional] AC3: rejected_at is a timezone-aware +08:00 moment of the call."""

    event_id = review_ready_event(client)
    before = datetime.now(SINGAPORE)
    body = reject(client, event_id).json
    after = datetime.now(SINGAPORE)
    stamp = body["event"]["rejected_at"]
    assert stamp.endswith("+08:00")
    assert before <= datetime.fromisoformat(stamp) <= after


def test_qa_spl68_031_the_transition_record_has_every_required_field(client):
    """QA-SPL-68-031 [Functional] AC3: action, before, after, actor and time are all reported."""

    event_id = review_ready_event(client)
    transition = reject(client, event_id).json["transition"]
    assert set(transition) == {
        "action",
        "previous_status",
        "resulting_status",
        "actor",
        "changed_at",
    }
    assert transition["action"] == "reject"
    assert transition["previous_status"] == "under_review"
    assert transition["resulting_status"] == "rejected"
    assert transition["changed_at"].endswith("+08:00")


def test_qa_spl68_032_one_audit_row_records_the_rejection(world, client):
    """QA-SPL-68-032 [White-box] AC3: the append-only history gains exactly one reject row."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    rows = rejections(world, event_id)
    assert len(rows) == 1
    assert (rows[0].previous_status, rows[0].resulting_status) == ("under_review", "rejected")
    assert rows[0].actor_account_id == ALICE
    assert rows[0].changed_at is not None


def test_qa_spl68_033_the_decision_columns_and_status_are_stored(world, client):
    """QA-SPL-68-033 [White-box] AC3: rejected_by, rejected_at and reason are persisted."""

    event_id = review_ready_event(client)
    reject(client, event_id, reason="Stored reason")
    status, rejecter, rejected_at, reason = stored_decision(world, event_id)
    assert (status, rejecter, reason) == ("rejected", ALICE, "Stored reason")
    assert rejected_at is not None


def test_qa_spl68_034_the_status_time_and_decision_time_agree(world, client):
    """QA-SPL-68-034 [White-box] AC3: the status change and the decision share one timestamp."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    columns, _ = snapshot(world, event_id)
    assert columns["status_changed_at"] == columns["rejected_at"]


def test_qa_spl68_035_rejection_leaves_the_approval_fields_empty(world, client):
    """QA-SPL-68-035 [Functional] AC3: a rejected request never looks approved."""

    event_id = review_ready_event(client)
    body = reject(client, event_id).json
    assert body["event"].get("approved_by") is None
    columns, _ = snapshot(world, event_id)
    assert (columns["approved_by_account_id"], columns["approved_at"]) == (None, None)


def test_qa_spl68_036_rejection_changes_only_the_decision_columns(world, client):
    """QA-SPL-68-036 [White-box] AC3,6: every other stored column is exactly as it was."""

    event_id = review_ready_event(client)
    before, _ = snapshot(world, event_id)
    reject(client, event_id)
    after, _ = snapshot(world, event_id)
    changed = {key for key in before if before[key] != after[key]}
    assert changed == REJECTION_COLUMNS


def test_qa_spl68_037_rejecting_one_event_does_not_touch_another(world, client):
    """QA-SPL-68-037 [Functional] AC3,6: a sibling event under review is unaffected."""

    first, second = review_ready_event(client), review_ready_event(client)
    other = snapshot(world, second)
    reject(client, first)
    assert_untouched(world, second, other)


def test_qa_spl68_038_two_events_keep_their_own_reasons(world, client):
    """QA-SPL-68-038 [Functional] AC3: reasons are per event, not shared or overwritten."""

    first, second = review_ready_event(client), review_ready_event(client)
    reject(client, first, reason="First reason")
    reject(client, second, reason="Second reason")
    assert stored_decision(world, first)[3] == "First reason"
    assert stored_decision(world, second)[3] == "Second reason"


def test_qa_spl68_039_a_clarified_then_resubmitted_event_can_still_be_rejected(world, client):
    """QA-SPL-68-039 [Functional] AC1,3: history of clarification does not block a decision."""

    event_id = review_ready_event(client)
    assert (
        client.post(
            f"/api/event-requests/{event_id}/request-clarification",
            json={"message": "Please confirm the layout."},
            headers=h(),
        ).status_code
        == 200
    )
    set_status(world, event_id, "under_review")
    assert reject(client, event_id).status_code == 200
    assert stored_decision(world, event_id)[0] == "rejected"


def test_qa_spl68_040_the_decision_and_the_transition_commit_together(world, client):
    """QA-SPL-68-040 [White-box] AC3,6: a failure recording the decision rolls everything back."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    engine = world.extensions["engine"]

    def fail_on_decision(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith("UPDATE")
            and "rejected_by_account_id" in statement
        ):
            raise RuntimeError("simulated failure while recording the decision")

    sa_event.listen(engine, "before_cursor_execute", fail_on_decision)
    try:
        with pytest.raises(RuntimeError, match="simulated failure"):
            reject(client, event_id)
    finally:
        sa_event.remove(engine, "before_cursor_execute", fail_on_decision)
    assert_untouched(world, event_id, before)
    assert reject(client, event_id).status_code == 200


# ---- AC4: the responsible Event Organiser can retrieve the outcome and reason --------------------


def test_qa_spl68_041_the_organiser_sees_no_decision_before_rejection(client):
    """QA-SPL-68-041 [Functional] AC4: rejected_by, rejected_at and reason are null until then."""

    event_id = review_ready_event(client)
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert (outcome["rejected_by"], outcome["rejected_at"], outcome["rejection_reason"]) == (
        None,
        None,
        None,
    )


def test_qa_spl68_042_the_organiser_retrieves_status_reason_decision_maker_and_time(client):
    """QA-SPL-68-042 [Functional] AC4: the detail read carries the full outcome."""

    event_id = review_ready_event(client)
    reject(client, event_id, reason="Clashes with exams.")
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert (outcome["status"], outcome["status_label"]) == ("rejected", "Not approved")
    assert outcome["rejection_reason"] == "Clashes with exams."
    assert outcome["rejected_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert outcome["rejected_at"].endswith("+08:00")


def test_qa_spl68_043_the_organiser_list_carries_the_outcome_too(client):
    """QA-SPL-68-043 [Functional] AC4: the status list shows the same decision."""

    event_id = review_ready_event(client)
    reject(client, event_id, reason="Out of scope.")
    listing = client.get("/api/event-requests", headers=h("owner")).json["event_requests"]
    row = next(item for item in listing if item["id"] == event_id)
    assert row["status"] == "rejected"
    assert row["rejection_reason"] == "Out of scope."
    assert row["rejected_by"] == {"id": ALICE, "name": "Alice Tan"}


def test_qa_spl68_044_the_organiser_reads_the_human_status_wording(client):
    """QA-SPL-68-044 [Functional] AC4: the status wording explains the outcome plainly."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert outcome["status_label"] == status_label("rejected") == "Not approved"
    assert outcome["status_explanation"] == status_explanation("rejected")
    assert outcome["status_changed_at"]


def test_qa_spl68_045_an_organiser_from_another_client_cannot_retrieve_it(client):
    """QA-SPL-68-045 [Security] AC4: a stranger gets 404 on the request and on the org view."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    assert client.get(f"/api/event-requests/{event_id}", headers=h("stranger")).status_code == 404
    assert (
        client.get(f"/api/organisation/events/{event_id}", headers=h("stranger")).status_code == 404
    )


def test_qa_spl68_046_an_unauthenticated_reader_is_refused(client):
    """QA-SPL-68-046 [Security] AC4: no token, no reason."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    assert client.get(f"/api/event-requests/{event_id}").status_code == 401


def test_qa_spl68_047_a_colleague_cannot_use_the_organiser_route_to_read_it(client):
    """QA-SPL-68-047 [Security] AC4: the outcome is on the responsible organiser's own route."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    assert client.get(f"/api/event-requests/{event_id}", headers=h("colleague")).status_code == 404


def test_qa_spl68_048_the_read_only_organisation_view_does_not_leak_the_reason(client):
    """QA-SPL-68-048 [Security] AC4: colleagues in the client organisation get no decision keys."""

    event_id = review_ready_event(client)
    reject(client, event_id, reason="Confidential reason text")
    seen = client.get(f"/api/organisation/events/{event_id}", headers=h("colleague"))
    assert seen.status_code == 200
    for key in ("rejected_by", "rejected_at", "rejection_reason"):
        assert key not in seen.json["event"]
    assert "Confidential reason text" not in seen.get_data(as_text=True)


def test_qa_spl68_049_the_manager_and_attendee_cannot_read_the_organiser_outcome(client):
    """QA-SPL-68-049 [Security] AC4: only the responsible organiser role reads this route."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    assert client.get(f"/api/event-requests/{event_id}", headers=h("manager")).status_code == 403
    assert client.get(f"/api/event-requests/{event_id}", headers=h("attendee")).status_code == 403


def test_qa_spl68_050_the_assigned_coordinator_can_also_read_the_outcome(client):
    """QA-SPL-68-050 [Functional] AC4: the coordinator's own detail shows the same decision."""

    event_id = review_ready_event(client)
    reject(client, event_id, reason="Out of scope.")
    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=h("alice")).json[
        "event"
    ]
    assert detail["status"] == "rejected"
    assert detail["rejection_reason"] == "Out of scope."
    assert detail["rejected_by"] == {"id": ALICE, "name": "Alice Tan"}


def test_qa_spl68_051_another_coordinator_cannot_read_the_assigned_detail(client):
    """QA-SPL-68-051 [Security] AC4: an unassigned coordinator gets 404 on the assigned detail."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    assert (
        client.get(f"/api/event-requests/assigned/{event_id}", headers=h("bob")).status_code == 404
    )


def test_qa_spl68_052_the_outcome_survives_repeated_reads(client):
    """QA-SPL-68-052 [Functional] AC4: reading is idempotent and never alters the decision."""

    event_id = review_ready_event(client)
    reject(client, event_id, reason="Stable reason")
    reads = [
        client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json["event_request"]
        for _ in range(3)
    ]
    assert reads[0] == reads[1] == reads[2]
    assert reads[0]["rejection_reason"] == "Stable reason"


def test_qa_spl68_053_the_outcome_names_the_coordinator_who_decided_it(client):
    """QA-SPL-68-053 [Functional] AC4: the outcome is attributed to the deciding coordinator."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert outcome["rejected_by"]["id"] == ALICE


# ---- AC5: a rejected request cannot be reviewed or planned further -------------------------------

FOLLOW_UPS = [
    ("begin-review", None),
    ("approve", None),
    ("request-clarification", {"message": "Can you tell me more?"}),
    ("reject", {"reason": "Rejecting again."}),
]


@pytest.mark.parametrize(("action", "body"), FOLLOW_UPS)
def test_qa_spl68_054_no_review_action_works_on_a_rejected_request(world, client, action, body):
    """QA-SPL-68-054 [Negative] AC5,6: begin review, approve, clarify and reject all answer 409."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    before = snapshot(world, event_id)
    response = client.post(f"/api/event-requests/{event_id}/{action}", headers=h(), json=body)
    assert response.status_code == 409
    assert_untouched(world, event_id, before)


def test_qa_spl68_055_a_second_rejection_keeps_the_first_reason_and_one_audit_row(world, client):
    """QA-SPL-68-055 [Negative] AC5,6: the first decision stands; nothing is overwritten."""

    event_id = review_ready_event(client)
    assert reject(client, event_id, reason="First reason").status_code == 200
    assert reject(client, event_id, reason="Second reason").status_code == 409
    assert stored_decision(world, event_id)[3] == "First reason"
    assert len(rejections(world, event_id)) == 1


def test_qa_spl68_056_a_rejected_request_never_reaches_planning(world, client):
    """QA-SPL-68-056 [Negative] AC5: no rule leaves Rejected, so planning cannot follow."""

    assert all(rule.previous_status != REJECTED for rule in TRANSITION_RULES.values())
    event_id = review_ready_event(client)
    reject(client, event_id)
    client.post(f"/api/event-requests/{event_id}/approve", headers=h())
    assert stored_decision(world, event_id)[0] == "rejected"


def test_qa_spl68_057_the_only_way_to_proceed_is_a_new_event_request(world, client):
    """QA-SPL-68-057 [Functional] AC5: the organiser can submit a new request; the old one stays."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    new_id = submit_event(client)
    assert new_id != event_id
    fresh = client.get(f"/api/event-requests/{new_id}", headers=h("owner")).json["event_request"]
    assert fresh["status"] == "submitted"
    assert fresh["rejected_by"] is None and fresh["rejection_reason"] is None
    assert stored_decision(world, event_id)[0] == "rejected"


@pytest.mark.parametrize("verb", ["put", "patch", "delete"])
def test_qa_spl68_058_the_organiser_cannot_edit_or_delete_a_rejected_request(world, client, verb):
    """QA-SPL-68-058 [Negative] AC5: there is no route to change or remove a rejected request."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    before = snapshot(world, event_id)
    response = getattr(client, verb)(
        f"/api/event-requests/{event_id}", json={"name": "Renamed"}, headers=h("owner")
    )
    assert response.status_code in (403, 404, 405)
    assert_untouched(world, event_id, before)


def test_qa_spl68_059_a_rejected_request_cannot_be_reopened_as_a_draft(world, client):
    """QA-SPL-68-059 [Negative] AC5: the draft routes refuse a rejected request."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    before = snapshot(world, event_id)
    patched = client.patch(
        f"/api/event-requests/drafts/{event_id}", json={"name": "Renamed"}, headers=h("owner")
    )
    submitted = client.post(f"/api/event-requests/drafts/{event_id}/submit", headers=h("owner"))
    deleted = client.delete(f"/api/event-requests/drafts/{event_id}", headers=h("owner"))
    assert (
        patched.status_code >= 400 and submitted.status_code >= 400 and deleted.status_code >= 400
    )
    assert_untouched(world, event_id, before)


def test_qa_spl68_060_rejection_books_and_reserves_nothing(world, client):
    """QA-SPL-68-060 [Functional] AC5: no venue booking is created or changed."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    with Session(world.extensions["engine"]) as session:
        assert session.scalars(select(VenueBooking)).all() == []
        event = session.get(EventRequest, event_id)
        assert event.registration_required in (False, True)
        assert event.status not in ("confirmed", "approved", "planning")


def test_qa_spl68_061_the_coordinator_keeps_read_access_to_a_rejected_request(client):
    """QA-SPL-68-061 [Functional] AC5: rejected work stays visible to the assigned coordinator."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    listing = client.get("/api/event-requests/assigned", headers=h()).json["events"]
    row = next(item for item in listing if item["id"] == event_id)
    assert row["status"] == "rejected"


# ---- AC6: an invalid or unauthorised attempt leaves the event unchanged --------------------------


@pytest.mark.parametrize("verb", ["get", "put", "patch", "delete"])
def test_qa_spl68_062_only_post_is_allowed_on_the_reject_route(world, client, verb):
    """QA-SPL-68-062 [Negative] AC6: other HTTP verbs cannot reject an event."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = getattr(client, verb)(f"/api/event-requests/{event_id}/reject", headers=h())
    assert response.status_code in (403, 405)
    assert_untouched(world, event_id, before)


def test_qa_spl68_063_a_status_in_the_query_string_is_ignored(world, client):
    """QA-SPL-68-063 [Security] AC6: only the server rule decides the resulting status."""

    event_id = review_ready_event(client)
    response = client.post(
        f"/api/event-requests/{event_id}/reject?status=planning&rejected_by=bob",
        json={"reason": REASON},
        headers=h(),
    )
    assert response.status_code == 200
    status, rejecter, _, _ = stored_decision(world, event_id)
    assert (status, rejecter) == ("rejected", ALICE)


def test_qa_spl68_064_forged_identity_headers_are_ignored(world, client):
    """QA-SPL-68-064 [Security] AC1,6: the decision-maker comes from the token, not a header."""

    event_id = review_ready_event(client)
    response = client.post(
        f"/api/event-requests/{event_id}/reject",
        json={"reason": REASON},
        headers={**h(), "X-User-Id": BOB, "X-Role": "Event Operations Manager"},
    )
    assert response.status_code == 200
    assert stored_decision(world, event_id)[1] == ALICE


def test_qa_spl68_065_a_failed_attempt_writes_no_audit_row(world, client):
    """QA-SPL-68-065 [Negative] AC6: refused attempts leave the audit history without a reject."""

    event_id = review_ready_event(client)
    reject(client, event_id, token="bob")
    reject(client, event_id, token="owner")
    reject(client, event_id, json={"reason": " "})
    reject(client, event_id, json={})
    assert rejections(world, event_id) == []
    assert stored_decision(world, event_id)[0] == "under_review"


def test_qa_spl68_066_a_refused_attempt_can_be_corrected_and_then_succeeds(world, client):
    """QA-SPL-68-066 [Functional] AC2,6: fixing the reason after a 400 rejects normally."""

    event_id = review_ready_event(client)
    assert reject(client, event_id, json={"reason": "   "}).status_code == 400
    assert reject(client, event_id, reason="Now with a reason").status_code == 200
    assert stored_decision(world, event_id)[3] == "Now with a reason"


@pytest.mark.parametrize("attempts", [1, 5])
def test_qa_spl68_067_repeated_invalid_attempts_never_change_the_event(world, client, attempts):
    """QA-SPL-68-067 [Boundary] AC6: no number of refused attempts wears the event down."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    for _ in range(attempts):
        assert reject(client, event_id, json={"reason": ""}).status_code == 400
        assert reject(client, event_id, token="bob").status_code == 404
    assert_untouched(world, event_id, before)


def test_qa_spl68_068_a_body_over_the_server_limit_is_refused_and_changes_nothing(world, client):
    """QA-SPL-68-068 [Boundary] AC6: an oversized body is a 413 with the standard error shape."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, json={"reason": "x" * 20_000})
    assert response.status_code == 413
    assert "error" in response.json
    assert_untouched(world, event_id, before)


def test_qa_spl68_069_a_reason_under_the_transport_limit_gets_the_friendly_length_message(
    world, client
):
    """QA-SPL-68-069 [Boundary] AC2,6: 16,000 characters is under 16 KiB, so the cap answers."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = reject(client, event_id, reason="x" * 16_000)
    assert response.status_code == 400
    assert "2000 characters" in response.json["error"]
    assert_untouched(world, event_id, before)


# ---- White-box: the code under test is called or inspected directly ------------------------------


def test_qa_spl68_070_the_rule_table_maps_under_review_to_rejected(client):
    """QA-SPL-68-070 [White-box] AC1,3,5: the server-owned rule is under_review to rejected."""

    rule = TRANSITION_RULES[REJECT]
    assert (rule.previous_status, rule.resulting_status) == (UNDER_REVIEW, REJECTED)
    assert (UNDER_REVIEW, REJECTED, REJECT) == ("under_review", "rejected", "reject")
    assert set(TRANSITION_RULES) == {
        BEGIN_REVIEW,
        REQUEST_CLARIFICATION,
        "respond_clarification",
        APPROVE,
        REJECT,
        "withdraw",
    }


def test_qa_spl68_071_rejected_is_a_known_terminal_status_with_wording(client):
    """QA-SPL-68-071 [White-box] AC3,5: the vocabulary already stores and words Rejected."""

    assert "rejected" in EVENT_REQUEST_STATUSES
    assert status_label("rejected") == "Not approved"
    assert status_explanation("rejected")
    assert not [rule for rule in TRANSITION_RULES.values() if rule.previous_status == "rejected"]


def test_qa_spl68_072_the_policy_function_applies_the_rule_and_records_evidence(world, client):
    """QA-SPL-68-072 [White-box] AC3: the shared policy writes status, time and the audit row."""

    event_id = review_ready_event(client)
    moment = datetime.now(SINGAPORE)
    with Session(world.extensions["engine"]) as session:
        audit = transition_event_status(
            session,
            event_request_id=event_id,
            action=REJECT,
            actor_account_id=ALICE,
            changed_at=moment,
        )
        session.commit()
        assert (audit.action, audit.previous_status, audit.resulting_status) == (
            "reject",
            "under_review",
            "rejected",
        )
    assert stored_decision(world, event_id)[0] == "rejected"
    assert len(rejections(world, event_id)) == 1


@pytest.mark.parametrize("status", OTHER_STATUSES)
def test_qa_spl68_073_the_policy_function_refuses_every_other_status(world, client, status):
    """QA-SPL-68-073 [White-box] AC1,6: the compare-and-swap UPDATE matches no row."""

    event_id = review_ready_event(client)
    set_status(world, event_id, status)
    with Session(world.extensions["engine"]) as session:
        with pytest.raises(InvalidStatusTransition):
            transition_event_status(
                session,
                event_request_id=event_id,
                action=REJECT,
                actor_account_id=ALICE,
                changed_at=datetime.now(SINGAPORE),
            )
        session.rollback()
    assert stored_decision(world, event_id)[0] == status
    assert rejections(world, event_id) == []


def test_qa_spl68_074_a_stale_check_cannot_reject_twice(world, client):
    """QA-SPL-68-074 [White-box] AC5,6: the second policy call after a rejection is refused."""

    event_id = review_ready_event(client)
    for attempt in range(2):
        with Session(world.extensions["engine"]) as session:
            try:
                transition_event_status(
                    session,
                    event_request_id=event_id,
                    action=REJECT,
                    actor_account_id=ALICE,
                    changed_at=datetime.now(SINGAPORE),
                )
                session.commit()
                assert attempt == 0
            except InvalidStatusTransition:
                session.rollback()
                assert attempt == 1
    assert len(rejections(world, event_id)) == 1


def test_qa_spl68_075_the_policy_refuses_an_unknown_action(world, client):
    """QA-SPL-68-075 [White-box] AC6: an action outside the rule table cannot be applied."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        with pytest.raises(KeyError):
            transition_event_status(
                session,
                event_request_id=event_id,
                action="reject_everything",
                actor_account_id=ALICE,
                changed_at=datetime.now(SINGAPORE),
            )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"reason": "Simple"}, "Simple"),
        ({"reason": "  padded  "}, "padded"),
        ({"reason": "a\nb"}, "a\nb"),
    ],
)
def test_qa_spl68_076_the_reason_validator_returns_the_trimmed_text(world, body, expected):
    """QA-SPL-68-076 [White-box] AC2: _rejection_reason accepts exactly {reason: text}."""

    with world.test_request_context(method="POST", json=body):
        assert _rejection_reason() == expected


@pytest.mark.parametrize(
    "body",
    [
        {"reason": ""},
        {"reason": "   "},
        {"reason": None},
        {"reason": 5},
        {},
        {"x": "y"},
        [],
        "text",
    ],
)
def test_qa_spl68_077_the_reason_validator_aborts_with_400(world, body):
    """QA-SPL-68-077 [White-box] AC2,6: bad input raises BadRequest before any database work."""

    with world.test_request_context(method="POST", json=body):
        with pytest.raises(BadRequest):
            _rejection_reason()


def test_qa_spl68_078_the_reason_validator_aborts_without_a_json_body(world):
    """QA-SPL-68-078 [White-box] AC2,6: no JSON at all raises BadRequest."""

    with world.test_request_context(method="POST", data="plain", content_type="text/plain"):
        with pytest.raises(BadRequest):
            _rejection_reason()


def test_qa_spl68_079_serialize_rejection_is_null_before_a_decision(world, client):
    """QA-SPL-68-079 [White-box] AC4: the serialiser reports nothing for an undecided request."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        assert serialize_rejection(session.get(EventRequest, event_id)) == {
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
        }


def test_qa_spl68_080_serialize_rejection_reports_the_decision(world, client):
    """QA-SPL-68-080 [White-box] AC3,4: id, display name, +08:00 time and reason are returned."""

    event_id = review_ready_event(client)
    reject(client, event_id, reason="Because.")
    with Session(world.extensions["engine"]) as session:
        result = serialize_rejection(session.get(EventRequest, event_id))
    assert result["rejected_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert result["rejected_at"].endswith("+08:00")
    assert result["rejection_reason"] == "Because."


def test_qa_spl68_081_serialize_rejection_treats_stored_time_as_singapore(world, client):
    """QA-SPL-68-081 [White-box] AC4: a stored naive time is reported as +08:00, not UTC."""

    event_id = review_ready_event(client)
    reject(client, event_id)
    with Session(world.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.rejected_at = datetime(2026, 10, 1, 9, 30)
        assert serialize_rejection(event)["rejected_at"] == "2026-10-01T09:30:00+08:00"
        session.rollback()


def test_qa_spl68_082_the_model_exposes_the_rejection_columns_and_relationship(client):
    """QA-SPL-68-082 [White-box] AC3: three nullable columns, an account FK and a rejecter link."""

    columns = EventRequest.__table__.c
    for name in ("rejected_by_account_id", "rejected_at", "rejection_reason"):
        assert columns[name].nullable is True
    foreign_keys = {fk.target_fullname for fk in columns["rejected_by_account_id"].foreign_keys}
    assert foreign_keys == {"accounts.id"}
    assert columns["rejected_at"].type.timezone is True
    assert EventRequest.rejecter.property.mapper.class_ is Account


PARTIAL_RECORDS = [
    {"rejected_by_account_id": ALICE},
    {"rejected_at": datetime(2026, 10, 1, 9, 30)},
    {"rejection_reason": "Only a reason"},
    {"rejected_by_account_id": ALICE, "rejected_at": datetime(2026, 10, 1, 9, 30)},
    {"rejected_by_account_id": ALICE, "rejection_reason": "No time"},
    {"rejected_at": datetime(2026, 10, 1, 9, 30), "rejection_reason": "No decision-maker"},
]


@pytest.mark.parametrize("values", PARTIAL_RECORDS)
def test_qa_spl68_083_the_database_refuses_a_partial_rejection_record(world, client, values):
    """QA-SPL-68-083 [White-box] AC3,6: the check constraint needs all three or none."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        for key, value in values.items():
            setattr(event, key, value)
        with pytest.raises(IntegrityError):
            session.commit()


def test_qa_spl68_084_the_database_accepts_all_three_or_none(world, client):
    """QA-SPL-68-084 [White-box] AC3: complete and empty records both satisfy the constraint."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.rejected_by_account_id = ALICE
        event.rejected_at = datetime(2026, 10, 1, 9, 30)
        event.rejection_reason = "Complete"
        session.commit()
        event.rejected_by_account_id = None
        event.rejected_at = None
        event.rejection_reason = None
        session.commit()


def test_qa_spl68_085_the_model_and_migration_state_the_same_constraint(client):
    """QA-SPL-68-085 [White-box] AC3,6: the migration expression equals the model's."""

    from importlib import import_module

    migration = import_module("migrations.versions.s2_event_rejection")
    model_sql = next(
        str(constraint.sqltext)
        for constraint in EventRequest.__table__.constraints
        if getattr(constraint, "name", None) == "ck_event_requests_rejection_complete"
    )
    assert " ".join(model_sql.split()) == " ".join(migration.COMPLETE.split())
    assert migration.CONSTRAINT == "ck_event_requests_rejection_complete"


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_qa_spl68_086_the_migration_extends_the_approval_head_as_the_only_head(client):
    """QA-SPL-68-086 [White-box] AC3: one linear head, chained after the approval migration."""

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["s2_clarification_responses"]
    assert script.get_revision("s2_event_rejection").down_revision == "s2_event_approval"


def test_qa_spl68_087_the_migration_source_adds_and_removes_columns_and_constraint(client):
    """QA-SPL-68-087 [White-box] AC3: upgrade adds, downgrade drops, all four objects."""

    source = (MIGRATIONS / "versions" / "s2_event_rejection.py").read_text()
    upgrade, downgrade = source.split("def downgrade")
    for name in ("rejected_by_account_id", "rejected_at", "rejection_reason"):
        assert name in upgrade and name in downgrade
    assert "add_column" in upgrade and "create_check_constraint" in upgrade
    assert "drop_column" in downgrade and "drop_constraint" in downgrade
    assert "drop_column" not in upgrade and "add_column" not in downgrade


def test_qa_spl68_088_the_migration_emits_the_expected_postgresql_ddl(client):
    """QA-SPL-68-088 [Migration] AC3: rendered offline, upgrade and downgrade are the right DDL."""

    import io
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = import_module("migrations.versions.s2_event_rejection")

    def render(step) -> str:
        buffer = io.StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer}
        )
        with Operations.context(context):
            step()
        return " ".join(buffer.getvalue().split())

    up, down = render(migration.upgrade), render(migration.downgrade)
    for column in ("rejected_by_account_id", "rejected_at", "rejection_reason"):
        assert f"ADD COLUMN {column}" in up
        assert f"DROP COLUMN {column}" in down
    assert "REFERENCES accounts (id)" in up
    assert "ADD CONSTRAINT ck_event_requests_rejection_complete CHECK" in up
    assert "DROP CONSTRAINT ck_event_requests_rejection_complete" in down
    assert up.index("ADD COLUMN") < up.index("ADD CONSTRAINT")
    assert down.index("DROP CONSTRAINT") < down.index("DROP COLUMN")


# ---- Performance / API contract ------------------------------------------------------------------


def test_qa_spl68_089_one_rejection_is_a_handful_of_statements_and_fast(world, client):
    """QA-SPL-68-089 [Performance] AC3: one rejection needs few statements and is well under 1s."""

    event_id = review_ready_event(client)
    engine = world.extensions["engine"]
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", count)
    try:
        started = clock.perf_counter()
        assert reject(client, event_id).status_code == 200
        elapsed = clock.perf_counter() - started
    finally:
        sa_event.remove(engine, "before_cursor_execute", count)
    assert len(statements) <= 20, statements
    assert elapsed < 1.0


def test_qa_spl68_090_thirty_rejections_in_a_row_all_succeed_quickly(world, client):
    """QA-SPL-68-090 [Load] AC3: 30 sequential rejections, each with its own reason."""

    ids = [review_ready_event(client) for _ in range(30)]
    started = clock.perf_counter()
    for index, event_id in enumerate(ids):
        assert reject(client, event_id, reason=f"Reason {index}").status_code == 200
    assert clock.perf_counter() - started < 15
    for index, event_id in enumerate(ids):
        assert stored_decision(world, event_id)[3] == f"Reason {index}"


def test_qa_spl68_091_the_success_response_contract_is_stable(client):
    """QA-SPL-68-091 [API] AC3,4: JSON with event, transition and message only."""

    event_id = review_ready_event(client)
    response = reject(client, event_id)
    assert response.is_json and response.mimetype == "application/json"
    assert set(response.json) == {"event", "transition", "message"}
    assert {"id", "name", "status", "status_label", "rejected_by", "rejected_at"} <= set(
        response.json["event"]
    )
    assert response.json["event"]["rejection_reason"] == REASON


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"token": "bob"}, 404),
        ({"token": "owner"}, 403),
        ({"json": {"reason": ""}}, 400),
        ({"json": {}}, 400),
    ],
)
def test_qa_spl68_092_every_refusal_uses_the_error_body_convention(client, kwargs, status):
    """QA-SPL-68-092 [API] AC6: refusals are {"error": "<message>"} with the right status."""

    event_id = review_ready_event(client)
    response = reject(client, event_id, **kwargs)
    assert response.status_code == status
    assert set(response.json) == {"error"}
    assert isinstance(response.json["error"], str) and response.json["error"]


def test_qa_spl68_093_a_conflict_uses_the_error_body_convention(client):
    """QA-SPL-68-093 [API] AC1,6: the wrong-status refusal is 409 with the documented message."""

    event_id = submit_event(client)
    assign(client, event_id)
    response = reject(client, event_id)
    assert response.status_code == 409
    assert response.json == {"error": WRONG_STATUS}
