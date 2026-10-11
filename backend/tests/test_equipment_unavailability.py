"""Acceptance coverage for SPL-96 (CS-E15-S3): Technical Support marks units unavailable.

Each test carries the QA-SPL-96 case identifier it proves. The cases were published on the
QA-SPL-96 page before this story's code existed.

All six acceptance criteria
---------------------------
AC3, AC4 and AC5 turn on the Review Required flag raised against reservations. SPL-97 merged on
10 October and supplied those reservations, so every criterion is now proved here:

- TC-SPL-96-01 (AC1, AC2, AC3, AC5) — a marking flags every contributing line with the reason,
  holds all units, and a restore clears no flag.
- TC-SPL-96-02 (AC1, AC6) — every refusal, and Technical Support only.
- TC-SPL-96-04 (AC2) — availability *and reservation* both use the reduced usable stock.
- TC-SPL-96-05 (AC3) — only lines on the days of the shortfall are flagged.
- TC-SPL-96-06 (AC1) — partial and full restores record the reason, who and when.
- TC-SPL-96-10 (AC1) — added during implementation: total stock can no longer be lowered below
  the units already marked unavailable. SPL-94's edit route is the other way to break AC1.
- TC-SPL-96-12 (AC3, AC5) — added during implementation: SPL-97's revalidation clears the flag
  *and* its reason together, so a stale reason cannot outlive the state it explains.

TC-SPL-96-03 (AC4) is proved in test_equipment_review_queue.py and test_equipment_requirements.py,
because AC4 is about what the queue and the coordinator's own line show. TC-SPL-96-09 (browser)
is the only case still unrun; QA-SPL-96 records why.

Worth knowing: until this change set, **nothing in the codebase ever set ``review_required``**,
so SPL-97's revalidate-reservation route could never be reached. AC3 is what makes it reachable.

How to read these tests
-----------------------
- Every test builds its own fresh SQLite database with one planning event and one catalogue type.
- Sign-in is simulated: a token such as "technical" maps to a known account id (``IDENTITIES``).
- The clock is frozen through the single clock function in app/equipment_unavailability.py.
- Every refusal test checks that neither total stock nor the unavailable total moved, and also
  proves a genuine recording succeeds in the same test, so a missing route could not make it pass.
"""

from datetime import date, datetime, timedelta

import pytest
from app import create_app
from app import equipment_unavailability as unavailability_module
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EquipmentUnavailabilityRecord,
    EventCoordinatorAssignment,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

IDENTITIES = {
    "technical": "00000000-0000-0000-0000-000000000961",
    "second-technical": "00000000-0000-0000-0000-000000000962",
    "coordinator": "00000000-0000-0000-0000-000000000963",
    "organiser": "00000000-0000-0000-0000-000000000964",
}

# Frozen so "when" is assertable. Singapore time, like every other story.
NOW = datetime(2026, 10, 10, 9, 30, tzinfo=SINGAPORE)

REQUIRED_START = date(2026, 10, 15)
REQUIRED_END = date(2026, 10, 16)
# SPL-95 collects the day before the requirement starts, so this is the commitment's first day.
COLLECTION_DAY = date(2026, 10, 14)


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/equipment-unavailability.db",
            "IDENTITY_VERIFIER": IDENTITIES.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organisation(id=1, name="Northstar Community Partners"))
        session.add_all(
            Account(id=account_id, display_name=name, is_active=True)
            for name, account_id in IDENTITIES.items()
        )
        session.add_all(
            [
                AccountRole(
                    account_id=IDENTITIES["technical"],
                    role=Role.TECHNICAL_SUPPORT_STAFF.value,
                ),
                AccountRole(
                    account_id=IDENTITIES["second-technical"],
                    role=Role.TECHNICAL_SUPPORT_STAFF.value,
                ),
                AccountRole(
                    account_id=IDENTITIES["coordinator"], role=Role.EVENT_COORDINATOR.value
                ),
                AccountRole(account_id=IDENTITIES["organiser"], role=Role.EVENT_ORGANISER.value),
            ]
        )
        session.commit()
    set_clock(monkeypatch, NOW)
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def equipment_type_id(app):
    """One catalogue type with stock 6, the figure TC-SPL-96-02 uses."""

    return add_equipment_type(app, total_stock=6)


def add_equipment_type(app, *, total_stock, name="Wireless Microphone"):
    with Session(app.extensions["engine"]) as session:
        item = EquipmentType(
            name=name,
            normalised_name=name.casefold(),
            description="Handheld wireless microphone with receiver.",
            location="Technical Store A",
            total_stock=total_stock,
        )
        session.add(item)
        session.commit()
        return item.id


def add_requirement(
    app,
    *,
    equipment_type_id,
    quantity,
    start=REQUIRED_START,
    end=REQUIRED_END,
    name="Community Leadership Forum",
):
    """A planning requirement, so SPL-95's availability route returns a line for it."""

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=IDENTITIES["organiser"],
            organisation_id=1,
            name=name,
            proposed_date=start,
            expected_attendance=80,
            status="planning",
        )
        session.add(event)
        session.flush()
        # AC4 shows the flag to the event's *assigned* coordinator, so every fixture event has one.
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=IDENTITIES["coordinator"],
                assigned_by_account_id=IDENTITIES["organiser"],
                assigned_at=NOW,
            )
        )
        requirement = EquipmentRequirement(
            event_request_id=event.id,
            equipment_type="Wireless microphones",
            quantity=quantity,
            equipment_type_id=equipment_type_id,
            required_start_date=start,
            required_end_date=end,
            status="requested",
        )
        session.add(requirement)
        session.commit()
        return requirement.id


def reserve_units(app, requirement_id, *, quantity, start, end):
    """A reservation held by SPL-97, written directly so this story's cases stay self-contained.

    AC3 is about what happens to reservations that already exist, so each case builds the
    commitment it needs rather than driving SPL-97's route to create it.
    """

    with Session(app.extensions["engine"]) as session:
        line = session.get(EquipmentRequirement, requirement_id)
        reservation = EquipmentReservation(
            event_request_id=line.event_request_id,
            equipment_requirement_id=line.id,
            equipment_type_id=line.equipment_type_id,
            commitment_start_date=start,
            commitment_end_date=end,
            quantity=quantity,
            reserved_by_account_id=IDENTITIES["technical"],
            reserved_at=NOW,
        )
        session.add(reservation)
        line.status = "reserved" if quantity >= line.quantity else "partially_reserved"
        session.commit()
        return reservation.id


def event_of(app, requirement_id):
    """The event a requirement line belongs to, for the coordinator-facing route."""

    with Session(app.extensions["engine"]) as session:
        return session.get(EquipmentRequirement, requirement_id).event_request_id


def review_state(app, requirement_id):
    """(status, review_reason, review_flagged_at) — the AC3/AC4 flag and its explanation."""

    with Session(app.extensions["engine"]) as session:
        line = session.get(EquipmentRequirement, requirement_id)
        return line.status, line.review_reason, line.review_flagged_at


def reservation_quantities(app, equipment_type_id):
    """AC3 keeps quantities and history: this is what must not change."""

    with Session(app.extensions["engine"]) as session:
        return sorted(
            session.scalars(
                select(EquipmentReservation.quantity).where(
                    EquipmentReservation.equipment_type_id == equipment_type_id
                )
            )
        )


def set_clock(monkeypatch, moment):
    monkeypatch.setattr(unavailability_module, "_now", lambda: moment)


def headers(identity="technical"):
    return {} if identity is None else {"Authorization": f"Bearer {identity}"}


def mark(client, equipment_type_id, identity="technical", **kwargs):
    return client.post(
        f"/api/equipment-types/{equipment_type_id}/unavailable-units",
        headers=headers(identity),
        **kwargs,
    )


def restore(client, equipment_type_id, identity="technical", **kwargs):
    return client.post(
        f"/api/equipment-types/{equipment_type_id}/restored-units",
        headers=headers(identity),
        **kwargs,
    )


def reserve(client, requirement_id, identity="technical", **kwargs):
    """SPL-97's reservation route, used here only to prove AC2 applies to reservations."""

    return client.post(
        f"/api/equipment-requirements/{requirement_id}/reservations",
        headers=headers(identity),
        **kwargs,
    )


def history(client, equipment_type_id, identity="technical"):
    return client.get(
        f"/api/equipment-types/{equipment_type_id}/unavailability",
        headers=headers(identity),
    )


def stock_and_unavailable(app, equipment_type_id):
    """(total_stock, unavailable_units) as saved in the database."""

    with Session(app.extensions["engine"]) as session:
        item = session.get(EquipmentType, equipment_type_id)
        return item.total_stock, item.unavailable_units


def records(app, equipment_type_id):
    with Session(app.extensions["engine"]) as session:
        return list(
            session.scalars(
                select(EquipmentUnavailabilityRecord)
                .where(EquipmentUnavailabilityRecord.equipment_type_id == equipment_type_id)
                .order_by(EquipmentUnavailabilityRecord.id)
            )
        )


# AC1, AC6 — only Technical Support, and only sensible amounts


# TC-SPL-96-02
# SPL-96 AC-1 / AC-6 Test-02
def test_tc_spl_96_02_only_technical_support_and_only_valid_amounts(app, client, equipment_type_id):
    body = {"quantity": 1, "reason": "Dropped and the capsule is cracked."}

    # Other roles never reach the records; no session is 401, not 403.
    for identity in ("coordinator", "organiser"):
        assert mark(client, equipment_type_id, identity, json=body).status_code == 403, identity
        assert restore(client, equipment_type_id, identity, json=body).status_code == 403, identity
    assert mark(client, equipment_type_id, None, json=body).status_code == 401
    assert restore(client, equipment_type_id, None, json=body).status_code == 401

    # More than the stock, nothing, a fraction, a negative, and a blank reason are each refused.
    refusals = [
        {"quantity": 7, "reason": "Water damage in the store."},
        {"quantity": 0, "reason": "Water damage in the store."},
        {"quantity": 1.5, "reason": "Water damage in the store."},
        {"quantity": -2, "reason": "Water damage in the store."},
        {"quantity": True, "reason": "Water damage in the store."},
        {"quantity": "2", "reason": "Water damage in the store."},
        {"quantity": 2, "reason": "   "},
        {"quantity": 2},
        {"reason": "Water damage in the store."},
        {"quantity": 2, "reason": "Water damage.", "unavailable_units": 99},
    ]
    for refused in refusals:
        response = mark(client, equipment_type_id, json=refused)
        assert response.status_code == 400, refused
        assert "error" in response.json, refused

    # Nothing can be restored before anything is unavailable.
    nothing_to_restore = restore(
        client, equipment_type_id, json={"quantity": 1, "reason": "Repaired."}
    )
    assert nothing_to_restore.status_code == 400

    # Not one refusal moved the stored figures, and no record was written.
    assert stock_and_unavailable(app, equipment_type_id) == (6, 0)
    assert records(app, equipment_type_id) == []

    # Technical Support succeeds in the same test, so none of the above can pass vacuously.
    accepted = mark(client, equipment_type_id, json=body)
    assert accepted.status_code == 201
    assert accepted.json["equipment_type"]["unavailable_units"] == 1
    assert accepted.json["equipment_type"]["usable_stock"] == 5
    assert stock_and_unavailable(app, equipment_type_id) == (6, 1)

    # An unknown equipment type is 404, and is not created by trying.
    assert mark(client, 999_999, json=body).status_code == 404


# AC1 — restoring, partially and fully


# TC-SPL-96-06
# SPL-96 AC-1 Test-06
def test_tc_spl_96_06_partial_and_full_restores_record_who_and_when(
    app, client, equipment_type_id, monkeypatch
):
    marked = mark(
        client, equipment_type_id, json={"quantity": 3, "reason": "Three capsules cracked."}
    )
    assert marked.status_code == 201
    assert stock_and_unavailable(app, equipment_type_id) == (6, 3)

    # A partial restore by a different member of Technical Support, a minute later.
    later = datetime(2026, 10, 10, 9, 31, tzinfo=SINGAPORE)
    set_clock(monkeypatch, later)
    partial = restore(
        client,
        equipment_type_id,
        "second-technical",
        json={"quantity": 2, "reason": "Two capsules replaced."},
    )
    assert partial.status_code == 201
    assert partial.json["equipment_type"]["unavailable_units"] == 1
    assert partial.json["equipment_type"]["usable_stock"] == 5

    # The full restore takes it to zero, and it can never go below.
    full = restore(client, equipment_type_id, json={"quantity": 1, "reason": "Last one repaired."})
    assert full.status_code == 201
    assert stock_and_unavailable(app, equipment_type_id) == (6, 0)

    refused = restore(client, equipment_type_id, json={"quantity": 1, "reason": "Nothing left."})
    assert refused.status_code == 400
    assert stock_and_unavailable(app, equipment_type_id) == (6, 0)

    # The total went 3, 1, 0 and every step kept its reason, its author and its time.
    written = records(app, equipment_type_id)
    assert [(item.action, item.quantity) for item in written] == [
        ("marked_unavailable", 3),
        ("restored", 2),
        ("restored", 1),
    ]
    assert [item.reason for item in written] == [
        "Three capsules cracked.",
        "Two capsules replaced.",
        "Last one repaired.",
    ]
    assert [item.recorded_by_account_id for item in written] == [
        IDENTITIES["technical"],
        IDENTITIES["second-technical"],
        IDENTITIES["technical"],
    ]
    assert written[1].recorded_at == later.replace(tzinfo=None)

    # The history route shows the same three entries, newest first, to Technical Support only.
    listed = history(client, equipment_type_id)
    assert listed.status_code == 200
    assert [entry["quantity"] for entry in listed.json["history"]] == [1, 2, 3]
    assert listed.json["equipment_type"]["unavailable_units"] == 0
    assert history(client, equipment_type_id, "coordinator").status_code == 403
    assert history(client, equipment_type_id, None).status_code == 401


# AC2 — availability uses the reduced usable stock


# TC-SPL-96-04
# SPL-96 AC-2 Test-04
def test_tc_spl_96_04_availability_uses_the_reduced_usable_stock(app, client):
    """TC-SPL-96-04 in full, including the reservation half once SPL-97 merged."""

    type_id = add_equipment_type(app, total_stock=5)
    requirement_id = add_requirement(app, equipment_type_id=type_id, quantity=4)

    # Before anything is unavailable, all five units can be promised.
    before = client.get("/api/equipment-availability", headers=headers())
    assert before.status_code == 200
    assessment = before.json["assessments"][0]
    assert (assessment["total_stock"], assessment["unavailable_units"]) == (5, 0)
    assert assessment["available_to_reserve"] == 5
    assert assessment["shortfall"] == 0

    marked = mark(client, type_id, json={"quantity": 2, "reason": "Two in for repair."})
    assert marked.status_code == 201

    # Afterwards the same line reports three usable, on every day of the commitment.
    after = client.get("/api/equipment-availability", headers=headers())
    assessment = after.json["assessments"][0]
    assert (assessment["total_stock"], assessment["unavailable_units"]) == (5, 2)
    assert assessment["available_to_reserve"] == 3
    # Four were required, three can be promised, so the line is one short.
    assert assessment["shortfall"] == 1
    # Unavailability has no end date, so every day of the window is equally affected and the
    # busiest day is the first of them.
    assert assessment["busiest_day"] == COLLECTION_DAY.isoformat()

    # SPL-95's placeholder notice must no longer claim unavailable units are missing.
    assert "No unavailable-unit records" not in after.json["input_notice"]

    # AC2's second half: a *reservation* must respect the reduced stock too, not just the read.
    # SPL-97 owns this route, and supplying the unavailable units inside _assessment_for is what
    # makes it honour them. Four cannot be promised out of three usable units.
    refused = reserve(client, requirement_id, json={"quantity": 4})
    assert refused.status_code == 409
    assert "not available" in refused.json["error"]

    # Three is exactly what is left, so it succeeds and consumes the usable stock.
    accepted = reserve(client, requirement_id, json={"quantity": 3})
    assert accepted.status_code == 201
    assert accepted.json["assessment"]["available_to_reserve"] == 0
    assert accepted.json["assessment"]["unavailable_units"] == 2

    # And a further unit cannot be reserved now that nothing usable is left.
    assert reserve(client, requirement_id, json={"quantity": 1}).status_code == 409


# TC-SPL-96-10
# SPL-96 AC-1 Test-10 (added during implementation; see this file's docstring)
def test_tc_spl_96_10_stock_cannot_be_lowered_below_the_unavailable_total(
    app, client, equipment_type_id
):
    marked = mark(client, equipment_type_id, json={"quantity": 4, "reason": "Flood damage."})
    assert marked.status_code == 201

    # SPL-94's edit route is the other way to break "never exceeds total stock".
    refused = client.patch(
        f"/api/equipment-types/{equipment_type_id}",
        headers=headers(),
        json={"total_stock": 3},
    )
    assert refused.status_code == 400
    assert "error" in refused.json
    assert stock_and_unavailable(app, equipment_type_id) == (6, 4)

    # Lowering it to exactly the unavailable total is allowed; nothing is usable afterwards.
    allowed = client.patch(
        f"/api/equipment-types/{equipment_type_id}",
        headers=headers(),
        json={"total_stock": 4},
    )
    assert allowed.status_code == 200
    assert stock_and_unavailable(app, equipment_type_id) == (4, 4)
    assert history(client, equipment_type_id).json["equipment_type"]["usable_stock"] == 0


# AC3, AC5 — reservations that no longer fit are flagged, and a restore clears nothing


# TC-SPL-96-01
# SPL-96 AC-1 / AC-2 / AC-3 / AC-5 Test-01
def test_tc_spl_96_01_a_shortfall_flags_every_contributing_line_and_a_restore_clears_nothing(
    app, client, monkeypatch
):
    """The published scenario: stock 6, two overlapping reservations of 3, mark 1 unavailable."""

    type_id = add_equipment_type(app, total_stock=6)
    first = add_requirement(app, equipment_type_id=type_id, quantity=3, name="First event")
    second = add_requirement(app, equipment_type_id=type_id, quantity=3, name="Second event")
    reserve_units(app, first, quantity=3, start=REQUIRED_START, end=REQUIRED_END)
    reserve_units(app, second, quantity=3, start=REQUIRED_START, end=REQUIRED_END)

    # All six units are promised, so before the marking neither line is flagged.
    assert review_state(app, first)[0] == "reserved"
    assert review_state(app, second)[0] == "reserved"

    reason = "One capsule cracked in the store."
    marked = mark(client, type_id, json={"quantity": 1, "reason": reason})
    assert marked.status_code == 201
    # AC3: both reservations span the short day, so both lines are flagged.
    assert marked.json["flagged_requirement_ids"] == sorted([first, second])

    for line_id in (first, second):
        status, stored_reason, flagged_at = review_state(app, line_id)
        assert status == "review_required", line_id
        assert stored_reason == reason, line_id
        assert flagged_at == NOW.replace(tzinfo=None), line_id

    # AC3: quantities and history are kept — nothing was released to make the numbers fit.
    assert reservation_quantities(app, type_id) == [3, 3]

    # AC2: with 5 usable against 6 promised, no further unit can be reserved on those days.
    assert reserve(client, first, json={"quantity": 1}).status_code == 409

    # AC5: restoring the unit clears no flag. Technical Support revalidates each line instead.
    later = NOW + timedelta(minutes=5)
    set_clock(monkeypatch, later)
    restored = restore(client, type_id, json={"quantity": 1, "reason": "Capsule replaced."})
    assert restored.status_code == 201
    assert restored.json["equipment_type"]["usable_stock"] == 6
    for line_id in (first, second):
        status, stored_reason, flagged_at = review_state(app, line_id)
        assert status == "review_required", line_id
        # The reason and its time are the originals, untouched by the restore.
        assert stored_reason == reason, line_id
        assert flagged_at == NOW.replace(tzinfo=None), line_id

    # AC5, the harder half: a restore that leaves the line *still* short must not re-flag it and
    # rewrite the original reason with the restore's wording. Take four more units out, then put
    # one back: two usable against six promised, so the shortfall persists either way.
    assert (
        mark(
            client, type_id, json={"quantity": 4, "reason": "Four more in for service."}
        ).status_code
        == 201
    )
    set_clock(monkeypatch, NOW + timedelta(minutes=10))
    partial = restore(client, type_id, json={"quantity": 1, "reason": "One came back early."})
    assert partial.status_code == 201
    assert partial.json["equipment_type"]["usable_stock"] == 3
    for line_id in (first, second):
        _, stored_reason, _ = review_state(app, line_id)
        # The most recent *marking* owns the reason; a restore never writes one.
        assert stored_reason == "Four more in for service.", line_id


# TC-SPL-96-05
# SPL-96 AC-3 Test-05
def test_tc_spl_96_05_only_lines_on_the_short_days_are_flagged(app, client):
    """Stock 6; 3 + 3 on one window and 2 on a later one; marking 1 flags only the first two."""

    type_id = add_equipment_type(app, total_stock=6)
    early_start, early_end = date(2026, 10, 14), date(2026, 10, 14)
    late_start, late_end = date(2026, 10, 20), date(2026, 10, 20)

    first = add_requirement(
        app,
        equipment_type_id=type_id,
        quantity=3,
        start=early_start,
        end=early_end,
        name="Early one",
    )
    second = add_requirement(
        app,
        equipment_type_id=type_id,
        quantity=3,
        start=early_start,
        end=early_end,
        name="Early two",
    )
    later = add_requirement(
        app,
        equipment_type_id=type_id,
        quantity=2,
        start=late_start,
        end=late_end,
        name="Later event",
    )
    reserve_units(app, first, quantity=3, start=early_start, end=early_end)
    reserve_units(app, second, quantity=3, start=early_start, end=early_end)
    reserve_units(app, later, quantity=2, start=late_start, end=late_end)

    marked = mark(client, type_id, json={"quantity": 1, "reason": "One unit withdrawn."})
    assert marked.status_code == 201

    # 6 promised against 5 usable on 14 Oct, but only 2 promised on 20 Oct, so that day is fine.
    assert marked.json["flagged_requirement_ids"] == sorted([first, second])
    assert review_state(app, first)[0] == "review_required"
    assert review_state(app, second)[0] == "review_required"
    # The later line keeps the status its own reservation gave it, with no reason attached.
    assert review_state(app, later) == ("reserved", None, None)


# TC-SPL-96-12
# SPL-96 AC-3 / AC-5 Test-12 (added during implementation; see this file's docstring)
def test_tc_spl_96_12_revalidation_clears_the_flag_and_its_reason_together(app, client):
    """A reason must never outlive the Review Required state it explains."""

    type_id = add_equipment_type(app, total_stock=6)
    line_id = add_requirement(app, equipment_type_id=type_id, quantity=3)
    reserve_units(app, line_id, quantity=3, start=REQUIRED_START, end=REQUIRED_END)

    # Take four units out, so 2 usable against 3 promised: the line is flagged.
    assert (
        mark(client, type_id, json={"quantity": 4, "reason": "Flood in the store."}).status_code
        == 201
    )
    assert review_state(app, line_id)[0] == "review_required"

    # While it is still short, SPL-97 refuses to revalidate it.
    refused = client.post(
        f"/api/equipment-requirements/{line_id}/revalidate-reservation", headers=headers()
    )
    assert refused.status_code == 409
    assert review_state(app, line_id)[0] == "review_required"

    # Put the units back, then revalidate: the flag and its reason go together (AC5's "Technical
    # Support revalidates each flagged reservation").
    assert (
        restore(client, type_id, json={"quantity": 4, "reason": "Store dried out."}).status_code
        == 201
    )
    accepted = client.post(
        f"/api/equipment-requirements/{line_id}/revalidate-reservation", headers=headers()
    )
    assert accepted.status_code == 200
    assert review_state(app, line_id) == ("reserved", None, None)


# AC4 — the flag and its reason are visible where the story says they are


# TC-SPL-96-03
# SPL-96 AC-4 Test-03
def test_tc_spl_96_03_the_flag_and_reason_reach_the_queue_and_the_coordinator(app, client):
    """AC4: Technical Support sees it in the SPL-92 review queue; the coordinator on their line."""

    type_id = add_equipment_type(app, total_stock=6)
    line_id = add_requirement(app, equipment_type_id=type_id, quantity=3)
    reserve_units(app, line_id, quantity=3, start=REQUIRED_START, end=REQUIRED_END)

    # Before the marking the line is Reserved, so it is not in the review queue at all.
    before = client.get("/api/equipment-review-queue", headers=headers())
    assert before.status_code == 200
    assert [item["id"] for item in before.json["requirements"]] == []

    reason = "Two units water damaged."
    assert mark(client, type_id, json={"quantity": 5, "reason": reason}).status_code == 201

    # AC4, first half: the flagged line now appears in Technical Support's queue, with the reason.
    listed = client.get("/api/equipment-review-queue", headers=headers())
    entries = listed.json["requirements"]
    assert [item["id"] for item in entries] == [line_id]
    assert entries[0]["status"] == "review_required"
    assert entries[0]["review_reason"] == reason
    assert entries[0]["review_flagged_at"].startswith("2026-10-10T09:30")

    # AC4, second half: the event's assigned coordinator sees it on their own line.
    event_id = event_of(app, line_id)
    coordinator_view = client.get(
        f"/api/event-requests/{event_id}/equipment-requirements",
        headers=headers("coordinator"),
    )
    assert coordinator_view.status_code == 200
    line = next(item for item in coordinator_view.json["requirements"] if item["id"] == line_id)
    assert line["status"] == "review_required"
    assert line["review_reason"] == reason
    assert line["review_flagged_at"].startswith("2026-10-10T09:30")

    # A line that was never flagged carries no reason, so the field cannot be mistaken for one.
    other_type = add_equipment_type(app, total_stock=4, name="Projector")
    unflagged = add_requirement(app, equipment_type_id=other_type, quantity=1, name="Calm event")
    other_event = event_of(app, unflagged)
    calm = client.get(
        f"/api/event-requests/{other_event}/equipment-requirements",
        headers=headers("coordinator"),
    )
    calm_line = next(item for item in calm.json["requirements"] if item["id"] == unflagged)
    assert calm_line["review_reason"] is None
    assert calm_line["review_flagged_at"] is None
