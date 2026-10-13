"""Acceptance coverage for SPL-91 (CS-E14-S2): the coordinator changes an equipment requirement.

Each test carries the QA-SPL-91 case identifier it proves. The cases were published on the
QA-SPL-91 page on 10 October 2026, before this story's code existed.

What this story adds to SPL-90
------------------------------
SPL-90 already lets the assigned coordinator change and remove a line that holds no stock
(Unmapped or Requested). This story covers the lines that *do*: Reserved, Partially Reserved and
Review Required. Its rule (AC2, built to "option A" — the reading of AC2 as written, which became
final when the open question passed its stand-up fallback unanswered) is that a change to a line
holding units releases all of them and marks the line Review Required, so a reservation can never
be left describing values the line no longer has (AC4).

Releases happen only through SPL-98's shared release operation, so the release history has one
owner. These tests assert against SPL-98's ``equipment_reservation_releases`` rows directly.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database with one Planning event, its assigned
  coordinator, and two catalogue types. ``add_line`` adds a requirement line, and ``reserve``
  gives it units the way SPL-97 would have.
- Sign-in is simulated: a token such as "coordinator" maps to a known account id.
- The clock is frozen through the single clock function in app/equipment_requirements.py.
- Every refusal test checks that no release row and no history row were written, and also proves
  a genuine change succeeds in the same test, so a missing route could not make it pass.

TC-SPL-91-04 (two simultaneous changes) needs two real transactions and lives in
test_equipment_requirement_changes_postgres.py. TC-SPL-91-10 is a component case and TC-SPL-91-11
a browser case.
"""

from datetime import date, datetime, time, timedelta

import pytest
from app import create_app
from app import equipment_requirements as requirements_module
from app.equipment_reservation_state import remaining_quantity
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentRequirementChange,
    EquipmentReservation,
    EquipmentReservationRelease,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

IDENTITIES = {
    "coordinator": "00000000-0000-0000-0000-000000000911",
    "other-coordinator": "00000000-0000-0000-0000-000000000912",
    "technical": "00000000-0000-0000-0000-000000000913",
    "organiser": "00000000-0000-0000-0000-000000000914",
    "venue": "00000000-0000-0000-0000-000000000915",
    "manager": "00000000-0000-0000-0000-000000000916",
}

ROLES = {
    "coordinator": Role.EVENT_COORDINATOR,
    "other-coordinator": Role.EVENT_COORDINATOR,
    "technical": Role.TECHNICAL_SUPPORT_STAFF,
    "organiser": Role.EVENT_ORGANISER,
    "venue": Role.VENUE_STAFF,
    "manager": Role.EVENT_OPERATIONS_MANAGER,
}

NOW = datetime(2026, 10, 13, 10, 0, tzinfo=SINGAPORE)
EVENT_DATE = date(2026, 11, 20)

# Every event status except In planning, which AC5 says must refuse a change.
NON_PLANNING_STATUSES = (
    "draft",
    "submitted",
    "under_review",
    "returned_for_clarification",
    "approved",
    "confirmed",
    "completed",
    "cancelled",
    "rejected",
    "withdrawn",
    "postponed",
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/equipment-requirement-changes.db",
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
        session.add_all(
            [
                EquipmentType(
                    id=1,
                    name="Wireless Microphone",
                    normalised_name="wireless microphone",
                    location="Technical Store A",
                    total_stock=10,
                ),
                EquipmentType(
                    id=2,
                    name="Portable Speaker",
                    normalised_name="portable speaker",
                    location="Technical Store B",
                    total_stock=6,
                ),
            ]
        )
        session.commit()
    monkeypatch.setattr(requirements_module, "_now", lambda: NOW)
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def event_id(app):
    return add_event(app)


def add_event(app, *, coordinator="coordinator", name="Community Leadership Forum"):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=IDENTITIES["organiser"],
            organisation_id=1,
            name=name,
            purpose="Annual leadership programme",
            proposed_date=EVENT_DATE,
            start_time=time(14, 0),
            end_time=time(17, 0),
            expected_attendance=80,
            status="planning",
            submitted_at=NOW,
        )
        session.add(event)
        session.flush()
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


def add_line(app, event_id, *, quantity=4, type_id=1, status="requested", notes="Panel."):
    with Session(app.extensions["engine"]) as session:
        line = EquipmentRequirement(
            event_request_id=event_id,
            equipment_type="Wireless microphones",
            quantity=quantity,
            notes=notes,
            equipment_type_id=type_id,
            required_start_date=EVENT_DATE,
            required_end_date=EVENT_DATE,
            status=status,
        )
        session.add(line)
        session.commit()
        return line.id


def reserve(app, line_id, units):
    """Give a line ``units`` the way SPL-97 would, and set the status SPL-97 would set."""

    with Session(app.extensions["engine"]) as session:
        line = session.get(EquipmentRequirement, line_id)
        session.add(
            EquipmentReservation(
                event_request_id=line.event_request_id,
                equipment_requirement_id=line.id,
                equipment_type_id=line.equipment_type_id,
                commitment_start_date=EVENT_DATE - timedelta(days=1),
                commitment_end_date=EVENT_DATE,
                quantity=units,
                reserved_by_account_id=IDENTITIES["technical"],
                reserved_at=NOW,
            )
        )
        line.status = "reserved" if units >= line.quantity else "partially_reserved"
        session.commit()


def headers(identity="coordinator"):
    return {} if identity is None else {"Authorization": f"Bearer {identity}"}


def line_url(event_id, line_id):
    return f"/api/event-requests/{event_id}/equipment-requirements/{line_id}"


def change(client, event_id, line_id, identity="coordinator", **kwargs):
    return client.patch(line_url(event_id, line_id), headers=headers(identity), **kwargs)


def remove(client, event_id, line_id, identity="coordinator"):
    return client.delete(line_url(event_id, line_id), headers=headers(identity))


def history(client, event_id, line_id, identity="coordinator"):
    return client.get(f"{line_url(event_id, line_id)}/history", headers=headers(identity))


def held(app, line_id):
    """Units this line still holds, using SPL-98's single definition of "still held"."""

    with Session(app.extensions["engine"]) as session:
        reservations = session.scalars(
            select(EquipmentReservation).where(
                EquipmentReservation.equipment_requirement_id == line_id
            )
        ).all()
        return sum(remaining_quantity(item) for item in reservations)


def held_for_type(app, type_id):
    with Session(app.extensions["engine"]) as session:
        reservations = session.scalars(
            select(EquipmentReservation).where(EquipmentReservation.equipment_type_id == type_id)
        ).all()
        return sum(remaining_quantity(item) for item in reservations)


def release_rows(app, line_id):
    with Session(app.extensions["engine"]) as session:
        return list(
            session.scalars(
                select(EquipmentReservationRelease)
                .join(EquipmentReservation)
                .where(EquipmentReservation.equipment_requirement_id == line_id)
                .order_by(EquipmentReservationRelease.id)
            )
        )


def change_rows(app, line_id):
    with Session(app.extensions["engine"]) as session:
        return list(
            session.scalars(
                select(EquipmentRequirementChange)
                .where(EquipmentRequirementChange.equipment_requirement_id == line_id)
                .order_by(EquipmentRequirementChange.id)
            )
        )


def line_state(app, line_id):
    with Session(app.extensions["engine"]) as session:
        line = session.get(EquipmentRequirement, line_id)
        return (
            line.status,
            line.quantity,
            line.equipment_type_id,
            line.notes,
            line.review_reason,
        )


def total_release_rows(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(EquipmentReservationRelease))


def total_change_rows(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(EquipmentRequirementChange))


# AC1, AC2, AC4 — the published headline scenario


# TC-SPL-91-01
# SPL-91 AC-1 / AC-2 / AC-4 Test-01
def test_tc_spl_91_01_a_quantity_change_releases_the_held_units_and_flags_the_line(
    app, client, event_id
):
    """A line needing 4 units with 2 reserved is changed to 5."""

    line_id = add_line(app, event_id, quantity=4)
    reserve(app, line_id, 2)
    assert line_state(app, line_id)[0] == "partially_reserved"
    assert held(app, line_id) == 2

    changed = change(client, event_id, line_id, json={"quantity": 5})
    assert changed.status_code == 200
    assert changed.json["requirement"]["quantity"] == 5
    assert changed.json["released_quantity"] == 2

    # AC2: the two units were released, through SPL-98's release rows, by the coordinator.
    releases = release_rows(app, line_id)
    assert [item.quantity for item in releases] == [2]
    assert releases[0].released_by_account_id == IDENTITIES["coordinator"]
    assert held(app, line_id) == 0

    # AC2: the line goes back to Technical Support, with a reason a reviewer can act on.
    status, quantity, _, _, reason = line_state(app, line_id)
    assert (status, quantity) == ("review_required", 5)
    assert "quantity" in reason and "4" in reason and "5" in reason

    # AC4: the change is recorded with its old and new values, who and when.
    entries = change_rows(app, line_id)
    assert len(entries) == 1
    assert entries[0].action == "changed"
    assert entries[0].old_values["quantity"] == 4
    assert entries[0].new_values["quantity"] == 5
    assert entries[0].released_quantity == 2
    assert entries[0].changed_by_account_id == IDENTITIES["coordinator"]
    assert entries[0].changed_at == NOW.replace(tzinfo=None)


# TC-SPL-91-02
# SPL-91 AC-1 / AC-2 / AC-3 Test-02
def test_tc_spl_91_02_a_note_change_releases_but_an_unchanged_save_does_nothing(
    app, client, event_id
):
    line_id = add_line(app, event_id, quantity=3, notes="Panel.")
    reserve(app, line_id, 3)
    other_id = add_line(app, event_id, quantity=2, type_id=2, notes="Foyer.")
    reserve(app, other_id, 2)

    # AC2: saving the values the line already has changes nothing, so releases and records
    # nothing. "Without changing anything" is about the values, not about the request.
    unchanged = change(client, event_id, line_id, json={"quantity": 3, "notes": "Panel."})
    assert unchanged.status_code == 200
    assert unchanged.json["released_quantity"] == 0
    assert release_rows(app, line_id) == []
    assert change_rows(app, line_id) == []
    assert line_state(app, line_id)[0] == "reserved"

    # AC1/AC2: a technical-note change counts — the story's assumption is that the system cannot
    # tell a typo from a change that affects suitability.
    noted = change(client, event_id, line_id, json={"notes": "Panel, plus a spare."})
    assert noted.status_code == 200
    assert noted.json["released_quantity"] == 3
    assert held(app, line_id) == 0
    assert line_state(app, line_id)[0] == "review_required"

    # AC3: the other line on the same event is untouched by both.
    assert held(app, other_id) == 2
    assert line_state(app, other_id)[0] == "reserved"
    assert release_rows(app, other_id) == []


# AC5 — refused, with nothing changed


# TC-SPL-91-03
# SPL-91 AC-5 Test-03
def test_tc_spl_91_03_wrong_status_wrong_coordinator_and_wrong_role_are_refused(
    app, client, event_id
):
    line_id = add_line(app, event_id, quantity=4)
    reserve(app, line_id, 4)

    # A removal by a coordinator who is not assigned answers exactly like an unknown event.
    assert remove(client, event_id, line_id, "other-coordinator").status_code == 404
    # A change by Technical Support is a role refusal, before anything is looked up.
    assert change(client, event_id, line_id, "technical", json={"quantity": 5}).status_code == 403

    # A change on a Confirmed event is refused. The story's own assumption: "Confirmed events are
    # changed through the event change workflow, not this story."
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "confirmed"
        session.commit()
    assert change(client, event_id, line_id, json={"quantity": 5}).status_code == 409

    # Not one of them released a unit or wrote a history entry.
    assert total_release_rows(app) == 0
    assert total_change_rows(app) == 0
    assert held(app, line_id) == 4
    assert line_state(app, line_id)[0] == "reserved"

    # Back in planning, the assigned coordinator succeeds, so none of the above is vacuous.
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "planning"
        session.commit()
    assert change(client, event_id, line_id, json={"quantity": 5}).status_code == 200
    assert total_release_rows(app) == 1


# AC1 — validation on a reserved line


# TC-SPL-91-05
# SPL-91 AC-1 Test-05
def test_tc_spl_91_05_invalid_changes_to_a_reserved_line_are_refused_and_release_nothing(
    app, client, event_id
):
    line_id = add_line(app, event_id, quantity=4)
    reserve(app, line_id, 4)
    before = line_state(app, line_id)

    refusals = [
        {"quantity": 0},
        {"quantity": -1},
        {"quantity": 2.5},
        {"quantity": True},
        {"quantity": "5"},
        {"equipment_type_id": 999},  # not a catalogue type
        {"equipment_type_id": "Wireless"},  # free text cannot become inventory
        {"required_start_date": "2026-11-21"},  # outside the event's date
        {"required_end_date": "not-a-date"},
        {"status": "requested"},  # server-owned
        {"reserved_quantity": 0},  # server-owned
        {},
    ]
    for refused in refusals:
        response = change(client, event_id, line_id, json=refused)
        assert response.status_code == 400, refused
        assert "error" in response.json, refused

    # Nothing changed and nothing was released by any refusal — the validation runs before the
    # release, so a bad request can never cost a line its reservation.
    assert line_state(app, line_id) == before
    assert held(app, line_id) == 4
    assert total_release_rows(app) == 0
    assert total_change_rows(app) == 0

    # A valid change succeeds in the same test.
    assert change(client, event_id, line_id, json={"quantity": 6}).status_code == 200


# TC-SPL-91-06
# SPL-91 AC-2 Test-06
def test_tc_spl_91_06_an_equipment_type_change_releases_the_old_pool(app, client, event_id):
    """True under either answer to the open question, so it pins the core of AC2."""

    line_id = add_line(app, event_id, quantity=3, type_id=1)
    reserve(app, line_id, 3)
    assert held_for_type(app, 1) == 3

    moved = change(client, event_id, line_id, json={"equipment_type_id": 2})
    assert moved.status_code == 200
    assert moved.json["released_quantity"] == 3

    # The units go back to the *old* pool, and nothing is taken from the new one: the line now
    # needs re-reviewing against type 2 before anything is reserved there.
    assert held_for_type(app, 1) == 0
    assert held_for_type(app, 2) == 0
    status, _, type_id, _, reason = line_state(app, line_id)
    assert (status, type_id) == ("review_required", 2)
    assert "equipment type" in reason

    entry = change_rows(app, line_id)[0]
    assert (entry.old_values["equipment_type_id"], entry.new_values["equipment_type_id"]) == (1, 2)


# AC3 — removal


# TC-SPL-91-07
# SPL-91 AC-3 Test-07
def test_tc_spl_91_07_removal_releases_once_and_keeps_the_history(app, client, event_id):
    full_id = add_line(app, event_id, quantity=3, type_id=1)
    reserve(app, full_id, 3)
    partial_id = add_line(app, event_id, quantity=5, type_id=1, notes="Breakout.")
    reserve(app, partial_id, 2)
    assert held_for_type(app, 1) == 5

    # Removing a Reserved line releases its 3 units once.
    removed = remove(client, event_id, full_id)
    assert removed.status_code == 200
    assert removed.json["released_quantity"] == 3
    assert removed.json["requirement"]["status"] == "removed"
    assert [item.quantity for item in release_rows(app, full_id)] == [3]
    # The type's held total falls by exactly the released units.
    assert held_for_type(app, 1) == 2

    # Removing a Partially Reserved line releases only what it held.
    partial = remove(client, event_id, partial_id)
    assert partial.json["released_quantity"] == 2
    assert held_for_type(app, 1) == 0

    # A second removal is refused and releases nothing more — "released once".
    again = remove(client, event_id, full_id)
    assert again.status_code == 409
    assert [item.quantity for item in release_rows(app, full_id)] == [3]

    # AC3: the removed line and its release stay in history.
    entry = change_rows(app, full_id)
    assert [(item.action, item.released_quantity) for item in entry] == [("removed", 3)]
    with Session(app.extensions["engine"]) as session:
        line = session.get(EquipmentRequirement, full_id)
        assert line.status == "removed"
        assert line.removed_by_account_id == IDENTITIES["coordinator"]


# AC4 — the history, readable by the coordinator


# TC-SPL-91-08
# SPL-91 AC-4 Test-08
def test_tc_spl_91_08_every_change_is_recorded_and_readable_newest_first(
    app, client, event_id, monkeypatch
):
    line_id = add_line(app, event_id, quantity=4)
    reserve(app, line_id, 4)

    assert change(client, event_id, line_id, json={"quantity": 6}).status_code == 200
    later = NOW + timedelta(minutes=5)
    monkeypatch.setattr(requirements_module, "_now", lambda: later)
    assert change(client, event_id, line_id, json={"notes": "Bring spares."}).status_code == 200
    latest = NOW + timedelta(minutes=9)
    monkeypatch.setattr(requirements_module, "_now", lambda: latest)
    assert remove(client, event_id, line_id).status_code == 200

    listed = history(client, event_id, line_id)
    assert listed.status_code == 200
    entries = listed.json["history"]
    # Newest first.
    assert [item["action"] for item in entries] == ["removed", "changed", "changed"]
    assert entries[-1]["old_values"]["quantity"] == 4
    assert entries[-1]["new_values"]["quantity"] == 6
    assert entries[-1]["released_quantity"] == 4
    assert entries[1]["new_values"]["notes"] == "Bring spares."
    # Only the first change held units; the later ones had nothing left to release.
    assert [item["released_quantity"] for item in entries] == [0, 0, 4]
    assert entries[0]["changed_by"]["id"] == IDENTITIES["coordinator"]
    assert entries[0]["changed_at"].startswith("2026-10-13T10:09")

    # The history is the assigned coordinator's; another coordinator gets the same 404 as an
    # unknown line, and other roles are refused before anything is looked up.
    assert history(client, event_id, line_id, "other-coordinator").status_code == 404
    assert history(client, event_id, line_id, "technical").status_code == 403
    assert history(client, event_id, line_id, None).status_code == 401
    assert history(client, event_id, 999_999).status_code == 404


# AC5 — every status, every role, and SPL-90 unchanged


# TC-SPL-91-09
# SPL-91 AC-5 Test-09
def test_tc_spl_91_09_only_the_assigned_coordinator_and_only_in_planning(app, client, event_id):
    line_id = add_line(app, event_id, quantity=4)
    reserve(app, line_id, 4)

    for status in NON_PLANNING_STATUSES:
        with Session(app.extensions["engine"]) as session:
            session.get(EventRequest, event_id).status = status
            session.commit()
        assert change(client, event_id, line_id, json={"quantity": 5}).status_code == 409, status
        assert remove(client, event_id, line_id).status_code == 409, status

    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "planning"
        session.commit()
    for identity in ("organiser", "venue", "manager", "technical"):
        assert change(client, event_id, line_id, identity, json={"quantity": 5}).status_code == 403
        assert remove(client, event_id, line_id, identity).status_code == 403
    assert change(client, event_id, line_id, None, json={"quantity": 5}).status_code == 401

    # Nothing was released or recorded by any of those.
    assert total_release_rows(app) == 0
    assert total_change_rows(app) == 0
    assert held(app, line_id) == 4

    # The assigned coordinator succeeds in the same test.
    assert change(client, event_id, line_id, json={"quantity": 5}).status_code == 200

    # SPL-90's edit and removal of a Requested line still behave as before: no units are held,
    # so nothing is released, and the line keeps its Requested status.
    requested_id = add_line(app, event_id, quantity=2, type_id=2)
    edited = change(client, event_id, requested_id, json={"quantity": 3})
    assert edited.status_code == 200
    assert edited.json["released_quantity"] == 0
    assert line_state(app, requested_id)[0] == "requested"
    assert release_rows(app, requested_id) == []
    gone = remove(client, event_id, requested_id)
    assert gone.status_code == 200
    assert gone.json["requirement"]["status"] == "removed"


# TC-SPL-91-12
# SPL-91 AC-2 Test-12 (added after mutation testing showed nothing pinned this boundary)
def test_tc_spl_91_12_recording_essentiality_keeps_the_reservation(app, client, event_id):
    """An essentiality decision is not one of AC1's fields, so it must not release stock.

    The story puts "recording whether equipment is essential" out of scope as SPL-90's, and it
    does not alter what Technical Support reserved. Mutation testing showed that adding it to
    the fields that trigger a release passed every other case, so a coordinator recording
    "Essential" on a reserved line could have silently cost it its units.
    """

    line_id = add_line(app, event_id, quantity=4)
    reserve(app, line_id, 4)

    decided = change(
        client,
        event_id,
        line_id,
        json={
            "essentiality": "essential",
            "consulted_technical_support_account_id": IDENTITIES["technical"],
            "essentiality_decision_note": "Keynote cannot run without it.",
        },
    )
    assert decided.status_code == 200
    assert decided.json["released_quantity"] == 0

    # The reservation and the status are exactly as Technical Support left them.
    assert held(app, line_id) == 4
    assert release_rows(app, line_id) == []
    status, _, _, _, reason = line_state(app, line_id)
    assert (status, reason) == ("reserved", None)

    # It is still a change to the line, so AC4 records it — with nothing released.
    entries = change_rows(app, line_id)
    assert len(entries) == 1
    assert entries[0].new_values["essentiality"] == "essential"
    assert entries[0].released_quantity == 0
