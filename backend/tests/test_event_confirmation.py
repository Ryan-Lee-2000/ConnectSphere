"""Acceptance coverage for SPL-85 (CS-E07-S3): the assigned coordinator confirms an event.

Each test is named after the QA-SPL-85 case it executes. The cases were published on Confluence
before this story's code existed; expected values come from the Jira acceptance criteria and the
customer answers (Q80, Q98, Q106, Q132), not from the implementation.
"""

from datetime import date, datetime, time

import pytest
from app import create_app
from app.coordinator_assignment import MAX_EVENT_REQUEST_ID
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentReservationRelease,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueBookingReviewFinding,
    VenueLayout,
    VenueOperationalBlock,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000008501"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000008502"
LEAD = "00000000-0000-0000-0000-000000008503"
ORGANISER = "00000000-0000-0000-0000-000000008504"
TECHNICAL = "00000000-0000-0000-0000-000000008505"
VENUE_STAFF = "00000000-0000-0000-0000-000000008506"
IDENTITIES = {
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "lead": LEAD,
    "organiser": ORGANISER,
    "technical": TECHNICAL,
    "venue-staff": VENUE_STAFF,
}
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=SINGAPORE)
EVENT_DATE = date(2026, 11, 20)
NOT_PLANNING = "Only an event in Planning can be confirmed."
BLOCKED = "This event cannot be confirmed yet."


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/event-confirmation.db",
            "IDENTITY_VERIFIER": IDENTITIES.__getitem__,
        }
    )
    engine = application.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organisation(id=99, name="Northstar Community Partners"))
        for account_id, name, role in (
            (COORDINATOR, "Casey Coordinator", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Jordan Coordinator", Role.EVENT_COORDINATOR),
            (LEAD, "Lee Lead", Role.EVENT_OPERATIONS_MANAGER),
            (ORGANISER, "Olivia Organiser", Role.EVENT_ORGANISER),
            (TECHNICAL, "Taylor Technical", Role.TECHNICAL_SUPPORT_STAFF),
            (VENUE_STAFF, "Valerie Venue", Role.VENUE_STAFF),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    is_active=True,
                    organisation_id=99 if account_id == ORGANISER else None,
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.add(
            EquipmentType(
                id=1,
                name="Wireless Microphone",
                normalised_name="wireless microphone",
                total_stock=12,
            )
        )
        for venue_id, name in ((1, "Harbour Hall"), (2, "Studio One"), (3, "Garden Room")):
            venue = Venue(
                id=venue_id,
                name=name,
                operating_slots=["AM", "PM", "NIGHT"],
                setup_buffer_slots=0,
                turnaround_buffer_slots=0,
            )
            venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
            session.add(venue)
        session.commit()
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(identity="coordinator"):
    return {} if identity is None else {"Authorization": f"Bearer {identity}"}


def confirm(client, event_id, identity="coordinator", **kwargs):
    return client.post(
        f"/api/event-requests/{event_id}/confirm", headers=headers(identity), **kwargs
    )


def add_event(app, *, status="planning", registration_required=False):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=99,
            name="Community Leadership Forum",
            purpose="Annual leadership programme",
            proposed_date=EVENT_DATE,
            start_time=time(14),
            end_time=time(17),
            expected_attendance=80,
            preferred_room_layout="theatre",
            status=status,
            submitted_at=NOW,
            registration_required=registration_required,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=LEAD,
                assigned_at=NOW,
            )
        )
        session.commit()
        return event.id


def add_booking(app, event_id, *, status="approved", venue_id=1, requires_review=False, **extra):
    with Session(app.extensions["engine"]) as session:
        block_id = None
        if requires_review:
            block = VenueOperationalBlock(
                venue_id=venue_id,
                start_date=EVENT_DATE,
                end_date=EVENT_DATE,
                slots=["PM"],
                reason="Ceiling repair",
                created_by_account_id=VENUE_STAFF,
                created_at=NOW,
            )
            session.add(block)
            session.flush()
            block_id = block.id
        booking = VenueBooking(
            event_request_id=event_id,
            venue_id=venue_id,
            status=status,
            layout="theatre",
            expected_attendance=80,
            booking_date=EVENT_DATE,
            event_slots=["PM"],
            requested_by_account_id=COORDINATOR,
            requested_at=NOW,
            approved_by_account_id=VENUE_STAFF if status == "approved" else None,
            approved_at=NOW if status == "approved" else None,
            requires_review=requires_review,
            review_trigger_block_id=block_id,
            review_marked_at=NOW if requires_review else None,
            review_marked_by_account_id=VENUE_STAFF if requires_review else None,
            **extra,
        )
        session.add(booking)
        session.commit()
        return booking.id


def add_line(
    app,
    event_id,
    *,
    quantity=4,
    status="reserved",
    essentiality="essential",
    mapped=True,
    review_reason=None,
):
    with Session(app.extensions["engine"]) as session:
        line = EquipmentRequirement(
            event_request_id=event_id,
            equipment_type="Wireless microphones",
            equipment_type_id=1 if mapped else None,
            quantity=quantity,
            required_start_date=EVENT_DATE,
            required_end_date=EVENT_DATE,
            status=status,
            essentiality=essentiality,
            review_reason=review_reason,
            review_flagged_at=NOW if review_reason else None,
        )
        session.add(line)
        session.commit()
        return line.id


def reserve(app, event_id, line_id, quantity, *, released=0):
    with Session(app.extensions["engine"]) as session:
        reservation = EquipmentReservation(
            event_request_id=event_id,
            equipment_requirement_id=line_id,
            equipment_type_id=1,
            commitment_start_date=date(2026, 11, 19),
            commitment_end_date=date(2026, 11, 21),
            quantity=quantity,
            reserved_by_account_id=TECHNICAL,
            reserved_at=NOW,
        )
        session.add(reservation)
        session.flush()
        if released:
            session.add(
                EquipmentReservationRelease(
                    reservation_id=reservation.id,
                    quantity=released,
                    reason="Units returned early.",
                    released_by_account_id=TECHNICAL,
                    released_at=NOW,
                )
            )
        session.commit()


def ready_event(app, **event_options):
    """A Planning event whose venue and essential equipment are both complete."""

    event_id = add_event(app, **event_options)
    add_booking(app, event_id)
    line_id = add_line(app, event_id)
    reserve(app, event_id, line_id, 4)
    return event_id


def snapshot(app, event_id):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        history = session.scalars(
            select(EventStatusHistory.action)
            .where(EventStatusHistory.event_request_id == event_id)
            .order_by(EventStatusHistory.id)
        ).all()
        return {
            "status": event.status,
            "status_changed_at": event.status_changed_at,
            "confirmed_by": event.confirmed_by_account_id,
            "confirmed_at": event.confirmed_at,
            "history": list(history),
        }


def blocker_codes(response):
    return [blocker["code"] for blocker in response.json["blockers"]]


# --- Acceptance Criterion 1 -------------------------------------------------------------------


# TC-SPL-85-01 — AC1 happy path: the assigned coordinator confirms a ready Planning event.
def test_tc_spl_85_01_assigned_coordinator_confirms_a_ready_planning_event(app, client):
    event_id = ready_event(app)

    response = confirm(client, event_id)

    assert response.status_code == 200, response.json
    assert response.json["event"]["status"] == "confirmed"
    assert response.json["event"]["status_label"] == "Confirmed"
    assert snapshot(app, event_id)["status"] == "confirmed"


# TC-SPL-85-02 — AC1 cross-cutting: nobody but the assigned coordinator can confirm.
@pytest.mark.parametrize(
    ("identity", "expected_status"),
    [
        ("other-coordinator", 404),
        ("lead", 403),
        ("organiser", 403),
        ("technical", 403),
        ("venue-staff", 403),
        (None, 401),
    ],
)
def test_tc_spl_85_02_only_the_assigned_coordinator_can_confirm(
    app, client, identity, expected_status
):
    event_id = ready_event(app)
    before = snapshot(app, event_id)

    response = confirm(client, event_id, identity)

    assert response.status_code == expected_status
    if identity == "other-coordinator":
        assert response.json["error"] == "Assigned event not found."
    assert snapshot(app, event_id) == before


# TC-SPL-85-03 — AC1 negative partition: every status other than Planning is refused.
@pytest.mark.parametrize(
    "status",
    [
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
    ],
)
def test_tc_spl_85_03_only_a_planning_event_can_be_confirmed(app, client, status):
    event_id = ready_event(app, status=status)
    before = snapshot(app, event_id)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert response.json["error"] == NOT_PLANNING
    assert snapshot(app, event_id) == before


# TC-SPL-85-04 (a) — AC1 input: the client cannot choose the status or the confirmer.
@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {"status": "confirmed"}},
        {"json": {"confirmed_by_account_id": OTHER_COORDINATOR}},
        {"json": ["confirm"]},
        {"data": "confirm", "content_type": "text/plain"},
    ],
)
def test_tc_spl_85_04_confirmation_accepts_no_parameters(app, client, kwargs):
    event_id = ready_event(app)
    before = snapshot(app, event_id)

    response = confirm(client, event_id, **kwargs)

    assert response.status_code == 400
    assert response.json["error"] == (
        "Confirmation does not accept a target status or other parameters."
    )
    assert snapshot(app, event_id) == before


# TC-SPL-85-04 (b) — AC1 identifiers: unknown and out-of-range ids are a plain 404.
def test_tc_spl_85_04_unknown_events_are_not_found(client):
    unknown = confirm(client, 999999)
    out_of_range = confirm(client, MAX_EVENT_REQUEST_ID + 1)

    assert unknown.status_code == out_of_range.status_code == 404
    assert unknown.json == out_of_range.json == {"error": "Assigned event not found."}


# An empty JSON object is still "no parameters" (the same rule as approval).
def test_tc_spl_85_04_an_empty_json_object_is_accepted(app, client):
    event_id = ready_event(app)

    assert confirm(client, event_id, json={}).status_code == 200


# --- Acceptance Criterion 2 -------------------------------------------------------------------


# TC-SPL-85-05 — AC2: an event with no venue booking at all cannot be confirmed.
def test_tc_spl_85_05_no_venue_booking_is_refused(app, client):
    event_id = add_event(app)
    line_id = add_line(app, event_id)
    reserve(app, event_id, line_id, 4)
    before = snapshot(app, event_id)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert response.json["error"] == BLOCKED
    assert blocker_codes(response) == ["no_approved_venue_booking"]
    assert snapshot(app, event_id) == before


# TC-SPL-85-06 — AC2 partition: only an Approved booking satisfies the venue arrangement.
@pytest.mark.parametrize(
    ("booking_status", "expected_codes"),
    [
        ("requested", ["no_approved_venue_booking", "venue_booking_pending"]),
        ("rejected", ["no_approved_venue_booking"]),
        ("withdrawn", ["no_approved_venue_booking"]),
        ("cancelled", ["no_approved_venue_booking"]),
    ],
)
def test_tc_spl_85_06_a_non_approved_booking_does_not_count(
    app, client, booking_status, expected_codes
):
    event_id = add_event(app)
    add_booking(app, event_id, status=booking_status)
    before = snapshot(app, event_id)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert blocker_codes(response) == expected_codes
    assert snapshot(app, event_id) == before


# TC-SPL-85-07 (a) — AC2 team interpretation: a still-Requested sibling venue blocks.
def test_tc_spl_85_07_a_pending_sibling_booking_blocks(app, client):
    event_id = ready_event(app)
    pending_id = add_booking(app, event_id, status="requested", venue_id=2)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert response.json["blockers"] == [
        {
            "code": "venue_booking_pending",
            "booking_id": pending_id,
            "message": "Studio One is still waiting for a Venue Staff decision.",
        }
    ]


# TC-SPL-85-07 (b) — AC2 boundary: inactive sibling history never blocks.
def test_tc_spl_85_07_inactive_sibling_bookings_do_not_block(app, client):
    event_id = ready_event(app)
    add_booking(app, event_id, status="rejected", venue_id=2)
    add_booking(app, event_id, status="cancelled", venue_id=3)

    response = confirm(client, event_id)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "confirmed"


# --- Acceptance Criterion 3 -------------------------------------------------------------------


# TC-SPL-85-08 — AC3 boundary: one unit short of the essential quantity is refused.
def test_tc_spl_85_08_one_essential_unit_short_is_refused(app, client):
    event_id = add_event(app)
    add_booking(app, event_id)
    line_id = add_line(app, event_id, status="partially_reserved")
    reserve(app, event_id, line_id, 3)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert response.json["blockers"] == [
        {
            "code": "essential_not_fully_reserved",
            "requirement_id": line_id,
            "message": "Reserve 1 more unit(s) of Wireless Microphone.",
        }
    ]
    assert snapshot(app, event_id)["status"] == "planning"


# TC-SPL-85-08 — AC3 boundary: exactly the essential quantity, across two reservations, passes.
def test_tc_spl_85_08_exactly_the_essential_quantity_is_accepted(app, client):
    event_id = add_event(app)
    add_booking(app, event_id)
    line_id = add_line(app, event_id)
    reserve(app, event_id, line_id, 2)
    reserve(app, event_id, line_id, 2)

    response = confirm(client, event_id)

    assert response.status_code == 200
    assert response.json["event"]["status"] == "confirmed"


# TC-SPL-85-09 — AC3: released units no longer count towards the essential quantity.
def test_tc_spl_85_09_released_units_are_not_counted(app, client):
    event_id = add_event(app)
    add_booking(app, event_id)
    line_id = add_line(app, event_id, status="partially_reserved")
    reserve(app, event_id, line_id, 4, released=1)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert blocker_codes(response) == ["essential_not_fully_reserved"]


# TC-SPL-85-10 — AC3 positive partitions: lines that are not essential, or not active, never block.
@pytest.mark.parametrize("partition", ["non_essential_shortfall", "removed_essential", "no_lines"])
def test_tc_spl_85_10_non_essential_removed_or_absent_lines_do_not_block(app, client, partition):
    event_id = add_event(app)
    add_booking(app, event_id)
    if partition == "non_essential_shortfall":
        add_line(app, event_id, quantity=3, status="requested", essentiality="non_essential")
    elif partition == "removed_essential":
        add_line(app, event_id, status="removed")

    response = confirm(client, event_id)

    assert response.status_code == 200, response.json
    assert response.json["event"]["status"] == "confirmed"


# TC-SPL-85-11 — AC3 (Q80, Q106): an undecided or unmapped line could still be essential.
@pytest.mark.parametrize(
    ("line_options", "expected_code"),
    [
        ({"essentiality": "undecided"}, "essentiality_undecided"),
        ({"essentiality": "non_essential", "mapped": False}, "legacy_requirement_unmapped"),
    ],
)
def test_tc_spl_85_11_undecided_or_unmapped_lines_block(app, client, line_options, expected_code):
    event_id = add_event(app)
    add_booking(app, event_id)
    line_id = add_line(app, event_id, **line_options)
    if line_options.get("mapped", True):
        reserve(app, event_id, line_id, 4)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert blocker_codes(response) == [expected_code]


# --- Acceptance Criterion 4 -------------------------------------------------------------------


# TC-SPL-85-12 — AC4: an Approved booking carrying the SPL-89 review marker blocks.
def test_tc_spl_85_12_a_booking_marked_for_review_blocks(app, client):
    event_id = add_event(app)
    booking_id = add_booking(app, event_id, requires_review=True)
    line_id = add_line(app, event_id)
    reserve(app, event_id, line_id, 4)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert response.json["blockers"] == [
        {
            "code": "venue_booking_review_required",
            "booking_id": booking_id,
            "message": "Resolve the review flagged on the Harbour Hall booking.",
        }
    ]


# TC-SPL-85-12 — AC4: an unresolved SPL-130 timing finding blocks; a resolved one does not.
@pytest.mark.parametrize(("resolved", "expected_status"), [(False, 409), (True, 200)])
def test_tc_spl_85_12_an_unresolved_timing_finding_blocks(app, client, resolved, expected_status):
    event_id = add_event(app)
    booking_id = add_booking(app, event_id)
    line_id = add_line(app, event_id)
    reserve(app, event_id, line_id, 4)
    with Session(app.extensions["engine"]) as session:
        session.add(
            VenueBookingReviewFinding(
                booking_id=booking_id,
                finding_key="hours:2026-11-20",
                reason_type="outside_operating_hours",
                detail="Harbour Hall now closes before the event's turnaround ends.",
                venue_timing_revision=2,
                first_assessed_at=NOW,
                last_assessed_at=NOW,
                resolved_at=NOW if resolved else None,
                resolved_by_account_id=VENUE_STAFF if resolved else None,
            )
        )
        session.commit()

    response = confirm(client, event_id)

    assert response.status_code == expected_status, response.json
    if not resolved:
        assert blocker_codes(response) == ["venue_booking_review_required"]


# TC-SPL-85-13 — AC4: SPL-137's current review reasons count, not only the stored marker.
def test_tc_spl_85_13_a_computed_exact_time_review_reason_blocks(app, client):
    event_id = add_event(app)
    add_booking(app, event_id, exact_timing={"unreadable": True})
    line_id = add_line(app, event_id)
    reserve(app, event_id, line_id, 4)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert blocker_codes(response) == ["venue_booking_review_required"]


# TC-SPL-85-14 — AC4: a review on any equipment line blocks, essential or not.
@pytest.mark.parametrize(
    ("essentiality", "expected_code"),
    [
        ("essential", "essential_review_outstanding"),
        ("non_essential", "equipment_review_required"),
    ],
)
def test_tc_spl_85_14_an_equipment_review_blocks(app, client, essentiality, expected_code):
    event_id = add_event(app)
    add_booking(app, event_id)
    line_id = add_line(
        app,
        event_id,
        status="review_required",
        essentiality=essentiality,
        review_reason="Dates changed after reservation.",
    )
    reserve(app, event_id, line_id, 4)

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert response.json["blockers"] == [
        {
            "code": expected_code,
            "requirement_id": line_id,
            "message": "Dates changed after reservation.",
        }
    ]


# TC-SPL-85-15 — AC2-4: every outstanding blocker is reported in one refusal.
def test_tc_spl_85_15_every_blocker_is_reported_together(app, client):
    event_id = add_event(app)
    short_id = add_line(app, event_id, status="partially_reserved")
    reserve(app, event_id, short_id, 1)
    add_line(
        app,
        event_id,
        quantity=2,
        status="review_required",
        essentiality="non_essential",
        review_reason="Supplier recall.",
    )

    response = confirm(client, event_id)

    assert response.status_code == 409
    assert blocker_codes(response) == [
        "no_approved_venue_booking",
        "essential_not_fully_reserved",
        "equipment_review_required",
    ]


# --- Acceptance Criterion 5 -------------------------------------------------------------------


# TC-SPL-85-16 — AC5: the confirmer comes from the session and the time is recorded with history.
def test_tc_spl_85_16_confirmer_time_and_history_are_recorded(app, client):
    event_id = ready_event(app)
    before = datetime.now(SINGAPORE)

    response = confirm(client, event_id)

    after = datetime.now(SINGAPORE)
    assert response.status_code == 200
    event = response.json["event"]
    assert event["confirmed_by"] == {"id": COORDINATOR, "name": "Casey Coordinator"}
    confirmed_at = datetime.fromisoformat(event["confirmed_at"])
    assert confirmed_at.utcoffset().total_seconds() == 8 * 3600
    assert before <= confirmed_at <= after
    assert response.json["transition"] == {
        "action": "confirm",
        "previous_status": "planning",
        "resulting_status": "confirmed",
        "actor": {"id": COORDINATOR, "name": "Casey Coordinator"},
        "changed_at": event["confirmed_at"],
    }
    stored = snapshot(app, event_id)
    assert stored["confirmed_by"] == COORDINATOR
    assert stored["history"] == ["confirm"]
    with Session(app.extensions["engine"]) as session:
        row = session.scalar(
            select(EventStatusHistory).where(EventStatusHistory.event_request_id == event_id)
        )
        assert (row.previous_status, row.resulting_status, row.actor_account_id) == (
            "planning",
            "confirmed",
            COORDINATOR,
        )


def _organiser_view(client, event_id):
    response = client.get("/api/event-requests", headers=headers("organiser"))
    assert response.status_code == 200
    return next(item for item in response.json["event_requests"] if item["id"] == event_id)


# TC-SPL-85-17 — AC5: the organiser sees Confirmed, who confirmed it, and the arrangements.
def test_tc_spl_85_17_organiser_sees_the_confirmed_arrangements(app, client):
    event_id = add_event(app)
    booking_id = add_booking(app, event_id)
    add_booking(app, event_id, status="rejected", venue_id=2)
    line_id = add_line(app, event_id)
    reserve(app, event_id, line_id, 4)
    optional_id = add_line(
        app, event_id, quantity=3, status="requested", essentiality="non_essential"
    )

    unconfirmed = _organiser_view(client, event_id)
    assert unconfirmed["confirmed_by"] is None
    assert unconfirmed["confirmed_at"] is None
    assert unconfirmed["confirmed_arrangements"] is None

    confirmed_at = confirm(client, event_id).json["event"]["confirmed_at"]
    view = _organiser_view(client, event_id)

    assert view["status"] == "confirmed"
    assert view["status_label"] == "Confirmed"
    assert view["confirmed_by"] == {"id": COORDINATOR, "name": "Casey Coordinator"}
    assert view["confirmed_at"] == confirmed_at
    assert view["confirmed_arrangements"] == {
        "venues": [
            {
                "booking_id": booking_id,
                "venue": "Harbour Hall",
                "date": "2026-11-20",
                "start_time": "14:00",
                "end_time": "17:00",
                "layout": "theatre",
            }
        ],
        "equipment": [
            {
                "requirement_id": line_id,
                "equipment": "Wireless Microphone",
                "quantity": 4,
                "reserved_quantity": 4,
                "essential": True,
            },
            {
                "requirement_id": optional_id,
                "equipment": "Wireless Microphone",
                "quantity": 3,
                "reserved_quantity": 0,
                "essential": False,
            },
        ],
    }


# TC-SPL-85-18 — AC5: the coordinator's checklist matches the server gate, and reading is pure.
def test_tc_spl_85_18_assigned_detail_reports_confirmation_readiness(app, client):
    blocked_id = add_event(app)
    ready_id = ready_event(app)
    before = snapshot(app, blocked_id)

    blocked = client.get(f"/api/event-requests/assigned/{blocked_id}", headers=headers())
    ready = client.get(f"/api/event-requests/assigned/{ready_id}", headers=headers())

    assert blocked.status_code == ready.status_code == 200
    assert blocked.json["event"]["confirmation_readiness"] == {
        "ready": False,
        "blockers": [
            {
                "code": "no_approved_venue_booking",
                "booking_id": None,
                "message": "Get a venue booking approved by Venue Staff.",
            }
        ],
    }
    assert ready.json["event"]["confirmation_readiness"] == {"ready": True, "blockers": []}
    assert ready.json["event"]["confirmed_by"] is None
    assert snapshot(app, blocked_id) == before

    confirm(client, ready_id)
    after = client.get(f"/api/event-requests/assigned/{ready_id}", headers=headers())
    assert after.json["event"]["confirmed_by"]["name"] == "Casey Coordinator"


# TC-SPL-85-19 — AC5: no refusal path leaves a partial change behind.
@pytest.mark.parametrize(
    "refusal", ["wrong_role", "other_coordinator", "not_planning", "parameters", "blocked"]
)
def test_tc_spl_85_19_refusals_change_nothing(app, client, refusal):
    if refusal == "not_planning":
        event_id = ready_event(app, status="under_review")
    elif refusal == "blocked":
        event_id = add_event(app)
    else:
        event_id = ready_event(app)
    before = snapshot(app, event_id)

    if refusal == "wrong_role":
        response = confirm(client, event_id, "lead")
    elif refusal == "other_coordinator":
        response = confirm(client, event_id, "other-coordinator")
    elif refusal == "parameters":
        response = confirm(client, event_id, json={"status": "confirmed"})
    else:
        response = confirm(client, event_id)

    assert response.status_code in (400, 403, 404, 409)
    assert snapshot(app, event_id) == before
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count(EventStatusHistory.id))) == 0


# A second confirmation of the same event is refused and appends nothing.
def test_tc_spl_85_19_a_repeated_confirmation_is_refused(app, client):
    event_id = ready_event(app)
    assert confirm(client, event_id).status_code == 200
    first = snapshot(app, event_id)

    again = confirm(client, event_id)

    assert again.status_code == 409
    assert again.json["error"] == NOT_PLANNING
    assert snapshot(app, event_id) == first


# --- Acceptance Criterion 6 -------------------------------------------------------------------


# TC-SPL-85-22 — AC6: registration settings are not a precondition.
def test_tc_spl_85_22_registration_setup_is_not_required(app, client):
    event_id = ready_event(app, registration_required=True)

    response = confirm(client, event_id)

    assert response.status_code == 200
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assert event.status == "confirmed"
        assert event.registration_opens_at is None
        assert event.registration_closes_at is None
        assert event.registration_capacity is None


# TC-SPL-85-23 — AC6: SPL-114 accepts registration settings once the event is Confirmed.
def test_tc_spl_85_23_registration_can_be_enabled_after_confirmation(app, client):
    event_id = ready_event(app, registration_required=True)
    settings = {"opens_at": "2026-11-01T09:00", "closes_at": "2026-11-18T18:00", "capacity": 80}

    before = client.put(
        f"/api/event-requests/{event_id}/registration", json=settings, headers=headers()
    )
    confirm(client, event_id)
    after = client.put(
        f"/api/event-requests/{event_id}/registration", json=settings, headers=headers()
    )

    assert before.status_code == 409
    assert after.status_code == 200, after.json
