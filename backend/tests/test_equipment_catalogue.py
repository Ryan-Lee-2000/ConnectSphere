import pytest
from app import create_app
from app.models import Account, AccountRole, Base, Role
from sqlalchemy.orm import Session


@pytest.fixture
def client(tmp_path):
    identities = {
        "technical": "00000000-0000-0000-0000-000000000941",
        "organiser": "00000000-0000-0000-0000-000000000942",
        "coordinator": "00000000-0000-0000-0000-000000000943",
        "outsider": "00000000-0000-0000-0000-000000000944",
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
                AccountRole(
                    account_id=identities["technical"], role=Role.TECHNICAL_SUPPORT_STAFF.value
                ),
                AccountRole(account_id=identities["organiser"], role=Role.EVENT_ORGANISER.value),
                AccountRole(
                    account_id=identities["coordinator"], role=Role.EVENT_COORDINATOR.value
                ),
                AccountRole(account_id=identities["outsider"], role=Role.ATTENDEE.value),
            ]
        )
        session.commit()
    yield app.test_client()
    engine.dispose()


def headers(identity="technical"):
    return {"Authorization": f"Bearer {identity}"}


def payload(**overrides):
    result = {
        "name": "Wireless Microphone",
        "description": "Handheld wireless microphone with receiver.",
        "location": "Technical Store A",
        "total_stock": 12,
    }
    result.update(overrides)
    return result


# SPL-94 AC-1 / TC-SPL-94-001: Technical Support can add a complete pooled catalogue type.
def test_tc_spl_94_001_technical_support_can_create_and_edit_equipment_types(client):
    created = client.post("/api/equipment-types", json=payload(), headers=headers())

    assert created.status_code == 201
    assert created.json["equipment_type"] == {
        "id": 1,
        "name": "Wireless Microphone",
        "description": "Handheld wireless microphone with receiver.",
        "location": "Technical Store A",
        "total_stock": 12,
    }

    updated = client.patch(
        "/api/equipment-types/1",
        json={"location": "Technical Store B", "total_stock": 16},
        headers=headers(),
    )
    assert updated.status_code == 200
    assert updated.json["equipment_type"]["location"] == "Technical Store B"
    assert updated.json["equipment_type"]["total_stock"] == 16


# SPL-94 AC-1 / TC-SPL-94-002: trim/case uniqueness protects a single inventory pool.
def test_tc_spl_94_002_duplicate_name_is_refused_case_insensitively(client):
    assert client.post("/api/equipment-types", json=payload(), headers=headers()).status_code == 201

    duplicate = client.post(
        "/api/equipment-types",
        json=payload(name="  wireless microphone  "),
        headers=headers(),
    )
    assert duplicate.status_code == 409
    assert duplicate.json["error"] == "An equipment type with this name already exists."


# SPL-94 AC-1 / TC-SPL-94-003: invalid inventory values do not create a record.
@pytest.mark.parametrize("stock", [-1, 1.5, True, "12"])
def test_tc_spl_94_003_invalid_stock_is_refused(client, stock):
    response = client.post(
        "/api/equipment-types", json=payload(total_stock=stock), headers=headers()
    )
    assert response.status_code == 400
    assert response.json["error"] == "Total stock must be a whole number of zero or more."


# SPL-94 AC-1 / TC-SPL-94-003b: zero is the inclusive lower stock boundary.
def test_tc_spl_94_003b_zero_stock_is_accepted(client):
    response = client.post("/api/equipment-types", json=payload(total_stock=0), headers=headers())
    assert response.status_code == 201
    assert response.json["equipment_type"]["total_stock"] == 0


# SPL-94 AC-2 / TC-SPL-94-004: organiser and coordinator receive the same saved catalogue choices.
@pytest.mark.parametrize("identity", ["organiser", "coordinator"])
def test_tc_spl_94_004_catalogue_is_selectable_by_organiser_and_coordinator(client, identity):
    assert client.post("/api/equipment-types", json=payload(), headers=headers()).status_code == 201
    response = client.get("/api/equipment-types", headers=headers(identity))
    assert response.status_code == 200
    assert response.json["equipment_types"] == [
        {
            "id": 1,
            "name": "Wireless Microphone",
            "description": "Handheld wireless microphone with receiver.",
            "location": "Technical Store A",
            "total_stock": 12,
        }
    ]


# SPL-94 AC-3 / TC-SPL-94-005: only Technical Support can mutate catalogue records.
@pytest.mark.parametrize("identity", ["organiser", "coordinator", "outsider"])
def test_tc_spl_94_005_non_technical_roles_cannot_create_or_edit_equipment_types(client, identity):
    assert client.post("/api/equipment-types", json=payload(), headers=headers()).status_code == 201
    assert (
        client.post(
            "/api/equipment-types", json=payload(name="Projector"), headers=headers(identity)
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/api/equipment-types/1", json={"total_stock": 10}, headers=headers(identity)
        ).status_code
        == 403
    )


# SPL-94 AC-3 / TC-SPL-94-005b: catalogue reads are not public.
@pytest.mark.parametrize("request_headers, status", [({}, 401), (headers("outsider"), 403)])
def test_tc_spl_94_005b_catalogue_reads_require_an_authorised_workflow_role(
    client, request_headers, status
):
    assert client.get("/api/equipment-types", headers=request_headers).status_code == status


# SPL-94 AC-4 / TC-SPL-94-006: no reservation/unavailability commitment exists yet, so a valid
# reduction is retained. SPL-95/96/97 extend the shared availability guard with active commitments.
def test_tc_spl_94_006_valid_stock_reduction_is_persisted(client):
    assert (
        client.post(
            "/api/equipment-types", json=payload(total_stock=12), headers=headers()
        ).status_code
        == 201
    )
    response = client.patch("/api/equipment-types/1", json={"total_stock": 3}, headers=headers())
    assert response.status_code == 200
    assert response.json["equipment_type"]["total_stock"] == 3


def test_tc_spl_94_007_missing_or_unknown_equipment_types_are_refused(client):
    assert (
        client.patch(
            "/api/equipment-types/999", json={"total_stock": 1}, headers=headers()
        ).status_code
        == 404
    )
    response = client.post(
        "/api/equipment-types", json={"name": "   ", "total_stock": 1}, headers=headers()
    )
    assert response.status_code == 400
    assert response.json["error"] == "Equipment type name is required."
