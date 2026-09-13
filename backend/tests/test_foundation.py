"""Infrastructure contracts without product-domain fixtures."""

import httpx
import pytest
from app import create_app
from app.models import Base


@pytest.fixture
def client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/test.db",
            "SUPABASE_URL": "http://localhost:54321",
            "SUPABASE_PUBLISHABLE_KEY": "fixture-key",
        }
    )
    Base.metadata.create_all(app.extensions["engine"])
    yield app.test_client()
    app.extensions["engine"].dispose()


def test_health_checks_database(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"


def test_health_reports_database_outage(client, monkeypatch):
    def unavailable():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(client.application.extensions["engine"], "connect", unavailable)
    assert client.get("/api/health").status_code == 503


@pytest.mark.parametrize("authorization", ["", "Basic abc", "Bearer "])
def test_identity_requires_bearer_token(client, authorization):
    assert client.get("/api/session", headers={"Authorization": authorization}).status_code == 401


def test_identity_comes_from_auth_service(client, monkeypatch):
    def validate(url, headers, timeout):
        assert url == "http://localhost:54321/auth/v1/user"
        assert headers["Authorization"] == "Bearer fixture-token"
        return httpx.Response(200, json={"id": "verified-user"})

    monkeypatch.setattr(httpx, "get", validate)
    response = client.get(
        "/api/session?user_id=spoofed", headers={"Authorization": "Bearer fixture-token"}
    )
    assert response.status_code == 200
    assert response.json == {"user_id": "verified-user"}


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, {}, 401),
        (403, {}, 401),
        (500, {}, 503),
        (200, {}, 401),
    ],
)
def test_rejected_or_missing_identity_fails_closed(client, monkeypatch, status, body, expected):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(status, json=body))
    assert (
        client.get("/api/session", headers={"Authorization": "Bearer fixture"}).status_code
        == expected
    )


def test_auth_outage_fails_closed(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", unavailable)
    assert (
        client.get("/api/session", headers={"Authorization": "Bearer fixture"}).status_code == 503
    )


def test_infrastructure_routes_remain_available(client):
    assert {
        "/",
        "/<path:path>",
        "/api/health",
        "/api/session",
        "/api/account/roles",
    } <= {rule.rule for rule in client.application.url_map.iter_rules()}
