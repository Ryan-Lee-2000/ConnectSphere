"""Acceptance coverage for CS-E01-S2's reusable authorization boundary."""

import pytest
from app import create_app
from app.authorization import require_roles
from app.models import Account, AccountRole, Base, Role
from flask import jsonify
from sqlalchemy.orm import Session

ORGANISER_ID = "00000000-0000-0000-0000-000000000001"
ATTENDEE_ID = "00000000-0000-0000-0000-000000000002"
MULTI_ROLE_ID = "00000000-0000-0000-0000-000000000003"
NO_ROLE_ID = "00000000-0000-0000-0000-000000000004"


@pytest.fixture
def authorization_client(tmp_path):
    identities = {
        "organiser-token": ORGANISER_ID,
        "attendee-token": ATTENDEE_ID,
        "multi-token": MULTI_ROLE_ID,
        "no-role-token": NO_ROLE_ID,
    }
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/authorization.db",
            "IDENTITY_VERIFIER": identities.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(Account(id=account_id) for account_id in identities.values())
        session.add_all(
            [
                AccountRole(account_id=ORGANISER_ID, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=ATTENDEE_ID, role=Role.ATTENDEE.value),
                AccountRole(account_id=MULTI_ROLE_ID, role=Role.ATTENDEE.value),
                AccountRole(account_id=MULTI_ROLE_ID, role=Role.TECHNICAL_SUPPORT_STAFF.value),
            ]
        )
        session.commit()

    executions = {"organiser": 0, "unruled": 0}

    @app.post("/api/test/organiser")
    @require_roles(Role.EVENT_ORGANISER)
    def organiser_operation():
        executions["organiser"] += 1
        return jsonify(result="protected organiser result")

    @app.post("/api/test/attendee-or-technical")
    @require_roles(Role.ATTENDEE, Role.TECHNICAL_SUPPORT_STAFF)
    def attendee_or_technical_operation():
        return jsonify(result="protected multi-role result")

    @app.post("/api/test/unruled")
    def operation_without_a_policy():
        executions["unruled"] += 1
        return jsonify(result="must never be returned")

    yield app.test_client(), executions
    engine.dispose()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_tc_cs_e01_s2_01_current_account_reads_only_server_owned_roles(authorization_client):
    client, _ = authorization_client

    response = client.get(
        f"/api/account/roles?account_id={ORGANISER_ID}&role=event_operations_manager",
        headers={**bearer("multi-token"), "X-Account-Role": "event_operations_manager"},
    )

    assert response.status_code == 200
    assert response.json == {"roles": ["attendee", "technical_support_staff"]}


def test_tc_cs_e01_s2_02_permitted_role_allows_the_operation(authorization_client):
    client, executions = authorization_client

    response = client.post("/api/test/organiser", headers=bearer("organiser-token"))

    assert response.status_code == 200
    assert response.json == {"result": "protected organiser result"}
    assert executions["organiser"] == 1


def test_tc_cs_e01_s2_03_prohibited_role_refuses_without_side_effects(authorization_client):
    client, executions = authorization_client

    response = client.post("/api/test/organiser", headers=bearer("attendee-token"))

    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}
    assert executions["organiser"] == 0


def test_tc_cs_e01_s2_04_any_permitted_role_allows_multi_role_account(authorization_client):
    client, _ = authorization_client

    response = client.post("/api/test/attendee-or-technical", headers=bearer("multi-token"))

    assert response.status_code == 200
    assert response.json == {"result": "protected multi-role result"}


def test_tc_cs_e01_s2_05_submitted_claim_cannot_forge_authorization(authorization_client):
    client, executions = authorization_client

    response = client.post(
        f"/api/test/organiser?account_id={ORGANISER_ID}&role=event_organiser",
        headers={**bearer("attendee-token"), "X-Account-Role": "event_organiser"},
        json={"account_id": ORGANISER_ID, "role": "event_organiser"},
    )

    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}
    assert executions["organiser"] == 0


def test_tc_cs_e01_s2_03_account_without_roles_is_refused(authorization_client):
    client, executions = authorization_client

    response = client.post("/api/test/organiser", headers=bearer("no-role-token"))

    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}
    assert executions["organiser"] == 0


def test_tc_cs_e01_s2_06_operation_without_rule_is_refused_by_default(authorization_client):
    client, executions = authorization_client

    response = client.post("/api/test/unruled", headers=bearer("organiser-token"))

    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}
    assert executions["unruled"] == 0


def test_role_protected_operation_must_declare_at_least_one_role():
    with pytest.raises(ValueError, match="at least one role"):
        require_roles()
