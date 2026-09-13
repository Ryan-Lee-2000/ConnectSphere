import pytest
from app import create_app
from app.models import Account, AccountRole, Base, Role
from sqlalchemy.orm import Session


@pytest.fixture
def client(tmp_path):
    identities = {
        "venue-user": "00000000-0000-0000-0000-000000000011",
        "coordinator-user": "00000000-0000-0000-0000-000000000012",
        "multi-role-user": "00000000-0000-0000-0000-000000000013",
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
                AccountRole(account_id=identities["venue-user"], role=Role.VENUE_STAFF.value),
                AccountRole(
                    account_id=identities["coordinator-user"], role=Role.EVENT_COORDINATOR.value
                ),
                AccountRole(
                    account_id=identities["multi-role-user"], role=Role.EVENT_COORDINATOR.value
                ),
                AccountRole(account_id=identities["multi-role-user"], role=Role.VENUE_STAFF.value),
            ]
        )
        session.commit()
    yield app.test_client()
    engine.dispose()


def venue_payload(**overrides):
    payload = {
        "name": "Harbour Hall",
        "location": "Level 3, Marina Centre",
        "description": "A flexible event space.",
        "facilities": ["Projector", "PA system"],
        "accessibility_features": ["Step-free access", "Accessible restroom"],
        "operating_slots": ["AM", "PM"],
        "setup_buffer_slots": 1,
        "turnaround_buffer_slots": 1,
    }
    payload.update(overrides)
    return payload


def request_headers(token="venue-user"):
    return {"Authorization": f"Bearer {token}"}


def create_venue(client):
    response = client.post("/api/venues", json=venue_payload(), headers=request_headers())
    assert response.status_code == 201
    return response.json["venue"]


def test_venue_staff_can_create_update_and_retrieve_a_venue(client):
    created = create_venue(client)
    assert created == {"id": 1, **venue_payload(), "layouts": []}

    updated = client.patch(
        "/api/venues/1",
        json={"name": "Harbour Grand Hall"},
        headers=request_headers(),
    )
    assert updated.status_code == 200
    assert updated.json["venue"]["name"] == "Harbour Grand Hall"
    assert updated.json["venue"]["setup_buffer_slots"] == venue_payload()["setup_buffer_slots"]
    assert updated.json["venue"]["location"] == venue_payload()["location"]

    retrieved = client.get("/api/venues/1", headers=request_headers())
    assert retrieved.status_code == 200
    assert retrieved.json["venue"] == updated.json["venue"]
    assert retrieved.json["capabilities"] == {"can_manage": True}


def test_zero_slot_buffers_are_accepted(client):
    response = client.post(
        "/api/venues",
        json=venue_payload(setup_buffer_slots=0, turnaround_buffer_slots=0),
        headers=request_headers(),
    )
    assert response.status_code == 201
    assert response.json["venue"]["setup_buffer_slots"] == 0
    assert response.json["venue"]["turnaround_buffer_slots"] == 0


def test_venue_staff_can_add_update_and_remove_layouts_for_selected_venue(client):
    venue = create_venue(client)
    created = client.post(
        f"/api/venues/{venue['id']}/layouts",
        json={"layout": "theatre", "capacity": 180},
        headers=request_headers(),
    )
    assert created.status_code == 201
    layout = created.json["layout"]

    updated = client.patch(
        f"/api/venues/{venue['id']}/layouts/{layout['id']}",
        json={"layout": "theatre", "capacity": 200},
        headers=request_headers(),
    )
    assert updated.status_code == 200
    assert updated.json == {"layout": {"id": layout["id"], "layout": "theatre", "capacity": 200}}

    stored = client.get(f"/api/venues/{venue['id']}", headers=request_headers())
    assert stored.json["venue"]["layouts"] == [updated.json["layout"]]

    removed = client.delete(
        f"/api/venues/{venue['id']}/layouts/{layout['id']}", headers=request_headers()
    )
    assert removed.status_code == 204
    stored = client.get(f"/api/venues/{venue['id']}", headers=request_headers())
    assert stored.json["venue"]["layouts"] == []


def test_save_venue_creates_and_replaces_its_complete_layout_list(client):
    created = client.post(
        "/api/venues",
        json=venue_payload(
            layouts=[
                {"layout": "theatre", "capacity": 180},
                {"layout": "classroom", "capacity": 120},
            ]
        ),
        headers=request_headers(),
    )
    assert created.status_code == 201
    created_layouts = [
        (layout["layout"], layout["capacity"]) for layout in created.json["venue"]["layouts"]
    ]
    assert created_layouts == [
        ("theatre", 180),
        ("classroom", 120),
    ]

    updated = client.patch(
        "/api/venues/1",
        json={"layouts": [{"layout": "banquet", "capacity": 96}]},
        headers=request_headers(),
    )
    assert updated.status_code == 200
    updated_layouts = [
        (layout["layout"], layout["capacity"]) for layout in updated.json["venue"]["layouts"]
    ]
    assert updated_layouts == [("banquet", 96)]


def test_venue_staff_can_record_a_custom_supported_room_layout(client):
    venue = create_venue(client)
    created = client.post(
        f"/api/venues/{venue['id']}/layouts",
        json={"layout": "Cabaret", "capacity": 90},
        headers=request_headers(),
    )
    assert created.status_code == 201
    assert created.json["layout"] == {"id": 1, "layout": "cabaret", "capacity": 90}


def test_save_venue_rejects_duplicate_layouts(client):
    response = client.post(
        "/api/venues",
        json=venue_payload(
            layouts=[
                {"layout": "theatre", "capacity": 180},
                {"layout": "theatre", "capacity": 120},
            ]
        ),
        headers=request_headers(),
    )
    assert response.status_code == 400
    assert response.json == {"error": "Room layouts must not contain duplicates."}


def test_coordinator_can_browse_list_and_details_but_cannot_change_catalogue(client):
    venue = create_venue(client)
    client.post(
        f"/api/venues/{venue['id']}/layouts",
        json={"layout": "classroom", "capacity": 80},
        headers=request_headers(),
    )

    catalogue = client.get("/api/venues", headers=request_headers("coordinator-user"))
    assert catalogue.status_code == 200
    assert catalogue.json == {
        "venues": [
            {
                "id": venue["id"],
                "name": "Harbour Hall",
                "location": "Level 3, Marina Centre",
            }
        ],
        "capabilities": {"can_manage": False},
    }
    detail = client.get(f"/api/venues/{venue['id']}", headers=request_headers("coordinator-user"))
    assert detail.status_code == 200
    assert detail.json["venue"]["layouts"] == [{"id": 1, "layout": "classroom", "capacity": 80}]

    for method, path, body in [
        ("patch", f"/api/venues/{venue['id']}", {"name": "Forged update"}),
        ("post", f"/api/venues/{venue['id']}/layouts", {"layout": "theatre", "capacity": 50}),
        ("delete", f"/api/venues/{venue['id']}/layouts/1", None),
    ]:
        response = getattr(client, method)(
            path, json=body, headers=request_headers("coordinator-user")
        )
        assert response.status_code == 403
    stored = client.get(f"/api/venues/{venue['id']}", headers=request_headers())
    assert stored.json["venue"]["name"] == "Harbour Hall"


@pytest.mark.parametrize(
    "payload,expected",
    [
        (venue_payload(name=" "), "Venue name is required."),
        (venue_payload(operating_slots=["AFTERNOON"]), "Unsupported operating slot: AFTERNOON."),
        (
            venue_payload(operating_slots=["AM", "AM"]),
            "Operating slots must not contain duplicates.",
        ),
        (venue_payload(operating_slots=[]), "Select at least one operating slot."),
        (
            venue_payload(setup_buffer_slots=-1),
            "Setup buffer must be a non-negative whole number of slots.",
        ),
        (
            venue_payload(turnaround_buffer_slots=1.5),
            "Turnaround buffer must be a non-negative whole number of slots.",
        ),
        (
            venue_payload(facilities=[" "]),
            "Facilities must be a list of non-empty text values.",
        ),
    ],
)
def test_invalid_venue_attributes_are_rejected(client, payload, expected):
    response = client.post("/api/venues", json=payload, headers=request_headers())
    assert response.status_code == 400
    assert response.json == {"error": expected}


@pytest.mark.parametrize(
    "payload,expected",
    [
        (
            {"layout": "other", "capacity": 20},
            "A custom room layout name is required when Other is selected.",
        ),
        ({"layout": "theatre", "capacity": 0}, "Capacity must be a positive whole number."),
        ({"layout": "theatre", "capacity": 22.5}, "Capacity must be a positive whole number."),
    ],
)
def test_invalid_layout_attributes_are_rejected(client, payload, expected):
    venue = create_venue(client)
    response = client.post(
        f"/api/venues/{venue['id']}/layouts", json=payload, headers=request_headers()
    )
    assert response.status_code == 400
    assert response.json == {"error": expected}


def test_duplicate_layout_is_rejected_for_the_same_selected_venue(client):
    venue = create_venue(client)
    client.post(
        f"/api/venues/{venue['id']}/layouts",
        json={"layout": "theatre", "capacity": 120},
        headers=request_headers(),
    )
    duplicate = client.post(
        f"/api/venues/{venue['id']}/layouts",
        json={"layout": "theatre", "capacity": 150},
        headers=request_headers(),
    )
    assert duplicate.status_code == 409
    assert duplicate.json == {"error": "This room layout is already recorded for the venue."}


def test_forged_role_is_not_accepted_and_unauthorized_access_is_denied(client):
    response = client.get("/api/venues", headers=request_headers("organiser"))
    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}
    forged = client.post(
        "/api/venues",
        json=venue_payload(role="venue_staff"),
        headers=request_headers("organiser"),
    )
    assert forged.status_code == 403
    assert client.get("/api/venues", headers=request_headers("venue-user")).json["venues"] == []


def test_missing_session_and_unknown_records_are_rejected(client):
    assert client.get("/api/venues").status_code == 401
    unknown_venue = client.patch(
        "/api/venues/999", json={"name": "Never"}, headers=request_headers()
    )
    assert unknown_venue.status_code == 404
    venue = create_venue(client)
    assert (
        client.patch(
            f"/api/venues/{venue['id']}/layouts/999",
            json={"layout": "theatre", "capacity": 100},
            headers=request_headers(),
        ).status_code
        == 404
    )


def test_multi_role_account_can_manage_the_catalogue(client):
    assert (
        client.post(
            "/api/venues", json=venue_payload(), headers=request_headers("multi-role-user")
        ).status_code
        == 201
    )
