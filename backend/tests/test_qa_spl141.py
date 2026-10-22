"""SPL-141 equipment proposals; API contract and transaction checks."""

import pytest
import test_event_change_requests as base
from app.models import EquipmentRequirement, EquipmentReservation, EquipmentType, EventRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

app = base.app
client = base.client


@pytest.fixture
def equipment(app):
    event = base.make_event(app)
    foreign = base.make_event(app, organiser_account_id=base.COLLEAGUE)
    with Session(app.extensions["engine"]) as session:
        kind = EquipmentType(name="Projector", normalised_name="projector", total_stock=20)
        session.add(kind)
        session.flush()
        lines = [
            EquipmentRequirement(
                event_request_id=event,
                equipment_type="Projector",
                equipment_type_id=kind.id,
                quantity=2,
                notes="HDMI",
                status="reserved",
            ),
            EquipmentRequirement(
                event_request_id=event,
                equipment_type="Custom microphone",
                quantity=3,
                notes="Wireless",
            ),
            EquipmentRequirement(event_request_id=foreign, equipment_type="Foreign", quantity=1),
            EquipmentRequirement(
                event_request_id=event, equipment_type="Removed", quantity=1, status="removed"
            ),
        ]
        session.add_all(lines)
        session.flush()
        session.add(
            EquipmentReservation(
                event_request_id=event,
                equipment_requirement_id=lines[0].id,
                equipment_type_id=kind.id,
                quantity=2,
                commitment_start_date=base.NOW.date(),
                commitment_end_date=base.NOW.date(),
                reserved_by_account_id=base.COORDINATOR,
                reserved_at=base.NOW,
            )
        )
        ids = dict(
            event=event,
            foreign=foreign,
            kind=kind.id,
            mapped=lines[0].id,
            unmapped=lines[1].id,
            other=lines[2].id,
            removed=lines[3].id,
        )
        session.commit()
    return ids


def proposal(ids, operation="add", **changes):
    value = {"operation": operation}
    if operation == "add":
        value.update(equipment_type_id=ids["kind"], quantity=4, notes="New screen")
    elif operation == "update":
        value.update(requirement_id=ids["unmapped"], quantity=5, notes="Updated notes")
    else:
        value.update(requirement_id=ids["mapped"])
    value.update(changes)
    return dict(field="equipment", requested_value=value, reason="Updated technical needs")


def send(client, ids, *items, token="organiser"):
    return base.submit(client, ids["event"], list(items), token=token)


def options(client, ids, token="organiser"):
    return client.get(
        f"/api/event-requests/{ids['event']}/change-requests/equipment-options",
        headers=base.headers(token),
    )


def arrangements(app):
    with Session(app.extensions["engine"]) as session:
        return [
            [
                {column.name: getattr(row, column.name) for column in model.__table__.columns}
                for row in session.scalars(select(model).order_by(model.id))
            ]
            for model in (EquipmentRequirement, EquipmentReservation)
        ]


# QA-SPL-141-001 | AC1 | BB
@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_qa_spl_141_001_each_action(client, equipment, operation):
    result = send(client, equipment, proposal(equipment, operation))
    assert result.status_code == 201
    assert result.json["change_request"]["items"][0]["requested_value"]["operation"] == operation


# QA-SPL-141-002 | AC1 | BB
def test_qa_spl_141_002_mix_event_and_equipment(client, equipment):
    result = send(
        client,
        equipment,
        proposal(equipment),
        proposal(equipment, "update"),
        proposal(equipment, "remove"),
        base.ITEM,
    )
    assert result.status_code == 201
    assert len(result.json["change_request"]["items"]) == 4


# QA-SPL-141-003 | AC1 | BB
def test_qa_spl_141_003_notes_only_unmapped(client, equipment):
    result = send(client, equipment, proposal(equipment, "update", quantity=3, notes="New note"))
    assert result.status_code == 201
    value = result.json["change_request"]["items"][0]["requested_value"]
    assert value["equipment_type_id"] is None
    assert value["quantity"] == 3 and value["notes"] == "New note"


# QA-SPL-141-004 | AC1 | BB
def test_qa_spl_141_004_multiple_additions(client, equipment):
    result = send(client, equipment, proposal(equipment), proposal(equipment, quantity=1))
    assert result.status_code == 201
    assert len({item["field"] for item in result.json["change_request"]["items"]}) == 2


# QA-SPL-141-005 | AC1 | BB
def test_qa_spl_141_005_options_filter_lines(client, equipment):
    response = options(client, equipment)
    assert response.status_code == 200
    assert {line["requirement_id"] for line in response.json["equipment_requirements"]} == {
        equipment["mapped"],
        equipment["unmapped"],
    }
    assert response.json["equipment_types"] == [{"id": equipment["kind"], "name": "Projector"}]


# QA-SPL-141-006 | AC2 | BB
def test_qa_spl_141_006_add_snapshot(client, equipment):
    item = send(client, equipment, proposal(equipment)).json["change_request"]["items"][0]
    assert item["current_value"] is None
    assert item["requested_value"] == {
        "operation": "add",
        "equipment_type_id": equipment["kind"],
        "equipment_type": "Projector",
        "quantity": 4,
        "notes": "New screen",
    }


# QA-SPL-141-007 | AC2 | BB
def test_qa_spl_141_007_update_snapshot(client, equipment):
    item = send(client, equipment, proposal(equipment, "update")).json["change_request"]["items"][0]
    assert item["current_value"] == {
        "requirement_id": equipment["unmapped"],
        "equipment_type_id": None,
        "equipment_type": "Custom microphone",
        "quantity": 3,
        "notes": "Wireless",
    }
    assert item["requested_value"] == {
        **item["current_value"],
        "operation": "update",
        "quantity": 5,
        "notes": "Updated notes",
    }


# QA-SPL-141-008 | AC2 | BB
def test_qa_spl_141_008_remove_snapshot(client, equipment):
    item = send(client, equipment, proposal(equipment, "remove")).json["change_request"]["items"][0]
    assert item["current_value"]["quantity"] == 2
    assert item["current_value"]["notes"] == "HDMI"
    assert item["requested_value"] == {"operation": "remove", "requirement_id": equipment["mapped"]}


# QA-SPL-141-009 | AC2 | WB
def test_qa_spl_141_009_snapshot_survives_later_edit(app, client, equipment):
    send(client, equipment, proposal(equipment, "update"))
    with Session(app.extensions["engine"]) as session:
        session.get(EquipmentRequirement, equipment["unmapped"]).quantity = 9
        session.commit()
    item = base.read(client, equipment["event"]).json["change_requests"][0]["items"][0]
    assert item["current_value"]["quantity"] == 3


# QA-SPL-141-010 | AC2 | BB
def test_qa_spl_141_010_assigned_reader(client, equipment):
    send(client, equipment, proposal(equipment))
    assert (
        base.read(client, equipment["event"], "coordinator").json["change_requests"][0]["items"][0][
            "requested_value"
        ]["quantity"]
        == 4
    )
    assert base.read(client, equipment["event"], "other-coordinator").status_code == 404


# QA-SPL-141-011 | AC3 | BB
@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "2", None, 2147483648])
def test_qa_spl_141_011_invalid_quantity(app, client, equipment, quantity):
    response = send(client, equipment, proposal(equipment, quantity=quantity))
    assert response.status_code == 400 and "positive whole number" in response.json["error"]
    assert base.stored(app) == (0, 0)


# QA-SPL-141-012 | AC3 | BB
def test_qa_spl_141_012_unknown_type_atomic(app, client, equipment):
    response = send(client, equipment, base.ITEM, proposal(equipment, equipment_type_id=99999))
    assert response.status_code == 400 and "catalogue" in response.json["error"]
    assert base.stored(app) == (0, 0)


# QA-SPL-141-013 | AC3 | BB
def test_qa_spl_141_013_empty(app, client, equipment):
    response = send(client, equipment)
    assert response.status_code == 400 and "at least one" in response.json["error"]
    assert base.stored(app) == (0, 0)


# QA-SPL-141-014 | AC3 | BB
@pytest.mark.parametrize("quantity", [1, 2147483647])
def test_qa_spl_141_014_quantity_bounds(client, equipment, quantity):
    assert send(client, equipment, proposal(equipment, quantity=quantity)).status_code == 201


# QA-SPL-141-015 | AC3 | BB
@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"operation": "bogus"},
        {"operation": "add", "equipment_type_id": True, "quantity": 1, "notes": None},
        {
            "operation": "add",
            "equipment_type_id": 1,
            "quantity": 1,
            "notes": [],
        },
        {"operation": "add", "equipment_type_id": 1, "quantity": 1, "notes": "x" * 2001},
        {"operation": "remove", "requirement_id": 1, "extra": 1},
    ],
)
def test_qa_spl_141_015_malformed_atomic(app, client, equipment, value):
    assert (
        send(
            client, equipment, dict(field="equipment", requested_value=value, reason="Reason")
        ).status_code
        == 400
    )
    assert base.stored(app) == (0, 0)


# QA-SPL-141-016 | AC4 | BB
@pytest.mark.parametrize(
    "token,expected", [("colleague", 404), ("coordinator", 403), ("attendee", 403), (None, 401)]
)
def test_qa_spl_141_016_only_owner(app, client, equipment, token, expected):
    assert send(client, equipment, proposal(equipment), token=token).status_code == expected
    assert options(client, equipment, token).status_code == expected
    assert base.stored(app) == (0, 0)


# QA-SPL-141-017 | AC4 | BB
@pytest.mark.parametrize(
    "status,expected", [("draft", 404), ("cancelled", 409), ("completed", 409)]
)
def test_qa_spl_141_017_closed_events(app, client, equipment, status, expected):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, equipment["event"]).status = status
        session.commit()
    assert send(client, equipment, proposal(equipment)).status_code == expected
    assert options(client, equipment).status_code == expected
    assert base.stored(app) == (0, 0)


# QA-SPL-141-018 | AC4 | BB
@pytest.mark.parametrize("status", ["under_review", "planning", "confirmed"])
def test_qa_spl_141_018_allowed_status(app, client, equipment, status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, equipment["event"]).status = status
        session.commit()
    assert send(client, equipment, proposal(equipment)).status_code == 201


# QA-SPL-141-019 | AC4 | BB
@pytest.mark.parametrize("target", ["other", "removed"])
def test_qa_spl_141_019_invalid_line(app, client, equipment, target):
    assert (
        send(
            client, equipment, proposal(equipment, "remove", requirement_id=equipment[target])
        ).status_code
        == 400
    )
    assert base.stored(app) == (0, 0)


# QA-SPL-141-020 | AC4 | WB
def test_qa_spl_141_020_other_organisation(app, client, equipment):
    from app.models import Organisation

    with Session(app.extensions["engine"]) as session:
        org = Organisation(name="Other client")
        session.add(org)
        session.flush()
        event = session.get(EventRequest, equipment["event"])
        event.organiser_account_id = base.COLLEAGUE
        event.organisation_id = org.id
        session.commit()
    assert send(client, equipment, proposal(equipment)).status_code == 404
    assert options(client, equipment).status_code == 404
    assert base.stored(app) == (0, 0)


# QA-SPL-141-021 | AC5 | WB
@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_qa_spl_141_021_arrangements_unchanged(app, client, equipment, operation):
    before = arrangements(app)
    assert send(client, equipment, proposal(equipment, operation)).status_code == 201
    assert arrangements(app) == before


# QA-SPL-141-022 | AC5 | WB
def test_qa_spl_141_022_failed_mixed_request_unchanged(app, client, equipment):
    before = arrangements(app)
    assert (
        send(
            client, equipment, proposal(equipment, "remove"), proposal(equipment, quantity=0)
        ).status_code
        == 400
    )
    assert arrangements(app) == before and base.stored(app) == (0, 0)


# QA-SPL-141-023 | AC5 | WB
def test_qa_spl_141_023_notification_failure_rolls_back(app, client, equipment, monkeypatch):
    before = arrangements(app)

    def fail(*args, **kwargs):
        raise RuntimeError("Injected notification failure")

    monkeypatch.setattr("app.event_change_requests.add_change_request_submitted_notice", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        send(client, equipment, proposal(equipment))
    assert base.stored(app) == (0, 0) and arrangements(app) == before


# QA-SPL-141-024 | AC5 | WB
def test_qa_spl_141_024_retry_pending_no_duplicate(app, client, equipment):
    before = arrangements(app)
    assert send(client, equipment, proposal(equipment)).status_code == 201
    assert send(client, equipment, proposal(equipment)).status_code == 409
    assert base.stored(app) == (1, 1) and arrangements(app) == before


# QA-SPL-141-025 | AC5 | WB
def test_qa_spl_141_025_duplicate_line_no_writes(app, client, equipment):
    before = arrangements(app)
    assert (
        send(
            client,
            equipment,
            proposal(equipment, "update"),
            proposal(equipment, "remove", requirement_id=equipment["unmapped"]),
        ).status_code
        == 400
    )
    assert base.stored(app) == (0, 0) and arrangements(app) == before


# QA-SPL-141-028 | AC3 | BB
@pytest.mark.parametrize("count,expected", [(100, 201), (101, 400)])
def test_qa_spl_141_028_item_limit(app, client, equipment, count, expected):
    assert (
        send(
            client,
            equipment,
            *[{**proposal(equipment, notes=None), "reason": "R"} for _ in range(count)],
        ).status_code
        == expected
    )
    assert base.stored(app) == ((1, count) if expected == 201 else (0, 0))


# QA-SPL-141-029 | AC3 | WB
def test_qa_spl_141_029_body_limit_atomic(app, client, equipment):
    assert send(client, equipment, *[proposal(equipment) for _ in range(100)]).status_code == 413
    assert base.stored(app) == (0, 0)
