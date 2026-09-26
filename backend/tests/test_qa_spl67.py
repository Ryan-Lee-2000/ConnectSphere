"""QA acceptance test scripts for SPL-67 (CS-E06-S4 — approve an event request).

Each function is the automated evidence for one QA test case ID in the QA-SPL-67 Confluence
report (QA SPACE). The function name embeds the ID and the docstring carries the ID, the test
category and the acceptance criteria, so a reader can jump from the report to the assertion:

    rg -n "QA-SPL-67-021" backend/tests frontend/src

Black-box cases drive only the public HTTP API with real submitted requests. White-box cases call
the code under test (`event_review`, `event_requests.serialize_approval`, the models and the
migration chain) directly. Interface cases are in frontend/src/QaSpl67.test.tsx and the
PostgreSQL migration cases are in test_qa_spl67_postgres.py.

Acceptance criteria (SPL-67):
  AC1 Only the assigned Event Coordinator can approve a request that is Under Review.
  AC2 Approval is refused while an unanswered clarification request remains outstanding.
  AC3 Approval records the decision-maker and date and time, and changes the event to Planning.
  AC4 The responsible Event Organiser can retrieve the approval outcome.
  AC5 Approval does not itself book a venue, reserve equipment, enable registration, or confirm
      the event.
  AC6 An invalid or unauthorised approval attempt leaves the event unchanged.
"""

import time as clock
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app import create_app
from app.event_requests import SINGAPORE, serialize_approval
from app.event_review import (
    APPROVE,
    BEGIN_REVIEW,
    PLANNING,
    REQUEST_CLARIFICATION,
    TRANSITION_RULES,
    UNDER_REVIEW,
    InvalidStatusTransition,
    transition_event_status,
)
from app.event_statuses import EVENT_REQUEST_STATUSES, status_label
from app.models import (
    Account,
    AccountRole,
    Base,
    ClarificationRequest,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    EventStatusHistory,
    Organisation,
    Role,
    VenueBooking,
)
from sqlalchemy import event as sa_event
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session
from test_event_requests import event_payload

MANAGER = "00000000-0000-0000-0000-0000000067a1"
ORG_A_OWNER = "00000000-0000-0000-0000-0000000067a2"
ORG_A_COLLEAGUE = "00000000-0000-0000-0000-0000000067a3"
ORG_B_OWNER = "00000000-0000-0000-0000-0000000067a4"
ALICE = "00000000-0000-0000-0000-0000000067a5"
BOB = "00000000-0000-0000-0000-0000000067a6"
ATTENDEE = "00000000-0000-0000-0000-0000000067a7"
DEAD = "00000000-0000-0000-0000-0000000067a8"
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
SUCCESS_MESSAGE = "Request approved. Event planning can begin."
WRONG_STATUS = "Only an event under review can be approved."
NOT_ASSIGNED = "Assigned event not found."
OTHER_STATUSES = sorted(set(EVENT_REQUEST_STATUSES) - {UNDER_REVIEW})
APPROVAL_COLUMNS = {"status", "status_changed_at", "approved_by_account_id", "approved_at"}


@pytest.fixture
def world(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/qa67.db",
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


def approve(client, event_id, token="alice", **kwargs):
    return client.post(f"/api/event-requests/{event_id}/approve", headers=h(token), **kwargs)


def clarify(client, event_id, message="Please confirm the room layout.", token="alice"):
    return client.post(
        f"/api/event-requests/{event_id}/request-clarification",
        json={"message": message},
        headers=h(token),
    )


def set_status(app, event_id, status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = status
        session.commit()


def snapshot(app, event_id):
    """Every stored column of the request, plus how many audit and clarification rows it has."""

    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        columns = {c.key: getattr(event, c.key) for c in inspect(EventRequest).column_attrs}
        audit = session.scalars(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        clarifications = session.scalars(
            select(ClarificationRequest).where(ClarificationRequest.event_request_id == event_id)
        ).all()
        return columns, [row.action for row in audit], len(clarifications)


def approvals(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return list(
            session.scalars(
                select(EventStatusHistory).where(
                    EventStatusHistory.event_request_id == event_id,
                    EventStatusHistory.action == APPROVE,
                )
            )
        )


def assert_untouched(app, event_id, before):
    assert snapshot(app, event_id) == before


# ---- AC1: only the assigned Event Coordinator can approve a request that is Under Review --------


def test_qa_spl67_001_assigned_coordinator_approves_an_event_under_review(client):
    """QA-SPL-67-001 [Functional] AC1,3: the assigned coordinator approves a real request."""

    event_id = review_ready_event(client)
    response = approve(client, event_id)
    assert response.status_code == 200
    assert response.json["event"]["id"] == event_id
    assert response.json["event"]["status"] == "planning"


def test_qa_spl67_002_unassigned_coordinator_gets_not_found(world, client):
    """QA-SPL-67-002 [Negative] AC1,6: another coordinator sees nothing and changes nothing."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = approve(client, event_id, token="bob")
    assert response.status_code == 404
    assert response.json == {"error": NOT_ASSIGNED}
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize("token", ["owner", "colleague", "stranger", "manager", "attendee"])
def test_qa_spl67_003_every_other_role_is_refused(world, client, token):
    """QA-SPL-67-003 [Negative] AC1,6: organisers, manager and attendee cannot approve."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = approve(client, event_id, token=token)
    assert response.status_code == 403
    assert_untouched(world, event_id, before)


def test_qa_spl67_004_no_bearer_token_is_unauthenticated(world, client):
    """QA-SPL-67-004 [Security] AC1,6: an anonymous request is a 401 and changes nothing."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = client.post(f"/api/event-requests/{event_id}/approve")
    assert response.status_code == 401
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize("header", ["Bearer ", "Bearer    ", "Basic alice", "alice"])
def test_qa_spl67_005_a_malformed_authorization_header_is_unauthenticated(world, client, header):
    """QA-SPL-67-005 [Security] AC1,6: a blank or non-Bearer credential is refused."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = client.post(
        f"/api/event-requests/{event_id}/approve", headers={"Authorization": header}
    )
    assert response.status_code == 401
    assert_untouched(world, event_id, before)


def test_qa_spl67_006_deactivated_coordinator_cannot_approve(world, client):
    """QA-SPL-67-006 [Security] AC1,6: an assigned but deactivated coordinator is refused."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        session.get(Account, ALICE).is_active = False
        session.commit()
    before = snapshot(world, event_id)
    response = approve(client, event_id, token="alice")
    assert response.status_code == 403
    assert_untouched(world, event_id, before)


def test_qa_spl67_007_reassignment_moves_the_right_to_approve(world, client):
    """QA-SPL-67-007 [Functional] AC1: after reassignment only the new coordinator may approve."""

    event_id = review_ready_event(client)
    reassign(client, event_id, BOB)
    before = snapshot(world, event_id)
    assert approve(client, event_id, token="alice").status_code == 404
    assert_untouched(world, event_id, before)
    assert approve(client, event_id, token="bob").status_code == 200
    assert snapshot(world, event_id)[0]["approved_by_account_id"] == BOB


def test_qa_spl67_008_a_coordinator_cannot_approve_a_colleagues_event(world, client):
    """QA-SPL-67-008 [Negative] AC1,6: assignment is per event, not per role."""

    mine = review_ready_event(client)
    theirs = submit_event(client, token="stranger")
    assign(client, theirs, coordinator=BOB)
    begin_review(client, theirs, token="bob")
    before = snapshot(world, theirs)
    assert approve(client, theirs, token="alice").status_code == 404
    assert_untouched(world, theirs, before)
    assert approve(client, mine, token="alice").status_code == 200


def test_qa_spl67_009_an_unassigned_event_cannot_be_approved_by_anyone(world, client):
    """QA-SPL-67-009 [Negative] AC1,6: no assignment means no coordinator may approve."""

    event_id = submit_event(client)
    set_status(world, event_id, UNDER_REVIEW)
    before = snapshot(world, event_id)
    for token in ("alice", "bob"):
        assert approve(client, event_id, token=token).status_code == 404
    assert_untouched(world, event_id, before)


def test_qa_spl67_010_a_missing_event_is_not_found(client):
    """QA-SPL-67-010 [Negative] AC1,6: an id that does not exist is a 404, same as unassigned."""

    response = approve(client, 999)
    assert response.status_code == 404
    assert response.json == {"error": NOT_ASSIGNED}


def test_qa_spl67_011_an_id_beyond_the_supported_range_is_not_found(client):
    """QA-SPL-67-011 [Boundary] AC1,6: ids above MAX_EVENT_REQUEST_ID never reach the database."""

    assert approve(client, 2**63).status_code == 404
    assert approve(client, 2**31).status_code == 404


def test_qa_spl67_012_a_non_numeric_id_is_not_routed(client):
    """QA-SPL-67-012 [Negative] AC1,6: only integer ids reach the endpoint (403/404)."""

    assert client.post("/api/event-requests/abc/approve", headers=h()).status_code in (403, 404)


def test_qa_spl67_013_only_post_is_allowed(world, client):
    """QA-SPL-67-013 [Negative] AC1,6: only POST approves; other verbs are refused (403/405)."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    url = f"/api/event-requests/{event_id}/approve"
    for method in ("get", "put", "patch", "delete"):
        assert getattr(client, method)(url, headers=h()).status_code in (403, 405)
    assert_untouched(world, event_id, before)


def test_qa_spl67_014_approval_needs_the_review_to_have_begun(world, client):
    """QA-SPL-67-014 [Functional] AC1,6: a Submitted event cannot skip begin-review."""

    event_id = submit_event(client)
    assign(client, event_id)
    before = snapshot(world, event_id)
    response = approve(client, event_id)
    assert response.status_code == 409
    assert_untouched(world, event_id, before)
    begin_review(client, event_id)
    assert approve(client, event_id).status_code == 200


# ---- AC2: approval is refused while a clarification request is outstanding ----------------------


def test_qa_spl67_015_approval_is_refused_after_clarification_is_requested(world, client):
    """QA-SPL-67-015 [Functional] AC2,6: an outstanding clarification blocks approval."""

    event_id = review_ready_event(client)
    assert clarify(client, event_id).status_code == 200
    before = snapshot(world, event_id)
    response = approve(client, event_id)
    assert response.status_code == 409
    assert response.json == {"error": WRONG_STATUS}
    assert_untouched(world, event_id, before)
    assert before[0]["status"] == "returned_for_clarification"


def test_qa_spl67_016_a_refused_approval_keeps_the_clarification_history(world, client):
    """QA-SPL-67-016 [Functional] AC2,6: the clarification and its audit row are not disturbed."""

    event_id = review_ready_event(client)
    clarify(client, event_id, message="First question")
    approve(client, event_id)
    approve(client, event_id)
    columns, audit, clarification_count = snapshot(world, event_id)
    assert audit == [BEGIN_REVIEW, REQUEST_CLARIFICATION]
    assert clarification_count == 1
    assert columns["approved_by_account_id"] is None


def test_qa_spl67_017_repeated_attempts_stay_refused_and_write_nothing(world, client):
    """QA-SPL-67-017 [Negative] AC2,6: ten attempts on an outstanding clarification all fail."""

    event_id = review_ready_event(client)
    clarify(client, event_id)
    before = snapshot(world, event_id)
    assert {approve(client, event_id).status_code for _ in range(10)} == {409}
    assert_untouched(world, event_id, before)


def test_qa_spl67_018_the_organiser_still_sees_it_returned_after_a_refused_approval(client):
    """QA-SPL-67-018 [Functional] AC2,4: the organiser's view is unchanged by the refusal."""

    event_id = review_ready_event(client)
    clarify(client, event_id)
    approve(client, event_id)
    seen = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json["event_request"]
    assert seen["status"] == "returned_for_clarification"
    assert seen["approved_by"] is None
    assert seen["approved_at"] is None
    assert len(seen["clarifications"]) == 1


def test_qa_spl67_019_approval_succeeds_once_the_event_is_back_under_review(world, client):
    """QA-SPL-67-019 [Functional] AC2,3: refused while outstanding, allowed once resolved.

    SPL-66 will move the event back to Under Review; the test stands in for it directly.
    """

    event_id = review_ready_event(client)
    clarify(client, event_id)
    assert approve(client, event_id).status_code == 409
    set_status(world, event_id, UNDER_REVIEW)
    assert approve(client, event_id).status_code == 200
    assert snapshot(world, event_id)[0]["status"] == "planning"


def test_qa_spl67_020_the_refusal_names_the_required_status(client):
    """QA-SPL-67-020 [Functional] AC2,6: the display message tells the coordinator why."""

    event_id = review_ready_event(client)
    clarify(client, event_id)
    assert approve(client, event_id).json["error"] == WRONG_STATUS


def test_qa_spl67_021_only_the_assigned_coordinator_learns_the_refusal_reason(client):
    """QA-SPL-67-021 [Security] AC2,6: another coordinator gets 404, not the 409 reason."""

    event_id = review_ready_event(client)
    clarify(client, event_id)
    assert approve(client, event_id, token="bob").status_code == 404


# ---- AC3: records the decision-maker and date and time, and changes the event to Planning -------


def test_qa_spl67_022_the_event_moves_to_planning(world, client):
    """QA-SPL-67-022 [Functional] AC3: the response and the stored event are Planning."""

    event_id = review_ready_event(client)
    response = approve(client, event_id)
    assert response.json["event"]["status"] == "planning"
    assert response.json["event"]["status_label"] == "In planning"
    assert snapshot(world, event_id)[0]["status"] == "planning"


def test_qa_spl67_023_the_display_message_is_returned(client):
    """QA-SPL-67-023 [Functional] AC3: the success message travels with the response."""

    event_id = review_ready_event(client)
    assert approve(client, event_id).json["message"] == SUCCESS_MESSAGE


def test_qa_spl67_024_the_decision_maker_is_recorded(world, client):
    """QA-SPL-67-024 [Functional] AC3: the coordinator's id and name are stored and returned."""

    event_id = review_ready_event(client)
    response = approve(client, event_id)
    assert response.json["event"]["approved_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert snapshot(world, event_id)[0]["approved_by_account_id"] == ALICE


def test_qa_spl67_025_the_decision_time_is_recorded_between_the_request_bounds(world, client):
    """QA-SPL-67-025 [Functional] AC3: approved_at is the server clock at the time of approval."""

    event_id = review_ready_event(client)
    before = datetime.now(SINGAPORE) - timedelta(seconds=1)
    approve(client, event_id)
    after = datetime.now(SINGAPORE) + timedelta(seconds=1)
    stored = snapshot(world, event_id)[0]["approved_at"]
    stored = stored if stored.tzinfo else stored.replace(tzinfo=SINGAPORE)
    assert before <= stored <= after


def test_qa_spl67_026_the_time_is_returned_in_singapore_time(client):
    """QA-SPL-67-026 [Functional] AC3: the API states the time with the +08:00 offset."""

    event_id = review_ready_event(client)
    stamped = approve(client, event_id).json["event"]["approved_at"]
    assert stamped.endswith("+08:00")
    assert datetime.fromisoformat(stamped).utcoffset() == timedelta(hours=8)


def test_qa_spl67_027_the_client_cannot_choose_the_decision_maker_or_time(world, client):
    """QA-SPL-67-027 [Security] AC3,6: a submitted approver or time is refused, not stored."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    for body in (
        {"approved_by": BOB},
        {"approved_at": "2020-01-01T00:00:00+08:00"},
        {"approved_by_account_id": BOB, "status": "planning"},
    ):
        assert approve(client, event_id, json=body).status_code == 400
    assert_untouched(world, event_id, before)


def test_qa_spl67_028_an_audit_row_records_the_transition(world, client):
    """QA-SPL-67-028 [Functional] AC3: action, previous and resulting status and the actor."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    [row] = approvals(world, event_id)
    assert (row.previous_status, row.resulting_status) == ("under_review", "planning")
    assert row.actor_account_id == ALICE
    assert row.changed_at is not None


def test_qa_spl67_029_the_response_transition_block_matches_the_audit_row(client):
    """QA-SPL-67-029 [API] AC3: the transition object carries the audit evidence."""

    event_id = review_ready_event(client)
    body = approve(client, event_id).json
    assert body["transition"]["action"] == "approve"
    assert body["transition"]["previous_status"] == "under_review"
    assert body["transition"]["resulting_status"] == "planning"
    assert body["transition"]["actor"] == {"id": ALICE, "name": "Alice Tan"}
    assert body["transition"]["changed_at"] == body["event"]["approved_at"]


def test_qa_spl67_030_the_audit_time_and_the_decision_time_are_one_instant(world, client):
    """QA-SPL-67-030 [White-box] AC3: audit changed_at, approved_at and status_changed_at agree."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    [row] = approvals(world, event_id)
    columns = snapshot(world, event_id)[0]
    assert row.changed_at == columns["approved_at"] == columns["status_changed_at"]


def test_qa_spl67_031_exactly_one_audit_row_is_written(world, client):
    """QA-SPL-67-031 [Functional] AC3: begin-review then approve leaves two rows, in order."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    assert snapshot(world, event_id)[1] == [BEGIN_REVIEW, APPROVE]


def test_qa_spl67_032_the_decision_survives_a_fresh_session(world, client):
    """QA-SPL-67-032 [Functional] AC3: the outcome is persisted, not held in memory."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    with Session(world.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assert (event.status, event.approved_by_account_id) == ("planning", ALICE)
        assert event.approver.display_name == "Alice Tan"


def test_qa_spl67_033_the_coordinator_detail_shows_the_decision(client):
    """QA-SPL-67-033 [Functional] AC3,4: GET assigned detail returns status and approver."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=h()).json["event"]
    assert detail["status"] == "planning"
    assert detail["status_label"] == "In planning"
    assert detail["approved_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert detail["approved_at"]


def test_qa_spl67_034_the_detail_shows_no_decision_before_approval(client):
    """QA-SPL-67-034 [Functional] AC3: an undecided request has null approval fields."""

    event_id = review_ready_event(client)
    detail = client.get(f"/api/event-requests/assigned/{event_id}", headers=h()).json["event"]
    assert (detail["approved_by"], detail["approved_at"]) == (None, None)


def test_qa_spl67_035_the_transition_rule_is_under_review_to_planning(client):
    """QA-SPL-67-035 [White-box] AC1,3: the server-owned rule table is exactly as specified."""

    rule = TRANSITION_RULES[APPROVE]
    assert (rule.previous_status, rule.resulting_status) == (UNDER_REVIEW, PLANNING)
    assert (UNDER_REVIEW, PLANNING) == ("under_review", "planning")
    assert set(TRANSITION_RULES) == {BEGIN_REVIEW, REQUEST_CLARIFICATION, APPROVE}


def test_qa_spl67_036_the_policy_function_applies_the_rule_and_records_evidence(world, client):
    """QA-SPL-67-036 [White-box] AC1,3: transition_event_status(approve) updates and audits."""

    event_id = review_ready_event(client)
    moment = datetime(2026, 10, 1, 9, 30, tzinfo=SINGAPORE)
    with Session(world.extensions["engine"]) as session:
        audit = transition_event_status(
            session,
            event_request_id=event_id,
            action=APPROVE,
            actor_account_id=ALICE,
            changed_at=moment,
        )
        session.commit()
        assert (audit.action, audit.previous_status, audit.resulting_status) == (
            "approve",
            "under_review",
            "planning",
        )
        assert session.get(EventRequest, event_id).status == "planning"


@pytest.mark.parametrize("status", OTHER_STATUSES)
def test_qa_spl67_037_the_policy_function_refuses_every_other_status(world, client, status):
    """QA-SPL-67-037 [White-box] AC1,6: the conditional UPDATE matches no row, nothing is added."""

    event_id = review_ready_event(client)
    set_status(world, event_id, status)
    before = snapshot(world, event_id)
    with Session(world.extensions["engine"]) as session:
        with pytest.raises(InvalidStatusTransition):
            transition_event_status(
                session,
                event_request_id=event_id,
                action=APPROVE,
                actor_account_id=ALICE,
                changed_at=datetime.now(SINGAPORE),
            )
        session.rollback()
    assert_untouched(world, event_id, before)


def test_qa_spl67_038_a_stale_read_cannot_approve_twice(world, client):
    """QA-SPL-67-038 [White-box] AC1,6: the compare-and-swap loses if the status changed first."""

    event_id = review_ready_event(client)
    with (
        Session(world.extensions["engine"]) as first,
        Session(world.extensions["engine"]) as second,
    ):
        assert first.get(EventRequest, event_id).status == "under_review"
        transition_event_status(
            first,
            event_request_id=event_id,
            action=APPROVE,
            actor_account_id=ALICE,
            changed_at=datetime.now(SINGAPORE),
        )
        first.commit()
        with pytest.raises(InvalidStatusTransition):
            transition_event_status(
                second,
                event_request_id=event_id,
                action=APPROVE,
                actor_account_id=ALICE,
                changed_at=datetime.now(SINGAPORE),
            )
    assert len(approvals(world, event_id)) == 1


def test_qa_spl67_039_the_decision_and_the_transition_commit_together(world, client):
    """QA-SPL-67-039 [White-box] AC3,6: a failure recording the approver rolls everything back."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    engine = world.extensions["engine"]

    def fail_on_approver(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith("UPDATE")
            and "approved_by_account_id" in statement
        ):
            raise RuntimeError("simulated failure while recording the approver")

    sa_event.listen(engine, "before_cursor_execute", fail_on_approver)
    try:
        with pytest.raises(RuntimeError, match="simulated failure"):
            approve(client, event_id)
    finally:
        sa_event.remove(engine, "before_cursor_execute", fail_on_approver)
    assert_untouched(world, event_id, before)


def test_qa_spl67_040_serialize_approval_is_null_before_a_decision(world, client):
    """QA-SPL-67-040 [White-box] AC3,4: the serialiser reports no approver for a new request."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        assert serialize_approval(session.get(EventRequest, event_id)) == {
            "approved_by": None,
            "approved_at": None,
        }


def test_qa_spl67_041_serialize_approval_reports_the_approver_in_singapore_time(world, client):
    """QA-SPL-67-041 [White-box] AC3,4: offset-less means Singapore; UTC is converted to +08:00."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    with Session(world.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.approved_at = datetime(2026, 10, 1, 9, 0)  # SQLite hands back offset-less values
        rendered = serialize_approval(event)
        assert rendered["approved_by"] == {"id": ALICE, "name": "Alice Tan"}
        assert rendered["approved_at"] == "2026-10-01T09:00:00+08:00"
        event.approved_at = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
        assert serialize_approval(event)["approved_at"] == "2026-10-01T09:00:00+08:00"
        session.rollback()


def test_qa_spl67_042_the_planning_status_exists_with_its_label(client):
    """QA-SPL-67-042 [White-box] AC3: the vocabulary already owns Planning; no new status added."""

    assert "planning" in EVENT_REQUEST_STATUSES
    assert status_label("planning") == "In planning"
    assert len(EVENT_REQUEST_STATUSES) == 12


# ---- AC4: the responsible Event Organiser can retrieve the approval outcome ---------------------


def test_qa_spl67_043_the_organiser_retrieves_the_outcome(client):
    """QA-SPL-67-043 [Functional] AC4: status, approver and time are on their own request."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert outcome["status"] == "planning"
    assert outcome["status_label"] == "In planning"
    assert outcome["approved_by"] == {"id": ALICE, "name": "Alice Tan"}
    assert outcome["approved_at"]


def test_qa_spl67_044_the_organiser_sees_no_outcome_before_approval(client):
    """QA-SPL-67-044 [Functional] AC4: the fields are present and null while undecided."""

    event_id = review_ready_event(client)
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert "approved_by" in outcome and "approved_at" in outcome
    assert (outcome["approved_by"], outcome["approved_at"]) == (None, None)


def test_qa_spl67_045_the_outcome_appears_in_the_organisers_request_list(client):
    """QA-SPL-67-045 [Functional] AC4: the status table's data source carries the decision."""

    approved = review_ready_event(client)
    waiting = submit_event(client)
    approve(client, approved)
    listed = {
        row["id"]: row
        for row in client.get("/api/event-requests", headers=h("owner")).json["event_requests"]
    }
    assert listed[approved]["approved_by"]["name"] == "Alice Tan"
    assert listed[approved]["status_label"] == "In planning"
    assert listed[waiting]["approved_by"] is None


def test_qa_spl67_046_the_retrieved_time_equals_the_time_returned_to_the_coordinator(client):
    """QA-SPL-67-046 [Functional] AC3,4: both parties see one decision time."""

    event_id = review_ready_event(client)
    decided = approve(client, event_id).json["event"]["approved_at"]
    outcome = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json[
        "event_request"
    ]
    assert datetime.fromisoformat(outcome["approved_at"]) == datetime.fromisoformat(decided)


def test_qa_spl67_047_repeated_reads_return_the_same_outcome(client):
    """QA-SPL-67-047 [Functional] AC4: reading the outcome is idempotent."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    reads = [
        client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json["event_request"]
        for _ in range(3)
    ]
    assert reads[0] == reads[1] == reads[2]


def test_qa_spl67_048_an_organiser_from_another_client_cannot_retrieve_it(client):
    """QA-SPL-67-048 [Security] AC4: a stranger gets 404 on the request and 404 on the org view."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    assert client.get(f"/api/event-requests/{event_id}", headers=h("stranger")).status_code == 404
    org_view = client.get(f"/api/organisation/events/{event_id}", headers=h("stranger"))
    assert org_view.status_code == 404


def test_qa_spl67_049_an_unauthenticated_reader_is_refused(client):
    """QA-SPL-67-049 [Security] AC4: no token, no outcome."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    assert client.get(f"/api/event-requests/{event_id}").status_code == 401


def test_qa_spl67_050_a_colleague_cannot_use_the_organiser_route_to_read_it(client):
    """QA-SPL-67-050 [Security] AC4: the outcome is on the responsible organiser's own route."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    assert client.get(f"/api/event-requests/{event_id}", headers=h("colleague")).status_code == 404


def test_qa_spl67_051_the_read_only_organisation_view_does_not_leak_the_approver(client):
    """QA-SPL-67-051 [Security] AC4: colleagues in the client organisation get no approval keys."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    seen = client.get(f"/api/organisation/events/{event_id}", headers=h("colleague"))
    assert seen.status_code == 200
    assert "approved_by" not in seen.json["event"]
    assert "approved_at" not in seen.json["event"]


def test_qa_spl67_052_the_assigned_coordinator_can_also_read_the_outcome(client):
    """QA-SPL-67-052 [Functional] AC4: the coordinator's own read shows the same decision."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    seen = client.get(f"/api/event-requests/{event_id}", headers=h("alice")).json["event_request"]
    assert seen["approved_by"]["id"] == ALICE


def test_qa_spl67_053_the_outcome_names_the_coordinator_shown_as_responsible(client):
    """QA-SPL-67-053 [Functional] AC4: approver and responsible coordinator agree."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    seen = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json["event_request"]
    assert seen["coordinator"] == seen["approved_by"] == {"id": ALICE, "name": "Alice Tan"}


# ---- AC5: approval does not book a venue, reserve equipment, enable registration, confirm -------


def test_qa_spl67_054_approval_changes_only_the_decision_columns(world, client):
    """QA-SPL-67-054 [White-box] AC5: every other stored column of the request is identical."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)[0]
    approve(client, event_id)
    after = snapshot(world, event_id)[0]
    changed = {key for key in before if before[key] != after[key]}
    assert changed == APPROVAL_COLUMNS


def test_qa_spl67_055_no_venue_booking_is_created(world, client):
    """QA-SPL-67-055 [Functional] AC5: the booking table stays empty."""

    event_id = review_ready_event(client)
    approve(client, event_id)
    with Session(world.extensions["engine"]) as session:
        assert session.scalars(select(VenueBooking)).all() == []
        assert session.get(EventRequest, event_id).venue_id is None


def test_qa_spl67_056_registration_stays_as_the_organiser_left_it(world, client):
    """QA-SPL-67-056 [Functional] AC5: registration is neither enabled nor disabled."""

    event_id = review_ready_event(client, registration_required=False)
    approve(client, event_id)
    with Session(world.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).registration_required is False
    other = review_ready_event(client, registration_required=True, registration_notes="Ticketed")
    approve(client, other)
    with Session(world.extensions["engine"]) as session:
        event = session.get(EventRequest, other)
        assert (event.registration_required, event.registration_notes) == (True, "Ticketed")


def test_qa_spl67_057_equipment_requirements_are_untouched(world, client):
    """QA-SPL-67-057 [Functional] AC5: no equipment line is added, removed or changed."""

    event_id = review_ready_event(
        client, equipment_requirements=[{"equipment_type": "Podium", "quantity": 2}]
    )
    with Session(world.extensions["engine"]) as session:
        before = [
            (line.equipment_type, line.quantity)
            for line in session.get(EventRequest, event_id).equipment_requirements
        ]
    approve(client, event_id)
    with Session(world.extensions["engine"]) as session:
        after = [
            (line.equipment_type, line.quantity)
            for line in session.get(EventRequest, event_id).equipment_requirements
        ]
    assert before == after == [("Podium", 2)]


def test_qa_spl67_058_the_event_is_planning_not_confirmed_or_approved(client):
    """QA-SPL-67-058 [Functional] AC5: approval never yields a confirmed or booked status."""

    event_id = review_ready_event(client)
    status = approve(client, event_id).json["event"]["status"]
    assert status == "planning"
    assert status not in {"confirmed", "approved", "completed"}
    assert TRANSITION_RULES[APPROVE].resulting_status not in {"confirmed", "approved"}


def test_qa_spl67_059_the_venue_and_slots_the_organiser_asked_for_are_kept(world, client):
    """QA-SPL-67-059 [Functional] AC5: date, time, layout, facilities stay as submitted."""

    event_id = review_ready_event(client)
    before = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json["event_request"]
    approve(client, event_id)
    after = client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json["event_request"]
    for key in (
        "proposed_date",
        "start_time",
        "end_time",
        "expected_attendance",
        "preferred_room_layout",
        "required_facilities",
        "venue_id",
        "registration_required",
    ):
        assert after[key] == before[key], key


def test_qa_spl67_060_no_clarification_or_reassignment_side_effect(world, client):
    """QA-SPL-67-060 [White-box] AC5: no clarification row, and the assignment is unchanged."""

    event_id = review_ready_event(client)
    with Session(world.extensions["engine"]) as session:
        history_before = len(session.scalars(select(EventCoordinatorHistory)).all())
    approve(client, event_id)
    with Session(world.extensions["engine"]) as session:
        assignment = session.get(EventCoordinatorAssignment, event_id)
        assert assignment.coordinator_account_id == ALICE
        assert len(session.scalars(select(EventCoordinatorHistory)).all()) == history_before
        assert session.scalars(select(ClarificationRequest)).all() == []


def test_qa_spl67_061_other_events_are_not_affected(world, client):
    """QA-SPL-67-061 [Functional] AC5,6: approving one request leaves the others as they were."""

    approved = review_ready_event(client)
    bystander = review_ready_event(client)
    untouched = snapshot(world, bystander)
    approve(client, approved)
    assert_untouched(world, bystander, untouched)


def test_qa_spl67_062_the_response_offers_no_booking_or_confirmation(client):
    """QA-SPL-67-062 [API] AC5: the approve payload carries no venue, booking or registration."""

    event_id = review_ready_event(client)
    body = approve(client, event_id).json
    assert set(body) == {"event", "transition", "message"}
    assert not {"booking", "venue_booking", "registration", "confirmed"} & set(body["event"])


# ---- AC6: an invalid or unauthorised attempt leaves the event unchanged --------------------------


@pytest.mark.parametrize("status", OTHER_STATUSES)
def test_qa_spl67_063_every_status_other_than_under_review_is_refused(world, client, status):
    """QA-SPL-67-063 [Boundary] AC1,6: 11 statuses, each a 409 that changes nothing."""

    event_id = review_ready_event(client)
    set_status(world, event_id, status)
    before = snapshot(world, event_id)
    response = approve(client, event_id)
    assert response.status_code == 409
    assert response.json == {"error": WRONG_STATUS}
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize(
    "body",
    [
        {"status": "confirmed"},
        {"status": "planning"},
        {"target_status": "confirmed"},
        {"message": "approve"},
        {"a": 1, "b": 2},
        [],
        ["planning"],
        "planning",
        1,
        True,
    ],
)
def test_qa_spl67_064_a_client_supplied_body_is_refused(world, client, body):
    """QA-SPL-67-064 [Security] AC6: the target status is server-owned; any payload is a 400."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    response = approve(client, event_id, json=body)
    assert response.status_code == 400
    assert response.json["error"].startswith("Approval does not accept")
    assert_untouched(world, event_id, before)


def test_qa_spl67_065_a_malformed_body_is_refused(world, client):
    """QA-SPL-67-065 [Negative] AC6: invalid JSON, or a non-JSON body, is a 400."""

    event_id = review_ready_event(client)
    before = snapshot(world, event_id)
    broken = approve(client, event_id, data="{not json", content_type="application/json")
    text = approve(client, event_id, data="approve", content_type="text/plain")
    assert broken.status_code == 400 and text.status_code == 400
    assert_untouched(world, event_id, before)


@pytest.mark.parametrize("kwargs", [{}, {"json": {}}])
def test_qa_spl67_066_no_body_or_an_empty_object_is_accepted(client, kwargs):
    """QA-SPL-67-066 [Boundary] AC1,6: the only accepted payloads carry no parameters."""

    event_id = review_ready_event(client)
    assert approve(client, event_id, **kwargs).status_code == 200


def test_qa_spl67_067_a_query_string_cannot_choose_the_status(world, client):
    """QA-SPL-67-067 [Security] AC6: ?status=confirmed is ignored; the rule table decides."""

    event_id = review_ready_event(client)
    response = approve(client, event_id, query_string={"status": "confirmed"})
    assert response.json["event"]["status"] == "planning"
    assert snapshot(world, event_id)[0]["status"] == "planning"


def test_qa_spl67_068_approving_twice_keeps_the_first_decision(world, client):
    """QA-SPL-67-068 [Negative] AC1,6: the second attempt is a 409; the record is kept."""

    event_id = review_ready_event(client)
    first = approve(client, event_id).json["event"]["approved_at"]
    after_first = snapshot(world, event_id)
    second = approve(client, event_id)
    assert second.status_code == 409
    assert snapshot(world, event_id) == after_first
    assert len(approvals(world, event_id)) == 1
    assert (
        first
        == client.get(f"/api/event-requests/{event_id}", headers=h("owner")).json["event_request"][
            "approved_at"
        ]
    )


def test_qa_spl67_069_a_refused_attempt_does_not_move_the_status_timestamp(world, client):
    """QA-SPL-67-069 [Negative] AC6: status_changed_at is not touched by a refusal."""

    event_id = review_ready_event(client)
    set_status(world, event_id, "submitted")
    before = snapshot(world, event_id)[0]["status_changed_at"]
    approve(client, event_id)
    assert snapshot(world, event_id)[0]["status_changed_at"] == before


def test_qa_spl67_070_a_refusal_writes_no_audit_row(world, client):
    """QA-SPL-67-070 [Negative] AC6: failed attempts leave no approve audit row."""

    event_id = review_ready_event(client)
    approve(client, event_id, token="bob")
    approve(client, event_id, token="owner")
    approve(client, event_id, json={"status": "planning"})
    assert approvals(world, event_id) == []


def test_qa_spl67_071_a_refused_attempt_can_be_followed_by_a_valid_one(world, client):
    """QA-SPL-67-071 [Functional] AC1,6: a refusal does not lock the event."""

    event_id = review_ready_event(client)
    assert approve(client, event_id, token="bob").status_code == 404
    assert approve(client, event_id, json={"status": "x"}).status_code == 400
    assert approve(client, event_id).status_code == 200


# ---- Cross-cutting: contract, performance, migration --------------------------------------------


def test_qa_spl67_072_the_success_response_contract(client):
    """QA-SPL-67-072 [API] AC1,3: JSON content type and the exact response keys."""

    event_id = review_ready_event(client)
    response = approve(client, event_id)
    assert response.content_type == "application/json"
    assert set(response.json) == {"event", "transition", "message"}
    assert {
        "id",
        "name",
        "status",
        "status_label",
        "proposed_date",
        "approved_by",
        "approved_at",
    } <= set(response.json["event"])
    assert set(response.json["transition"]) == {
        "action",
        "previous_status",
        "resulting_status",
        "actor",
        "changed_at",
    }


@pytest.mark.parametrize(
    ("token", "expected"),
    [("bob", 404), ("owner", 403), (None, 401)],
)
def test_qa_spl67_073_error_bodies_use_the_error_key(client, token, expected):
    """QA-SPL-67-073 [API] AC6: every refusal is {"error": "<message>"} with the right status."""

    event_id = review_ready_event(client)
    headers = h(token) if token else {}
    response = client.post(f"/api/event-requests/{event_id}/approve", headers=headers)
    assert response.status_code == expected
    assert isinstance(response.json["error"], str) and response.json["error"]


def test_qa_spl67_074_approval_is_fast_and_uses_few_queries(world, client):
    """QA-SPL-67-074 [Performance] AC3: one approval is a handful of statements, well under 1s."""

    event_id = review_ready_event(client)
    statements: list[str] = []
    engine = world.extensions["engine"]

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", count)
    try:
        started = clock.perf_counter()
        assert approve(client, event_id).status_code == 200
        elapsed = clock.perf_counter() - started
    finally:
        sa_event.remove(engine, "before_cursor_execute", count)
    assert elapsed < 1.0
    assert len(statements) <= 20, statements


def test_qa_spl67_075_thirty_events_approve_in_sequence(world, client):
    """QA-SPL-67-075 [Load] AC1,3: 30 sequential approvals all succeed inside 15 seconds."""

    events = [review_ready_event(client) for _ in range(30)]
    started = clock.perf_counter()
    assert {approve(client, event_id).status_code for event_id in events} == {200}
    assert clock.perf_counter() - started < 15
    with Session(world.extensions["engine"]) as session:
        assert (
            len(
                session.scalars(
                    select(EventStatusHistory).where(EventStatusHistory.action == APPROVE)
                ).all()
            )
            == 30
        )


def test_qa_spl67_076_the_model_columns_are_nullable_and_reference_accounts(world):
    """QA-SPL-67-076 [White-box] AC3: approved_by is a nullable FK to accounts."""

    columns = {
        c["name"]: c for c in inspect(world.extensions["engine"]).get_columns("event_requests")
    }
    assert columns["approved_by_account_id"]["nullable"] is True
    assert columns["approved_at"]["nullable"] is True
    foreign_keys = inspect(world.extensions["engine"]).get_foreign_keys("event_requests")
    assert any(
        fk["constrained_columns"] == ["approved_by_account_id"]
        and fk["referred_table"] == "accounts"
        for fk in foreign_keys
    )


def test_qa_spl67_077_a_new_request_starts_without_a_decision(world, client):
    """QA-SPL-67-077 [White-box] AC3: submission leaves both approval columns null."""

    event_id = submit_event(client)
    columns = snapshot(world, event_id)[0]
    assert (columns["approved_by_account_id"], columns["approved_at"]) == (None, None)


def test_qa_spl67_078_the_migration_extends_the_clarification_head_as_the_only_head(client):
    """QA-SPL-67-078 [White-box] AC3: the migration extends the clarification head."""

    migrations = Path(__file__).resolve().parents[1] / "migrations"
    config = Config()
    config.set_main_option("script_location", str(migrations))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["s2_event_approval"]
    revision = script.get_revision("s2_event_approval")
    assert revision.down_revision == "s2_clarification_requests"


def test_qa_spl67_079_the_migration_source_adds_and_removes_both_columns(client):
    """QA-SPL-67-079 [White-box] AC3: upgrade adds, downgrade drops, both approval columns."""

    source = (
        Path(__file__).resolve().parents[1] / "migrations" / "versions" / "s2_event_approval.py"
    ).read_text()
    upgrade, downgrade = source.split("def downgrade")
    assert "approved_by_account_id" in upgrade and "approved_at" in upgrade
    assert "add_column" in upgrade and "drop_column" not in upgrade
    assert "approved_by_account_id" in downgrade and "approved_at" in downgrade
    assert "drop_column" in downgrade
