"""QA coverage for CS-E20-S4 (SPL-103): be notified of new work assigned to me.

Case IDs QA-SPL-103-NNN match the QA report in the QA space. "BB" is a black-box case that only
uses the public API; "WB" is a white-box case that inspects stored rows, the helpers or the
transaction boundary. The triggers are the real existing actions (assign, reassign, request
clarification, respond, submit a change request), so no notice is ever seeded for these cases.

AC1 and AC2 were delivered by SPL-134's shared trigger; these cases verify them from the
coordinator's side. AC3 and AC4 are SPL-103's own code. AC5 spans all four.
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
    EventChangeRequest,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Notification,
    Organisation,
    Role,
)
from app.notifications import add_change_request_submitted_notice
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

MANAGER, ORGANISER, ALICE, BOB = base.MANAGER, base.ORGANISER, base.ALICE, base.BOB
RIVAL = "00000000-0000-0000-0000-000000000185"  # another organiser of the same client
ATTENDEE = "00000000-0000-0000-0000-000000000186"
DUAL = "00000000-0000-0000-0000-000000000187"  # an organiser who also holds the coordinator role
TOKENS = {**base.TOKENS, "rival": RIVAL, "attendee": ATTENDEE, "dual": DUAL}
EVENT_NAME = "Community Forum"
headers = base.headers
ITEM = {"field": "expected_attendance", "requested_value": 150, "reason": "More guests are coming."}
ALL_FIELDS = [
    ("name", "New name", "Event name"),
    ("purpose", "New purpose", "Purpose"),
    ("description", "New description", "Description"),
    ("proposed_date", "2026-12-12", "Proposed date"),
    ("start_time", "10:00", "Start time"),
    ("end_time", "13:00", "End time"),
    ("expected_attendance", 90, "Expected attendance"),
    ("preferred_room_layout", "Theatre", "Preferred room layout"),
    ("required_facilities", ["Stage"], "Required facilities"),
    ("accessibility_needs", ["Hearing loop"], "Accessibility needs"),
    ("venue_notes", "Near the lift", "Venue notes"),
]
WORK_KINDS = (
    "coordinator_assigned",
    "coordinator_removed",
    "clarification_answered",
    "change_request_submitted",
)


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/spl103.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Northstar Community Partners")
        session.add(organisation)
        session.flush()
        for account_id, name, roles in (
            (MANAGER, "Morgan Manager", [Role.EVENT_OPERATIONS_MANAGER]),
            (ORGANISER, "Olivia Organiser", [Role.EVENT_ORGANISER]),
            (ALICE, "Alice Tan", [Role.EVENT_COORDINATOR]),
            (BOB, "Bob Lim", [Role.EVENT_COORDINATOR]),
            (RIVAL, "Riley Rival", [Role.EVENT_ORGANISER]),
            (ATTENDEE, "Avery Attendee", [Role.ATTENDEE]),
            (DUAL, "Dana Dual", [Role.EVENT_ORGANISER, Role.EVENT_COORDINATOR]),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    is_active=True,
                    organisation_id=organisation.id,
                )
            )
            for role in roles:
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


def submitted_request(app, *, status="submitted", organiser=ORGANISER, name=EVENT_NAME) -> int:
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=organiser,
            organisation_id=app.config["TEST_ORGANISATION_ID"],
            name=name,
            purpose="Community consultation",
            proposed_date=date(2026, 12, 5),
            start_time=time(9),
            end_time=time(12),
            expected_attendance=120,
            status=status,
            submitted_at=datetime(2026, 9, 20, 9, tzinfo=SINGAPORE),
        )
        session.add(event)
        session.commit()
        return event.id


def set_status(app, event_id, status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = status
        session.commit()


def assign(client, event_id, coordinator=ALICE, token="manager", body=None):
    return client.post(
        f"/api/event-requests/{event_id}/coordinator",
        headers=headers(token),
        json={"coordinator_account_id": coordinator} if body is None else body,
    )


def reassign(client, event_id, coordinator=BOB, token="manager"):
    return client.put(
        f"/api/event-requests/{event_id}/coordinator",
        headers=headers(token),
        json={"coordinator_account_id": coordinator},
    )


def assigned_event(app, client, *, status="under_review", coordinator=ALICE, **kwargs) -> int:
    """An event assigned through the real endpoint, then moved to ``status``."""

    event_id = submitted_request(app, **kwargs)
    assert assign(client, event_id, coordinator).status_code == 201
    set_status(app, event_id, status)
    return event_id


def clarify(client, event_id, message=base.MESSAGE, token="alice"):
    return client.post(
        f"/api/event-requests/{event_id}/request-clarification",
        headers=headers(token),
        json={"message": message},
    )


def respond(client, event_id, clarification_id, token="organiser", text="Attendance is 120."):
    return client.post(
        f"/api/event-requests/{event_id}/clarifications/{clarification_id}/respond",
        headers=headers(token),
        json={"response": text},
    )


def asked(client, event_id, message=base.MESSAGE) -> int:
    """Alice requests clarification and the new clarification's id is returned."""

    response = clarify(client, event_id, message)
    assert response.status_code == 200
    return response.get_json()["clarifications"][0]["id"]


def change(client, event_id, items=None, token="organiser", body=None):
    payload = body if body is not None else {"items": [ITEM] if items is None else items}
    return client.post(
        f"/api/event-requests/{event_id}/change-requests", headers=headers(token), json=payload
    )


def inbox(client, token="alice"):
    return client.get("/api/notifications", headers=headers(token))


def inbox_messages(client, token="alice"):
    return [n["message"] for n in inbox(client, token).get_json()["notifications"]]


def stored_notices(app, recipient=None):
    with Session(app.extensions["engine"]) as session:
        query = select(Notification).order_by(Notification.id)
        if recipient:
            query = query.where(Notification.recipient_account_id == recipient)
        return session.scalars(query).all()


def of_kind(app, recipient, kind):
    """The recipient's stored notices of one kind (the dedupe key's prefix)."""

    return [
        notice
        for notice in stored_notices(app, recipient)
        if notice.dedupe_key.split(":", 1)[0] == kind
    ]


def work_notices(app, recipient):
    notices = stored_notices(app, recipient)
    return [n for n in notices if n.dedupe_key.split(":", 1)[0] in WORK_KINDS]


def notice_count(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(Notification))


def change_request_count(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(EventChangeRequest))


def history_rows(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(
            select(EventCoordinatorHistory)
            .where(EventCoordinatorHistory.event_request_id == event_id)
            .order_by(EventCoordinatorHistory.id)
        ).all()


# ---------------------------------------------------------------------------------------------
# AC1. Assigned to me: an event assigned or reassigned to me notifies me, naming the event.
# (Delivered by SPL-134's shared trigger; SPL-103 verifies it from the coordinator's side.)
# ---------------------------------------------------------------------------------------------


# QA-SPL-103-001 | AC1 | BB: assignment notifies the new coordinator, naming the event
def test_qa_spl_103_001_assignment_notifies_the_new_coordinator_naming_the_event(app, client):
    event_id = submitted_request(app)

    assert assign(client, event_id, ALICE).status_code == 201

    assert inbox_messages(client, "alice") == [f"You have been assigned to {EVENT_NAME}."]
    assert inbox(client, "alice").get_json()["notifications"][0]["event"] == {
        "id": event_id,
        "name": EVENT_NAME,
    }


# QA-SPL-103-002 | AC1 | BB: reassignment notifies the newly assigned coordinator, naming the event
def test_qa_spl_103_002_reassignment_notifies_the_new_coordinator_naming_the_event(app, client):
    event_id = assigned_event(app, client, status="submitted")

    assert reassign(client, event_id, BOB).status_code == 200

    assert inbox_messages(client, "bob") == [f"You have been assigned to {EVENT_NAME}."]


# QA-SPL-103-003 | AC1 | BB: the notice is unread in my own inbox and opens the assigned-event page
def test_qa_spl_103_003_the_notice_is_unread_and_links_to_the_assigned_event_page(app, client):
    event_id = submitted_request(app)
    assign(client, event_id, ALICE)

    body = inbox(client, "alice").get_json()

    assert body["unread_count"] == 1
    assert body["notifications"][0]["read"] is False
    assert body["notifications"][0]["link"] == f"/workspace/assigned-events/{event_id}"


# QA-SPL-103-004 | AC1 | BB boundary: assigned to A, then B, then A again - A is told each time
def test_qa_spl_103_004_a_coordinator_assigned_twice_to_one_event_is_told_twice(app, client):
    event_id = assigned_event(app, client, status="submitted")
    reassign(client, event_id, BOB)
    reassign(client, event_id, ALICE)

    alice = of_kind(app, ALICE, "coordinator_assigned")
    bob = of_kind(app, BOB, "coordinator_assigned")

    assert len(alice) == 2 and len({n.dedupe_key for n in alice}) == 2
    assert len(bob) == 1


# QA-SPL-103-005 | AC1 | BB negative: an assignment to an account that is not a coordinator is
# refused and notifies nobody
def test_qa_spl_103_005_a_refused_assignment_to_a_non_coordinator_notifies_nobody(app, client):
    event_id = submitted_request(app)

    refused = assign(client, event_id, ATTENDEE)

    assert refused.status_code >= 400
    assert notice_count(app) == 0


# QA-SPL-103-006 | AC1 | BB negative: assigning an already assigned event is refused and the
# coordinator still has exactly one notice
def test_qa_spl_103_006_a_repeated_assignment_adds_no_second_notice(app, client):
    event_id = submitted_request(app)
    assign(client, event_id, ALICE)

    assert assign(client, event_id, ALICE).status_code == 409
    assert assign(client, event_id, BOB).status_code == 409

    assert len(of_kind(app, ALICE, "coordinator_assigned")) == 1
    assert of_kind(app, BOB, "coordinator_assigned") == []


# QA-SPL-103-007 | AC1 | BB security: a submitted recipient cannot redirect the notice
def test_qa_spl_103_007_a_submitted_recipient_cannot_redirect_the_notice(app, client):
    event_id = submitted_request(app)

    assign(
        client,
        event_id,
        body={"coordinator_account_id": ALICE, "recipient_account_id": BOB},
    )

    assert of_kind(app, BOB, "coordinator_assigned") == []
    assert work_notices(app, BOB) == []


# QA-SPL-103-008 | AC1 | BB security: another coordinator, the Lead and an anonymous caller do not
# receive or read my notice
def test_qa_spl_103_008_my_assignment_notice_is_visible_to_me_only(app, client):
    submitted = submitted_request(app)
    assign(client, submitted, ALICE)

    assert inbox_messages(client, "bob") == []
    assert [n for n in stored_notices(app, MANAGER)] == []
    assert client.get("/api/notifications").status_code == 401
    assert inbox(client, "attendee").get_json()["notifications"] == []


# QA-SPL-103-009 | AC1 | WB: the dedupe key is keyed to the assignment's history row
def test_qa_spl_103_009_the_assignment_notice_is_keyed_to_its_history_row(app, client):
    event_id = submitted_request(app)
    assign(client, event_id, ALICE)

    (history,) = history_rows(app, event_id)
    (notice,) = of_kind(app, ALICE, "coordinator_assigned")

    assert notice.dedupe_key == f"coordinator_assigned:{history.id}"


# ---------------------------------------------------------------------------------------------
# AC2. Reassigned away: the previous coordinator is told, naming the event.
# (Delivered by SPL-134's shared trigger; SPL-103 verifies it from the coordinator's side.)
# ---------------------------------------------------------------------------------------------


# QA-SPL-103-010 | AC2 | BB: reassignment notifies the previous coordinator, naming the event
def test_qa_spl_103_010_reassignment_notifies_the_previous_coordinator_naming_the_event(
    app, client
):
    event_id = assigned_event(app, client, status="submitted")

    assert reassign(client, event_id, BOB).status_code == 200

    assert inbox_messages(client, "alice")[0] == (
        f"You are no longer responsible for {EVENT_NAME}. It has been reassigned to Bob Lim."
    )


# QA-SPL-103-011 | AC2 | BB: the notice is unread in the previous coordinator's inbox
def test_qa_spl_103_011_the_removal_notice_is_unread_in_the_previous_coordinators_inbox(
    app, client
):
    event_id = assigned_event(app, client, status="submitted")
    reassign(client, event_id, BOB)

    body = inbox(client, "alice").get_json()
    removal = [n for n in body["notifications"] if "no longer responsible" in n["message"]]

    assert len(removal) == 1
    assert removal[0]["read"] is False and removal[0]["event"]["name"] == EVENT_NAME
    assert body["unread_count"] == 2  # the original assignment and the removal


# QA-SPL-103-012 | AC2 | BB negative: a first assignment has no previous coordinator, so nobody
# is told they are no longer responsible
def test_qa_spl_103_012_a_first_assignment_sends_no_removal_notice(app, client):
    event_id = submitted_request(app)

    assign(client, event_id, ALICE)

    assert [n for n in stored_notices(app) if n.dedupe_key.startswith("coordinator_removed")] == []


# QA-SPL-103-013 | AC2 | BB negative: a refused reassignment sends no removal notice
@pytest.mark.parametrize("status", ["completed", "cancelled", "rejected", "withdrawn"])
def test_qa_spl_103_013_a_refused_reassignment_sends_no_removal_notice(app, client, status):
    event_id = assigned_event(app, client, status=status)
    before = notice_count(app)

    refused = reassign(client, event_id, BOB)

    assert refused.status_code == 409
    assert notice_count(app) == before
    assert of_kind(app, ALICE, "coordinator_removed") == []


# QA-SPL-103-014 | AC2 | BB boundary: A -> B -> A -> B tells A twice and B once, never the
# coordinator who was just assigned
def test_qa_spl_103_014_each_hand_over_tells_only_the_coordinator_who_lost_the_event(app, client):
    event_id = assigned_event(app, client, status="submitted")
    reassign(client, event_id, BOB)
    reassign(client, event_id, ALICE)
    reassign(client, event_id, BOB)

    assert len(of_kind(app, ALICE, "coordinator_removed")) == 2
    assert len(of_kind(app, BOB, "coordinator_removed")) == 1


# QA-SPL-103-015 | AC2 | BB access after reassignment: the previous coordinator keeps the notice
# but can no longer open the event; the new coordinator can
def test_qa_spl_103_015_after_reassignment_the_previous_coordinator_loses_access(app, client):
    event_id = assigned_event(app, client, status="submitted")
    reassign(client, event_id, BOB)

    assert of_kind(app, ALICE, "coordinator_removed")
    url = f"/api/event-requests/assigned/{event_id}"
    assert client.get(url, headers=headers("alice")).status_code == 404
    assert client.get(url, headers=headers("bob")).status_code == 200


# QA-SPL-103-016 | AC2 | BB negative: repeating the same reassignment is refused and adds no
# second removal notice
def test_qa_spl_103_016_a_repeated_reassignment_adds_no_second_removal_notice(app, client):
    event_id = assigned_event(app, client, status="submitted")
    reassign(client, event_id, BOB)

    again = reassign(client, event_id, BOB)

    assert again.status_code == 400  # Bob already holds the event: choose a different coordinator
    assert len(of_kind(app, ALICE, "coordinator_removed")) == 1


# QA-SPL-103-017 | AC2 | WB: the dedupe key is keyed to the reassignment's history row
def test_qa_spl_103_017_the_removal_notice_is_keyed_to_its_history_row(app, client):
    event_id = assigned_event(app, client, status="submitted")
    reassign(client, event_id, BOB)

    _, reassignment = history_rows(app, event_id)
    (notice,) = of_kind(app, ALICE, "coordinator_removed")

    assert notice.dedupe_key == f"coordinator_removed:{reassignment.id}"


# ---------------------------------------------------------------------------------------------
# AC3. Clarification answered: the organiser's response notifies the coordinator who asked.
# ---------------------------------------------------------------------------------------------


# QA-SPL-103-020 | AC3 | BB: the response notifies the coordinator who asked, naming the event
def test_qa_spl_103_020_the_response_notifies_the_asking_coordinator_naming_the_event(app, client):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)

    assert respond(client, event_id, clarification_id).status_code == 200

    assert (
        f"The organiser responded to your clarification request on {EVENT_NAME}."
        in inbox_messages(client, "alice")
    )
    assert len(of_kind(app, ALICE, "clarification_answered")) == 1


# QA-SPL-103-021 | AC3 | BB: the response text is not copied into the notice
def test_qa_spl_103_021_the_response_text_is_not_copied_into_the_notice(app, client):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)
    respond(client, event_id, clarification_id, text="Private detail 4242 for the coordinator.")

    (notice,) = of_kind(app, ALICE, "clarification_answered")

    assert "4242" not in notice.message and "Private detail" not in notice.message


# QA-SPL-103-022 | AC3 | BB: the notice is unread, opens the assigned-event page and is still one
# notice after reloading the inbox
def test_qa_spl_103_022_the_notice_is_unread_linked_and_stable_across_reloads(app, client):
    event_id = assigned_event(app, client)
    respond(client, event_id, asked(client, event_id))

    first = inbox(client, "alice").get_json()
    second = inbox(client, "alice").get_json()
    answered = [n for n in second["notifications"] if "responded to your" in n["message"]]

    assert len(answered) == 1 and answered[0]["read"] is False
    assert answered[0]["link"] == f"/workspace/assigned-events/{event_id}"
    assert first["unread_count"] == second["unread_count"]


# QA-SPL-103-023 | AC3 | BB negative: every refused response leaves no notice
def test_qa_spl_103_023_a_refused_response_creates_no_notice(app, client):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)
    other_event = assigned_event(app, client)
    before = notice_count(app)

    refusals = [
        respond(client, event_id, clarification_id, text=""),  # nothing to send
        respond(client, event_id, clarification_id, token="rival"),  # not the owner
        respond(client, event_id, clarification_id, token="alice"),  # coordinators cannot answer
        respond(client, event_id, clarification_id, token="attendee"),
        respond(client, event_id, 999999),  # unknown clarification
        respond(client, other_event, clarification_id),  # clarification of another event
        client.post(
            f"/api/event-requests/{event_id}/clarifications/{clarification_id}/respond",
            json={"response": "No session."},
        ),
    ]

    assert [r.status_code for r in refusals][0] == 400
    assert all(r.status_code >= 400 for r in refusals)
    assert notice_count(app) == before
    assert of_kind(app, ALICE, "clarification_answered") == []


# QA-SPL-103-024 | AC3 | BB negative: answering twice is refused and there is still one notice
def test_qa_spl_103_024_a_repeated_response_adds_no_second_notice(app, client):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)
    respond(client, event_id, clarification_id)

    again = respond(client, event_id, clarification_id)

    assert again.status_code == 409
    assert len(of_kind(app, ALICE, "clarification_answered")) == 1


# QA-SPL-103-025 | AC3 | BB boundary: a 2000-character response is accepted and notifies once;
# 2001 characters is refused and notifies nobody
def test_qa_spl_103_025_the_response_length_limit_decides_whether_a_notice_is_sent(app, client):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)

    too_long = respond(client, event_id, clarification_id, text="x" * 2001)
    assert too_long.status_code == 400
    assert of_kind(app, ALICE, "clarification_answered") == []

    assert respond(client, event_id, clarification_id, text="x" * 2000).status_code == 200
    assert len(of_kind(app, ALICE, "clarification_answered")) == 1


# QA-SPL-103-026 | AC3 | BB boundary: two question-and-answer rounds give two separate notices
def test_qa_spl_103_026_each_answered_clarification_gets_its_own_notice(app, client):
    event_id = assigned_event(app, client)
    first = asked(client, event_id, "First question")
    respond(client, event_id, first)
    second = asked(client, event_id, "Second question")
    respond(client, event_id, second)

    notices = of_kind(app, ALICE, "clarification_answered")

    assert [n.dedupe_key for n in notices] == [
        f"clarification_answered:{first}",
        f"clarification_answered:{second}",
    ]


# QA-SPL-103-027 | AC3 | BB after reassignment: the coordinator who asked is told, not the one who
# now holds the event
def test_qa_spl_103_027_after_reassignment_the_coordinator_who_asked_is_told(app, client):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)
    assert reassign(client, event_id, BOB).status_code == 200

    assert respond(client, event_id, clarification_id).status_code == 200

    assert len(of_kind(app, ALICE, "clarification_answered")) == 1
    assert of_kind(app, BOB, "clarification_answered") == []


# QA-SPL-103-028 | AC3 | BB security: only the coordinator who asked is notified
def test_qa_spl_103_028_nobody_but_the_asking_coordinator_is_notified(app, client):
    event_id = assigned_event(app, client)
    respond(client, event_id, asked(client, event_id))

    for account in (BOB, MANAGER, ORGANISER, RIVAL, ATTENDEE, DUAL):
        assert of_kind(app, account, "clarification_answered") == []


# QA-SPL-103-029 | AC3 | WB: the dedupe key is the clarification id and the database refuses a
# second notice for the same clarification
def test_qa_spl_103_029_the_database_refuses_a_duplicate_clarification_notice(app, client):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)
    respond(client, event_id, clarification_id)
    (notice,) = of_kind(app, ALICE, "clarification_answered")
    assert notice.dedupe_key == f"clarification_answered:{clarification_id}"

    with Session(app.extensions["engine"]) as session:
        session.add(
            Notification(
                recipient_account_id=ALICE,
                event_request_id=event_id,
                message="duplicate",
                dedupe_key=notice.dedupe_key,
                created_at=datetime.now(SINGAPORE),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


# QA-SPL-103-030 | AC3 | WB: a failure while notifying rolls the response back
def test_qa_spl_103_030_a_failure_while_notifying_rolls_back_the_response(app, client, monkeypatch):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)
    before = notice_count(app)

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_review.add_clarification_answered_notice", explode)
    with pytest.raises(RuntimeError):
        respond(client, event_id, clarification_id)

    clarifications, _ = base.stored_rows(app, event_id)
    assert clarifications[0].response is None
    assert base.stored_status(app, event_id) == "returned_for_clarification"
    assert notice_count(app) == before


# ---------------------------------------------------------------------------------------------
# AC4. Change request submitted: the assigned coordinator is told, naming the event.
# ---------------------------------------------------------------------------------------------


# QA-SPL-103-040 | AC4 | BB: a change request notifies the assigned coordinator, naming the event
def test_qa_spl_103_040_a_change_request_notifies_the_assigned_coordinator(app, client):
    event_id = assigned_event(app, client)

    assert change(client, event_id).status_code == 201

    assert (
        f"A change request was submitted on {EVENT_NAME}: Expected attendance."
        in inbox_messages(client, "alice")
    )


# QA-SPL-103-041 | AC4 | BB: the notice lists the changed fields in order and none of the values
# or reasons
def test_qa_spl_103_041_the_notice_names_the_fields_but_not_values_or_reasons(app, client):
    event_id = assigned_event(app, client)
    items = [
        {"field": "venue_notes", "requested_value": "SECRET-VALUE-77", "reason": "SECRET-REASON"},
        {"field": "expected_attendance", "requested_value": 61, "reason": "Another reason."},
    ]

    assert change(client, event_id, items).status_code == 201

    (notice,) = of_kind(app, ALICE, "change_request_submitted")
    assert notice.message == (
        f"A change request was submitted on {EVENT_NAME}: Venue notes, Expected attendance."
    )
    assert "SECRET" not in notice.message and "61" not in notice.message


# QA-SPL-103-042 | AC4 | BB: the notice is unread, opens the assigned-event page and is one notice
# after reloading the inbox
def test_qa_spl_103_042_the_notice_is_unread_linked_and_stable_across_reloads(app, client):
    event_id = assigned_event(app, client)
    change(client, event_id)

    inbox(client, "alice")
    body = inbox(client, "alice").get_json()
    submitted = [n for n in body["notifications"] if "change request" in n["message"]]

    assert len(submitted) == 1 and submitted[0]["read"] is False
    assert submitted[0]["link"] == f"/workspace/assigned-events/{event_id}"


# QA-SPL-103-043 | AC4 | BB boundary: one field, and every changeable field in one request
def test_qa_spl_103_043_the_notice_lists_every_field_of_the_largest_request(app, client):
    event_id = assigned_event(app, client)
    items = [{"field": f, "requested_value": v, "reason": "Needed."} for f, v, _ in ALL_FIELDS]

    assert change(client, event_id, items).status_code == 201

    (notice,) = of_kind(app, ALICE, "change_request_submitted")
    for _, _, label in ALL_FIELDS:
        assert label in notice.message
    assert notice.message.count(",") == len(ALL_FIELDS) - 1


# QA-SPL-103-044 | AC4 | BB boundary: each status that allows a change request notifies
@pytest.mark.parametrize("status", ["under_review", "planning", "confirmed"])
def test_qa_spl_103_044_every_allowed_status_notifies(app, client, status):
    event_id = assigned_event(app, client, status=status)

    assert change(client, event_id).status_code == 201

    assert len(of_kind(app, ALICE, "change_request_submitted")) == 1


# QA-SPL-103-045 | AC4 | BB negative: every refused submission leaves no notice and no request
def test_qa_spl_103_045_a_refused_submission_creates_no_notice(app, client):
    event_id = assigned_event(app, client)
    submitted = assigned_event(app, client, status="submitted")
    cancelled = assigned_event(app, client, status="cancelled")
    before = notice_count(app)

    refusals = [
        change(client, event_id, body={"items": []}),  # empty
        change(client, event_id, [{"field": "status", "requested_value": "x", "reason": "r"}]),
        change(client, event_id, body={"items": [ITEM], "recipient_account_id": BOB}),
        change(client, event_id, token="rival"),  # another organiser
        change(client, event_id, token="alice"),  # a coordinator
        change(client, event_id, token="attendee"),
        client.post(f"/api/event-requests/{event_id}/change-requests", json={"items": [ITEM]}),
        change(client, submitted),  # not yet changeable
        change(client, cancelled),  # closed
    ]

    assert all(r.status_code >= 400 for r in refusals)
    assert notice_count(app) == before
    assert change_request_count(app) == 0
    assert of_kind(app, ALICE, "change_request_submitted") == []


# QA-SPL-103-046 | AC4 | BB negative: a second request while one is pending is refused and does not
# add a second notice
def test_qa_spl_103_046_a_second_pending_request_adds_no_second_notice(app, client):
    event_id = assigned_event(app, client)
    change(client, event_id)

    assert change(client, event_id).status_code == 409

    assert len(of_kind(app, ALICE, "change_request_submitted")) == 1


# QA-SPL-103-047 | AC4 | BB: an event with no assigned coordinator still accepts the request and
# notifies nobody
def test_qa_spl_103_047_an_unassigned_event_notifies_nobody_and_still_saves(app, client):
    event_id = submitted_request(app, status="under_review")

    assert change(client, event_id).status_code == 201

    assert change_request_count(app) == 1
    assert notice_count(app) == 0


# QA-SPL-103-048 | AC4 | BB after reassignment: the coordinator who now holds the event is told,
# not the previous one
def test_qa_spl_103_048_after_reassignment_the_current_coordinator_is_told(app, client):
    event_id = assigned_event(app, client)
    assert reassign(client, event_id, BOB).status_code == 200

    change(client, event_id)

    assert len(of_kind(app, BOB, "change_request_submitted")) == 1
    assert of_kind(app, ALICE, "change_request_submitted") == []


# QA-SPL-103-049 | AC4 | BB security: only the assigned coordinator is notified
def test_qa_spl_103_049_nobody_but_the_assigned_coordinator_is_notified(app, client):
    event_id = assigned_event(app, client)
    change(client, event_id)

    for account in (BOB, MANAGER, ORGANISER, RIVAL, ATTENDEE, DUAL):
        assert of_kind(app, account, "change_request_submitted") == []


# QA-SPL-103-050 | AC4 | WB: the dedupe key is the change request id and the database refuses a
# second notice for it
def test_qa_spl_103_050_the_database_refuses_a_duplicate_change_request_notice(app, client):
    event_id = assigned_event(app, client)
    created = change(client, event_id).get_json()["change_request"]
    (notice,) = of_kind(app, ALICE, "change_request_submitted")
    assert notice.dedupe_key == f"change_request_submitted:{created['id']}"

    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        with pytest.raises(IntegrityError):
            add_change_request_submitted_notice(
                session, event, change_request_id=created["id"], field_labels=["Purpose"]
            )
            session.commit()


# QA-SPL-103-051 | AC4 | WB: a failure while notifying rolls the change request back
def test_qa_spl_103_051_a_failure_while_notifying_rolls_back_the_change_request(
    app, client, monkeypatch
):
    event_id = assigned_event(app, client)
    before = notice_count(app)

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_change_requests.add_change_request_submitted_notice", explode)
    with pytest.raises(RuntimeError):
        change(client, event_id)

    assert change_request_count(app) == 0
    assert notice_count(app) == before


# QA-SPL-103-052 | AC4 | WB: when the partial unique index is the only thing that stops a second
# pending request, it is refused with 409 and no notice is added
def test_qa_spl_103_052_the_unique_index_backstop_leaves_no_second_notice(app, client, monkeypatch):
    from app import event_change_requests as module

    event_id = assigned_event(app, client)
    change(client, event_id)
    monkeypatch.setattr(module, "_pending_request", lambda session, event_request_id: None)

    assert change(client, event_id).status_code == 409

    assert len(of_kind(app, ALICE, "change_request_submitted")) == 1
    assert change_request_count(app) == 1


# QA-SPL-103-053 | AC4 | WB: an organiser who is also the assigned coordinator is still notified
def test_qa_spl_103_053_an_organiser_who_is_also_the_coordinator_is_notified(app, client):
    event_id = submitted_request(app, organiser=DUAL, status="under_review")
    with Session(app.extensions["engine"]) as session:
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event_id,
                coordinator_account_id=DUAL,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 21, 9, tzinfo=SINGAPORE),
            )
        )
        session.commit()

    assert change(client, event_id, token="dual").status_code == 201

    assert len(of_kind(app, DUAL, "change_request_submitted")) == 1


# ---------------------------------------------------------------------------------------------
# AC5. No false notices: a refused or repeated action creates nothing; uninvolved coordinators
# are not notified.
# ---------------------------------------------------------------------------------------------


def run_lifecycle(app, client):
    """Assign Alice, ask, answer, change request, then reassign to Bob. Returns the event id."""

    event_id = submitted_request(app)
    assign(client, event_id, ALICE)
    set_status(app, event_id, "under_review")
    respond(client, event_id, asked(client, event_id))
    change(client, event_id)
    reassign(client, event_id, BOB)
    return event_id


# QA-SPL-103-060 | AC5 | BB: across a full lifecycle each account gets exactly the notices it earned
def test_qa_spl_103_060_a_full_lifecycle_notifies_each_account_exactly_once_per_event(app, client):
    run_lifecycle(app, client)

    assert [len(of_kind(app, ALICE, k)) for k in WORK_KINDS] == [1, 1, 1, 1]
    assert [len(of_kind(app, BOB, k)) for k in WORK_KINDS] == [1, 0, 0, 0]
    for account in (MANAGER, RIVAL, ATTENDEE):
        assert stored_notices(app, account) == []
    # The organiser's own assignment notices belong to SPL-134 and SPL-102; SPL-103 adds none.
    assert of_kind(app, ORGANISER, "change_request_submitted") == []
    assert of_kind(app, ORGANISER, "clarification_answered") == []
    assert of_kind(app, ORGANISER, "coordinator_removed") == []


# QA-SPL-103-061 | AC5 | BB: refused attempts at all four triggers leave the notice table unchanged
def test_qa_spl_103_061_refused_actions_leave_the_notice_table_unchanged(app, client):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)
    before = notice_count(app)

    refused = [
        assign(client, event_id, ALICE, token="alice"),  # a coordinator cannot assign
        reassign(client, event_id, BOB, token="alice"),
        reassign(client, event_id, ALICE),  # same coordinator
        respond(client, event_id, clarification_id, token="rival"),
        respond(client, event_id, clarification_id, text=" "),
        change(client, event_id, token="rival"),
        change(client, event_id, body={"items": [{"field": "name"}]}),
    ]

    assert all(r.status_code >= 400 for r in refused)
    assert notice_count(app) == before


# QA-SPL-103-062 | AC5 | BB: replaying every action a second time adds nothing
def test_qa_spl_103_062_repeated_actions_add_no_notices(app, client):
    event_id = submitted_request(app)
    assign(client, event_id, ALICE)
    set_status(app, event_id, "under_review")
    clarification_id = asked(client, event_id)
    respond(client, event_id, clarification_id)
    change(client, event_id)
    reassign(client, event_id, BOB)
    settled = notice_count(app)

    replays = [
        assign(client, event_id, ALICE),
        reassign(client, event_id, BOB),
        respond(client, event_id, clarification_id),
        change(client, event_id),
    ]

    # Assignment, response and change request are 409 conflicts; naming the coordinator who
    # already holds the event is a 400.
    assert [r.status_code for r in replays] == [409, 400, 409, 409]
    assert notice_count(app) == settled


# QA-SPL-103-063 | AC5 | BB: a coordinator who is not involved never gets a notice about the event
def test_qa_spl_103_063_an_uninvolved_coordinator_is_never_notified(app, client):
    event_id = submitted_request(app)
    assign(client, event_id, ALICE)
    set_status(app, event_id, "under_review")
    respond(client, event_id, asked(client, event_id))
    change(client, event_id)

    assert stored_notices(app, BOB) == []
    assert inbox(client, "bob").get_json() == {"notifications": [], "unread_count": 0}


# QA-SPL-103-064 | AC5 | BB: two events with different coordinators notify only their own
def test_qa_spl_103_064_notices_follow_the_event_not_the_other_coordinator(app, client):
    alice_event = assigned_event(app, client, coordinator=ALICE, name="Alice Forum")
    bob_event = assigned_event(app, client, coordinator=BOB, name="Bob Summit")

    change(client, bob_event)
    respond(client, alice_event, asked(client, alice_event))

    bob_work = [n.event_request_id for n in of_kind(app, BOB, "change_request_submitted")]
    alice_work = [n.event_request_id for n in of_kind(app, ALICE, "clarification_answered")]
    assert bob_work == [bob_event] and alice_work == [alice_event]
    assert of_kind(app, ALICE, "change_request_submitted") == []
    assert of_kind(app, BOB, "clarification_answered") == []


# QA-SPL-103-065 | AC5 | BB: reading and marking notices read creates none
def test_qa_spl_103_065_reading_the_inbox_creates_no_notices(app, client):
    run_lifecycle(app, client)
    settled = notice_count(app)

    inbox(client, "alice")
    client.post("/api/notifications/read-all", headers=headers("alice"))
    inbox(client, "bob")

    assert notice_count(app) == settled


# QA-SPL-103-066 | AC5 | BB: an unrelated account sees an empty inbox
def test_qa_spl_103_066_an_unrelated_account_has_an_empty_inbox(app, client):
    run_lifecycle(app, client)

    assert inbox(client, "attendee").get_json() == {"notifications": [], "unread_count": 0}
    assert inbox(client, "rival").get_json() == {"notifications": [], "unread_count": 0}


# QA-SPL-103-067 | AC5 | WB: a failed trigger leaves every stored notice exactly as it was
def test_qa_spl_103_067_a_rolled_back_trigger_leaves_stored_notices_unchanged(
    app, client, monkeypatch
):
    event_id = assigned_event(app, client)
    clarification_id = asked(client, event_id)
    other_event = assigned_event(app, client)
    snapshot = [(n.recipient_account_id, n.dedupe_key) for n in stored_notices(app)]

    def explode(*args, **kwargs):
        raise RuntimeError("notice failed")

    monkeypatch.setattr("app.event_review.add_clarification_answered_notice", explode)
    monkeypatch.setattr("app.event_change_requests.add_change_request_submitted_notice", explode)
    with pytest.raises(RuntimeError):
        respond(client, event_id, clarification_id)
    with pytest.raises(RuntimeError):
        change(client, other_event)

    assert [(n.recipient_account_id, n.dedupe_key) for n in stored_notices(app)] == snapshot
