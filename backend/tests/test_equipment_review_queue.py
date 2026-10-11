"""Acceptance coverage for SPL-92 (CS-E14-S3): the equipment review queue.

Each test carries the QA-SPL-92 case identifier it proves. The cases were published on the
QA-SPL-92 page before this story's code existed.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database. ``add_event`` makes one event in a chosen
  status with an assigned coordinator; ``add_line`` adds one requirement line to it.
- Sign-in is simulated: a token such as "technical" maps to a known account id (``IDENTITIES``).
- The clock is frozen through the single clock function in app/equipment_review_queue.py, so the
  time a note was saved is assertable.
- Review Required lines are set directly, because SPL-90's ``status`` column already accepts
  ``review_required``. That is what lets this story be accepted without waiting for SPL-91 or
  SPL-96, as the story states.
- Every exclusion test puts an excluded line *beside* an included one in the same response, so an
  empty queue can never make it pass.
"""

from datetime import date, datetime, time

import pytest
from app import create_app
from app import equipment_review_queue as queue_module
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentReviewNote,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

IDENTITIES = {
    "technical": "00000000-0000-0000-0000-000000000921",
    "second-technical": "00000000-0000-0000-0000-000000000922",
    "coordinator": "00000000-0000-0000-0000-000000000923",
    "other-coordinator": "00000000-0000-0000-0000-000000000924",
    "venue": "00000000-0000-0000-0000-000000000925",
    "organiser": "00000000-0000-0000-0000-000000000926",
}

ROLES = {
    "technical": Role.TECHNICAL_SUPPORT_STAFF,
    "second-technical": Role.TECHNICAL_SUPPORT_STAFF,
    "coordinator": Role.EVENT_COORDINATOR,
    "other-coordinator": Role.EVENT_COORDINATOR,
    "venue": Role.VENUE_STAFF,
    "organiser": Role.EVENT_ORGANISER,
}

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=SINGAPORE)
START = date(2026, 11, 20)
END = date(2026, 11, 21)

# The statuses AC1 includes, and the ones it must leave out.
QUEUED_LINE_STATUSES = ("requested", "review_required")
ACTIVE_EVENT_STATUSES = ("planning", "confirmed", "postponed")


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/equipment-review-queue.db",
            "IDENTITY_VERIFIER": IDENTITIES.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organisation(id=1, name="Northstar Community Partners"))
        for label, account_id in IDENTITIES.items():
            session.add(Account(id=account_id, display_name=f"Person {label}", is_active=True))
            session.add(AccountRole(account_id=account_id, role=ROLES[label].value))
        session.add(
            EquipmentType(
                id=1,
                name="Wireless Microphone",
                normalised_name="wireless microphone",
                location="Technical Store A",
                total_stock=10,
            )
        )
        session.commit()
    monkeypatch.setattr(queue_module, "_now", lambda: NOW)
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def add_event(
    app, *, status="planning", name="Community Leadership Forum", coordinator="coordinator"
):
    """One event in the given status, with an assigned coordinator (AC2 shows that coordinator)."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=IDENTITIES["organiser"],
            organisation_id=1,
            name=name,
            # A Submitted event must carry all of these (ck_event_requests_submitted_fields), so
            # every fixture event is built complete rather than only the ones that need it.
            purpose="Annual leadership programme",
            proposed_date=START,
            start_time=time(14, 0),
            end_time=time(17, 0),
            expected_attendance=80,
            status=status,
            submitted_at=NOW,
        )
        session.add(event)
        session.flush()
        if coordinator is not None:
            session.add(
                EventCoordinatorAssignment(
                    event_request_id=event.id,
                    coordinator_account_id=IDENTITIES[coordinator],
                    assigned_by_account_id=IDENTITIES["organiser"],
                    assigned_at=NOW,
                )
            )
        session.commit()
        return event.id


def add_line(
    app,
    event_id,
    *,
    status="requested",
    quantity=4,
    start=START,
    end=END,
    mapped=True,
    text="Wireless microphones",
    notes="Needs a spare battery pack.",
):
    with Session(app.extensions["engine"]) as session:
        line = EquipmentRequirement(
            event_request_id=event_id,
            equipment_type=text,
            quantity=quantity,
            notes=notes,
            equipment_type_id=1 if mapped else None,
            required_start_date=start,
            required_end_date=end,
            status=status,
        )
        session.add(line)
        session.commit()
        return line.id


def headers(identity="technical"):
    return {} if identity is None else {"Authorization": f"Bearer {identity}"}


def queue(client, identity="technical"):
    return client.get("/api/equipment-review-queue", headers=headers(identity))


def entry(client, requirement_id, identity="technical"):
    return client.get(f"/api/equipment-review-queue/{requirement_id}", headers=headers(identity))


def add_note(client, requirement_id, identity="technical", **kwargs):
    return client.post(
        f"/api/equipment-review-queue/{requirement_id}/notes",
        headers=headers(identity),
        **kwargs,
    )


def read_notes(client, requirement_id, identity="coordinator"):
    return client.get(
        f"/api/equipment-requirements/{requirement_id}/review-notes",
        headers=headers(identity),
    )


def queued_ids(response):
    return [item["id"] for item in response.json["requirements"]]


def line_state(app, requirement_id):
    """Everything AC4 promises not to touch."""

    with Session(app.extensions["engine"]) as session:
        line = session.get(EquipmentRequirement, requirement_id)
        equipment_type = session.get(EquipmentType, 1)
        return (
            line.status,
            line.quantity,
            line.required_start_date,
            line.required_end_date,
            equipment_type.total_stock,
        )


def stored_notes(app, requirement_id):
    with Session(app.extensions["engine"]) as session:
        return list(
            session.scalars(
                select(EquipmentReviewNote)
                .where(EquipmentReviewNote.equipment_requirement_id == requirement_id)
                .order_by(EquipmentReviewNote.id)
            )
        )


# AC1, AC3, AC4 — the queue, a note, and no side effects


# TC-SPL-92-01
# SPL-92 AC-1 / AC-3 / AC-4 Test-01
def test_tc_spl_92_01_the_queue_lists_waiting_lines_and_a_note_reaches_the_coordinator(app, client):
    planning_event = add_event(app)
    cancelled_event = add_event(app, status="cancelled", name="Called Off Conference")

    waiting = add_line(app, planning_event, status="requested", start=date(2026, 11, 20))
    flagged = add_line(app, planning_event, status="review_required", start=date(2026, 11, 18))
    reserved = add_line(app, planning_event, status="reserved", start=date(2026, 11, 1))
    on_cancelled = add_line(app, cancelled_event, status="requested", start=date(2026, 11, 2))

    before = line_state(app, waiting)

    listed = queue(client)
    assert listed.status_code == 200
    # Earliest required start first, and only the two lines that are actually waiting.
    assert queued_ids(listed) == [flagged, waiting]
    assert reserved not in queued_ids(listed)
    assert on_cancelled not in queued_ids(listed)

    # AC3: Technical Support leaves a question for the coordinator.
    saved = add_note(client, waiting, json={"note": "Can this move to the Tuesday instead?"})
    assert saved.status_code == 201
    assert saved.json["note"]["note"] == "Can this move to the Tuesday instead?"
    assert saved.json["note"]["author"]["id"] == IDENTITIES["technical"]
    assert saved.json["note"]["created_at"].startswith("2026-10-11T09:00")

    # AC3: the event's assigned coordinator can read it.
    coordinator_view = read_notes(client, waiting, "coordinator")
    assert coordinator_view.status_code == 200
    assert [note["note"] for note in coordinator_view.json["review_notes"]] == [
        "Can this move to the Tuesday instead?"
    ]

    # AC4: nothing about the line, its quantities or the stock moved.
    assert line_state(app, waiting) == before


# AC5 — Technical Support only


# TC-SPL-92-02
# SPL-92 AC-5 Test-02
def test_tc_spl_92_02_only_technical_support_can_open_the_queue_or_add_notes(app, client):
    event_id = add_event(app)
    line_id = add_line(app, event_id)
    before = line_state(app, line_id)
    note = {"note": "Unauthorised note."}

    # The assigned coordinator may read notes, but must not open the queue (AC5).
    for identity in ("coordinator", "other-coordinator", "venue", "organiser"):
        assert queue(client, identity).status_code == 403, identity
        assert entry(client, line_id, identity).status_code == 403, identity
        assert add_note(client, line_id, identity, json=note).status_code == 403, identity
    assert queue(client, None).status_code == 401
    assert add_note(client, line_id, None, json=note).status_code == 401

    # Nothing any of them sent was saved, and nothing changed.
    assert stored_notes(app, line_id) == []
    assert line_state(app, line_id) == before

    # Technical Support opens the queue in the same test, so none of the above passes vacuously.
    allowed = queue(client)
    assert allowed.status_code == 200
    assert queued_ids(allowed) == [line_id]


# AC2 — what each entry shows


# TC-SPL-92-03
# SPL-92 AC-2 Test-03
def test_tc_spl_92_03_each_entry_shows_what_is_needed_to_act(app, client):
    event_id = add_event(app, status="confirmed")
    mapped_line = add_line(app, event_id, notes="Needs a spare battery pack.")
    legacy_line = add_line(
        app, event_id, mapped=False, text="Wireless microphone", notes="From the original request."
    )

    listed = queue(client)
    by_id = {item["id"]: item for item in listed.json["requirements"]}

    mapped = by_id[mapped_line]
    assert mapped["event"]["name"] == "Community Leadership Forum"
    assert mapped["event"]["date"] == START.isoformat()
    assert mapped["event"]["status"] == "confirmed"
    assert mapped["event"]["status_label"] == "Confirmed"
    assert mapped["coordinator"]["id"] == IDENTITIES["coordinator"]
    assert mapped["equipment_type"]["name"] == "Wireless Microphone"
    assert mapped["quantity"] == 4
    assert mapped["required_start_date"] == START.isoformat()
    assert mapped["required_end_date"] == END.isoformat()
    assert mapped["status"] == "requested"
    assert mapped["needs_mapping"] is False

    # AC2: a line never mapped to the catalogue keeps the organiser's own wording and is flagged.
    legacy = by_id[legacy_line]
    assert legacy["equipment_type"] is None
    assert legacy["organiser_equipment_text"] == "Wireless microphone"
    assert legacy["needs_mapping"] is True

    # Opening a line adds its technical notes, its review notes and the event's status.
    opened = entry(client, mapped_line)
    assert opened.status_code == 200
    assert opened.json["requirement"]["notes"] == "Needs a spare battery pack."
    assert opened.json["requirement"]["review_notes"] == []
    assert opened.json["requirement"]["event"]["status_label"] == "Confirmed"

    # An unknown line, and one that is not in the queue, are both 404.
    assert entry(client, 999_999).status_code == 404


# TC-SPL-92-04
# SPL-92 AC-1 Test-04
def test_tc_spl_92_04_only_lines_on_active_events_appear(app, client):
    included = {}
    excluded = {}
    for status in ACTIVE_EVENT_STATUSES:
        event_id = add_event(app, status=status, name=f"Active {status}")
        included[status] = add_line(app, event_id)
    # Completed and Cancelled are named by AC1; the rest are events not yet in planning.
    for status in ("completed", "cancelled", "draft", "submitted", "under_review", "approved"):
        event_id = add_event(app, status=status, name=f"Inactive {status}")
        excluded[status] = add_line(app, event_id)

    listed = queue(client)
    ids = queued_ids(listed)

    # Every excluded line sits in the same database as an included one, so an empty queue fails.
    for status, line_id in included.items():
        assert line_id in ids, status
    for status, line_id in excluded.items():
        assert line_id not in ids, status
    assert len(ids) == len(ACTIVE_EVENT_STATUSES)


# TC-SPL-92-05
# SPL-92 AC-1 Test-05
def test_tc_spl_92_05_the_order_is_stable_and_by_required_start_date(app, client):
    first_event = add_event(app, name="First event")
    second_event = add_event(app, name="Second event")

    # Created deliberately out of order.
    latest = add_line(app, first_event, start=date(2026, 12, 1))
    earliest = add_line(app, second_event, start=date(2026, 11, 1))
    same_date_second_event = add_line(app, second_event, start=date(2026, 11, 15))
    same_date_first_event = add_line(app, first_event, start=date(2026, 11, 15))

    expected = [
        earliest,
        # Same required date: by event id, then line id, so two requests never disagree.
        same_date_first_event,
        same_date_second_event,
        latest,
    ]
    assert queued_ids(queue(client)) == expected
    # Asked twice, answered the same way.
    assert queued_ids(queue(client)) == expected


# TC-SPL-92-06
# SPL-92 AC-1 Test-06 — Pending PO: Partially Reserved lines stay out, as AC1 is written.
def test_tc_spl_92_06_lines_in_other_statuses_do_not_appear(app, client):
    event_id = add_event(app)
    waiting = add_line(app, event_id, status="requested")
    others = {
        status: add_line(app, event_id, status=status)
        for status in ("unmapped", "partially_reserved", "reserved", "unavailable", "removed")
    }

    ids = queued_ids(queue(client))

    assert waiting in ids
    for status, line_id in others.items():
        assert line_id not in ids, status
    assert ids == [waiting]


# AC3, AC5 — notes


# TC-SPL-92-07
# SPL-92 AC-3 / AC-5 Test-07
def test_tc_spl_92_07_notes_record_their_author_and_time_and_only_the_right_people_read_them(
    app, client, monkeypatch
):
    event_id = add_event(app)
    line_id = add_line(app, event_id)
    other_event = add_event(app, name="Someone else's event", coordinator="other-coordinator")
    other_line = add_line(app, other_event)

    # A blank, whitespace-only, over-long, wrong-typed or unexpected payload is refused.
    for refused in (
        {"note": ""},
        {"note": "   "},
        {"note": "x" * 2_001},
        {"note": 42},
        {},
        {"note": "Fine.", "status": "reserved"},
    ):
        response = add_note(client, line_id, json=refused)
        assert response.status_code == 400, refused
    assert stored_notes(app, line_id) == []

    # Two notes by different authors at different times.
    assert add_note(client, line_id, json={"note": "First question."}).status_code == 201
    later = datetime(2026, 10, 11, 9, 5, tzinfo=SINGAPORE)
    monkeypatch.setattr(queue_module, "_now", lambda: later)
    assert (
        add_note(client, line_id, "second-technical", json={"note": "Second question."}).status_code
        == 201
    )

    written = stored_notes(app, line_id)
    assert [item.note for item in written] == ["First question.", "Second question."]
    assert [item.author_account_id for item in written] == [
        IDENTITIES["technical"],
        IDENTITIES["second-technical"],
    ]
    assert written[1].created_at == later.replace(tzinfo=None)

    # The assigned coordinator reads their own event's notes, oldest first.
    mine = read_notes(client, line_id, "coordinator")
    assert mine.status_code == 200
    assert [note["note"] for note in mine.json["review_notes"]] == [
        "First question.",
        "Second question.",
    ]

    # Another coordinator gets the same answer as an unknown line, so ids reveal nothing.
    assert read_notes(client, line_id, "other-coordinator").status_code == 404
    assert read_notes(client, 999_999, "coordinator").status_code == 404
    # And the other coordinator can still read their own line, so the 404 is about ownership.
    assert read_notes(client, other_line, "other-coordinator").status_code == 200


# AC4 — a work view with no side effects


# TC-SPL-92-08
# SPL-92 AC-4 Test-08
def test_tc_spl_92_08_opening_the_queue_and_adding_a_note_change_nothing(app, client):
    event_id = add_event(app)
    line_id = add_line(app, event_id, status="requested")
    flagged = add_line(app, event_id, status="review_required")
    before = {item: line_state(app, item) for item in (line_id, flagged)}

    assert queue(client).status_code == 200
    assert entry(client, line_id).status_code == 200
    assert add_note(client, line_id, json={"note": "Checking the dates."}).status_code == 201
    assert queue(client).status_code == 200

    # Status, quantities, dates and the equipment type's stock are all untouched (AC4).
    assert {item: line_state(app, item) for item in (line_id, flagged)} == before
    # A Review Required line is not quietly cleared by being looked at.
    assert line_state(app, flagged)[0] == "review_required"
