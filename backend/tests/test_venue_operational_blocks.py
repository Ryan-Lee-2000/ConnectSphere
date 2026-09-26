from datetime import date, datetime

import pytest
from app import create_app
from app.models import Account, AccountRole, Base, Role, Venue
from app.venue_operational_blocks import operational_block_for_slot
from sqlalchemy.orm import Session

VENUE_STAFF_ID = "00000000-0000-0000-0000-000000000089"


@pytest.fixture
def operational_block_app(tmp_path):
    identities = {
        "venue-staff": VENUE_STAFF_ID,
        "coordinator": "00000000-0000-0000-0000-000000000090",
    }
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/test.db",
            "IDENTITY_VERIFIER": identities.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(Account(id=account_id) for account_id in identities.values())
        session.add_all(
            [
                AccountRole(account_id=VENUE_STAFF_ID, role=Role.VENUE_STAFF.value),
                AccountRole(
                    account_id=identities["coordinator"], role=Role.EVENT_COORDINATOR.value
                ),
                Venue(
                    name="Harbour Hall",
                    location="Marina Centre",
                    facilities=[],
                    accessibility_features=[],
                    operating_slots=["AM", "PM"],
                ),
            ]
        )
        session.commit()
    yield app
    engine.dispose()


@pytest.fixture
def client(operational_block_app):
    return operational_block_app.test_client()


def headers(token="venue-staff"):
    return {"Authorization": f"Bearer {token}"}


def test_tc_spl_89_01_venue_staff_records_an_active_operational_block(client):
    response = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-07",
            "slots": ["AM", "PM"],
            "reason": "Annual fire-safety inspection",
        },
        headers=headers(),
    )

    assert response.status_code == 201
    block = response.json["operational_block"]
    assert block["venue_id"] == 1
    assert block["start_date"] == "2026-10-05"
    assert block["end_date"] == "2026-10-07"
    assert block["slots"] == ["AM", "PM"]
    assert block["reason"] == "Annual fire-safety inspection"
    assert block["created_by_account_id"] == VENUE_STAFF_ID
    assert datetime.fromisoformat(block["created_at"]).tzinfo is not None
    assert block["removed_by_account_id"] is None
    assert block["removed_at"] is None

    listed = client.get("/api/venues/1/operational-blocks", headers=headers())
    assert listed.status_code == 200
    assert listed.json == {"operational_blocks": [block]}


def test_tc_spl_89_02_venue_staff_removes_only_the_selected_block_with_audit(client):
    first = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "Inspection",
        },
        headers=headers(),
    ).json["operational_block"]
    second = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-06",
            "end_date": "2026-10-06",
            "slots": ["PM"],
            "reason": "Maintenance",
        },
        headers=headers(),
    ).json["operational_block"]

    removed_response = client.delete(
        f"/api/venues/1/operational-blocks/{first['id']}", headers=headers()
    )

    assert removed_response.status_code == 200
    removed = removed_response.json["operational_block"]
    assert removed["id"] == first["id"]
    assert removed["removed_by_account_id"] == VENUE_STAFF_ID
    assert datetime.fromisoformat(removed["removed_at"]).tzinfo is not None

    active = client.get("/api/venues/1/operational-blocks", headers=headers())
    assert active.json == {"operational_blocks": [second]}


def test_tc_spl_89_03_invalid_or_unauthorised_attempts_leave_no_block(client):
    invalid_payloads = [
        {
            "start_date": "2026-10-07",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "Invalid date order",
        },
        {
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "   ",
        },
        {
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["NIGHT"],
            "reason": "Venue does not operate at night",
        },
    ]
    for payload in invalid_payloads:
        response = client.post("/api/venues/1/operational-blocks", json=payload, headers=headers())
        assert response.status_code == 400

    unauthorised = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "slots": ["AM"],
            "reason": "Forged block",
        },
        headers=headers("coordinator"),
    )
    assert unauthorised.status_code == 403

    active = client.get("/api/venues/1/operational-blocks", headers=headers())
    assert active.json == {"operational_blocks": []}


def test_tc_spl_89_04_active_blocks_feed_shared_availability_for_the_inclusive_range(
    client, operational_block_app
):
    created = client.post(
        "/api/venues/1/operational-blocks",
        json={
            "start_date": "2026-10-05",
            "end_date": "2026-10-07",
            "slots": ["AM"],
            "reason": "Inspection",
        },
        headers=headers(),
    ).json["operational_block"]

    engine = operational_block_app.extensions["engine"]
    with Session(engine) as session:
        for blocked_day in (date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)):
            assert operational_block_for_slot(session, 1, blocked_day, "AM").id == created["id"]
        assert operational_block_for_slot(session, 1, date(2026, 10, 8), "AM") is None
        assert operational_block_for_slot(session, 1, date(2026, 10, 6), "PM") is None

    client.delete(f"/api/venues/1/operational-blocks/{created['id']}", headers=headers())
    with Session(engine) as session:
        assert operational_block_for_slot(session, 1, date(2026, 10, 6), "AM") is None
