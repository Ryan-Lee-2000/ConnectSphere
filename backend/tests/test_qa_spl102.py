"""QA coverage for CS-E20-S2 (SPL-102): be notified of my request's review outcome.

Case IDs QA-SPL-102-NNN match the QA report in the QA space. "BB" is a black-box case that only
uses the public API; "WB" is a white-box case that inspects stored rows, the helper or the
transaction boundary. The triggers are the real existing actions (assign, reassign, request
clarification, approve, reject, withdraw), so no notice is ever seeded for these cases.
"""

from datetime import date, datetime, time

import pytest
import test_request_clarification as base
from app import create_app
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    Organisation,
    Role,
)
from app.notifications import add_review_outcome_notice
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

MANAGER, ORGANISER, ALICE, BOB = base.MANAGER, base.ORGANISER, base.ALICE, base.BOB
RIVAL = "00000000-0000-0000-0000-000000000085"  # another organiser of the same client
ATTENDEE = "00000000-0000-0000-0000-000000000086"
TOKENS = {**base.TOKENS, "rival": RIVAL, "attendee": ATTENDEE}
EVENT_NAME = "Community Forum"
headers = base.headers


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/spl102.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (MANAGER, "Morgan Manager", Role.EVENT_OPERATIONS_MANAGER),
            (ORGANISER, "Olivia Organiser", Role.EVENT_ORGANISER),
            (ALICE, "Alice Tan", Role.EVENT_COORDINATOR),
            (BOB, "Bob Lim", Role.EVENT_COORDINATOR),
            (RIVAL, "Riley Rival", Role.EVENT_ORGANISER),
            (ATTENDEE, "Avery Attendee", Role.ATTENDEE),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    is_active=True,
                    organisation_id=organisation.id,
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
        application.config["TEST_ORGANISATION_ID"] = organisation.id
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def submitted_request(app, *, status="submitted", organiser=ORGANISER) -> int:
    """An event with no coordinator yet, as the manager sees it before assigning."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=organiser,
            organisation_id=app.config["TEST_ORGANISATION_ID"],
            name=EVENT_NAME,
            purpose="Community consultation",
            proposed_date=date(2026, 10, 12),
            start_time=time(9),
            end_time=time(12),
            expected_attendance=120,
            status=status,
            submitted_at=datetime(2026, 9, 20, 9, tzinfo=SINGAPORE),
        )
        session.add(event)
        session.commit()
        return event.id


def assign(client, event_id, coordinator=ALICE, token="manager"):
    return client.post(
        f"/api/event-requests/{event_id}/coordinator",
        headers=headers(token),
        json={"coordinator_account_id": coordinator},
    )


def reassign(client, event_id, coordinator=BOB, token="manager"):
    return client.put(
        f"/api/event-requests/{event_id}/coordinator",
        headers=headers(token),
        json={"coordinator_account_id": coordinator},
    )


def clarify(client, event_id, message=base.MESSAGE, token="alice", body=None):
    return client.post(
        f"/api/event-requests/{event_id}/request-clarification",
        headers=headers(token),
        json={"message": message} if body is None else body,
    )


def respond(client, event_id, clarification_id, token="organiser"):
    return client.post(
        f"/api/event-requests/{event_id}/clarifications/{clarification_id}/respond",
        headers=headers(token),
        json={"response": "Attendance is 120 and the layout is theatre."},
    )


def approve(client, event_id, token="alice"):
    return client.post(f"/api/event-requests/{event_id}/approve", headers=headers(token))


def reject(client, event_id, reason="The venue plan is not workable.", token="alice", body=None):
    return client.post(
        f"/api/event-requests/{event_id}/reject",
        headers=headers(token),
        json={"reason": reason} if body is None else body,
    )


def withdraw(client, event_id, token="alice", body=None):
    kwargs = {} if body is None else {"json": body}
    return client.post(f"/api/event-requests/{event_id}/withdraw", headers=headers(token), **kwargs)


def inbox(client, token="organiser"):
    return client.get("/api/notifications", headers=headers(token))


def inbox_messages(client, token="organiser"):
    return [n["message"] for n in inbox(client, token).get_json()["notifications"]]


def stored_notices(app, recipient=None):
    with Session(app.extensions["engine"]) as session:
        query = select(Notification).order_by(Notification.id)
        if recipient:
            query = query.where(Notification.recipient_account_id == recipient)
        return session.scalars(query).all()


def notice_count(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(Notification))


def status_of(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return session.get(EventRequest, event_id).status


def make_coordinator(app, account_id):
    with Session(app.extensions["engine"]) as session:
        session.add(AccountRole(account_id=account_id, role=Role.EVENT_COORDINATOR.value))
        session.commit()


# ---------------------------------------------------------------------------------------------
# AC1. Assignment or reassignment: the organiser is notified, naming the event.
# (Delivered by SPL-134's shared trigger; SPL-102 only verifies it.)
# ---------------------------------------------------------------------------------------------


# QA-SPL-102-001 | AC1 | BB happy path
def test_qa_spl_102_001_assignment_notifies_the_organiser_naming_the_event(app, client):
    event_id = submitted_request(app)

    assert assign(client, event_id).status_code == 201

    messages = inbox_messages(client)
    assert len(messages) == 1
    assert EVENT_NAME in messages[0]
    assert "Alice Tan" in messages[0]


# QA-SPL-102-002 | AC1 | BB happy path: reassignment
def test_qa_spl_102_002_reassignment_notifies_the_organiser_again_naming_the_event(app, client):
    event_id = submitted_request(app)
    assign(client, event_id)

    assert reassign(client, event_id).status_code == 200

    messages = inbox_messages(client)
    assert len(messages) == 2
    assert all(EVENT_NAME in message for message in messages)
    assert any("Bob Lim" in message and "Alice Tan" in message for message in messages)


# QA-SPL-102-003 | AC1 | BB negative: a refused assignment leaves no notice
def test_qa_spl_102_003_a_refused_assignment_creates_no_notice(app, client):
    event_id = submitted_request(app)
    assign(client, event_id)
    before = notice_count(app)

    assert assign(client, event_id, coordinator=BOB).status_code == 409
    assert assign(client, event_id, token="organiser").status_code == 403
    assert reassign(client, event_id, coordinator=ALICE).status_code == 400  # same coordinator

    assert notice_count(app) == before


# QA-SPL-102-004 | AC1 | BB security: only the organiser of that event receives the organiser notice
def test_qa_spl_102_004_other_organisers_and_attendees_receive_nothing(app, client):
    event_id = submitted_request(app)
    assign(client, event_id)

    assert inbox_messages(client, "rival") == []
    assert inbox_messages(client, "attendee") == []
    assert inbox_messages(client, "manager") == []
    assert inbox_messages(client, "bob") == []


# QA-SPL-102-005 | AC1 | WB: recipient and dedupe key come from the stored event and history row
def test_qa_spl_102_005_the_organiser_notice_is_keyed_to_the_history_row(app, client):
    event_id = submitted_request(app)
    assign(client, event_id)

    notice = stored_notices(app, ORGANISER)[0]

    assert notice.event_request_id == event_id
    assert notice.dedupe_key.startswith("organiser_coordinator_changed:")
    assert notice.read_at is None


# QA-SPL-102-006 | AC1 | BB boundary: an organiser who is also the new coordinator gets one notice
def test_qa_spl_102_006_an_organiser_assigned_to_their_own_event_is_told_once(app, client):
    make_coordinator(app, ORGANISER)
    event_id = submitted_request(app)

    assert assign(client, event_id, coordinator=ORGANISER).status_code == 201

    messages = inbox_messages(client)
    assert len(messages) == 1
    assert EVENT_NAME in messages[0]


# QA-SPL-102-007 | AC1 | BB: the assignment notice is still there after reload
def test_qa_spl_102_007_the_assignment_notice_is_stored_and_survives_reload(app, client):
    event_id = submitted_request(app)
    assign(client, event_id)

    first = inbox(client).get_json()
    second = inbox(client).get_json()

    assert first == second
    assert first["unread_count"] == 1


# ---------------------------------------------------------------------------------------------
# AC2. Clarification requested: the notice names the event and includes the coordinator's message.
# ---------------------------------------------------------------------------------------------


# QA-SPL-102-010 | AC2 | BB happy path
def test_qa_spl_102_010_clarification_notifies_the_organiser_with_event_and_message(app, client):
    event_id = base.assigned_request(app)

    assert clarify(client, event_id).status_code == 200

    messages = inbox_messages(client)
    assert len(messages) == 1
    assert EVENT_NAME in messages[0]
    assert base.MESSAGE in messages[0]


# QA-SPL-102-011 | AC2 | BB: the notice carries the stored (trimmed) message
def test_qa_spl_102_011_the_notice_carries_the_trimmed_message(app, client):
    event_id = base.assigned_request(app)

    clarify(client, event_id, message="   Please confirm the budget.  \n")

    message = inbox_messages(client)[0]
    assert message.endswith("Please confirm the budget.")
    assert not message.endswith(" ")


# QA-SPL-102-012 | AC2 | BB boundary: a 2000-character message is delivered in full
def test_qa_spl_102_012_a_maximum_length_message_is_delivered_in_full(app, client):
    event_id = base.assigned_request(app)
    long_message = "q" * 2000

    assert clarify(client, event_id, message=long_message).status_code == 200

    assert long_message in inbox_messages(client)[0]


# QA-SPL-102-013 | AC2 | BB boundary: one character over the limit is refused with no notice
def test_qa_spl_102_013_an_overlong_message_is_refused_and_creates_no_notice(app, client):
    event_id = base.assigned_request(app)

    assert clarify(client, event_id, message="q" * 2001).status_code == 400

    assert notice_count(app) == 0
    assert status_of(app, event_id) == "under_review"


# QA-SPL-102-014 | AC2 | BB negative: blank, wrong-typed or extra-field bodies create no notice
@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "   "},
        {"message": 7},
        {},
        {"message": "x", "status": "approved"},
    ],
)
def test_qa_spl_102_014_an_invalid_request_creates_no_notice(app, client, body):
    event_id = base.assigned_request(app)

    assert clarify(client, event_id, body=body).status_code == 400

    assert notice_count(app) == 0


# QA-SPL-102-015 | AC2 | BB negative: only an event under review can be questioned
@pytest.mark.parametrize("status", ["submitted", "returned_for_clarification", "planning"])
def test_qa_spl_102_015_a_clarification_outside_review_creates_no_notice(app, client, status):
    event_id = base.assigned_request(app, status=status)

    assert clarify(client, event_id).status_code == 409

    assert notice_count(app) == 0
    assert status_of(app, event_id) == status


# QA-SPL-102-016 | AC2 | BB security: wrong role or unassigned coordinator creates no notice
@pytest.mark.parametrize(("token", "code"), [("manager", 403), ("organiser", 403), ("bob", 404)])
def test_qa_spl_102_016_unauthorised_clarification_creates_no_notice(app, client, token, code):
    event_id = base.assigned_request(app)

    assert clarify(client, event_id, token=token).status_code == code

    assert notice_count(app) == 0


# QA-SPL-102-017 | AC2 | BB: a second round of clarification sends a second, separate notice
def test_qa_spl_102_017_each_clarification_round_has_its_own_notice(app, client):
    event_id = base.assigned_request(app)
    first = clarify(client, event_id, message="First question").get_json()
    respond(client, event_id, first["clarifications"][0]["id"])

    assert clarify(client, event_id, message="Second question").status_code == 200

    messages = inbox_messages(client)
    assert len(messages) == 2
    assert "Second question" in messages[0]
    assert "First question" in messages[1]


# QA-SPL-102-018 | AC2 | WB: the notice commits or rolls back with the transition
def test_qa_spl_102_018_a_failure_while_notifying_rolls_back_the_clarification(
    app, client, monkeypatch
):
    event_id = base.assigned_request(app)

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_review.add_review_outcome_notice", explode)
    with pytest.raises(RuntimeError):
        clarify(client, event_id)

    assert status_of(app, event_id) == "under_review"
    assert notice_count(app) == 0
    clarifications, audit = base.stored_rows(app, event_id)
    assert clarifications == [] and audit == []


# QA-SPL-102-019 | AC2 | BB: the notice is unread, links to the organiser's event page, and the
# coordinator gets nothing
def test_qa_spl_102_019_the_notice_is_unread_and_opens_the_organiser_event_page(app, client):
    event_id = base.assigned_request(app)
    clarify(client, event_id)

    body = inbox(client).get_json()
    notice = body["notifications"][0]

    assert body["unread_count"] == 1
    assert notice["read"] is False
    assert notice["event"] == {"id": event_id, "name": EVENT_NAME}
    assert notice["link"] == f"/workspace/organisation-events/{event_id}"
    assert inbox_messages(client, "alice") == []


# ---------------------------------------------------------------------------------------------
# AC3. Decision: the notice names the event; a rejection includes the reason.
# ---------------------------------------------------------------------------------------------


# QA-SPL-102-020 | AC3 | BB happy path: approval
def test_qa_spl_102_020_approval_notifies_the_organiser_naming_the_event(app, client):
    event_id = base.assigned_request(app)

    assert approve(client, event_id).status_code == 200

    messages = inbox_messages(client)
    assert len(messages) == 1
    assert EVENT_NAME in messages[0]
    assert "approved" in messages[0]
    assert "rejected" not in messages[0]


# QA-SPL-102-021 | AC3 | BB happy path: rejection includes the reason
def test_qa_spl_102_021_rejection_notifies_the_organiser_with_event_and_reason(app, client):
    event_id = base.assigned_request(app)

    assert reject(client, event_id, reason="  Clashes with exams.  ").status_code == 200

    messages = inbox_messages(client)
    assert len(messages) == 1
    assert EVENT_NAME in messages[0]
    assert "rejected" in messages[0]
    assert messages[0].endswith("Reason: Clashes with exams.")


# QA-SPL-102-022 | AC3 | BB boundary: a 2000-character reason is delivered in full
def test_qa_spl_102_022_a_maximum_length_reason_is_delivered_in_full(app, client):
    event_id = base.assigned_request(app)
    reason = "r" * 2000

    assert reject(client, event_id, reason=reason).status_code == 200

    assert reason in inbox_messages(client)[0]


# QA-SPL-102-023 | AC3 | BB negative: an invalid rejection creates no notice
@pytest.mark.parametrize(
    "body",
    [
        {"reason": ""},
        {"reason": "  "},
        {"reason": 3},
        {},
        {"reason": "x" * 2001},
        {"reason": "x", "status": "approved"},
    ],
)
def test_qa_spl_102_023_an_invalid_rejection_creates_no_notice(app, client, body):
    event_id = base.assigned_request(app)

    assert reject(client, event_id, body=body).status_code == 400

    assert notice_count(app) == 0
    assert status_of(app, event_id) == "under_review"


# QA-SPL-102-024 | AC3 | BB negative: a decision outside review creates no notice
@pytest.mark.parametrize(
    "status", ["submitted", "returned_for_clarification", "planning", "rejected"]
)
def test_qa_spl_102_024_a_decision_outside_review_creates_no_notice(app, client, status):
    event_id = base.assigned_request(app, status=status)

    assert approve(client, event_id).status_code == 409
    assert reject(client, event_id).status_code == 409

    assert notice_count(app) == 0


# QA-SPL-102-025 | AC3 | BB "repeated": approving twice sends exactly one notice
def test_qa_spl_102_025_a_repeated_approval_creates_no_second_notice(app, client):
    event_id = base.assigned_request(app)

    assert approve(client, event_id).status_code == 200
    assert approve(client, event_id).status_code == 409

    assert len(inbox_messages(client)) == 1


# QA-SPL-102-026 | AC3 | BB "repeated": rejecting twice sends exactly one notice, first reason kept
def test_qa_spl_102_026_a_repeated_rejection_creates_no_second_notice(app, client):
    event_id = base.assigned_request(app)

    assert reject(client, event_id, reason="First reason").status_code == 200
    assert reject(client, event_id, reason="Second reason").status_code == 409

    messages = inbox_messages(client)
    assert len(messages) == 1
    assert "First reason" in messages[0]
    assert "Second reason" not in messages[0]


# QA-SPL-102-027 | AC3 | BB: a conflicting second decision does not send a contradicting notice
def test_qa_spl_102_027_approve_then_reject_keeps_only_the_approval_notice(app, client):
    event_id = base.assigned_request(app)
    approve(client, event_id)

    assert reject(client, event_id).status_code == 409

    messages = inbox_messages(client)
    assert len(messages) == 1
    assert "approved" in messages[0]


# QA-SPL-102-028 | AC3 | BB security: wrong role or unassigned coordinator decides nothing
@pytest.mark.parametrize(("token", "code"), [("manager", 403), ("organiser", 403), ("bob", 404)])
def test_qa_spl_102_028_unauthorised_decisions_create_no_notice(app, client, token, code):
    event_id = base.assigned_request(app)

    assert approve(client, event_id, token=token).status_code == code
    assert reject(client, event_id, token=token).status_code == code

    assert notice_count(app) == 0
    assert status_of(app, event_id) == "under_review"


# QA-SPL-102-029 | AC3 | BB boundary: the organiser who is also the coordinator is still notified
def test_qa_spl_102_029_an_organiser_deciding_their_own_event_is_still_notified(app, client):
    make_coordinator(app, ORGANISER)
    event_id = submitted_request(app, status="under_review")
    with Session(app.extensions["engine"]) as session:
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event_id,
                coordinator_account_id=ORGANISER,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 21, 9, tzinfo=SINGAPORE),
            )
        )
        session.commit()

    assert approve(client, event_id, token="organiser").status_code == 200

    assert len(inbox_messages(client)) == 1


# QA-SPL-102-030 | AC3 | WB: the decision notice commits or rolls back with the decision
@pytest.mark.parametrize("decide", [approve, reject])
def test_qa_spl_102_030_a_failure_while_notifying_rolls_back_the_decision(
    app, client, monkeypatch, decide
):
    event_id = base.assigned_request(app)

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_review.add_review_outcome_notice", explode)
    with pytest.raises(RuntimeError):
        decide(client, event_id)

    assert status_of(app, event_id) == "under_review"
    assert notice_count(app) == 0
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assert event.approved_at is None and event.rejected_at is None


# QA-SPL-102-031 | AC3 | WB: decision notices are keyed to the status history row
def test_qa_spl_102_031_decision_notices_are_keyed_to_the_status_history(app, client):
    approved = base.assigned_request(app)
    rejected = base.assigned_request(app)
    approve(client, approved)
    reject(client, rejected)

    keys = [notice.dedupe_key for notice in stored_notices(app, ORGANISER)]

    assert len(keys) == 2 and len(set(keys)) == 2
    assert all(key.startswith("organiser_decision:") for key in keys)


# ---------------------------------------------------------------------------------------------
# AC4. Withdrawal: the notice names the event.
# ---------------------------------------------------------------------------------------------


# QA-SPL-102-040 | AC4 | BB happy path from every withdrawable state
@pytest.mark.parametrize("status", ["submitted", "under_review", "returned_for_clarification"])
def test_qa_spl_102_040_withdrawal_notifies_the_organiser_naming_the_event(app, client, status):
    event_id = base.assigned_request(app, status=status)

    assert withdraw(client, event_id).status_code == 200

    messages = inbox_messages(client)
    assert len(messages) == 1
    assert EVENT_NAME in messages[0]
    assert "withdrawal" in messages[0]


# QA-SPL-102-041 | AC4 | BB: the optional note is not copied into the notice
def test_qa_spl_102_041_the_withdrawal_note_is_not_copied_into_the_notice(app, client):
    event_id = base.assigned_request(app)

    assert (
        withdraw(client, event_id, body={"note": "Internal: organiser phoned."}).status_code == 200
    )

    assert "Internal" not in inbox_messages(client)[0]


# QA-SPL-102-042 | AC4 | BB "repeated": withdrawing twice sends exactly one notice
def test_qa_spl_102_042_a_repeated_withdrawal_creates_no_second_notice(app, client):
    event_id = base.assigned_request(app)

    assert withdraw(client, event_id).status_code == 200
    assert withdraw(client, event_id).status_code == 409

    assert len(inbox_messages(client)) == 1


# QA-SPL-102-043 | AC4 | BB negative: states that cannot be withdrawn create no notice
@pytest.mark.parametrize("status", ["planning", "rejected", "withdrawn", "confirmed"])
def test_qa_spl_102_043_a_refused_withdrawal_creates_no_notice(app, client, status):
    event_id = base.assigned_request(app, status=status)

    assert withdraw(client, event_id).status_code == 409

    assert notice_count(app) == 0


# QA-SPL-102-044 | AC4 | BB security: wrong role or unassigned coordinator withdraws nothing
@pytest.mark.parametrize(("token", "code"), [("manager", 403), ("organiser", 403), ("bob", 404)])
def test_qa_spl_102_044_unauthorised_withdrawal_creates_no_notice(app, client, token, code):
    event_id = base.assigned_request(app)

    assert withdraw(client, event_id, token=token).status_code == code

    assert notice_count(app) == 0
    assert status_of(app, event_id) == "under_review"


# QA-SPL-102-045 | AC4 | BB negative: an invalid body creates no notice
@pytest.mark.parametrize("body", [{"note": 5}, {"note": "x" * 2001}, {"status": "approved"}])
def test_qa_spl_102_045_an_invalid_withdrawal_creates_no_notice(app, client, body):
    event_id = base.assigned_request(app)

    assert withdraw(client, event_id, body=body).status_code == 400

    assert notice_count(app) == 0
    assert status_of(app, event_id) == "under_review"


# QA-SPL-102-046 | AC4 | WB: the withdrawal notice commits or rolls back with the withdrawal
def test_qa_spl_102_046_a_failure_while_notifying_rolls_back_the_withdrawal(
    app, client, monkeypatch
):
    event_id = base.assigned_request(app)

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_review.add_review_outcome_notice", explode)
    with pytest.raises(RuntimeError):
        withdraw(client, event_id)

    assert status_of(app, event_id) == "under_review"
    assert notice_count(app) == 0
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).withdrawn_at is None


# QA-SPL-102-047 | AC4 | BB: a blank withdrawal body (no note) still notifies
def test_qa_spl_102_047_a_withdrawal_with_an_empty_note_still_notifies(app, client):
    event_id = base.assigned_request(app)

    assert withdraw(client, event_id, body={"note": ""}).status_code == 200

    assert len(inbox_messages(client)) == 1


# ---------------------------------------------------------------------------------------------
# AC5. No false notices: a refused or repeated action creates nothing, only the organiser is told.
# ---------------------------------------------------------------------------------------------


# QA-SPL-102-050 | AC5 | BB: across a full lifecycle only the organiser of that event is notified
def test_qa_spl_102_050_a_full_review_cycle_notifies_only_the_organiser(app, client):
    event_id = submitted_request(app)
    assign(client, event_id)
    base_notices = {ALICE: len(stored_notices(app, ALICE))}
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "under_review"
        session.commit()

    clarified = clarify(client, event_id).get_json()
    respond(client, event_id, clarified["clarifications"][0]["id"])
    approve(client, event_id)

    # Alice gained one notice, the organiser's answer to her clarification (SPL-103 AC3), and none
    # from the approval; the rival and others none at all.
    assert len(stored_notices(app, ALICE)) == base_notices[ALICE] + 1
    for other in (RIVAL, ATTENDEE, MANAGER, BOB):
        assert stored_notices(app, other) == []
    organiser_notices = stored_notices(app, ORGANISER)
    assert len(organiser_notices) == 3  # assignment, clarification, approval
    assert {n.event_request_id for n in organiser_notices} == {event_id}


# QA-SPL-102-051 | AC5 | BB: every refused review action leaves the notice table unchanged
def test_qa_spl_102_051_every_refused_action_leaves_the_notice_table_unchanged(app, client):
    event_id = base.assigned_request(app, status="planning")

    refused = [
        clarify(client, event_id),
        approve(client, event_id),
        reject(client, event_id),
        reject(client, event_id, body={}),
        withdraw(client, event_id),
        clarify(client, event_id, token="bob"),
        approve(client, event_id, token="attendee"),
    ]

    assert all(response.status_code >= 400 for response in refused)
    assert notice_count(app) == 0


# QA-SPL-102-052 | AC5 | WB: the unique (recipient, dedupe key) constraint blocks a duplicate notice
def test_qa_spl_102_052_the_same_action_cannot_notify_the_organiser_twice(app, client):
    event_id = base.assigned_request(app)
    approve(client, event_id)

    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        key = stored_notices(app, ORGANISER)[0].dedupe_key
        source_id = int(key.split(":")[1])
        add_review_outcome_notice(
            session, event, kind="decision", source_id=source_id, message="duplicate"
        )
        with pytest.raises(IntegrityError):
            session.commit()

    assert len(stored_notices(app, ORGANISER)) == 1


# QA-SPL-102-053 | AC5 | BB security: the recipient cannot be chosen by the request
@pytest.mark.parametrize(
    "extra",
    [{"recipient_account_id": RIVAL}, {"organiser_account_id": RIVAL}, {"account_id": RIVAL}],
)
def test_qa_spl_102_053_a_client_supplied_recipient_is_refused(app, client, extra):
    event_id = base.assigned_request(app)

    assert clarify(client, event_id, body={"message": "Hello", **extra}).status_code == 400
    assert reject(client, event_id, body={"reason": "No", **extra}).status_code == 400
    assert withdraw(client, event_id, body={"note": "x", **extra}).status_code == 400

    assert notice_count(app) == 0


# QA-SPL-102-054 | AC5 | BB: each event's notice goes to that event's own organiser
def test_qa_spl_102_054_the_notice_goes_to_the_organiser_of_that_event(app, client):
    mine = base.assigned_request(app)
    theirs = submitted_request(app, status="under_review", organiser=RIVAL)
    with Session(app.extensions["engine"]) as session:
        session.add(
            EventCoordinatorAssignment(
                event_request_id=theirs,
                coordinator_account_id=ALICE,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 21, 9, tzinfo=SINGAPORE),
            )
        )
        session.commit()

    reject(client, theirs, reason="Not this time")
    approve(client, mine)

    assert [n.event_request_id for n in stored_notices(app, RIVAL)] == [theirs]
    assert [n.event_request_id for n in stored_notices(app, ORGANISER)] == [mine]
    assert "Not this time" not in " ".join(inbox_messages(client))


# QA-SPL-102-055 | AC5 | BB "after reassignment": the old coordinator can no longer act or notify;
# the new coordinator's action still reaches the same organiser
def test_qa_spl_102_055_after_reassignment_only_the_new_coordinator_notifies(app, client):
    event_id = submitted_request(app)
    assign(client, event_id)
    reassign(client, event_id)
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "under_review"
        session.commit()
    before = notice_count(app)

    assert clarify(client, event_id, token="alice").status_code == 404
    assert notice_count(app) == before

    assert clarify(client, event_id, token="bob").status_code == 200
    assert notice_count(app) == before + 1
    assert base.MESSAGE in inbox_messages(client)[0]


# QA-SPL-102-056 | AC5 | BB security: the inbox needs a session and never shows another account's
def test_qa_spl_102_056_the_inbox_requires_a_session_and_stays_private(app, client):
    event_id = base.assigned_request(app)
    approve(client, event_id)

    assert client.get("/api/notifications").status_code == 401
    assert inbox_messages(client, "rival") == []
    notice_id = inbox(client).get_json()["notifications"][0]["id"]
    assert (
        client.post(f"/api/notifications/{notice_id}/read", headers=headers("rival")).status_code
        == 404
    )
    assert inbox(client).get_json()["unread_count"] == 1


# QA-SPL-102-057 | AC5 | BB: reading a notice does not recreate or duplicate it
def test_qa_spl_102_057_reading_a_notice_does_not_create_another(app, client):
    event_id = base.assigned_request(app)
    withdraw(client, event_id)
    notice_id = inbox(client).get_json()["notifications"][0]["id"]

    read = client.post(f"/api/notifications/{notice_id}/read", headers=headers("organiser"))
    assert read.status_code == 200
    assert (
        client.post("/api/notifications/read-all", headers=headers("organiser")).status_code == 200
    )

    assert notice_count(app) == 1
    assert inbox(client).get_json()["unread_count"] == 0
