"""Real PostgreSQL serialization and rollback for equipment proposals."""

import pytest
import test_event_change_requests_postgres as base
from app.models import EquipmentRequirement, EquipmentType
from sqlalchemy.orm import Session
from test_exact_venue_bookings_postgres import ordered_race

pytestmark = base.pytestmark
pg_url = base.pg_url
scenario = base.scenario


def equipment_item(engine, event):
    with Session(engine) as session:
        kind = EquipmentType(name="QA projector", normalised_name="qa projector", total_stock=10)
        session.add(kind)
        session.flush()
        line = EquipmentRequirement(
            event_request_id=event, equipment_type=kind.name, equipment_type_id=kind.id, quantity=2
        )
        session.add(line)
        session.commit()
        return line.id, {
            "field": "equipment",
            "requested_value": {
                "operation": "update",
                "requirement_id": line.id,
                "quantity": 4,
                "notes": "HDMI",
            },
            "reason": "More screens",
        }


# QA-SPL-141-026 | AC5 | WB
def test_qa_spl_141_026_concurrent_proposals_save_one(scenario):
    app, engine, event, _ = scenario
    line, item = equipment_item(engine, event)
    first, second = ordered_race(
        app, base._submit_call(event, item), base._submit_call(event, item)
    )
    assert first[0] == 201 and second[0] == 409
    assert base._counts(engine) == (1, 1)
    with Session(engine) as session:
        assert session.get(EquipmentRequirement, line).quantity == 2


# QA-SPL-141-027 | AC5 | WB
def test_qa_spl_141_027_notification_failure_rolls_back(scenario, monkeypatch):
    app, engine, event, _ = scenario
    line, item = equipment_item(engine, event)

    def fail(*args, **kwargs):
        raise RuntimeError("Injected notification failure")

    monkeypatch.setattr("app.event_change_requests.add_change_request_submitted_notice", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        base._submit_call(event, item)(app.test_client())
    assert base._counts(engine) == (0, 0)
    with Session(engine) as session:
        assert session.get(EquipmentRequirement, line).quantity == 2
