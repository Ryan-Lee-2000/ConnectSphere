"""QA coverage for CS-E20-S1 (SPL-101): the personal notification inbox.

Case IDs QA-SPL-101-NNN match the QA report in the QA space. "BB" is a black-box case that only
uses the public API; "WB" is a white-box case that inspects or drives internals (the helper, the
stored rows, the transaction boundary). Accounts and request helpers come from the
coordinator-assignment tests, whose existing assignment action is this story's real trigger.
"""

import time
from datetime import datetime, timedelta

import pytest
import test_coordinator_assignment as assignment
from app import coordinator_assignment
from app.event_requests import SINGAPORE
from app.models import (
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Notification,
)
from app.notifications import _timestamp, add_coordinator_assigned_notice
from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_coordinator_assignment import (
    ALICE,
    BOB,
    INACTIVE_COORDINATOR,
    VENUE_STAFF,
    add_request,
    assign,
    deactivate,
    headers,
    reassign,
    set_status,
)

# Re-exported as plain assignments (not imports) so test parameters named `app` and `client`
# are not flagged as redefinitions; pytest still finds them by these names.
app = assignment.app
client = assignment.client

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=SINGAPORE)


def add_notice(app, recipient, event_id, message="Something happened", *, minutes=0, read=False):
    with Session(app.extensions["engine"]) as session:
        notice = Notification(
            recipient_account_id=recipient,
            event_request_id=event_id,
            message=message,
            dedupe_key=f"seed:{recipient}:{message}:{minutes}",
            created_at=NOW + timedelta(minutes=minutes),
            read_at=NOW if read else None,
        )
        session.add(notice)
        session.commit()
        return notice.id


def inbox(client, token="coordinator"):
    return client.get("/api/notifications", headers=headers(token))


def notice_count(app, recipient=None):
    with Session(app.extensions["engine"]) as session:
        query = select(func.count()).select_from(Notification)
        if recipient:
            query = query.where(Notification.recipient_account_id == recipient)
        return session.scalar(query)


def read_at(app, notice_id):
    with Session(app.extensions["engine"]) as session:
        return session.get(Notification, notice_id).read_at


def open_event(client, event_id, token):
    return client.get(f"/api/event-requests/assigned/{event_id}", headers=headers(token))


# ---------------------------------------------------------------------------------------------
# AC1. A user sees only their own notices, newest first, with the required details.
# ---------------------------------------------------------------------------------------------


# QA-SPL-101-001 | AC1 | BB happy path
def test_qa_spl_101_001_inbox_is_newest_first_with_event_time_and_read_state(app, client):
    event_id = add_request(app, "Harbour Summit")
    add_notice(app, ALICE, event_id, "older", minutes=0, read=True)
    add_notice(app, ALICE, event_id, "newer", minutes=5)

    response = inbox(client)

    assert response.status_code == 200
    first, second = response.get_json()["notifications"]
    assert [first["message"], second["message"]] == ["newer", "older"]
    assert first["event"] == {"id": event_id, "name": "Harbour Summit"}
    assert first["created_at"] == (NOW + timedelta(minutes=5)).isoformat()
    assert (first["read"], second["read"]) == (False, True)


# QA-SPL-101-002 | AC1 | BB boundary: identical timestamps keep a stable newest-first order
def test_qa_spl_101_002_notices_with_the_same_time_order_by_newest_id_first(app, client):
    event_id = add_request(app)
    first = add_notice(app, ALICE, event_id, "first", minutes=0)
    second = add_notice(app, ALICE, event_id, "second", minutes=1)
    with Session(app.extensions["engine"]) as session:
        session.get(Notification, second).created_at = NOW
        session.commit()

    ids = [n["id"] for n in inbox(client).get_json()["notifications"]]

    assert ids == [second, first]


# QA-SPL-101-003 | AC1 | BB cross-cut: account isolation
def test_qa_spl_101_003_inbox_never_includes_another_accounts_notices(app, client):
    event_id = add_request(app)
    add_notice(app, ALICE, event_id, "for alice")
    add_notice(app, BOB, event_id, "for bob")

    alice = inbox(client, "coordinator").get_json()
    bob = inbox(client, "coordinator-b").get_json()

    assert [n["message"] for n in alice["notifications"]] == ["for alice"]
    assert [n["message"] for n in bob["notifications"]] == ["for bob"]
    assert alice["unread_count"] == bob["unread_count"] == 1


# QA-SPL-101-004 | AC1 | BB boundary: empty inbox for every role
@pytest.mark.parametrize("token", ["manager", "organiser", "coordinator", "venue-staff"])
def test_qa_spl_101_004_every_role_has_an_empty_inbox_by_default(app, client, token):
    response = inbox(client, token)

    assert response.status_code == 200
    assert response.get_json() == {"notifications": [], "unread_count": 0}


# QA-SPL-101-005 | AC1 | BB negative: no session, deactivated account
def test_qa_spl_101_005_inbox_requires_a_signed_in_active_account(app, client):
    event_id = add_request(app)
    add_notice(app, ALICE, event_id)

    assert client.get("/api/notifications").status_code == 401
    assert client.get("/api/notifications", headers={"Authorization": "Bearer "}).status_code == 401
    deactivate(app, ALICE)
    assert inbox(client, "coordinator").status_code == 403


# QA-SPL-101-006 | AC1 | BB negative: a client-supplied account never selects the inbox
def test_qa_spl_101_006_client_supplied_account_ids_are_ignored(app, client):
    event_id = add_request(app)
    add_notice(app, BOB, event_id, "bob's private notice")

    by_query = client.get(
        "/api/notifications",
        query_string={"account_id": BOB, "recipient_account_id": BOB},
        headers=headers("coordinator"),
    )
    by_header = client.get(
        "/api/notifications", headers={**headers("coordinator"), "X-Account-Id": BOB}
    )

    for response in (by_query, by_header):
        assert response.status_code == 200
        assert response.get_json() == {"notifications": [], "unread_count": 0}


# QA-SPL-101-007 | AC1 | WB serialiser: naive timestamps get the known zone, aware ones are kept
def test_qa_spl_101_007_timestamp_is_always_reported_in_singapore_time():
    naive = datetime(2026, 10, 7, 9, 0)
    aware = datetime(2026, 10, 7, 9, 0, tzinfo=SINGAPORE)

    assert _timestamp(naive) == "2026-10-07T09:00:00+08:00"
    assert _timestamp(aware) == "2026-10-07T09:00:00+08:00"


# ---------------------------------------------------------------------------------------------
# AC2. Mark one or all as read; the unread count follows and persists after reopening.
# ---------------------------------------------------------------------------------------------


# QA-SPL-101-013 | AC2 | BB happy path
def test_qa_spl_101_013_marking_one_read_lowers_the_count_and_persists(app, client):
    event_id = add_request(app)
    first = add_notice(app, ALICE, event_id, "one", minutes=0)
    add_notice(app, ALICE, event_id, "two", minutes=1)

    response = client.post(f"/api/notifications/{first}/read", headers=headers("coordinator"))

    assert response.get_json() == {"unread_count": 1}
    reloaded = inbox(client).get_json()
    assert reloaded["unread_count"] == 1
    assert {n["message"]: n["read"] for n in reloaded["notifications"]} == {
        "one": True,
        "two": False,
    }


# QA-SPL-101-014 | AC2 | BB happy path: read-all only touches the caller's notices
def test_qa_spl_101_014_marking_all_read_clears_the_count_and_persists(app, client):
    event_id = add_request(app)
    add_notice(app, ALICE, event_id, "one", minutes=0)
    add_notice(app, ALICE, event_id, "two", minutes=1)
    add_notice(app, BOB, event_id, "bob's")

    response = client.post("/api/notifications/read-all", headers=headers("coordinator"))

    assert response.get_json() == {"unread_count": 0}
    assert inbox(client).get_json()["unread_count"] == 0
    assert inbox(client, "coordinator-b").get_json()["unread_count"] == 1


# QA-SPL-101-015 | AC2 | BB boundary: reading twice changes nothing
def test_qa_spl_101_015_marking_a_read_notice_again_keeps_the_first_read_time(app, client):
    event_id = add_request(app)
    notice = add_notice(app, ALICE, event_id, read=True)
    original = read_at(app, notice)

    response = client.post(f"/api/notifications/{notice}/read", headers=headers("coordinator"))

    assert response.status_code == 200
    assert response.get_json() == {"unread_count": 0}
    assert read_at(app, notice) == original


# QA-SPL-101-016 | AC2 | BB boundary: read-all on an empty inbox
def test_qa_spl_101_016_marking_all_read_on_an_empty_inbox_is_a_no_op(app, client):
    response = client.post("/api/notifications/read-all", headers=headers("coordinator"))

    assert response.status_code == 200
    assert response.get_json() == {"unread_count": 0}


# QA-SPL-101-017 | AC2 | BB negative: someone else's notice looks the same as a missing one
def test_qa_spl_101_017_another_accounts_notice_cannot_be_marked_read(app, client):
    event_id = add_request(app)
    bobs = add_notice(app, BOB, event_id)

    refused = client.post(f"/api/notifications/{bobs}/read", headers=headers("coordinator"))
    missing = client.post("/api/notifications/9999/read", headers=headers("coordinator"))

    assert refused.status_code == missing.status_code == 404
    assert refused.get_json() == missing.get_json()
    assert read_at(app, bobs) is None
    assert inbox(client, "coordinator-b").get_json()["unread_count"] == 1


# QA-SPL-101-018 | AC2 | BB negative: sign-in is required to change read state
def test_qa_spl_101_018_marking_read_requires_a_signed_in_account(app, client):
    event_id = add_request(app)
    notice = add_notice(app, ALICE, event_id)

    assert client.post(f"/api/notifications/{notice}/read").status_code == 401
    assert client.post("/api/notifications/read-all").status_code == 401
    assert read_at(app, notice) is None


# QA-SPL-101-019 | AC2 | WB: read-all stamps only unread rows, so earlier read times survive
def test_qa_spl_101_019_marking_all_read_does_not_restamp_notices_already_read(app, client):
    event_id = add_request(app)
    already = add_notice(app, ALICE, event_id, "already read", minutes=0)
    add_notice(app, ALICE, event_id, "still unread", minutes=1)
    client.post(f"/api/notifications/{already}/read", headers=headers("coordinator"))
    first_read = read_at(app, already)
    time.sleep(0.01)

    client.post("/api/notifications/read-all", headers=headers("coordinator"))

    assert read_at(app, already) == first_read


# QA-SPL-101-020 | AC2 | BB boundary/negative: ids that cannot name a notice
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("0", 404),
        ("2147483647", 404),
        ("2147483648", 404),
        ("99999999999999999999", 404),
        # Not integers, so no route matches; the app's default-deny rule answers 403 for any
        # unrouted API path (existing behaviour, not specific to this story).
        ("-1", 403),
        ("abc", 403),
    ],
)
def test_qa_spl_101_020_ids_that_cannot_name_a_notice_change_nothing(app, client, path, expected):
    event_id = add_request(app)
    notice = add_notice(app, ALICE, event_id)

    response = client.post(f"/api/notifications/{path}/read", headers=headers("coordinator"))

    assert response.status_code == expected
    assert read_at(app, notice) is None


# ---------------------------------------------------------------------------------------------
# AC3. The assignment action notifies its coordinator once; refusals and retries add none.
# ---------------------------------------------------------------------------------------------


# QA-SPL-101-025 | AC3 | BB happy path
def test_qa_spl_101_025_assignment_notifies_only_the_assigned_coordinator(app, client):
    event_id = add_request(app, "Harbour Summit")

    assert assign(client, event_id, ALICE).status_code == 201

    notices = inbox(client, "coordinator").get_json()
    assert notices["unread_count"] == 1
    assert [n["event"]["name"] for n in notices["notifications"]] == ["Harbour Summit"]
    assert "Harbour Summit" in notices["notifications"][0]["message"]
    assert "assigned" in notices["notifications"][0]["message"]
    assert notice_count(app) == 1
    for other in ("coordinator-b", "manager", "organiser", "venue-staff"):
        assert inbox(client, other).get_json()["notifications"] == []


# QA-SPL-101-026 | AC3 | BB: separate assignments are separate notices
def test_qa_spl_101_026_each_assignment_to_the_same_coordinator_gets_its_own_notice(app, client):
    first = add_request(app, "Harbour Summit")
    second = add_request(app, "Coastal Forum")

    assert assign(client, first, ALICE).status_code == 201
    assert assign(client, second, ALICE).status_code == 201

    names = {n["event"]["name"] for n in inbox(client).get_json()["notifications"]}
    assert names == {"Harbour Summit", "Coastal Forum"}
    assert notice_count(app, ALICE) == 2


# QA-SPL-101-027 | AC3 | BB negative: retrying the same assignment
def test_qa_spl_101_027_repeating_the_assignment_adds_no_second_notice(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    for _ in range(3):
        assert assign(client, event_id, ALICE).status_code == 409
    assert assign(client, event_id, BOB).status_code == 409

    assert notice_count(app) == 1
    assert inbox(client, "coordinator-b").get_json()["notifications"] == []


# QA-SPL-101-028 | AC3 | BB negative: every refused assignment leaves no notice
@pytest.mark.parametrize(
    "attempt",
    [
        "wrong_role",
        "venue_staff_caller",
        "not_submitted",
        "inactive_coordinator",
        "not_a_coordinator",
        "unknown_coordinator",
        "unexpected_field",
        "unknown_event",
    ],
)
def test_qa_spl_101_028_refused_assignments_create_no_notice(app, client, attempt):
    event_id = add_request(app)
    if attempt == "wrong_role":
        response = assign(client, event_id, ALICE, token="organiser")
    elif attempt == "venue_staff_caller":
        response = assign(client, event_id, ALICE, token="venue-staff")
    elif attempt == "not_submitted":
        set_status(app, event_id, "under_review")
        response = assign(client, event_id, ALICE)
    elif attempt == "inactive_coordinator":
        response = assign(client, event_id, INACTIVE_COORDINATOR)
    elif attempt == "not_a_coordinator":
        response = assign(client, event_id, VENUE_STAFF)
    elif attempt == "unknown_coordinator":
        response = assign(client, event_id, "00000000-0000-0000-0000-0000000000ff")
    elif attempt == "unexpected_field":
        response = client.post(
            f"/api/event-requests/{event_id}/coordinator",
            json={"coordinator_account_id": ALICE, "role": "admin"},
            headers=headers("manager"),
        )
    else:
        response = assign(client, 9999, ALICE)

    assert response.status_code in (400, 403, 404, 409)
    assert notice_count(app) == 0


# QA-SPL-101-029 | AC3 | WB: the helper builds exactly the row the inbox expects
def test_qa_spl_101_029_the_helper_stores_an_unread_account_scoped_notice(app):
    event_id = add_request(app, "Harbour Summit")
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        before = datetime.now(SINGAPORE)

        add_coordinator_assigned_notice(session, event, ALICE, 42)
        session.commit()

        notice = session.scalar(select(Notification))
        assert notice.recipient_account_id == ALICE
        assert notice.event_request_id == event_id
        assert notice.message == "You have been assigned to Harbour Summit."
        assert notice.dedupe_key == "coordinator_assigned:42"
        assert notice.read_at is None
        created = notice.created_at
        created = created if created.tzinfo else created.replace(tzinfo=SINGAPORE)
        assert before - timedelta(seconds=1) <= created <= datetime.now(SINGAPORE)


# QA-SPL-101-030 | AC3 | WB/boundary: the dedupe constraint is per recipient and per change
def test_qa_spl_101_030_the_same_change_cannot_be_stored_twice_for_one_recipient(app):
    event_id = add_request(app)

    def notice(recipient, key):
        return Notification(
            recipient_account_id=recipient,
            event_request_id=event_id,
            message="x",
            dedupe_key=key,
            created_at=NOW,
        )

    with Session(app.extensions["engine"]) as session:
        session.add_all([notice(ALICE, "k1"), notice(BOB, "k1"), notice(ALICE, "k2")])
        session.commit()  # same key for another recipient, or another key, is allowed
        session.add(notice(ALICE, "k1"))
        with pytest.raises(IntegrityError):
            session.commit()


# QA-SPL-101-031 | AC3 | WB: the notice commits or rolls back with the assignment
def test_qa_spl_101_031_a_failure_writing_the_notice_rolls_the_assignment_back(
    app, client, monkeypatch
):
    event_id = add_request(app)

    def explode(*args, **kwargs):
        raise RuntimeError("notice store unavailable")

    monkeypatch.setattr(coordinator_assignment, "add_coordinator_assigned_notice", explode)

    with pytest.raises(RuntimeError):
        assign(client, event_id, ALICE)

    with Session(app.extensions["engine"]) as session:
        assert session.get(EventCoordinatorAssignment, event_id) is None
        assert session.scalar(select(func.count()).select_from(EventCoordinatorHistory)) == 0
    assert notice_count(app) == 0


# QA-SPL-101-032 | AC3 | BB scope guard: reassignment is not part of this story
def test_qa_spl_101_032_reassignment_adds_and_moves_no_notice(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200

    assert notice_count(app, ALICE) == 1
    assert notice_count(app, BOB) == 0
    assert notice_count(app) == 1


# ---------------------------------------------------------------------------------------------
# AC4. A notice never grants access; related records enforce current permissions.
# ---------------------------------------------------------------------------------------------


# QA-SPL-101-033 | AC4 | BB: an old notice does not open the event after reassignment
def test_qa_spl_101_033_old_notice_does_not_open_an_event_after_reassignment(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    assert open_event(client, event_id, "coordinator").status_code == 200
    assert reassign(client, event_id, BOB).status_code == 200

    assert inbox(client, "coordinator").get_json()["unread_count"] == 1
    assert open_event(client, event_id, "coordinator").status_code == 404
    assert open_event(client, event_id, "coordinator-b").status_code == 200


# QA-SPL-101-034 | AC4 | BB negative: a coordinator who was never assigned learns nothing
def test_qa_spl_101_034_an_unassigned_coordinator_cannot_tell_an_event_exists(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    other = open_event(client, event_id, "coordinator-b")
    missing = open_event(client, 9999, "coordinator-b")

    assert other.status_code == missing.status_code == 404
    assert other.get_json() == missing.get_json()


# QA-SPL-101-035 | AC4 | BB cross-cut: reassignment does not leak a notice between inboxes
def test_qa_spl_101_035_reassignment_does_not_leak_notices_between_accounts(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200

    alice = inbox(client, "coordinator").get_json()["notifications"]
    assert [n["event"]["id"] for n in alice] == [event_id]
    for other in ("coordinator-b", "organiser", "manager", "venue-staff"):
        assert inbox(client, other).get_json()["notifications"] == []


# QA-SPL-101-036 | AC4 | BB negative: access follows the account's current state
def test_qa_spl_101_036_a_deactivated_account_cannot_read_or_change_its_old_notices(app, client):
    event_id = add_request(app)
    notice = add_notice(app, ALICE, event_id)
    deactivate(app, ALICE)

    assert inbox(client, "coordinator").status_code == 403
    one = client.post(f"/api/notifications/{notice}/read", headers=headers("coordinator"))
    everything = client.post("/api/notifications/read-all", headers=headers("coordinator"))
    assert one.status_code == everything.status_code == 403
    assert read_at(app, notice) is None


# ---------------------------------------------------------------------------------------------
# Cross-cutting quality: efficiency and size (the inbox has no size limit).
# ---------------------------------------------------------------------------------------------


# QA-SPL-101-039 | all ACs | WB efficiency: query count does not grow with the inbox
def test_qa_spl_101_039_listing_uses_a_constant_number_of_queries(app, client):
    event_id = add_request(app)
    engine = app.extensions["engine"]
    counts = {}
    for size in (1, 60):
        with Session(engine) as session:
            session.add_all(
                Notification(
                    recipient_account_id=ALICE,
                    event_request_id=event_id,
                    message=f"n{size}-{i}",
                    dedupe_key=f"{size}:{i}",
                    created_at=NOW + timedelta(minutes=i),
                )
                for i in range(size)
            )
            session.commit()
        selects = []

        def count(conn, cursor, statement, *args, _selects=selects):
            if statement.lstrip().upper().startswith("SELECT"):
                _selects.append(statement)

        sa_event.listen(engine, "before_cursor_execute", count)
        try:
            assert inbox(client).status_code == 200
        finally:
            sa_event.remove(engine, "before_cursor_execute", count)
        counts[size] = len(selects)

    # Account roles are loaded once; the list and the unread count are the only other reads.
    assert counts[60] == counts[1]
    assert counts[60] <= 5


# QA-SPL-101-040 | all ACs | BB performance: an unbounded inbox is returned whole and quickly
def test_qa_spl_101_040_a_large_inbox_is_returned_in_full(app, client):
    event_id = add_request(app)
    total = 2000
    with Session(app.extensions["engine"]) as session:
        session.add_all(
            Notification(
                recipient_account_id=ALICE,
                event_request_id=event_id,
                message=f"notice {i}",
                dedupe_key=f"bulk:{i}",
                created_at=NOW + timedelta(seconds=i),
                read_at=NOW if i % 2 else None,
            )
            for i in range(total)
        )
        session.commit()

    started = time.perf_counter()
    response = inbox(client)
    elapsed = time.perf_counter() - started
    print(f"QA-SPL-101-040 listed {total} notices in {elapsed:.3f}s")

    body = response.get_json()
    assert response.status_code == 200
    assert len(body["notifications"]) == total
    assert body["unread_count"] == total // 2
    assert body["notifications"][0]["message"] == f"notice {total - 1}"
    assert elapsed < 5
