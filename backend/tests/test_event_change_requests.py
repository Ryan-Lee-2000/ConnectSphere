"""Acceptance coverage for SPL-111 (CS-E18-S1): an organiser submits a change request.

Every test carries the QA-SPL-111 case ID it proves, the acceptance criterion (AC) it covers and
whether it is black-box (BB: asserts only the HTTP contract and stored result) or white-box (WB:
written from the code's branches). Search with: rg -n "QA-SPL-111-0" backend/tests frontend/src e2e

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database with one organiser who owns events in each
  status, a second organiser in the same client organisation, an assigned coordinator, another
  coordinator and an attendee.
- Sign-in is simulated: a token such as "organiser" maps to a known account id (``TOKENS``).
- The clock is frozen at ``NOW`` through the single clock function in app/registration_settings.py.
- Every refusal test also checks that nothing was written, and proves a genuine submission
  succeeds in the same test where that matters, so a missing route could not make it pass.
- The PostgreSQL-only cases (the race between two submissions, the partial unique index and the
  grants) are in test_event_change_requests_postgres.py.
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from app import create_app
from app import event_change_requests as module
from app import registration_settings as settings_module
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EventChangeRequest,
    EventChangeRequestItem,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ORGANISER = "00000000-0000-0000-0000-000000011101"
COLLEAGUE = "00000000-0000-0000-0000-000000011102"
COORDINATOR = "00000000-0000-0000-0000-000000011103"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000011104"
ATTENDEE = "00000000-0000-0000-0000-000000011105"
TOKENS = {
    "organiser": ORGANISER,
    "colleague": COLLEAGUE,
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "attendee": ATTENDEE,
}
NOW = datetime(2026, 10, 20, 12, tzinfo=SINGAPORE)
ITEM = {"field": "expected_attendance", "requested_value": 50, "reason": "More guests are coming."}
ALLOWED = ("under_review", "planning", "confirmed")
REFUSED = (
    "submitted",
    "approved",
    "returned_for_clarification",
    "completed",
    "cancelled",
    "rejected",
    "withdrawn",
    "postponed",
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "_now", lambda: NOW)
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/change-requests.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-111 client")
        session.add(organisation)
        session.flush()
        for account_id, name, role in (
            (ORGANISER, "Erin Goh", Role.EVENT_ORGANISER),
            (COLLEAGUE, "Colin Tay", Role.EVENT_ORGANISER),
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Kim Ho", Role.EVENT_COORDINATOR),
            (ATTENDEE, "Avery Koh", Role.ATTENDEE),
        ):
            session.add(Account(id=account_id, display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
        app.config["ORGANISATION_ID"] = organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="organiser"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def make_event(app, status="under_review", *, assigned=COORDINATOR, **overrides):
    values = {
        "organiser_account_id": ORGANISER,
        "organisation_id": app.config["ORGANISATION_ID"],
        "name": "Harbour Lights Gala",
        "purpose": "Annual fundraiser",
        "description": "An evening of music.",
        "proposed_date": date(2026, 12, 5),
        "start_time": time(18),
        "end_time": time(22),
        "expected_attendance": 150,
        "status": status,
        "required_facilities": ["Projector"],
    }
    values.update(overrides)
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(**values)
        session.add(event)
        session.flush()
        if assigned:
            session.add(
                EventCoordinatorAssignment(
                    event_request_id=event.id,
                    coordinator_account_id=assigned,
                    assigned_by_account_id=assigned,
                    assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                )
            )
        session.commit()
        return event.id


def submit(client, event_id, items=None, token="organiser", body=None):
    payload = body if body is not None else {"items": items if items is not None else [ITEM]}
    return client.post(
        f"/api/event-requests/{event_id}/change-requests", json=payload, headers=headers(token)
    )


def read(client, event_id, token="organiser"):
    return client.get(f"/api/event-requests/{event_id}/change-requests", headers=headers(token))


def stored(app):
    """(requests, items) currently in the database."""

    with Session(app.extensions["engine"]) as session:
        return (
            session.scalar(select(func.count()).select_from(EventChangeRequest)),
            session.scalar(select(func.count()).select_from(EventChangeRequestItem)),
        )


# --------------------------------------------------------------------------------------------
# AC1 Availability: Under Review, Planning or Confirmed only.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ALLOWED)
def test_qa_spl_111_001_ac1_bb_offered_for_each_allowed_status(app, client, status):
    event_id = make_event(app, status)
    response = submit(client, event_id)
    assert response.status_code == 201
    assert response.get_json()["change_request"]["status"] == "pending"
    assert stored(app) == (1, 1)


@pytest.mark.parametrize("status", REFUSED)
def test_qa_spl_111_002_ac1_bb_refused_for_every_other_status_and_nothing_saved(
    app, client, status
):
    event_id = make_event(app, status)
    response = submit(client, event_id)
    assert response.status_code == 409
    assert "under review, in planning or confirmed" in response.get_json()["error"]
    assert stored(app) == (0, 0)
    # The same caller, same payload, succeeds once the event is in an allowed status: the
    # refusal was about the status and not about the caller or the request.
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "planning"
        session.commit()
    assert submit(client, event_id).status_code == 201


def test_qa_spl_111_003_ac1_bb_a_draft_is_not_found_not_refused(app, client):
    event_id = make_event(app, "draft")
    response = submit(client, event_id)
    assert response.status_code == 404
    assert response.get_json()["error"] == "Event not found."
    assert stored(app) == (0, 0)


def test_qa_spl_111_004_ac1_bb_access_after_a_state_change(app, client):
    """The event leaves the allowed statuses while a request is pending."""

    event_id = make_event(app, "planning")
    assert submit(client, event_id).status_code == 201
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "cancelled"
        session.commit()
    # A new request is refused...
    assert submit(client, event_id).status_code == 409
    # ...but the organiser can still read what they submitted.
    body = read(client, event_id).get_json()
    assert [row["status"] for row in body["change_requests"]] == ["pending"]
    assert stored(app) == (1, 1)


def test_qa_spl_111_005_ac1_bb_unknown_and_out_of_range_event_ids(app, client):
    assert submit(client, 999).status_code == 404
    assert submit(client, 2**31).status_code == 404  # beyond an Integer column; must not 500
    assert read(client, 999).status_code == 404
    assert read(client, 2**31).status_code == 404
    # A path that matches no route has no declared policy, so it is denied by default.
    assert (
        client.post(
            "/api/event-requests/abc/change-requests", json={"items": [ITEM]}, headers=headers()
        ).status_code
        == 403
    )
    assert stored(app) == (0, 0)


def test_qa_spl_111_006_ac1_bb_security_only_the_owner_can_submit(app, client):
    event_id = make_event(app, "planning")
    # A colleague in the same client organisation owns no such event.
    assert submit(client, event_id, token="colleague").status_code == 404
    # The assigned coordinator and an attendee are the wrong role.
    assert submit(client, event_id, token="coordinator").status_code == 403
    assert submit(client, event_id, token="attendee").status_code == 403
    assert submit(client, event_id, token=None).status_code == 401
    assert stored(app) == (0, 0)
    assert submit(client, event_id).status_code == 201


# --------------------------------------------------------------------------------------------
# AC2 Request items: field, requested new value, reason; at least one complete item.
# --------------------------------------------------------------------------------------------


def test_qa_spl_111_010_ac2_bb_one_item_is_stored_with_field_value_reason_and_current(app, client):
    event_id = make_event(app, "planning")
    body = submit(client, event_id).get_json()["change_request"]
    assert body["event_request_id"] == event_id
    assert body["items"][0]["field"] == "expected_attendance"
    assert body["items"][0]["field_label"] == "Expected attendance"
    assert body["items"][0]["requested_value"] == 50
    assert body["items"][0]["reason"] == "More guests are coming."
    # The value being replaced is kept, so the coordinator sees what changes.
    assert body["items"][0]["current_value"] == 150


def test_qa_spl_111_011_ac2_bb_several_items_in_one_request(app, client):
    event_id = make_event(app, "planning")
    items = [
        ITEM,
        {"field": "proposed_date", "requested_value": "2026-12-12", "reason": "Venue clash."},
        {"field": "start_time", "requested_value": "17:30", "reason": "Earlier setup."},
        {"field": "required_facilities", "requested_value": ["Stage", "AV"], "reason": "Band."},
        {"field": "name", "requested_value": "  Harbour Lights  ", "reason": "Rebrand."},
    ]
    response = submit(client, event_id, items)
    assert response.status_code == 201
    saved = response.get_json()["change_request"]["items"]
    assert [item["field"] for item in saved] == [item["field"] for item in items]
    assert saved[1]["current_value"] == "2026-12-05"
    assert saved[2]["current_value"] == "18:00"
    assert saved[3]["current_value"] == ["Projector"]
    assert saved[4]["requested_value"] == "Harbour Lights"  # trimmed
    assert stored(app) == (1, 5)


def test_qa_spl_111_012_ac2_bb_cannot_submit_without_an_item(app, client):
    event_id = make_event(app, "planning")
    for body in ({"items": []}, {"items": None}, {"items": "x"}, {"items": {}}):
        response = submit(client, event_id, body=body)
        assert response.status_code == 400, body
    assert stored(app) == (0, 0)


@pytest.mark.parametrize(
    "item",
    [
        {"field": "expected_attendance", "requested_value": 50},  # no reason
        {"field": "expected_attendance", "requested_value": 50, "reason": ""},
        {"field": "expected_attendance", "requested_value": 50, "reason": "   "},
        {"field": "expected_attendance", "requested_value": 50, "reason": 5},
        {"field": "expected_attendance", "reason": "Why."},  # no value
        {"requested_value": 50, "reason": "Why."},  # no field
        {"field": "", "requested_value": 50, "reason": "Why."},
        {"field": None, "requested_value": 50, "reason": "Why."},
        {"field": "name", "requested_value": "   ", "reason": "Why."},
        {"field": "name", "requested_value": None, "reason": "Why."},
        {"field": "name", "requested_value": 7, "reason": "Why."},
    ],
)
def test_qa_spl_111_013_ac2_bb_an_incomplete_item_is_refused_and_nothing_saved(app, client, item):
    event_id = make_event(app, "planning")
    assert submit(client, event_id, [item]).status_code == 400
    assert stored(app) == (0, 0)


def test_qa_spl_111_014_ac2_bb_one_bad_item_refuses_the_whole_request(app, client):
    """Atomic: a complete item is not saved when another item in the request is incomplete."""

    event_id = make_event(app, "planning")
    bad = {"field": "name", "requested_value": "New name", "reason": ""}
    assert submit(client, event_id, [ITEM, bad]).status_code == 400
    assert stored(app) == (0, 0)
    # And the event can still receive a request afterwards (no half-written pending row).
    assert submit(client, event_id, [ITEM]).status_code == 201


@pytest.mark.parametrize(
    "field",
    ["status", "organiser_account_id", "organisation_id", "id", "venue_id", "submitted_at", "x"],
)
def test_qa_spl_111_015_ac2_bb_security_only_listed_fields_can_be_changed(app, client, field):
    event_id = make_event(app, "planning")
    item = {"field": field, "requested_value": "approved", "reason": "Because."}
    assert submit(client, event_id, [item]).status_code == 400
    assert stored(app) == (0, 0)
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status == "planning"


def test_qa_spl_111_016_ac2_bb_boundary_text_lengths(app, client):
    event_id = make_event(app, "planning")
    at_limit = {"field": "name", "requested_value": "n" * 2000, "reason": "r" * 1000}
    assert submit(client, event_id, [at_limit]).status_code == 201
    event_id = make_event(app, "planning")
    for item in (
        {"field": "name", "requested_value": "n" * 2001, "reason": "ok"},
        {"field": "name", "requested_value": "ok", "reason": "r" * 1001},
    ):
        assert submit(client, event_id, [item]).status_code == 400
    assert stored(app) == (1, 1)


@pytest.mark.parametrize("value", [1, 10_000])
def test_qa_spl_111_017_ac2_bb_boundary_attendance_accepted(app, client, value):
    event_id = make_event(app, "planning")
    item = {**ITEM, "requested_value": value}
    assert submit(client, event_id, [item]).status_code == 201


@pytest.mark.parametrize("value", [0, -1, 1.5, "50", True, None, [50]])
def test_qa_spl_111_018_ac2_bb_boundary_attendance_refused(app, client, value):
    event_id = make_event(app, "planning")
    item = {**ITEM, "requested_value": value}
    assert submit(client, event_id, [item]).status_code == 400
    assert stored(app) == (0, 0)


@pytest.mark.parametrize(
    "field, value",
    [
        ("proposed_date", "2026-13-01"),
        ("proposed_date", "05/12/2026"),
        ("proposed_date", 20261205),
        ("start_time", "9:00"),
        ("start_time", "25:00"),
        ("start_time", "18:00:00"),
        ("end_time", "18:00+08:00"),
        ("end_time", 1800),
        ("required_facilities", "Stage"),
        ("required_facilities", ["Stage", ""]),
        ("accessibility_needs", [1]),
    ],
)
def test_qa_spl_111_019_ac2_bb_malformed_values_are_refused(app, client, field, value):
    event_id = make_event(app, "planning")
    item = {"field": field, "requested_value": value, "reason": "Because."}
    assert submit(client, event_id, [item]).status_code == 400
    assert stored(app) == (0, 0)


def test_qa_spl_111_020_ac2_bb_the_same_field_cannot_appear_twice(app, client):
    event_id = make_event(app, "planning")
    second = {**ITEM, "requested_value": 60}
    response = submit(client, event_id, [ITEM, second])
    assert response.status_code == 400
    assert "more than once" in response.get_json()["error"]
    assert stored(app) == (0, 0)


def test_qa_spl_111_021_ac2_wb_too_many_items_and_extra_keys_are_refused(app, client):
    event_id = make_event(app, "planning")
    too_many = [{**ITEM, "field": f"x{i}"} for i in range(len(module.FIELDS) + 1)]
    assert submit(client, event_id, too_many).status_code == 400
    assert submit(client, event_id, body={"items": [ITEM], "status": "pending"}).status_code == 400
    assert submit(client, event_id, [{**ITEM, "extra": 1}]).status_code == 400
    assert submit(client, event_id, ["not an object"]).status_code == 400
    assert submit(client, event_id, body={}).status_code == 400
    assert stored(app) == (0, 0)


def test_qa_spl_111_022_ac2_bb_malformed_body(app, client):
    event_id = make_event(app, "planning")
    url = f"/api/event-requests/{event_id}/change-requests"
    for kwargs in (
        {"data": "not json", "content_type": "application/json"},
        {"data": "[1]", "content_type": "application/json"},
        {"data": "", "content_type": "application/json"},
    ):
        assert client.post(url, headers=headers(), **kwargs).status_code == 400
    assert stored(app) == (0, 0)


def test_qa_spl_111_023_ac2_wb_empty_list_value_and_null_current_values(app, client):
    """A list may be emptied; a field the event never had is recorded as null, not an error."""

    event_id = make_event(
        app, "planning", description=None, proposed_date=None, start_time=None, end_time=None
    )
    items = [
        {"field": "required_facilities", "requested_value": [], "reason": "None needed."},
        {"field": "description", "requested_value": "A new one.", "reason": "Missing."},
        {"field": "proposed_date", "requested_value": "2027-01-02", "reason": "Set it."},
        {"field": "start_time", "requested_value": "08:00", "reason": "Set it."},
        {"field": "end_time", "requested_value": "09:00", "reason": "Set it."},
    ]
    saved = submit(client, event_id, items).get_json()["change_request"]["items"]
    assert saved[0]["requested_value"] == []
    assert [item["current_value"] for item in saved[1:]] == [None, None, None, None]


# --------------------------------------------------------------------------------------------
# AC3 Submitted state: Pending, and the assigned coordinator can see it.
# --------------------------------------------------------------------------------------------


def test_qa_spl_111_030_ac3_bb_status_is_pending_in_the_response_and_when_read_back(app, client):
    event_id = make_event(app, "planning")
    assert submit(client, event_id).get_json()["change_request"]["status"] == "pending"
    rows = read(client, event_id).get_json()["change_requests"]
    assert [row["status"] for row in rows] == ["pending"]


def test_qa_spl_111_031_ac3_bb_the_assigned_coordinator_sees_the_request_and_items(app, client):
    event_id = make_event(app, "planning")
    assert read(client, event_id, "coordinator").get_json() == {"change_requests": []}
    submit(client, event_id, [ITEM, {**ITEM, "field": "name", "requested_value": "New"}])
    response = read(client, event_id, "coordinator")
    assert response.status_code == 200
    row = response.get_json()["change_requests"][0]
    assert row["status"] == "pending"
    assert [item["field"] for item in row["items"]] == ["expected_attendance", "name"]


def test_qa_spl_111_032_ac3_bb_security_a_coordinator_not_assigned_sees_nothing(app, client):
    event_id = make_event(app, "planning")
    submit(client, event_id)
    for token in ("other-coordinator", "colleague", "attendee"):
        response = read(client, event_id, token)
        assert response.status_code in (403, 404)
        assert "items" not in response.get_data(as_text=True)
    assert read(client, event_id, None).status_code == 401


def test_qa_spl_111_033_ac3_bb_after_reassignment_only_the_new_coordinator_sees_it(app, client):
    event_id = make_event(app, "planning")
    submit(client, event_id)
    assert read(client, event_id, "coordinator").status_code == 200
    assert read(client, event_id, "other-coordinator").status_code == 404
    with Session(app.extensions["engine"]) as session:
        assignment = session.scalar(
            select(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event_id
            )
        )
        assignment.coordinator_account_id = OTHER_COORDINATOR
        session.commit()
    assert read(client, event_id, "other-coordinator").status_code == 200
    assert read(client, event_id, "coordinator").status_code == 404


def test_qa_spl_111_034_ac3_bb_an_unassigned_event_is_visible_to_no_coordinator(app, client):
    event_id = make_event(app, "planning", assigned=None)
    submit(client, event_id)
    assert read(client, event_id, "coordinator").status_code == 404
    assert read(client, event_id, "organiser").status_code == 200


def test_qa_spl_111_035_ac3_bb_submitter_and_time_come_from_the_server(app, client):
    event_id = make_event(app, "planning")
    body = {
        "items": [ITEM],
    }
    assert submit(client, event_id, body=body).status_code == 201
    with Session(app.extensions["engine"]) as session:
        row = session.scalar(select(EventChangeRequest))
        assert row.submitted_by_account_id == ORGANISER
        assert row.status == "pending"
        # SQLite keeps the wall-clock value without its offset; the +08:00 reading is asserted
        # through the API below, and the stored instant on PostgreSQL in the integration suite.
        assert row.submitted_at.replace(tzinfo=None) == NOW.replace(tzinfo=None)
    shown = read(client, event_id).get_json()["change_requests"][0]
    assert shown["submitted_at"] == "2026-10-20T12:00:00+08:00"
    # A client cannot supply who submitted or when.
    spoof = {"items": [ITEM], "submitted_by_account_id": COLLEAGUE, "submitted_at": "2020-01-01"}
    assert submit(client, make_event(app, "planning"), body=spoof).status_code == 400


def test_qa_spl_111_036_ac3_wb_the_event_itself_is_not_changed_by_submitting(app, client):
    event_id = make_event(app, "planning")
    submit(client, event_id)
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assert event.expected_attendance == 150
        assert event.status == "planning"


# --------------------------------------------------------------------------------------------
# AC4 One at a time: no second request while one is Pending.
# --------------------------------------------------------------------------------------------


def test_qa_spl_111_040_ac4_bb_a_second_request_is_refused(app, client):
    event_id = make_event(app, "planning")
    assert submit(client, event_id).status_code == 201
    other = {"field": "name", "requested_value": "Different", "reason": "Rebrand."}
    response = submit(client, event_id, [other])
    assert response.status_code == 409
    assert "already has a pending change request" in response.get_json()["error"]
    assert stored(app) == (1, 1)


def test_qa_spl_111_041_ac4_bb_an_identical_retry_is_refused_not_duplicated(app, client):
    event_id = make_event(app, "planning")
    assert submit(client, event_id).status_code == 201
    for _ in range(3):
        assert submit(client, event_id).status_code == 409
    assert stored(app) == (1, 1)


def test_qa_spl_111_042_ac4_bb_the_rule_is_per_event(app, client):
    first = make_event(app, "planning")
    second = make_event(app, "confirmed")
    assert submit(client, first).status_code == 201
    assert submit(client, second).status_code == 201
    assert stored(app) == (2, 2)


def test_qa_spl_111_043_ac4_wb_a_refusal_for_another_reason_does_not_hide_the_pending_one(
    app, client
):
    """A bad body is refused before the pending check, so the state is reported truthfully."""

    event_id = make_event(app, "planning")
    submit(client, event_id)
    assert submit(client, event_id, [{**ITEM, "reason": ""}]).status_code == 400
    assert submit(client, event_id).status_code == 409


def test_qa_spl_111_044_ac4_wb_the_database_refuses_a_second_pending_row(app):
    """Backstop: even a write that bypasses the route cannot create two Pending requests."""

    event_id = make_event(app, "planning")
    with Session(app.extensions["engine"]) as session:
        for _ in range(2):
            session.add(
                EventChangeRequest(
                    event_request_id=event_id,
                    status="pending",
                    submitted_by_account_id=ORGANISER,
                    submitted_at=NOW,
                )
            )
        with pytest.raises(IntegrityError):
            session.commit()


def test_qa_spl_111_045_ac4_wb_losing_a_race_at_commit_is_a_409_and_saves_nothing(
    app, client, monkeypatch
):
    """The route's own pending check can be raced; the index then refuses the commit."""

    event_id = make_event(app, "planning")
    assert submit(client, event_id).status_code == 201
    monkeypatch.setattr(module, "_pending_request", lambda session, event_request_id: None)
    response = submit(client, event_id, [{**ITEM, "requested_value": 70}])
    assert response.status_code == 409
    assert stored(app) == (1, 1)
    monkeypatch.undo()
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(EventChangeRequestItem.requested_value)) == 50


# --------------------------------------------------------------------------------------------
# AC5 Viewing: the pending request, including all of its items.
# --------------------------------------------------------------------------------------------


def test_qa_spl_111_050_ac5_bb_the_owner_sees_the_pending_request_with_all_items(app, client):
    event_id = make_event(app, "planning")
    items = [
        ITEM,
        {"field": "venue_notes", "requested_value": "Step-free entrance", "reason": "Access."},
        {"field": "accessibility_needs", "requested_value": ["Hearing loop"], "reason": "Guest."},
    ]
    submit(client, event_id, items)
    row = read(client, event_id).get_json()["change_requests"][0]
    assert row["status"] == "pending"
    assert len(row["items"]) == 3
    assert {item["reason"] for item in row["items"]} == {
        "More guests are coming.",
        "Access.",
        "Guest.",
    }
    assert all(item["field_label"] and "id" in item for item in row["items"])


def test_qa_spl_111_051_ac5_bb_nothing_pending_reads_as_an_empty_list(app, client):
    event_id = make_event(app, "planning")
    response = read(client, event_id)
    assert response.status_code == 200
    assert response.get_json() == {"change_requests": []}


def test_qa_spl_111_052_ac5_bb_the_request_is_still_there_after_reload_and_new_session(app, client):
    event_id = make_event(app, "planning")
    created = submit(client, event_id).get_json()["change_request"]
    again = app.test_client()  # a different client stands in for a reload / new browser session
    rows = read(again, event_id).get_json()["change_requests"]
    assert rows == [created]


def test_qa_spl_111_053_ac5_bb_security_same_client_colleagues_and_drafts_are_hidden(app, client):
    event_id = make_event(app, "planning")
    submit(client, event_id)
    assert read(client, event_id, "colleague").status_code == 404
    draft = make_event(app, "draft")
    assert read(client, draft).status_code == 404  # even the owner: drafts have no requests
    assert read(client, event_id, "attendee").status_code == 403


def test_qa_spl_111_054_ac5_wb_the_current_value_is_the_one_at_submission(app, client):
    event_id = make_event(app, "planning")
    submit(client, event_id)
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).expected_attendance = 999
        session.commit()
    item = read(client, event_id).get_json()["change_requests"][0]["items"][0]
    assert item["current_value"] == 150


def test_qa_spl_111_055_ac5_wb_an_unknown_stored_field_still_displays(app, client):
    """Serialisation does not depend on the allowlist: a field removed later still shows."""

    event_id = make_event(app, "planning")
    with Session(app.extensions["engine"]) as session:
        request = EventChangeRequest(
            event_request_id=event_id,
            status="pending",
            submitted_by_account_id=ORGANISER,
            submitted_at=NOW + timedelta(seconds=0),
            items=[
                EventChangeRequestItem(
                    field="legacy_field", current_value=None, requested_value="v", reason="r"
                )
            ],
        )
        session.add(request)
        session.commit()
    item = read(client, event_id).get_json()["change_requests"][0]["items"][0]
    assert item["field_label"] == "legacy_field"
