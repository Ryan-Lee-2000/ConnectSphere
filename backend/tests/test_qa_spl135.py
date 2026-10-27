"""QA coverage for SPL-135: Safety Officer review and the Preparation gate."""
# ruff: noqa: E501, E702

from datetime import date, datetime, time

import pytest
from app import create_app
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
    EventStatusHistory,
    Notification,
    Organisation,
    Role,
    SafetyReview,
    Venue,
    VenueBooking,
    VenueBookingReviewFinding,
    VenueLayout,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000013501"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000013502"
LEAD = "00000000-0000-0000-0000-000000013503"
ORGANISER = "00000000-0000-0000-0000-000000013504"
TECHNICAL = "00000000-0000-0000-0000-000000013505"
SAFETY = "00000000-0000-0000-0000-000000013506"
NOW = datetime(2026, 10, 25, 9, tzinfo=SINGAPORE)
EVENT_DATE = date(2026, 11, 20)
TOKENS = {
    "coordinator": COORDINATOR,
    "other": OTHER_COORDINATOR,
    "lead": LEAD,
    "organiser": ORGANISER,
    "technical": TECHNICAL,
    "safety": SAFETY,
}


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/safety-review.db",
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
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR),
            (OTHER_COORDINATOR, "Devon Lee", Role.EVENT_COORDINATOR),
            (LEAD, "Aisha Rahman", Role.EVENT_OPERATIONS_MANAGER),
            (ORGANISER, "Olivia Tan", Role.EVENT_ORGANISER),
            (TECHNICAL, "Taylor Goh", Role.TECHNICAL_SUPPORT_STAFF),
            (SAFETY, "Samira Hassan", Role.SAFETY_OFFICER),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    is_active=True,
                    organisation_id=organisation.id if account_id == ORGANISER else None,
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        venue = Venue(
            name="Harbour Hall",
            location="Marina Centre",
            operating_slots=["AM", "PM"],
            facilities=["PA system"],
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=180)]
        session.add_all(
            [
                venue,
                EquipmentType(
                    name="Wireless Microphone",
                    normalised_name="wireless microphone",
                    total_stock=12,
                ),
            ]
        )
        session.commit()
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(identity="coordinator"):
    return {"Authorization": f"Bearer {identity}"}


def plan(**overrides):
    value = {
        "emergency_access": {
            "value": "Keep the west fire exit clear and brief stewards.",
            "not_applicable_reason": "",
        },
        "equipment_placement": {
            "value": "Keep microphones behind the marked cable route.",
            "not_applicable_reason": "",
        },
        "crowd_movement": {
            "value": "Use separate entry and exit queues with two ushers.",
            "not_applicable_reason": "",
        },
        "venue_restrictions": {
            "value": "No open flame or blocked exits.",
            "not_applicable_reason": "",
        },
    }
    value.update(overrides)
    return {"plan": value}


def ready_event(app, *, status="confirmed", venue_notes="No open flame or blocked exits."):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=1,
            name="Northstar Leadership Forum",
            purpose="Leadership programme",
            proposed_date=EVENT_DATE,
            start_time=time(9),
            end_time=time(12),
            expected_attendance=120,
            accessibility_needs=["Step-free access"],
            venue_notes=venue_notes,
            status=status,
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
        session.add(
            VenueBooking(
                event_request_id=event.id,
                venue_id=1,
                status="approved",
                layout="theatre",
                expected_attendance=120,
                booking_date=EVENT_DATE,
                event_slots=["AM"],
                requested_by_account_id=COORDINATOR,
                requested_at=NOW,
                approved_by_account_id=LEAD,
                approved_at=NOW,
            )
        )
        line = EquipmentRequirement(
            event_request_id=event.id,
            equipment_type="Wireless Microphone",
            equipment_type_id=1,
            quantity=4,
            required_start_date=EVENT_DATE,
            required_end_date=EVENT_DATE,
            status="reserved",
            essentiality="essential",
        )
        session.add(line)
        session.flush()
        session.add(
            EquipmentReservation(
                event_request_id=event.id,
                equipment_requirement_id=line.id,
                equipment_type_id=1,
                commitment_start_date=EVENT_DATE,
                commitment_end_date=EVENT_DATE,
                quantity=4,
                reserved_by_account_id=TECHNICAL,
                reserved_at=NOW,
            )
        )
        session.commit()
        return event.id


def submit(client, event_id, identity="coordinator", payload=None):
    return client.post(
        f"/api/event-requests/{event_id}/safety-review",
        headers=headers(identity),
        json=payload or plan(),
    )


def decide(client, review_id, decision, reason="Reposition the entrance queue."):
    return client.post(
        f"/api/safety-reviews/{review_id}/decision",
        headers=headers("safety"),
        json={"decision": decision, "reason": reason},
    )


def review_count(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(
            select(func.count(SafetyReview.id)).where(SafetyReview.event_request_id == event_id)
        )


def test_spl136_technical_notes_change_invalidates_safety_approval(app, client):
    """Changing technical notes must make the previous Safety decision stale."""
    event_id = ready_event(app)
    submitted = submit(client, event_id)
    assert submitted.status_code == 200, submitted.json
    review_id = submitted.json["review"]["id"]
    assert decide(client, review_id, "approved").status_code == 200
    with Session(app.extensions["engine"]) as session:
        line = session.scalar(
            select(EquipmentRequirement).where(EquipmentRequirement.event_request_id == event_id)
        )
        line.notes = "Keep cables clear of the exit"
        session.commit()
    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())
    assert response.status_code == 409, response.json
    assert "no longer current" in response.json["error"]


def test_spl136_preparing_notes_change_requires_new_safety_decision(app, client):
    """A nonessential unreserved line must still invalidate the old Safety approval."""
    event_id = ready_event(app)
    with Session(app.extensions["engine"]) as session:
        line = EquipmentRequirement(
            event_request_id=event_id,
            equipment_type="Display screen",
            equipment_type_id=1,
            quantity=1,
            required_start_date=EVENT_DATE,
            required_end_date=EVENT_DATE,
            status="requested",
            essentiality="non_essential",
        )
        session.add(line)
        session.commit()
        line_id = line.id
    submitted = submit(client, event_id)
    assert submitted.status_code == 200, submitted.json
    review_id = submitted.json["review"]["id"]
    assert decide(client, review_id, "approved").status_code == 200
    assert (
        client.post(
            f"/api/event-requests/{event_id}/begin-preparation", headers=headers()
        ).status_code
        == 200
    )
    endpoint = f"/api/event-requests/assigned/{event_id}/significant-changes"
    payload = {"equipment_requirement_id": line_id, "values": {"notes": "Keep exit clear"}}
    preview = client.post(endpoint + "/preview", headers=headers(), json=payload)
    assert preview.status_code == 200 and preview.json["returns_to_planning"]
    saved = client.patch(
        endpoint,
        headers=headers(),
        json={**payload, "preview_token": preview.json["preview_token"]},
    )
    assert saved.status_code == 200, saved.json
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        assert event.status == "planning"
        # Model successful reconfirmation; the unchanged stock must not hide the notes change.
        event.status = "confirmed"
        session.commit()
    result = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())
    assert result.status_code == 409, result.json
    assert "no longer current" in result.json["error"]


def save_significant_change(client, event_id, values):
    """Apply the real significant-change workflow, including its server-issued preview token."""

    route = f"/api/event-requests/assigned/{event_id}/significant-changes"
    preview = client.post(route + "/preview", headers=headers(), json={"values": values})
    assert preview.status_code == 200, preview.json
    return client.patch(
        route,
        headers=headers(),
        json={"values": values, "preview_token": preview.json["preview_token"]},
    )


# QA-SPL-135-001 | AC1 | BB
def test_qa_spl_135_001_assigned_coordinator_submits_a_ready_confirmed_arrangement(app, client):
    event_id = ready_event(app)
    response = submit(client, event_id)
    assert response.status_code == 200
    assert response.json["review"]["status"] == "submitted"
    assert review_count(app, event_id) == 1


# QA-SPL-135-002 | AC1 | security
@pytest.mark.parametrize(
    ("identity", "expected"),
    [("other", 404), ("organiser", 403), ("technical", 403), ("safety", 403)],
)
def test_qa_spl_135_002_only_the_assigned_coordinator_submits(app, client, identity, expected):
    event_id = ready_event(app)
    response = submit(client, event_id, identity)
    assert response.status_code == expected
    assert review_count(app, event_id) == 0


# QA-SPL-135-003 | AC1 | negative
@pytest.mark.parametrize("status", ["planning", "preparing", "cancelled"])
def test_qa_spl_135_003_only_confirmed_events_accept_safety_information(app, client, status):
    event_id = ready_event(app, status=status)
    response = submit(client, event_id)
    assert response.status_code == 409
    assert review_count(app, event_id) == 0


# QA-SPL-135-004 | AC1 | negative
def test_qa_spl_135_004_unresolved_essential_arrangements_block_submission(app, client):
    event_id = ready_event(app)
    with Session(app.extensions["engine"]) as session:
        # The stored status alone is not trusted: the actual retained reservation is removed.
        session.delete(
            session.scalar(
                select(EquipmentReservation).where(
                    EquipmentReservation.event_request_id == event_id
                )
            )
        )
        session.commit()
    response = submit(client, event_id)
    assert response.status_code == 409
    assert (
        response.json["error"]
        == "Resolve the current venue and essential technical arrangements first."
    )


# QA-SPL-135-005 | AC1 | boundary
def test_qa_spl_135_005_current_pending_review_cannot_be_duplicated(app, client):
    event_id = ready_event(app)
    assert submit(client, event_id).status_code == 200
    response = submit(client, event_id)
    assert response.status_code == 409
    assert "already has a safety review awaiting" in response.json["error"]
    assert review_count(app, event_id) == 1


# QA-SPL-135-006 | AC2 | negative
@pytest.mark.parametrize(
    "payload", [None, {"emergency_access": {"value": "", "not_applicable_reason": ""}}]
)
def test_qa_spl_135_006_every_operational_plan_item_is_required(app, client, payload):
    event_id = ready_event(app)
    response = client.post(
        f"/api/event-requests/{event_id}/safety-review",
        headers=headers(),
        json={"plan": payload} if payload is not None else {},
    )
    assert response.status_code == 400
    assert review_count(app, event_id) == 0


# QA-SPL-135-007 | AC2 | negative
def test_qa_spl_135_007_not_applicable_needs_a_meaningful_reason(app, client):
    event_id = ready_event(app)
    response = submit(
        client, event_id, payload=plan(crowd_movement={"value": "", "not_applicable_reason": "  "})
    )
    assert response.status_code == 400
    assert "Explain each safety-plan item" in response.json["error"]


# QA-SPL-135-008 | AC2 | happy path
def test_qa_spl_135_008_a_justified_not_applicable_item_is_retained(app, client):
    event_id = ready_event(app)
    response = submit(
        client,
        event_id,
        payload=plan(
            crowd_movement={
                "value": "",
                "not_applicable_reason": "Invite-only meeting uses seated entry.",
            }
        ),
    )
    assert response.status_code == 200
    assert (
        response.json["review"]["plan"]["crowd_movement"]["not_applicable_reason"]
        == "Invite-only meeting uses seated entry."
    )


# QA-SPL-135-009 | AC2 | BB
def test_qa_spl_135_009_context_presents_venue_capacity_layout_restrictions_accessibility_and_equipment(
    app, client
):
    event_id = ready_event(app)
    response = client.get(f"/api/event-requests/{event_id}/safety-review", headers=headers())
    assert response.status_code == 200
    event = response.json["event"]
    assert event["venues"] == [
        {
            "name": "Harbour Hall",
            "layout": "theatre",
            "capacity": 180,
            "attendance": 120,
            "restrictions": "No open flame or blocked exits.",
        }
    ]
    assert event["accessibility_needs"] == ["Step-free access"]
    assert event["equipment"][0] == {
        "name": "Wireless Microphone",
        "required": 4,
        "reserved": 4,
        "essentiality": "essential",
        "status": "reserved",
    }


# QA-SPL-135-010 | AC2 | boundary
def test_qa_spl_135_010_overlong_safety_information_is_refused(app, client):
    event_id = ready_event(app)
    response = submit(
        client,
        event_id,
        payload=plan(emergency_access={"value": "x" * 2001, "not_applicable_reason": ""}),
    )
    assert response.status_code == 400
    assert response.json["error"] == "Safety-plan details are too long."


# QA-SPL-135-011 | AC3 | security
@pytest.mark.parametrize("identity", ["coordinator", "lead", "organiser", "technical"])
def test_qa_spl_135_011_only_safety_officer_can_decide(app, client, identity):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    response = client.post(
        f"/api/safety-reviews/{review_id}/decision",
        headers=headers(identity),
        json={"decision": "approved"},
    )
    assert response.status_code == 403


# QA-SPL-135-012 | AC3 | happy path
def test_qa_spl_135_012_approval_records_actor_time_and_notifies_the_assigned_coordinator(
    app, client
):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    response = decide(client, review_id, "approved", "")
    assert response.status_code == 200
    assert response.json["review"]["decided_by"] == {"id": SAFETY, "name": "Samira Hassan"}
    assert response.json["review"]["decided_at"]
    with Session(app.extensions["engine"]) as session:
        notice = session.scalar(
            select(Notification).where(Notification.event_request_id == event_id)
        )
        assert notice.recipient_account_id == COORDINATOR
        assert "approved" in notice.message


# QA-SPL-135-013 | AC3 | negative
def test_qa_spl_135_013_changes_require_a_reason_and_return_event_to_planning(app, client):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "changes_requested", " ").status_code == 400
    response = decide(client, review_id, "changes_requested")
    assert response.status_code == 200
    assert response.json["event"]["status"] == "planning"


# QA-SPL-135-014 | AC3 | negative
def test_qa_spl_135_014_rejection_keeps_the_event_and_audits_the_return_to_planning(app, client):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    response = decide(client, review_id, "rejected", "Exit path is obstructed.")
    assert response.status_code == 200
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        history = session.scalars(
            select(EventStatusHistory.action).where(EventStatusHistory.event_request_id == event_id)
        ).all()
        assert event.status == "planning"
        assert "safety_rework" in history


# QA-SPL-135-015 | AC3 | BB
def test_qa_spl_135_015_lead_can_read_decision_evidence_but_an_unassigned_coordinator_cannot(
    app, client
):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "rejected", "Exit path is obstructed.").status_code == 200
    lead = client.get(f"/api/event-requests/{event_id}/safety-review", headers=headers("lead"))
    other = client.get(f"/api/event-requests/{event_id}/safety-review", headers=headers("other"))
    assert lead.status_code == 200
    assert lead.json["review"]["reason"] == "Exit path is obstructed."
    assert other.status_code == 404


# QA-SPL-135-016 | AC4 | happy path
def test_qa_spl_135_016_current_approval_allows_the_assigned_coordinator_to_begin_preparation(
    app, client
):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())
    assert response.status_code == 200
    assert response.json["event"]["status"] == "preparing"


# QA-SPL-135-017 | AC4 | negative
@pytest.mark.parametrize("decision", [None, "changes_requested", "rejected"])
def test_qa_spl_135_017_no_pending_or_negative_decision_can_begin_preparation(
    app, client, decision
):
    event_id = ready_event(app)
    if decision:
        review_id = submit(client, event_id).json["review"]["id"]
        assert decide(client, review_id, decision).status_code == 200
    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())
    assert response.status_code == 409
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status != "preparing"


# QA-SPL-135-018 | AC4 | boundary
def test_qa_spl_135_018_changing_arrangements_invalidates_an_old_approval(app, client):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).expected_attendance = 121
        session.commit()
    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())
    assert response.status_code == 409
    assert "no longer current" in response.json["error"]


# QA-SPL-135-021 | AC4 | regression
def test_qa_spl_135_021_current_venue_review_requirement_blocks_preparation(app, client):
    """An approval cannot bypass a venue booking that was flagged after Safety decided."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    with Session(app.extensions["engine"]) as session:
        session.scalar(
            select(VenueBooking).where(VenueBooking.event_request_id == event_id)
        ).requires_review = True
        session.commit()

    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())

    assert response.status_code == 409
    assert response.json["blockers"][0]["code"] == "venue_booking_review_required"
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status == "confirmed"


# QA-SPL-135-022 | AC4 | regression
def test_qa_spl_135_022_changed_venue_restrictions_invalidate_safety_approval(app, client):
    """Safety must re-review the event when the venue restrictions it saw have changed."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    with Session(app.extensions["engine"]) as session:
        session.get(
            EventRequest, event_id
        ).venue_notes = "West emergency exit is closed; use the east exit."
        session.commit()

    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())

    assert response.status_code == 409
    assert "no longer current" in response.json["error"]


# QA-SPL-135-023 | AC2, AC3 | integration
def test_qa_spl_135_023_safety_queue_returns_the_actual_arrangement_evidence(app, client):
    """The decision queue returns the approved venue and equipment context, not only a title."""

    event_id = ready_event(app)
    assert submit(client, event_id).status_code == 200

    response = client.get("/api/safety-reviews", headers=headers("safety"))

    assert response.status_code == 200
    event = response.json["reviews"][0]["event"]
    assert event["venues"][0]["name"] == "Harbour Hall"
    assert event["venues"][0]["restrictions"] == "No open flame or blocked exits."
    assert event["equipment"][0]["name"] == "Wireless Microphone"


# QA-SPL-135-024 | AC4 | P1 review-round-2 regression
def test_qa_spl_135_024_changed_event_timing_invalidates_an_approved_safety_review(app, client):
    """A Safety approval belongs to the reviewed schedule, not merely its AM booking slot."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    with Session(app.extensions["engine"]) as session:
        # 10:00 remains within AM, so this isolates stale Safety approval from venue readiness.
        session.get(EventRequest, event_id).start_time = time(10)
        session.commit()

    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())

    assert response.status_code == 409
    assert "no longer current" in response.json["error"]
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status == "confirmed"


# QA-SPL-135-025 | AC4 | P1 review-round-2 integration regression
def test_qa_spl_135_025_reconfirmation_cannot_resurrect_safety_approval_for_changed_schedule(
    app, client
):
    """The significant-change and reconfirmation flow still requires a fresh Safety review."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200

    changed = save_significant_change(client, event_id, {"start_time": "10:00"})
    assert changed.status_code == 200, changed.json
    assert changed.json["event"]["status"] == "planning"
    with Session(app.extensions["engine"]) as session:
        # SPL-109 appropriately asks Venue and Technical Support to revalidate affected
        # arrangements.  Clearing those separate reviews makes the event confirmable again, but
        # cannot revive the old Safety decision for the changed schedule.
        booking = session.scalar(
            select(VenueBooking).where(VenueBooking.event_request_id == event_id)
        )
        booking.requires_review = False
        # The real revalidation route closes these findings.  The Safety test only needs the
        # confirmed, revalidated arrangement it leaves behind.
        session.query(VenueBookingReviewFinding).filter_by(booking_id=booking.id).delete()
        requirement = session.scalar(
            select(EquipmentRequirement).where(EquipmentRequirement.event_request_id == event_id)
        )
        requirement.status = "reserved"
        requirement.review_reason = None
        requirement.review_flagged_at = None
        session.commit()
    reconfirmed = client.post(f"/api/event-requests/{event_id}/confirm", headers=headers())
    assert reconfirmed.status_code == 200, reconfirmed.json

    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())

    assert response.status_code == 409
    assert "no longer current" in response.json["error"]
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status == "confirmed"


# QA-SPL-136-001 | AC1 | BB
def test_qa_spl_136_001_assigned_detail_marks_only_a_safety_return_as_safety_rework(app, client):
    """The coordinator sees why Planning reopened when Safety requests a correction."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert (
        decide(
            client, review_id, "changes_requested", "Move the cable route away from the exit."
        ).status_code
        == 200
    )

    response = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers())

    assert response.status_code == 200
    assert response.json["event"]["status"] == "planning"
    assert response.json["event"]["safety_rework"] is True


# QA-SPL-136-002 | AC2 | regression
def test_qa_spl_136_002_old_safety_rejection_does_not_mislabel_a_later_significant_change(
    app, client
):
    """Planning's reason follows the newest durable transition, not an old review record."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "rejected", "Use the east exit instead.").status_code == 200
    assert (
        client.post(f"/api/event-requests/{event_id}/confirm", headers=headers()).status_code == 200
    )

    changed = save_significant_change(client, event_id, {"start_time": "10:00"})
    assert changed.status_code == 200, changed.json

    response = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers())

    assert response.status_code == 200
    assert response.json["event"]["status"] == "planning"
    assert response.json["event"]["safety_rework"] is False


# QA-SPL-136-003 | AC3 | regression
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("preferred_room_layout", "theatre"),
        ("required_facilities", ["PA system"]),
        ("location_preference", "Marina Centre"),
    ],
)
def test_qa_spl_136_003_revalidated_arrangement_preferences_cannot_reuse_old_safety_approval(
    app, client, field, value
):
    """Every safety-relevant venue preference needs a renewed Safety decision after Planning."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    assert (
        client.post(
            f"/api/event-requests/{event_id}/begin-preparation", headers=headers()
        ).status_code
        == 200
    )

    changed = save_significant_change(client, event_id, {field: value})
    assert changed.status_code == 200, changed.json
    assert changed.json["event"]["status"] == "planning"
    with Session(app.extensions["engine"]) as session:
        booking = session.scalar(
            select(VenueBooking).where(VenueBooking.event_request_id == event_id)
        )
        # This models the separate venue/technical revalidation workflows.  They make the event
        # confirmable again, but must not make the old safety approval current.
        booking.requires_review = False
        session.query(VenueBookingReviewFinding).filter_by(booking_id=booking.id).delete()
        requirement = session.scalar(
            select(EquipmentRequirement).where(EquipmentRequirement.event_request_id == event_id)
        )
        requirement.status = "reserved"
        requirement.review_reason = None
        requirement.review_flagged_at = None
        session.commit()

    assert (
        client.post(f"/api/event-requests/{event_id}/confirm", headers=headers()).status_code == 200
    )
    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())

    assert response.status_code == 409
    assert "no longer current" in response.json["error"]


# QA-SPL-136-004 | AC3 | boundary
def test_qa_spl_136_004_name_only_correction_keeps_an_approved_safety_review_current(app, client):
    """A cosmetic name correction is deliberately outside the Safety arrangement boundary."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).name = "Northstar Leadership Forum 2026"
        session.commit()

    response = client.post(f"/api/event-requests/{event_id}/begin-preparation", headers=headers())

    assert response.status_code == 200
    assert response.json["event"]["status"] == "preparing"


# QA-SPL-136-005 | AC4 | API contract
def test_qa_spl_136_005_read_returns_latest_review_and_accountable_history(app, client):
    """The current review is convenient at the top level while the complete audit history remains readable."""

    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "changes_requested", "Use the east exit.").status_code == 200

    response = client.get(f"/api/event-requests/{event_id}/safety-review", headers=headers())

    assert response.status_code == 200
    assert response.json["review"]["id"] == review_id
    assert [item["id"] for item in response.json["reviews"]] == [review_id]
    assert response.json["reviews"][0]["reason"] == "Use the east exit."


# QA-SPL-135-019 | AC4 | security
@pytest.mark.parametrize(("identity", "expected"), [("other", 404), ("lead", 403), ("safety", 403)])
def test_qa_spl_135_019_every_other_entry_path_is_refused(app, client, identity, expected):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    response = client.post(
        f"/api/event-requests/{event_id}/begin-preparation", headers=headers(identity)
    )
    assert response.status_code == expected


# QA-SPL-135-020 | AC4 | concurrency-safe repeat
def test_qa_spl_135_020_a_second_decision_or_preparation_attempt_is_refused(app, client):
    event_id = ready_event(app)
    review_id = submit(client, event_id).json["review"]["id"]
    assert decide(client, review_id, "approved", "").status_code == 200
    assert (
        client.post(
            f"/api/event-requests/{event_id}/begin-preparation", headers=headers()
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/event-requests/{event_id}/begin-preparation", headers=headers()
        ).status_code
        == 409
    )
    assert decide(client, review_id, "rejected").status_code == 409
