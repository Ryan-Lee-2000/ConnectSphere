"""SPL-112 decisions: public contracts, atomic effects and durable finality."""

from datetime import datetime, timezone

import pytest
import test_event_change_requests as base
import test_qa_spl141 as equipment_base
from app import event_change_decisions as module
from app.equipment_releases import _held_quantity
from app.models import (
    EquipmentRequirement,
    EquipmentReservationRelease,
    EventChangeRequestItem,
    EventCoordinatorAssignment,
    EventDetailChange,
    EventRequest,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

app = base.app
client = base.client
equipment = equipment_base.equipment


def item(field="name", value="Revised gala"):
    return dict(field=field, requested_value=value, reason="Programme revised")


def request(client, event, *items):
    result = base.submit(client, event, list(items) or [item()])
    assert result.status_code == 201, result.json
    return result.json["change_request"]


def choices(req, decision="accepted", reason=None):
    return [
        dict(
            item_id=i["id"],
            decision=decision,
            **({"decline_reason": reason} if reason is not None else {}),
        )
        for i in req["items"]
    ]


def url(event, req):
    return f"/api/event-requests/assigned/{event}/change-requests/{req['id']}/decisions"


def preview(client, event, req, decisions, token="coordinator", **extra):
    return client.post(
        url(event, req) + "/preview",
        json={"decisions": decisions, **extra},
        headers=base.headers(token),
    )


def save(client, event, req, decisions):
    check = preview(client, event, req, decisions)
    assert check.status_code == 200, check.json
    return client.post(
        url(event, req),
        json={"decisions": decisions, "preview_token": check.json["preview_token"]},
        headers=base.headers("coordinator"),
    )


def state(app):
    from app.models import Base

    with app.extensions["engine"].connect() as conn:
        return {
            t.name: [tuple(r) for r in conn.execute(t.select())]
            for t in Base.metadata.sorted_tables
        }


# QA-SPL-112-001 | AC1 | BB
def test_qa_spl_112_001_accept(app, client):
    event = base.make_event(app)
    req = request(client, event)
    result = save(client, event, req, choices(req))
    assert result.status_code == 200
    assert result.json["change_request"]["items"][0]["decision"] == "accepted"
    assert result.json["event"]["name"] == "Revised gala"


# QA-SPL-112-002 | AC1 | BB
def test_qa_spl_112_002_decline(app, client):
    event = base.make_event(app)
    req = request(client, event)
    result = save(client, event, req, choices(req, "declined", "  Not suitable  "))
    assert result.status_code == 200
    assert result.json["change_request"]["items"][0]["decline_reason"] == "Not suitable"
    assert result.json["event"]["name"] == "Harbour Lights Gala"


@pytest.mark.parametrize("reason", [None, "", "  ", 42, "x" * 1001])
# QA-SPL-112-003 | AC1 | BB
def test_qa_spl_112_003_reason_required(app, client, reason):
    event = base.make_event(app)
    req = request(client, event)
    before = state(app)
    assert preview(client, event, req, choices(req, "declined", reason)).status_code == 400
    assert state(app) == before


# QA-SPL-112-004 | AC1 | BB
def test_qa_spl_112_004_reason_boundary(app, client):
    event = base.make_event(app)
    req = request(client, event)
    result = save(client, event, req, choices(req, "declined", "x" * 1000))
    assert len(result.json["change_request"]["items"][0]["decline_reason"]) == 1000


@pytest.mark.parametrize(
    "token,code", [(None, 401), ("organiser", 403), ("attendee", 403), ("other-coordinator", 404)]
)
# QA-SPL-112-005 | AC1 | BB
def test_qa_spl_112_005_assigned_coordinator_only(app, client, token, code):
    event = base.make_event(app)
    req = request(client, event)
    before = state(app)
    for suffix in ("/preview", ""):
        result = client.post(
            url(event, req) + suffix, json={"decisions": choices(req)}, headers=base.headers(token)
        )
        assert result.status_code == code
    assert state(app) == before


# QA-SPL-112-006 | AC2 | WB
def test_qa_spl_112_006_ordinary_retains_confirmation(app, client):
    event = base.make_event(app, "confirmed")
    req = request(client, event, item(), item("venue_notes", "North entrance"))
    result = save(client, event, req, choices(req))
    assert result.json["event"]["status"] == "confirmed"
    with Session(app.extensions["engine"]) as s:
        audit = s.scalar(select(EventDetailChange))
        assert set(audit.changes) == {"name", "venue_notes"}


# QA-SPL-112-007 | AC2 | WB
def test_qa_spl_112_007_significant_combined_times(app, client):
    event = base.make_event(app, "confirmed")
    req = request(client, event, item("start_time", "09:00"), item("end_time", "10:00"))
    check = preview(client, event, req, choices(req))
    assert check.json["returns_to_planning"] is True
    result = save(client, event, req, choices(req))
    assert result.status_code == 200, result.json
    assert result.json["event"]["status"] == "planning"
    with Session(app.extensions["engine"]) as s:
        event = s.get(EventRequest, event)
        assert event.start_time.hour == 9 and event.end_time.hour == 10


# QA-SPL-136-007 | AC2 | regression
def test_qa_spl_136_007_change_request_preview_warns_that_preparing_event_returns_to_planning(
    app, client
):
    """The preview must not promise that a Preparing event will stay in Preparation."""

    event = base.make_event(app, "confirmed")
    req = request(client, event, item("expected_attendance", 151))
    # A request can be submitted while Confirmed and still be pending when the event enters
    # Preparation.  Its later decision preview must describe the real resulting transition.
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).status = "preparing"
        s.commit()

    check = preview(client, event, req, choices(req))

    assert check.status_code == 200, check.json
    assert check.json["returns_to_planning"] is True


# QA-SPL-112-008 | AC2 | WB
def test_qa_spl_112_008_equipment_add_final_date(app, client, equipment):
    event = equipment["event"]
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).status = "confirmed"
        s.commit()
    req = request(
        client, event, item("proposed_date", "2026-12-06"), equipment_base.proposal(equipment)
    )
    assert save(client, event, req, choices(req)).status_code == 200
    with Session(app.extensions["engine"]) as s:
        line = s.scalar(
            select(EquipmentRequirement).where(EquipmentRequirement.notes == "New screen")
        )
        assert line.quantity == 4 and line.status == "requested"
        assert line.required_start_date.isoformat() == "2026-12-06"
        assert line.required_end_date == line.required_start_date
        assert line.essentiality == "undecided"


@pytest.mark.parametrize("operation", ["update", "remove"])
# QA-SPL-112-009 | AC2 | WB
def test_qa_spl_112_009_equipment_stock_effects(app, client, equipment, operation):
    event = equipment["event"]
    with Session(app.extensions["engine"]) as s:
        e = s.get(EventRequest, event)
        e.status = "confirmed"
        line = s.get(EquipmentRequirement, equipment["mapped"])
        line.required_start_date = line.required_end_date = e.proposed_date
        s.commit()
    req = request(
        client,
        event,
        equipment_base.proposal(equipment, operation, requirement_id=equipment["mapped"]),
    )
    result = save(client, event, req, choices(req))
    assert result.status_code == 200, result.json
    with Session(app.extensions["engine"]) as s:
        line = s.get(EquipmentRequirement, equipment["mapped"])
        assert line.status == ("review_required" if operation == "update" else "removed")
        assert _held_quantity(s, line.id) == 0
        assert s.scalar(select(EquipmentReservationRelease)).quantity == 2
        assert s.get(EventRequest, event).status == "planning"


# QA-SPL-112-010 | AC2 | BB
def test_qa_spl_112_010_stale_and_under_review(app, client, equipment):
    event = equipment["event"]
    req = request(client, event, item(), equipment_base.proposal(equipment))
    before = state(app)
    assert preview(client, event, req, choices(req)).status_code == 409
    assert state(app) == before
    assert save(client, event, req, choices(req, "declined", "Await planning")).status_code == 200
    req = request(client, event)
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).name = "Changed elsewhere"
        s.commit()
    before = state(app)
    assert preview(client, event, req, choices(req)).status_code == 409
    assert state(app) == before
    assert save(client, event, req, choices(req, "declined", "Stale proposal")).status_code == 200


# QA-SPL-112-011 | AC3 | BB
def test_qa_spl_112_011_partial_pending(app, client):
    event = base.make_event(app)
    req = request(client, event, item(), item("description", "Longer programme"))
    result = save(client, event, req, choices(req)[:1]).json["change_request"]
    assert result["status"] == "pending"
    assert [i["decision"] for i in result["items"]] == ["accepted", "pending"]


# QA-SPL-112-012 | AC3 | BB
def test_qa_spl_112_012_mixed_closes(app, client):
    event = base.make_event(app)
    req = request(client, event, item(), item("description", "Longer programme"))
    decisions = choices(req)[:1] + choices(req, "declined", "Keep description")[1:]
    result = save(client, event, req, decisions)
    assert result.json["change_request"]["status"] == "closed"
    assert result.json["event"]["name"] == "Revised gala"
    assert result.json["event"]["description"] == "An evening of music."


# QA-SPL-112-013 | AC3 | BB
def test_qa_spl_112_013_last_decision_closes(app, client):
    event = base.make_event(app)
    req = request(client, event, item(), item("description", "Longer programme"))
    assert save(client, event, req, choices(req)[:1]).json["change_request"]["status"] == "pending"
    assert save(client, event, req, choices(req)[1:]).json["change_request"]["status"] == "closed"


# QA-SPL-112-014 | AC3 | WB
def test_qa_spl_112_014_preview_is_read_only(app, client):
    event = base.make_event(app, "confirmed")
    req = request(client, event, item("expected_attendance", 200))
    before = state(app)
    assert preview(client, event, req, choices(req)).status_code == 200
    assert state(app) == before


# QA-SPL-112-015 | AC3 | WB
def test_qa_spl_112_015_rollback_after_effect(app, client, monkeypatch):
    event = base.make_event(app)
    req = request(client, event)
    before = state(app)

    def fail(*args):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(module, "_audit", fail)
    with pytest.raises(RuntimeError, match="injected"):
        save(client, event, req, choices(req))
    assert state(app) == before


# QA-SPL-112-016 | AC4 | BB
def test_qa_spl_112_016_identity(app, client):
    event = base.make_event(app)
    req = request(client, event)
    result = save(client, event, req, choices(req)).json["change_request"]["items"][0]
    assert result["decided_by"] == {"id": base.COORDINATOR, "display_name": "Casey Lim"}


# QA-SPL-112-017 | AC4 | BB
def test_qa_spl_112_017_time(app, client):
    event = base.make_event(app)
    req = request(client, event)
    before = datetime.now(timezone.utc)
    result = save(client, event, req, choices(req)).json["change_request"]["items"][0]
    assert before <= datetime.fromisoformat(result["decided_at"]) <= datetime.now(timezone.utc)


# QA-SPL-112-018 | AC4 | BB
def test_qa_spl_112_018_reload_preserves_audit(app, client):
    event = base.make_event(app)
    req = request(client, event, item(), item("description", "Longer programme"))
    result = save(client, event, req, choices(req, "declined", "Unsuitable")[:1]).json[
        "change_request"
    ]
    loaded = client.get(
        f"/api/event-requests/{event}/change-requests", headers=base.headers("coordinator")
    )
    assert loaded.status_code == 200
    assert loaded.json["change_requests"][0]["items"] == result["items"]


# QA-SPL-112-019 | AC4 | WB
def test_qa_spl_112_019_pending_has_no_audit(app, client):
    event = base.make_event(app)
    req = request(client, event, item(), item("description", "Longer programme"))
    save(client, event, req, choices(req)[:1])
    with Session(app.extensions["engine"]) as s:
        pending = s.get(EventChangeRequestItem, req["items"][1]["id"])
        assert pending.decision is pending.decided_at is pending.decided_by_account_id is None


# QA-SPL-112-020 | AC4 | BB
def test_qa_spl_112_020_cannot_spoof_audit(app, client):
    event = base.make_event(app)
    req = request(client, event)
    before = state(app)
    assert (
        preview(
            client, event, req, choices(req), decided_by_account_id=base.OTHER_COORDINATOR
        ).status_code
        == 400
    )
    assert state(app) == before


# QA-SPL-112-021 | AC5 | WB
def test_qa_spl_112_021_closed_immutable(app, client):
    event = base.make_event(app)
    req = request(client, event)
    assert save(client, event, req, choices(req)).status_code == 200
    before = state(app)
    assert preview(client, event, req, choices(req, "declined", "Changed mind")).status_code == 409
    assert state(app) == before


@pytest.mark.parametrize("status", ["cancelled", "completed"])
# QA-SPL-112-022 | AC5 | WB
def test_qa_spl_112_022_terminal_before_preview(app, client, status):
    event = base.make_event(app)
    req = request(client, event)
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).status = status
        s.commit()
    before = state(app)
    assert preview(client, event, req, choices(req)).status_code == 409
    assert state(app) == before


@pytest.mark.parametrize("status", ["cancelled", "completed"])
# QA-SPL-112-023 | AC5 | WB
def test_qa_spl_112_023_terminal_after_preview(app, client, status):
    event = base.make_event(app)
    req = request(client, event)
    check = preview(client, event, req, choices(req))
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).status = status
        s.commit()
    before = state(app)
    result = client.post(
        url(event, req),
        json={"decisions": choices(req), "preview_token": check.json["preview_token"]},
        headers=base.headers("coordinator"),
    )
    assert result.status_code == 409
    assert state(app) == before


# QA-SPL-112-024 | AC5 | WB
def test_qa_spl_112_024_saved_partial_immutable(app, client):
    event = base.make_event(app)
    req = request(client, event, item(), item("description", "Longer programme"))
    save(client, event, req, choices(req)[:1])
    before = state(app)
    assert preview(client, event, req, choices(req)).status_code == 409
    assert state(app) == before


# QA-SPL-112-025 | AC5 | WB
def test_qa_spl_112_025_reassignment_after_preview(app, client):
    event = base.make_event(app)
    req = request(client, event)
    check = preview(client, event, req, choices(req))
    with Session(app.extensions["engine"]) as s:
        s.scalar(select(EventCoordinatorAssignment)).coordinator_account_id = base.OTHER_COORDINATOR
        s.commit()
    before = state(app)
    result = client.post(
        url(event, req),
        json={"decisions": choices(req), "preview_token": check.json["preview_token"]},
        headers=base.headers("coordinator"),
    )
    assert result.status_code == 404
    assert state(app) == before


@pytest.mark.parametrize(
    "variant",
    [
        "empty",
        "not-list",
        "too-many",
        "not-object",
        "unknown-key",
        "bad-id",
        "bool-id",
        "duplicate",
        "bad-decision",
        "accept-reason",
    ],
)
# QA-SPL-112-026 | AC1 | BB
def test_qa_spl_112_026_payload_validation(app, client, variant):
    event = base.make_event(app)
    req = request(client, event)
    entry = choices(req)[0]
    invalid = {
        "empty": [],
        "not-list": {},
        "too-many": [entry] * 101,
        "not-object": [None],
        "unknown-key": [{**entry, "actor": "spoof"}],
        "bad-id": [{**entry, "item_id": 999}],
        "bool-id": [{**entry, "item_id": True}],
        "duplicate": [entry, entry],
        "bad-decision": [{**entry, "decision": "approved"}],
        "accept-reason": [{**entry, "decline_reason": "irrelevant"}],
    }[variant]
    before = state(app)
    assert preview(client, event, req, invalid).status_code == 400
    assert state(app) == before


# QA-SPL-112-027 | AC2 | WB
def test_qa_spl_112_027_stale_token_atomic(app, client):
    event = base.make_event(app)
    req = request(client, event)
    check = preview(client, event, req, choices(req))
    with Session(app.extensions["engine"]) as s:
        s.get(EventRequest, event).description = "Concurrent edit"
        s.commit()
    before = state(app)
    result = client.post(
        url(event, req),
        json={"decisions": choices(req), "preview_token": check.json["preview_token"]},
        headers=base.headers("coordinator"),
    )
    assert result.status_code == 409
    assert state(app) == before
    assert save(client, event, req, choices(req)).status_code == 200


@pytest.mark.parametrize("request_id", [999, 2**31])
# QA-SPL-112-028 | AC5 | BB
def test_qa_spl_112_028_missing_request(app, client, request_id):
    event = base.make_event(app)
    req = request(client, event)
    before = state(app)
    assert preview(client, event, {**req, "id": request_id}, choices(req)).status_code == 404
    assert state(app) == before


# QA-SPL-112-029 | AC2 | WB
def test_qa_spl_112_029_stale_equipment(app, client, equipment):
    event = equipment["event"]
    with Session(app.extensions["engine"]) as s:
        e = s.get(EventRequest, event)
        e.status = "planning"
        line = s.get(EquipmentRequirement, equipment["mapped"])
        line.required_start_date = line.required_end_date = e.proposed_date
        s.commit()
    req = request(client, event, equipment_base.proposal(equipment, "remove"))
    with Session(app.extensions["engine"]) as s:
        s.get(EquipmentRequirement, equipment["mapped"]).notes = "Changed externally"
        s.commit()
    before = state(app)
    assert preview(client, event, req, choices(req)).status_code == 409
    assert state(app) == before
    assert save(client, event, req, choices(req, "declined", "Stale")).status_code == 200


# QA-SPL-112-031 | AC2 | WB
def test_qa_spl_112_031_unchanged_values_do_not_reopen_event(app, client, equipment):
    event = equipment["event"]
    with Session(app.extensions["engine"]) as s:
        e = s.get(EventRequest, event)
        e.status = "confirmed"
        line = s.get(EquipmentRequirement, equipment["mapped"])
        line.required_start_date = line.required_end_date = e.proposed_date
        s.commit()
    req = request(
        client,
        event,
        item("name", "Harbour Lights Gala"),
        item("expected_attendance", 150),
        equipment_base.proposal(
            equipment, "update", requirement_id=equipment["mapped"], quantity=2, notes="HDMI"
        ),
    )
    check = preview(client, event, req, choices(req))
    assert check.status_code == 200, check.json
    assert check.json["returns_to_planning"] is False
    result = save(client, event, req, choices(req))
    assert result.status_code == 200
    assert result.json["event"]["status"] == "confirmed"
    with Session(app.extensions["engine"]) as s:
        assert s.scalar(select(EventDetailChange)) is None
        assert _held_quantity(s, equipment["mapped"]) == 2
