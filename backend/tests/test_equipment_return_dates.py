"""Acceptance coverage for SPL-100 (CS-E16-S4): the planned return date of a reservation.

Each test carries the QA-SPL-100 case identifier it proves. The cases were published on the
QA-SPL-100 page before this story's code existed.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database with one catalogue type and, through
  ``add_reservation``, a planning event whose requirement line already holds units.
- Sign-in is simulated: a token such as "technical" maps to a known account id (``IDENTITIES``).
- The clock is frozen through the single clock function in app/equipment_return_dates.py, so the
  time a change was recorded is assertable.
- Reservations come from SPL-97. They are written directly here rather than through its route,
  because this story is about changing a date on a reservation that already exists.
- Every refusal test checks the stored date, quantity and status are untouched, and also proves a
  genuine change succeeds in the same test, so a missing route could not make it pass.

What "overcommit" means on this branch
--------------------------------------
Stock here is ``equipment_types.total_stock``. SPL-96 adds ``unavailable_units`` and the notion of
*usable* stock; it is on a separate branch. **When SPL-96 merges, the overcommit check in
app/equipment_return_dates.py must switch from total stock to usable stock.** Flagged in that
module, in docs/tasks/SPL-100.md and on the pull request.
"""

from datetime import date, datetime, time, timedelta

import pytest
from app import create_app
from app import equipment_return_dates as return_dates_module
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy.orm import Session

IDENTITIES = {
    "technical": "00000000-0000-0000-0000-000000001001",
    "coordinator": "00000000-0000-0000-0000-000000001002",
    "organiser": "00000000-0000-0000-0000-000000001003",
    "venue": "00000000-0000-0000-0000-000000001004",
    "manager": "00000000-0000-0000-0000-000000001005",
}

ROLES = {
    "technical": Role.TECHNICAL_SUPPORT_STAFF,
    "coordinator": Role.EVENT_COORDINATOR,
    "organiser": Role.EVENT_ORGANISER,
    "venue": Role.VENUE_STAFF,
    "manager": Role.EVENT_OPERATIONS_MANAGER,
}

NOW = datetime(2026, 10, 11, 10, 0, tzinfo=SINGAPORE)

# The published scenario's dates: required 13-14 Oct, so the commitment collects on 12 Oct.
REQUIRED_START = date(2026, 10, 13)
REQUIRED_END = date(2026, 10, 14)
COLLECTION_DAY = date(2026, 10, 12)


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/equipment-return-dates.db",
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
        session.commit()
    monkeypatch.setattr(return_dates_module, "_now", lambda: NOW)
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def add_equipment_type(app, *, total_stock, name="Wireless Microphone"):
    with Session(app.extensions["engine"]) as session:
        item = EquipmentType(
            name=name,
            normalised_name=name.casefold(),
            location="Technical Store A",
            total_stock=total_stock,
        )
        session.add(item)
        session.commit()
        return item.id


def add_reservation(
    app,
    equipment_type_id,
    *,
    quantity,
    start=REQUIRED_START,
    end=REQUIRED_END,
    name="Community Leadership Forum",
):
    """One planning event with a requirement line that already holds ``quantity`` units.

    Returns (reservation_id, requirement_id). The reservation's commitment runs from the day
    before the required start (SPL-95's collection rule) to the required end date, which is
    SPL-97's own default and the AC1 default this story must preserve.
    """

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=IDENTITIES["organiser"],
            organisation_id=1,
            name=name,
            purpose="Annual leadership programme",
            proposed_date=start,
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
                coordinator_account_id=IDENTITIES["coordinator"],
                assigned_by_account_id=IDENTITIES["organiser"],
                assigned_at=NOW,
            )
        )
        line = EquipmentRequirement(
            event_request_id=event.id,
            equipment_type="Wireless microphones",
            quantity=quantity,
            equipment_type_id=equipment_type_id,
            required_start_date=start,
            required_end_date=end,
            status="reserved",
        )
        session.add(line)
        session.flush()
        reservation = EquipmentReservation(
            event_request_id=event.id,
            equipment_requirement_id=line.id,
            equipment_type_id=equipment_type_id,
            commitment_start_date=start - timedelta(days=1),
            commitment_end_date=end,
            quantity=quantity,
            reserved_by_account_id=IDENTITIES["technical"],
            reserved_at=NOW,
        )
        session.add(reservation)
        session.commit()
        return reservation.id, line.id


def add_bare_reservation(app, equipment_type_id, *, quantity, commitment_start, commitment_end):
    """A competing reservation whose commitment days are set exactly, not derived from a required
    date. Needed to put a full day *inside* an extension rather than at its edge.
    """

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=IDENTITIES["organiser"],
            organisation_id=1,
            name=f"Competing event {commitment_start.isoformat()}",
            purpose="Annual leadership programme",
            proposed_date=commitment_start,
            start_time=time(14, 0),
            end_time=time(17, 0),
            expected_attendance=80,
            status="planning",
            submitted_at=NOW,
        )
        session.add(event)
        session.flush()
        line = EquipmentRequirement(
            event_request_id=event.id,
            equipment_type="Wireless microphones",
            quantity=quantity,
            equipment_type_id=equipment_type_id,
            required_start_date=commitment_start,
            required_end_date=commitment_end,
            status="reserved",
        )
        session.add(line)
        session.flush()
        session.add(
            EquipmentReservation(
                event_request_id=event.id,
                equipment_requirement_id=line.id,
                equipment_type_id=equipment_type_id,
                commitment_start_date=commitment_start,
                commitment_end_date=commitment_end,
                quantity=quantity,
                reserved_by_account_id=IDENTITIES["technical"],
                reserved_at=NOW,
            )
        )
        session.commit()


def headers(identity="technical"):
    return {} if identity is None else {"Authorization": f"Bearer {identity}"}


def set_return_date(client, reservation_id, identity="technical", **kwargs):
    return client.patch(
        f"/api/equipment-reservations/{reservation_id}/planned-return-date",
        headers=headers(identity),
        **kwargs,
    )


def stored(app, reservation_id):
    """Everything a refusal must leave alone, plus the AC3 audit fields."""

    with Session(app.extensions["engine"]) as session:
        row = session.get(EquipmentReservation, reservation_id)
        line = session.get(EquipmentRequirement, row.equipment_requirement_id)
        return (
            row.commitment_end_date,
            row.quantity,
            line.status,
            row.return_date_changed_by_account_id,
            row.return_date_changed_at,
        )


def reserve(client, requirement_id, quantity, identity="technical"):
    """SPL-97's reserve route. Used here to show which days a commitment really occupies."""

    return client.post(
        f"/api/equipment-requirements/{requirement_id}/reservations",
        headers=headers(identity),
        json={"quantity": quantity},
    )


def add_requirement_only(app, equipment_type_id, *, quantity, start, end, name):
    """A requirement line with no reservation yet, so SPL-97's route can be asked to fill it."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=IDENTITIES["organiser"],
            organisation_id=1,
            name=name,
            purpose="Annual leadership programme",
            proposed_date=start,
            start_time=time(14, 0),
            end_time=time(17, 0),
            expected_attendance=80,
            status="planning",
            submitted_at=NOW,
        )
        session.add(event)
        session.flush()
        line = EquipmentRequirement(
            event_request_id=event.id,
            equipment_type="Wireless microphones",
            quantity=quantity,
            equipment_type_id=equipment_type_id,
            required_start_date=start,
            required_end_date=end,
            status="requested",
        )
        session.add(line)
        session.commit()
        return line.id


# AC1, AC2, AC3 — the published headline scenario


# TC-SPL-100-01
# SPL-100 AC-1 / AC-2 / AC-3 Test-01
def test_tc_spl_100_01_the_commitment_ends_on_the_planned_date_and_bounds_are_enforced(app, client):
    type_id = add_equipment_type(app, total_stock=2)
    reservation_id, _ = add_reservation(app, type_id, quantity=2)

    # AC1: the default is the requirement's required end date, with no edit recorded.
    assert stored(app, reservation_id) == (REQUIRED_END, 2, "reserved", None, None)

    # AC2: another event can hold the same units from the day after the planned return. Its own
    # collection day is 15 Oct, which is the first day this reservation no longer occupies.
    other_id, _ = add_reservation(
        app,
        type_id,
        quantity=2,
        start=date(2026, 10, 16),
        end=date(2026, 10, 17),
        name="Follow-on event",
    )
    assert stored(app, other_id)[0] == date(2026, 10, 17)

    # AC3: 15 Oct is fully allocated to that second event's collection day, so extending this
    # reservation into it is refused and nothing moves.
    before = stored(app, reservation_id)
    refused = set_return_date(client, reservation_id, json={"planned_return_date": "2026-10-15"})
    assert refused.status_code == 409
    assert "overcommit" in refused.json["error"].lower() or "stock" in refused.json["error"].lower()
    assert stored(app, reservation_id) == before

    # AC1: a date before the requirement's required end date is refused, with the field named.
    earlier = set_return_date(client, reservation_id, json={"planned_return_date": "2026-10-13"})
    assert earlier.status_code == 400
    assert earlier.json["field"] == "planned_return_date"
    assert stored(app, reservation_id) == before


# AC4 — Technical Support only


# TC-SPL-100-02
# SPL-100 AC-4 Test-02
def test_tc_spl_100_02_only_technical_support_can_change_the_planned_return_date(app, client):
    type_id = add_equipment_type(app, total_stock=5)
    reservation_id, _ = add_reservation(app, type_id, quantity=2)
    before = stored(app, reservation_id)
    body = {"planned_return_date": "2026-10-16"}

    for identity in ("coordinator", "organiser", "venue", "manager"):
        assert set_return_date(client, reservation_id, identity, json=body).status_code == 403, (
            identity
        )
    assert set_return_date(client, reservation_id, None, json=body).status_code == 401

    # Not one of them moved the date or left an audit trail.
    assert stored(app, reservation_id) == before

    # Technical Support succeeds in the same test, so none of the above passes vacuously.
    accepted = set_return_date(client, reservation_id, json=body)
    assert accepted.status_code == 200
    assert accepted.json["reservation"]["planned_return_date"] == "2026-10-16"

    # An unknown reservation is 404, and is not created by trying.
    assert set_return_date(client, 999_999, json=body).status_code == 404


# TC-SPL-100-03
# SPL-100 AC-1 Test-03
def test_tc_spl_100_03_a_new_reservation_defaults_to_the_required_end_date(app, client):
    """AC1's default is SPL-97's behaviour.

    This case pins it so a later change cannot silently move it. It therefore passes without this
    story's code, which is its purpose: it is a regression guard, not a test of new behaviour.
    """

    type_id = add_equipment_type(app, total_stock=4)
    reservation_id, requirement_id = add_reservation(
        app, type_id, quantity=1, start=date(2026, 11, 3), end=date(2026, 11, 6)
    )

    with Session(app.extensions["engine"]) as session:
        line = session.get(EquipmentRequirement, requirement_id)
        reservation = session.get(EquipmentReservation, reservation_id)
        assert reservation.commitment_end_date == line.required_end_date
        # And the commitment starts the day before the required start, SPL-95's collection rule.
        assert reservation.commitment_start_date == line.required_start_date - timedelta(days=1)


# TC-SPL-100-04
# SPL-100 AC-1 Test-04
def test_tc_spl_100_04_boundaries_and_malformed_requests_are_refused(app, client):
    type_id = add_equipment_type(app, total_stock=5)
    reservation_id, _ = add_reservation(app, type_id, quantity=1)
    before = stored(app, reservation_id)

    # The required end date itself is accepted: AC1 allows "the required end date or any later".
    same = set_return_date(client, reservation_id, json={"planned_return_date": "2026-10-14"})
    assert same.status_code == 200
    assert stored(app, reservation_id)[0] == REQUIRED_END

    refusals = [
        {"planned_return_date": "2026-10-13"},  # one day before the required end
        {"planned_return_date": "not-a-date"},
        {"planned_return_date": "2026-13-45"},
        {"planned_return_date": ""},
        {"planned_return_date": None},
        {"planned_return_date": 20261016},
        {},  # missing
        {"planned_return_date": "2026-10-16", "quantity": 9},
        {"planned_return_date": "2026-10-16", "status": "reserved"},
    ]
    for refused in refusals:
        response = set_return_date(client, reservation_id, json=refused)
        assert response.status_code == 400, refused
        assert "error" in response.json, refused

    # The accepted change above is the only one that landed.
    assert stored(app, reservation_id)[0] == REQUIRED_END
    assert stored(app, reservation_id)[1:3] == before[1:3]


# AC2, AC3 — a feasible extension is saved and availability follows it


# TC-SPL-100-05
# SPL-100 AC-2 / AC-3 Test-05
def test_tc_spl_100_05_a_feasible_extension_is_recorded_and_the_days_become_committed(app, client):
    """Stock 5, this reservation holds 2 to 14 Oct; extend it to 16 Oct."""

    type_id = add_equipment_type(app, total_stock=5)
    reservation_id, _ = add_reservation(app, type_id, quantity=2)

    accepted = set_return_date(client, reservation_id, json={"planned_return_date": "2026-10-16"})
    assert accepted.status_code == 200
    assert accepted.json["reservation"]["planned_return_date"] == "2026-10-16"

    # AC3: saved with who made it and when.
    end_date, quantity, _, changed_by, changed_at = stored(app, reservation_id)
    assert end_date == date(2026, 10, 16)
    assert quantity == 2
    assert changed_by == IDENTITIES["technical"]
    assert changed_at == NOW.replace(tzinfo=None)
    assert accepted.json["reservation"]["return_date_changed_at"].startswith("2026-10-11T10:00")

    # AC2: the added days are genuinely committed now. A line needing 16 Oct collects on 15 Oct,
    # so it overlaps the extension: only 3 of the 5 units are left to promise.
    overlapping = add_requirement_only(
        app,
        type_id,
        quantity=4,
        start=date(2026, 10, 16),
        end=date(2026, 10, 16),
        name="Overlapping event",
    )
    assert reserve(client, overlapping, 4).status_code == 409
    assert reserve(client, overlapping, 3).status_code == 201

    # And a line clear of the extension is untouched: required 18 Oct collects on 17 Oct, after
    # this reservation now ends, so all 5 units are available to it.
    clear = add_requirement_only(
        app,
        type_id,
        quantity=5,
        start=date(2026, 10, 18),
        end=date(2026, 10, 18),
        name="Later event",
    )
    assert reserve(client, clear, 5).status_code == 201


# TC-SPL-100-06
# SPL-100 AC-3 Test-06
def test_tc_spl_100_06_a_refused_extension_leaves_everything_as_it_was(app, client):
    type_id = add_equipment_type(app, total_stock=3)
    reservation_id, _ = add_reservation(app, type_id, quantity=2)

    # Make the day after the planned return fully committed by another event.
    add_reservation(
        app,
        type_id,
        quantity=3,
        start=date(2026, 10, 16),
        end=date(2026, 10, 16),
        name="Full day event",
    )

    # One accepted change first, so the audit fields hold real values to preserve.
    assert (
        set_return_date(
            client, reservation_id, json={"planned_return_date": "2026-10-14"}
        ).status_code
        == 200
    )
    before = stored(app, reservation_id)
    assert before[3] == IDENTITIES["technical"]

    # Extending into 15 Oct (the clashing event's collection day) would overcommit.
    refused = set_return_date(client, reservation_id, json={"planned_return_date": "2026-10-16"})
    assert refused.status_code == 409

    # The date, the quantity, the line's status and the change history are all exactly as before.
    assert stored(app, reservation_id) == before


# Added during implementation, after mutation testing showed the cases above did not pin these


# TC-SPL-100-10
# SPL-100 AC-1 Test-10
def test_tc_spl_100_10_the_floor_is_the_required_end_date_not_the_current_planned_date(app, client):
    """AC1 allows changing it "to the required end date or any later date".

    So after an extension, pulling the date back to the required end must still be accepted. The
    cases above never had the two dates differ, so they could not tell the two floors apart.
    """

    type_id = add_equipment_type(app, total_stock=4)
    reservation_id, _ = add_reservation(app, type_id, quantity=2)

    # Extend well past the required end date.
    assert (
        set_return_date(
            client, reservation_id, json={"planned_return_date": "2026-10-18"}
        ).status_code
        == 200
    )
    assert stored(app, reservation_id)[0] == date(2026, 10, 18)

    # Now pull it back to the required end date. Giving days back can never overcommit, and the
    # floor is the requirement's required end date, so this is allowed.
    back = set_return_date(client, reservation_id, json={"planned_return_date": "2026-10-14"})
    assert back.status_code == 200
    assert stored(app, reservation_id)[0] == REQUIRED_END

    # One day below the required end date is still refused, so the floor has not simply vanished.
    assert (
        set_return_date(
            client, reservation_id, json={"planned_return_date": "2026-10-13"}
        ).status_code
        == 400
    )
    assert stored(app, reservation_id)[0] == REQUIRED_END


# TC-SPL-100-11
# SPL-100 AC-3 Test-11
def test_tc_spl_100_11_every_added_day_is_checked_and_one_unit_over_is_over(app, client):
    """Two boundaries the cases above missed, both found by mutation testing.

    First: the blocking day may be in the *middle* of an extension, not at its end.
    Second: overcommitting by exactly one unit must still be refused.
    """

    type_id = add_equipment_type(app, total_stock=5)
    reservation_id, _ = add_reservation(app, type_id, quantity=2)

    # A competing reservation that occupies 16 Oct only, so it sits inside an extension to 17 Oct
    # rather than at its edge. 4 promised + this reservation's 2 = 6 against stock 5: one over.
    add_bare_reservation(
        app,
        type_id,
        quantity=4,
        commitment_start=date(2026, 10, 16),
        commitment_end=date(2026, 10, 16),
    )

    before = stored(app, reservation_id)
    refused = set_return_date(client, reservation_id, json={"planned_return_date": "2026-10-17"})
    assert refused.status_code == 409
    # The message names the intermediate day, not the last one.
    assert "2026-10-16" in refused.json["error"]
    assert stored(app, reservation_id) == before

    # Stopping short of that day is feasible, so the refusal is about 16 Oct specifically.
    allowed = set_return_date(client, reservation_id, json={"planned_return_date": "2026-10-15"})
    assert allowed.status_code == 200
    assert stored(app, reservation_id)[0] == date(2026, 10, 15)
