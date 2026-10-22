"""SPL-109 acceptance tests: warnings, retained arrangements and atomic changes."""

import pytest
import test_qa_spl106_requirements as venue
from app.models import (
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentReservationRelease,
    EquipmentType,
    EventCoordinatorAssignment,
    EventDetailChange,
    EventRequest,
    EventStatusHistory,
    Venue,
    VenueBooking,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

app = venue.app
base_app = venue.base_app
client = venue.client


def url(event):
    return f"/api/event-requests/assigned/{event}/significant-changes"


def preview(client, event, values, token="coordinator", **extra):
    return client.post(
        url(event) + "/preview", json={"values": values, **extra}, headers=venue.base.headers(token)
    )


def save(client, event, values, **extra):
    response = preview(client, event, values, **extra)
    assert response.status_code == 200, response.json
    return client.patch(
        url(event),
        json={"values": values, "preview_token": response.json["preview_token"], **extra},
        headers=venue.base.headers(),
    )


def state(app):
    with app.extensions["engine"].connect() as conn:
        from app.models import Base

        return {
            t.name: [tuple(row) for row in conn.execute(t.select())]
            for t in Base.metadata.sorted_tables
        }


def equipment(app, event, status="reserved"):
    with Session(app.extensions["engine"]) as s:
        kind = EquipmentType(
            name="QA microphone", normalised_name="qa microphone", location="Store", total_stock=10
        )
        s.add(kind)
        s.flush()
        line = EquipmentRequirement(
            event_request_id=event,
            equipment_type=kind.name,
            equipment_type_id=kind.id,
            quantity=4,
            required_start_date=venue.DAY,
            required_end_date=venue.DAY,
            status=status,
        )
        s.add(line)
        s.flush()
        s.add(
            EquipmentReservation(
                event_request_id=event,
                equipment_requirement_id=line.id,
                equipment_type_id=kind.id,
                commitment_start_date=venue.DAY,
                commitment_end_date=venue.DAY,
                quantity=4,
                reserved_by_account_id=venue.base.VENUE_STAFF,
                reserved_at=venue.WHEN,
            )
        )
        s.commit()
        return line.id


def confirmed(app, event):
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).status = "confirmed"
        s.commit()


@pytest.mark.parametrize(
    "values",
    [
        {"proposed_date": "2030-06-16"},
        {"start_time": "09:30"},
        {"end_time": "12:30"},
        {"expected_attendance": 400},
        {"preferred_room_layout": "cabaret"},
        {"required_facilities": ["Lift"]},
        {"accessibility_needs": ["Lift"]},
    ],
)
# QA-SPL-109-001 | AC1 | BB
def test_qa_spl_109_001_significant_fields(app, client, values):
    event, _, _ = venue.scenario(app, client)
    response = save(client, event, values)
    assert response.status_code == 200, response.json
    for field, value in values.items():
        assert response.json["change"]["changes"][field]["new"] == value


@pytest.mark.parametrize(
    "values",
    [
        {"setup_minutes": 30},
        {"name": "Changed"},
        {"status": "confirmed"},
        {"organiser_account_id": "spoof"},
    ],
)
# QA-SPL-109-002 | AC1 | BB
def test_qa_spl_109_002_whitelist(app, client, values):
    event, _, _ = venue.scenario(app, client)
    before = state(app)
    assert preview(client, event, values).status_code == 400
    assert state(app) == before


@pytest.mark.parametrize(
    "values",
    [
        {"expected_attendance": 0},
        {"expected_attendance": True},
        {"expected_attendance": 2147483648},
        {"start_time": "12:00"},
        {"end_time": "09:00"},
        {"proposed_date": "2000-01-01"},
        {"required_facilities": ["x" * 201]},
        {"accessibility_needs": "Lift"},
        {"preferred_room_layout": 123},
    ],
)
# QA-SPL-109-003 | AC1 | BB
def test_qa_spl_109_003_validation(app, client, values):
    event, _, _ = venue.scenario(app, client)
    before = state(app)
    assert preview(client, event, values).status_code == 400
    assert state(app) == before


# QA-SPL-109-004 | AC1 | BB
def test_qa_spl_109_004_boundary(app, client):
    event, _, _ = venue.scenario(app, client)
    assert save(client, event, {"expected_attendance": 2147483647}).status_code == 200


# QA-SPL-109-005 | AC1 | WB
def test_qa_spl_109_005_direct_equipment(app, client):
    event, _, _ = venue.scenario(app, client)
    line = equipment(app, event)
    confirmed(app, event)
    response = save(client, event, {"quantity": 5}, equipment_requirement_id=line)
    assert response.status_code == 200, response.json
    assert response.json["released_quantity"] == 4
    with Session(app.extensions["engine"]) as s:
        assert s.get(EquipmentRequirement, line).status == "review_required"
        assert s.scalar(select(func.count()).select_from(EquipmentReservationRelease)) == 1


# QA-SPL-109-006 | AC2 | WB
def test_qa_spl_109_006_preview_cancel_no_writes(app, client):
    event, _, _ = venue.scenario(app, client)
    equipment(app, event)
    confirmed(app, event)
    before = state(app)
    response = preview(client, event, {"proposed_date": "2030-06-16"})
    assert response.status_code == 200
    assert response.json["returns_to_planning"]
    assert state(app) == before


# QA-SPL-109-007 | AC2 | BB
def test_qa_spl_109_007_every_arrangement(app, client):
    event, _, bookings = venue.scenario(app, client, siblings=True)
    line = equipment(app, event)
    response = preview(client, event, {"proposed_date": "2030-06-16"})
    assert {(i["kind"], i["id"]) for i in response.json["arrangements"]} == {
        ("venue", b["id"]) for b in bookings
    } | {("equipment", line)}


# QA-SPL-109-008 | AC2 | WB
def test_qa_spl_109_008_stale_preview(app, client):
    event, room, _ = venue.scenario(app, client)
    values = {"expected_attendance": 400}
    token = preview(client, event, values).json["preview_token"]
    with Session(app.extensions["engine"]) as s:
        s.get(Venue, room).location = "Elsewhere"
        s.commit()
    before = state(app)
    response = client.patch(
        url(event), json={"values": values, "preview_token": token}, headers=venue.base.headers()
    )
    assert response.status_code == 409
    assert state(app) == before


# QA-SPL-109-009 | AC2 | BB
def test_qa_spl_109_009_missing_confirmation(app, client):
    event, _, _ = venue.scenario(app, client)
    before = state(app)
    assert (
        client.patch(
            url(event), json={"values": {"expected_attendance": 400}}, headers=venue.base.headers()
        ).status_code
        == 409
    )
    assert state(app) == before


# QA-SPL-109-010 | AC2 | BB
def test_qa_spl_109_010_no_arrangements(app, client):
    event = venue.base.make_event(app, day=venue.DAY)
    response = preview(client, event, {"expected_attendance": 160})
    assert response.status_code == 200
    assert response.json["arrangements"] == []


# QA-SPL-109-011 | AC3 | WB
def test_qa_spl_109_011_date_keeps_bookings(app, client):
    event, _, bookings = venue.scenario(app, client, approved=True, siblings=True)
    assert save(client, event, {"proposed_date": "2030-06-16"}).status_code == 200
    for booking in bookings:
        detail = venue.detail(client, booking)
        assert detail["booking"]["status"] == "approved"
        assert detail["review"]["requires_review"]
        with Session(app.extensions["engine"]) as s:
            assert s.get(VenueBooking, booking["id"]).booking_date == venue.DAY


# QA-SPL-109-012 | AC3 | BB
def test_qa_spl_109_012_time_flags_only_affected(app, client):
    event, _, (first, second) = venue.scenario(app, client, siblings=True)
    assert save(client, event, {"end_time": "11:00"}).status_code == 200
    assert not venue.kinds(client, first)
    assert "event_times" in venue.kinds(client, second)


# QA-SPL-109-013 | AC3 | BB
def test_qa_spl_109_013_independent_allocations(app, client):
    event, _, bookings = venue.scenario(app, client, siblings=True)
    assert (
        save(
            client,
            event,
            {
                "expected_attendance": 500,
                "preferred_room_layout": "cabaret",
                "required_facilities": ["Lift"],
            },
        ).status_code
        == 200
    )
    for booking in bookings:
        assert not venue.kinds(client, booking)


# QA-SPL-109-014 | AC3 | WB
def test_qa_spl_109_014_equipment_retained(app, client):
    event, _, _ = venue.scenario(app, client)
    line = equipment(app, event)
    assert save(client, event, {"proposed_date": "2030-06-16"}).status_code == 200
    with Session(app.extensions["engine"]) as s:
        row = s.get(EquipmentRequirement, line)
        assert row.status == "review_required"
        assert row.required_start_date == venue.DAY and row.quantity == 4
        assert s.scalar(select(EquipmentReservation)).quantity == 4
        assert s.scalar(select(func.count()).select_from(EquipmentReservationRelease)) == 0


# QA-SPL-109-015 | AC3 | BB
def test_qa_spl_109_015_resolved_flags_clear(app, client):
    event, _, (booking,) = venue.scenario(app, client)
    assert save(client, event, {"expected_attendance": 100}).status_code == 200
    assert "attendance" in venue.kinds(client, booking)
    response = preview(client, event, {"expected_attendance": 300})
    assert response.json["arrangements"][0]["kind"] == "venue"
    assert save(client, event, {"expected_attendance": 300}).status_code == 200
    assert not venue.kinds(client, booking)


# QA-SPL-109-016 | AC4 | WB
def test_qa_spl_109_016_confirmed_history(app, client):
    event, _, _ = venue.scenario(app, client)
    confirmed(app, event)
    response = save(client, event, {"expected_attendance": 400})
    assert response.status_code == 200
    assert response.json["event"]["status"] == "planning"
    with Session(app.extensions["engine"]) as s:
        history = s.scalar(select(EventStatusHistory))
        assert history.previous_status == "confirmed" and history.resulting_status == "planning"
        assert response.json["status_change_id"] == history.id


# QA-SPL-109-017 | AC4 | WB
def test_qa_spl_109_017_planning_no_transition(app, client):
    event, _, _ = venue.scenario(app, client)
    assert save(client, event, {"expected_attendance": 400}).status_code == 200
    with Session(app.extensions["engine"]) as s:
        assert s.scalar(select(func.count()).select_from(EventStatusHistory)) == 0


# QA-SPL-109-018 | AC4 | WB
def test_qa_spl_109_018_noop_confirmed(app, client):
    event, _, _ = venue.scenario(app, client)
    confirmed(app, event)
    before = state(app)
    response = save(client, event, {"expected_attendance": 300})
    assert response.status_code == 200 and response.json["change"] is None
    assert response.json["event"]["status"] == "confirmed"
    assert state(app) == before


# QA-SPL-109-019 | AC4 | WB
def test_qa_spl_109_019_retry_once(app, client):
    event, _, _ = venue.scenario(app, client)
    confirmed(app, event)
    assert save(client, event, {"expected_attendance": 400}).status_code == 200
    before = state(app)
    assert save(client, event, {"expected_attendance": 400}).json["change"] is None
    assert state(app) == before


# QA-SPL-109-020 | AC4 | WB
def test_qa_spl_109_020_transaction_failure(app, client, monkeypatch):
    event, _, _ = venue.scenario(app, client)
    equipment(app, event)
    confirmed(app, event)
    before = state(app)

    def fail(*args, **kwargs):
        raise RuntimeError("Injected audit failure")

    monkeypatch.setattr("app.significant_event_changes.return_to_planning", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        save(client, event, {"expected_attendance": 100})
    assert state(app) == before


# QA-SPL-109-021 | AC5 | WB
def test_qa_spl_109_021_truthful_audit(app, client):
    event, _, _ = venue.scenario(app, client)
    assert save(client, event, {"expected_attendance": 400}).status_code == 200
    with Session(app.extensions["engine"]) as s:
        audit = s.scalar(select(EventDetailChange))
        assert audit.changes == {"expected_attendance": {"previous": 300, "new": 400}}
        assert audit.changed_by_account_id == venue.base.COORDINATOR


@pytest.mark.parametrize("status", ["cancelled", "completed"])
# QA-SPL-109-022 | AC5 | WB
def test_qa_spl_109_022_closed_refused(app, client, status):
    event, _, _ = venue.scenario(app, client)
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).status = status
        s.commit()
    before = state(app)
    assert preview(client, event, {"expected_attendance": 400}).status_code == 409
    assert (
        client.patch(
            url(event), json={"values": {"expected_attendance": 400}}, headers=venue.base.headers()
        ).status_code
        == 409
    )
    assert state(app) == before


@pytest.mark.parametrize(
    "token,code",
    [("organiser", 403), ("venue-staff", 403), ("other-coordinator", 404), (None, 401)],
)
# QA-SPL-109-023 | AC5 | BB
def test_qa_spl_109_023_access(app, client, token, code):
    event, _, _ = venue.scenario(app, client)
    before = state(app)
    assert preview(client, event, {"expected_attendance": 400}, token=token).status_code == code
    assert state(app) == before


# QA-SPL-109-024 | AC5 | WB
def test_qa_spl_109_024_reassigned_before_save(app, client):
    event, _, _ = venue.scenario(app, client)
    values = {"expected_attendance": 400}
    token = preview(client, event, values).json["preview_token"]
    with Session(app.extensions["engine"]) as s:
        s.scalar(
            select(EventCoordinatorAssignment)
        ).coordinator_account_id = venue.base.OTHER_COORDINATOR
        s.commit()
    before = state(app)
    assert (
        client.patch(
            url(event),
            json={"values": values, "preview_token": token},
            headers=venue.base.headers(),
        ).status_code
        == 404
    )
    assert state(app) == before


# QA-SPL-109-025 | AC5 | WB
def test_qa_spl_109_025_closed_after_preview(app, client):
    event, _, _ = venue.scenario(app, client)
    values = {"expected_attendance": 400}
    token = preview(client, event, values).json["preview_token"]
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).status = "cancelled"
        s.commit()
    before = state(app)
    assert (
        client.patch(
            url(event),
            json={"values": values, "preview_token": token},
            headers=venue.base.headers(),
        ).status_code
        == 409
    )
    assert state(app) == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"values": {}},
        {"values": {"expected_attendance": 400}, "role": "admin"},
        {"values": {"quantity": 5}, "equipment_requirement_id": True},
        {"values": {"quantity": 5}, "equipment_requirement_id": -1},
    ],
)
# QA-SPL-109-026 | AC1 | BB
def test_qa_spl_109_026_envelope_validation(app, client, body):
    event, _, _ = venue.scenario(app, client)
    before = state(app)
    assert (
        client.post(url(event) + "/preview", json=body, headers=venue.base.headers()).status_code
        == 400
    )
    assert state(app) == before


# QA-SPL-109-027 | AC3 | WB
def test_qa_spl_109_027_existing_equipment_reason_retained(app, client):
    event, _, _ = venue.scenario(app, client)
    line = equipment(app, event)
    with Session(app.extensions["engine"]) as s:
        s.get(EquipmentRequirement, line).review_reason = "Original equipment concern"
        s.commit()
    assert save(client, event, {"expected_attendance": 400}).status_code == 200
    assert save(client, event, {"expected_attendance": 500}).status_code == 200
    with Session(app.extensions["engine"]) as s:
        reason = s.get(EquipmentRequirement, line).review_reason
        assert reason.startswith("Original equipment concern")
        assert reason.count("Event requirements changed.") == 1


# QA-SPL-109-028 | AC1 | WB
def test_qa_spl_109_028_equipment_active_guard(app, client):
    event, _, _ = venue.scenario(app, client)
    line = equipment(app, event)
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).status = "approved"
        s.commit()
    assert preview(client, event, {"quantity": 5}, equipment_requirement_id=line).status_code == 409


# QA-SPL-109-029 | AC4 | WB
def test_qa_spl_109_029_equipment_noop(app, client):
    event, _, _ = venue.scenario(app, client)
    line = equipment(app, event)
    confirmed(app, event)
    before = state(app)
    assert (
        save(client, event, {"quantity": 4}, equipment_requirement_id=line).json["change"] is None
    )
    assert state(app) == before


# QA-SPL-109-037 | AC1 | BB
def test_qa_spl_109_037_confirmed_equipment_read(app, client):
    event, _, _ = venue.scenario(app, client)
    equipment(app, event)
    confirmed(app, event)
    response = client.get(
        f"/api/event-requests/{event}/equipment-requirements", headers=venue.base.headers()
    )
    assert response.status_code == 200


@pytest.mark.parametrize("changed_date,expected", [(False, 200), (True, 409)])
# QA-SPL-109-038 | AC3 | WB
def test_qa_spl_109_038_revalidation_matches_event_date(app, client, changed_date, expected):
    from app.models import AccountRole, Role

    event, _, _ = venue.scenario(app, client)
    line = equipment(app, event)
    with Session(app.extensions["engine"]) as s:
        s.add(
            AccountRole(account_id=venue.base.VENUE_STAFF, role=Role.TECHNICAL_SUPPORT_STAFF.value)
        )
        s.commit()
    values = {"proposed_date": "2030-06-16"} if changed_date else {"expected_attendance": 400}
    assert save(client, event, values).status_code == 200
    response = client.post(
        f"/api/equipment-requirements/{line}/revalidate-reservation",
        json={},
        headers=venue.base.headers("venue-staff"),
    )
    assert response.status_code == expected, response.json
    with Session(app.extensions["engine"]) as s:
        assert s.get(EquipmentRequirement, line).status == (
            "review_required" if changed_date else "reserved"
        )
