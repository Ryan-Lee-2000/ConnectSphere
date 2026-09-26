from datetime import date, datetime, timedelta, timezone

import pytest
from app import create_app
from app.models import (
    Account,
    AccountRole,
    Base,
    EventRequest,
    Organisation,
    Role,
    Venue,
    VenueOperationalBlock,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ORGANISER_ONE = "00000000-0000-0000-0000-000000000021"
ORGANISER_TWO = "00000000-0000-0000-0000-000000000022"
COORDINATOR = "00000000-0000-0000-0000-000000000023"
ATTENDEE = "00000000-0000-0000-0000-000000000024"


@pytest.fixture
def event_app(tmp_path):
    identities = {
        "organiser-one": ORGANISER_ONE,
        "organiser-two": ORGANISER_TWO,
        "coordinator": COORDINATOR,
        "attendee": ATTENDEE,
    }
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/events.db",
            "IDENTITY_VERIFIER": identities.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Community Partners")
        session.add(organisation)
        session.flush()
        session.add_all(
            Account(
                id=account_id,
                display_name=f"Test account {index}",
                organisation_id=(
                    organisation.id if account_id in {ORGANISER_ONE, ORGANISER_TWO} else None
                ),
            )
            for index, account_id in enumerate(identities.values(), start=1)
        )
        session.add_all(
            [
                AccountRole(account_id=ORGANISER_ONE, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=ORGANISER_TWO, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=COORDINATOR, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=ATTENDEE, role=Role.ATTENDEE.value),
            ]
        )
        session.commit()
    yield app
    engine.dispose()


@pytest.fixture
def client(event_app):
    return event_app.test_client()


def headers(identity="organiser-one"):
    return {"Authorization": f"Bearer {identity}"}


def event_payload(**overrides):
    payload = {
        "name": "Community Technology Forum",
        "purpose": "Connect residents with local technology partners",
        "description": "A half-day forum.",
        "proposed_date": (date.today() + timedelta(days=7)).isoformat(),
        "start_time": "11:00",
        "end_time": "14:00",
        "expected_attendance": 120,
        "preferred_room_layout": "Theatre",
        "required_facilities": ["Projector", "Step-free access"],
        "facilities_notes": "Two wireless microphones",
        "accessibility_needs": ["Reserved wheelchair spaces"],
        "location_preference": "Central",
        "venue_notes": "Near public transport",
        "registration_required": True,
        "registration_notes": None,
        "equipment_requirements": [
            {"equipment_type": "Wireless microphone", "quantity": 2, "notes": "Handheld"},
            {"equipment_type": "Lectern", "quantity": 1},
        ],
    }
    payload.update(overrides)
    return payload


def create_event(client, *, identity="organiser-one", **overrides):
    response = client.post(
        "/api/event-requests", json=event_payload(**overrides), headers=headers(identity)
    )
    assert response.status_code == 201
    return response.json["event_request"]


def test_organiser_creates_complete_request_with_server_owned_identity_and_equipment(
    client, event_app
):
    created = create_event(client)

    assert created["id"] == 1
    assert created["organiser_account_id"] == ORGANISER_ONE
    assert isinstance(created["organisation_id"], int)
    assert created["status"] == "submitted"
    assert created["mapped_slots"] == ["AM", "PM"]
    assert created["registration_required"] is True
    assert created["registration_notes"] is None
    assert created["equipment_requirements"] == [
        {
            "id": 1,
            "equipment_type": "Wireless microphone",
            "quantity": 2,
            "notes": "Handheld",
        },
        {"id": 2, "equipment_type": "Lectern", "quantity": 1, "notes": None},
    ]

    with Session(event_app.extensions["engine"]) as session:
        stored = session.scalar(select(EventRequest))
        assert stored is not None
        assert stored.organiser_account_id == ORGANISER_ONE
        assert stored.organisation_id == created["organisation_id"]


@pytest.mark.parametrize("field", ["organiser_account_id", "organisation_id", "status"])
def test_client_cannot_submit_server_owned_fields(client, field):
    response = client.post(
        "/api/event-requests",
        json=event_payload(**{field: "forged"}),
        headers=headers(),
    )

    assert response.status_code == 400
    assert response.json == {"error": f"Unexpected event request field: {field}."}


def test_organisers_see_only_their_own_requests_while_coordinator_sees_all(client):
    first = create_event(client, name="First organiser request")
    second = create_event(client, identity="organiser-two", name="Second organiser request")

    own_list = client.get("/api/event-requests", headers=headers("organiser-one"))
    other_detail = client.get(
        f"/api/event-requests/{second['id']}", headers=headers("organiser-one")
    )
    coordinator_list = client.get("/api/event-requests", headers=headers("coordinator"))
    coordinator_detail = client.get(
        f"/api/event-requests/{first['id']}", headers=headers("coordinator")
    )

    assert own_list.status_code == 200
    assert [event["id"] for event in own_list.json["event_requests"]] == [first["id"]]
    assert other_detail.status_code == 404
    assert other_detail.json == {"error": "Event request not found."}
    assert coordinator_list.status_code == 200
    assert [event["id"] for event in coordinator_list.json["event_requests"]] == [
        first["id"],
        second["id"],
    ]
    assert coordinator_detail.status_code == 200
    assert coordinator_detail.json["event_request"]["id"] == first["id"]


def test_drafts_are_visible_only_to_their_creator_even_with_a_coordinator_role(client, event_app):
    submitted = create_event(client)
    with Session(event_app.extensions["engine"]) as session:
        draft = EventRequest(
            organiser_account_id=ORGANISER_TWO,
            organisation_id=submitted["organisation_id"],
            name="Private draft",
            status="draft",
        )
        session.add(draft)
        session.add(AccountRole(account_id=ORGANISER_ONE, role=Role.EVENT_COORDINATOR.value))
        session.commit()
        draft_id = draft.id

    creator_list = client.get("/api/event-requests", headers=headers("organiser-two"))
    coordinator_list = client.get("/api/event-requests", headers=headers("coordinator"))
    multi_role_list = client.get("/api/event-requests", headers=headers("organiser-one"))
    creator_detail = client.get(f"/api/event-requests/{draft_id}", headers=headers("organiser-two"))
    coordinator_detail = client.get(
        f"/api/event-requests/{draft_id}", headers=headers("coordinator")
    )
    multi_role_detail = client.get(
        f"/api/event-requests/{draft_id}", headers=headers("organiser-one")
    )

    assert [event["id"] for event in creator_list.json["event_requests"]] == [draft_id]
    assert creator_detail.json["event_request"]["status"] == "draft"
    assert creator_detail.json["event_request"]["mapped_slots"] == []
    assert [event["id"] for event in coordinator_list.json["event_requests"]] == [submitted["id"]]
    assert [event["id"] for event in multi_role_list.json["event_requests"]] == [submitted["id"]]
    assert coordinator_detail.status_code == 404
    assert multi_role_detail.status_code == 404


def test_database_allows_name_only_draft_but_not_incomplete_submitted_request(event_app):
    with Session(event_app.extensions["engine"]) as session:
        session.add(
            EventRequest(
                organiser_account_id=ORGANISER_ONE,
                organisation_id=1,
                name="Early idea",
                status="draft",
            )
        )
        session.commit()

    with Session(event_app.extensions["engine"]) as session:
        session.add(
            EventRequest(
                organiser_account_id=ORGANISER_ONE,
                organisation_id=1,
                name="Incomplete",
                status="submitted",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_draft_lifecycle_preserves_id_and_last_saved_time(client):
    created_response = client.post(
        "/api/event-requests/drafts", json={"name": "  Early idea  "}, headers=headers()
    )
    assert created_response.status_code == 201
    draft = created_response.json["event_request"]
    assert draft["name"] == "Early idea"
    assert draft["status"] == "draft"
    assert draft["purpose"] is None
    assert draft["last_saved_at"]
    assert draft["required_facilities"] == []
    assert draft["accessibility_needs"] == []

    saved_response = client.patch(
        f"/api/event-requests/drafts/{draft['id']}",
        json={"purpose": "A useful event", "proposed_date": event_payload()["proposed_date"]},
        headers=headers(),
    )
    assert saved_response.status_code == 200
    saved = saved_response.json["event_request"]
    assert saved["id"] == draft["id"]
    assert saved["last_saved_at"] >= draft["last_saved_at"]

    incomplete = client.post(
        f"/api/event-requests/drafts/{draft['id']}/submit", json={}, headers=headers()
    )
    assert incomplete.status_code == 400
    assert (
        client.get(f"/api/event-requests/{draft['id']}", headers=headers()).json["event_request"][
            "status"
        ]
        == "draft"
    )

    submitted_response = client.post(
        f"/api/event-requests/drafts/{draft['id']}/submit",
        json={"start_time": "10:00", "end_time": "11:00", "expected_attendance": 25},
        headers=headers(),
    )
    assert submitted_response.status_code == 200
    assert submitted_response.json["event_request"]["id"] == draft["id"]
    assert submitted_response.json["event_request"]["status"] == "submitted"
    assert (
        client.delete(f"/api/event-requests/drafts/{draft['id']}", headers=headers()).status_code
        == 404
    )


def test_draft_save_delete_are_creator_only_and_never_expose_to_coordinator(client):
    response = client.post(
        "/api/event-requests/drafts", json={"name": "Private draft"}, headers=headers()
    )
    draft_id = response.json["event_request"]["id"]
    url = f"/api/event-requests/drafts/{draft_id}"
    assert (
        client.get(f"/api/event-requests/{draft_id}", headers=headers("coordinator")).status_code
        == 404
    )
    for identity in ("organiser-two", "coordinator"):
        assert client.patch(
            url, json={"name": "Stolen"}, headers=headers(identity)
        ).status_code in (403, 404)
        assert client.post(
            f"{url}/submit", json=event_payload(), headers=headers(identity)
        ).status_code in (403, 404)
        assert client.delete(url, headers=headers(identity)).status_code in (403, 404)
    assert client.delete(url, headers=headers()).status_code == 204
    assert client.get(f"/api/event-requests/{draft_id}", headers=headers()).status_code == 404
    assert client.get("/api/event-requests", headers=headers()).json["event_requests"] == []


def test_draft_rejects_forged_identity_and_invalid_fields(client):
    for field in ("organiser_account_id", "organisation_id", "status"):
        response = client.post(
            "/api/event-requests/drafts", json={"name": "Idea", field: "forged"}, headers=headers()
        )
        assert response.status_code == 400
    assert client.post("/api/event-requests/drafts", json={}, headers=headers()).status_code == 400
    assert (
        client.post(
            "/api/event-requests/drafts",
            json={"name": "Idea", "expected_attendance": 0},
            headers=headers(),
        ).status_code
        == 400
    )


def test_reopened_draft_retains_optional_fields_and_replaces_equipment_lines(client):
    created = client.post(
        "/api/event-requests/drafts", json=event_payload(), headers=headers()
    ).json["event_request"]
    assert created["preferred_room_layout"] == "Theatre"
    assert len(created["equipment_requirements"]) == 2

    saved = client.patch(
        f"/api/event-requests/drafts/{created['id']}",
        json={
            "description": "Revised description",
            "preferred_room_layout": None,
            "equipment_requirements": [
                {"equipment_type": "Projector", "quantity": 1, "notes": "Main stage"}
            ],
        },
        headers=headers(),
    )
    assert saved.status_code == 200
    reopened = client.get(f"/api/event-requests/{created['id']}", headers=headers()).json[
        "event_request"
    ]
    assert reopened["description"] == "Revised description"
    assert reopened["preferred_room_layout"] is None
    assert reopened["required_facilities"] == ["Projector", "Step-free access"]
    assert reopened["accessibility_needs"] == ["Reserved wheelchair spaces"]
    assert reopened["registration_required"] is True
    assert len(reopened["equipment_requirements"]) == 1
    assert reopened["equipment_requirements"][0]["equipment_type"] == "Projector"
    assert reopened["equipment_requirements"][0]["notes"] == "Main stage"


def test_event_request_routes_enforce_declared_roles(client):
    attendee_create = client.post(
        "/api/event-requests", json=event_payload(), headers=headers("attendee")
    )
    attendee_list = client.get("/api/event-requests", headers=headers("attendee"))
    unauthenticated = client.get("/api/event-requests")

    assert attendee_create.status_code == 403
    assert attendee_list.status_code == 403
    assert unauthenticated.status_code == 401


# Missing mandatory information no longer produces a single per-field message. CS-E03-S5
# refuses the whole submission and names every missing field at once, so those two cases moved
# to test_event_request_submission.py (TC-CS-E03-S5-04, -05 and -06). The per-field messages
# below still apply to values that are present but invalid.
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"proposed_date": (date.today() - timedelta(days=1)).isoformat()},
            "Proposed date cannot be in the past.",
        ),
        ({"start_time": "14:00", "end_time": "14:00"}, "End time must be after start time."),
        ({"start_time": "11:00:30"}, "Start time must use HH:MM."),
        ({"expected_attendance": 0}, "Expected attendance must be a positive whole number."),
        ({"expected_attendance": 2.5}, "Expected attendance must be a positive whole number."),
        (
            {"required_facilities": ["Projector", " "]},
            "Required facilities must contain only non-empty text values.",
        ),
        (
            {"accessibility_needs": ["Wheelchair access", " "]},
            "Accessibility needs must contain only non-empty text values.",
        ),
        (
            {"registration_required": "yes"},
            "Registration required must be true or false.",
        ),
        (
            {"equipment_requirements": [{"equipment_type": "Projector", "quantity": 0}]},
            "Equipment requirement 1 quantity must be a positive whole number.",
        ),
    ],
)
def test_invalid_request_is_rejected_without_creating_partial_rows(
    client, event_app, overrides, message
):
    response = client.post(
        "/api/event-requests", json=event_payload(**overrides), headers=headers()
    )

    assert response.status_code == 400
    assert response.json == {"error": message}
    with Session(event_app.extensions["engine"]) as session:
        assert session.scalars(select(EventRequest)).all() == []


def test_slot_mapping_uses_the_shared_venue_windows(client):
    am_only = create_event(client, start_time="07:00", end_time="12:00")
    night_only = create_event(client, start_time="19:00", end_time="23:59")
    gap_only = create_event(client, start_time="12:15", end_time="12:45")

    assert am_only["mapped_slots"] == ["AM"]
    assert night_only["mapped_slots"] == ["NIGHT"]
    assert gap_only["mapped_slots"] == []


def _add_venue(event_app, **overrides):
    attributes = {
        "name": "Harbour Hall",
        "location": "Central",
        "operating_slots": ["AM", "PM"],
    }
    attributes.update(overrides)
    with Session(event_app.extensions["engine"]) as session:
        venue = Venue(**attributes)
        session.add(venue)
        session.commit()
        return venue.id


def test_organiser_selects_a_venue_whose_operating_slots_cover_the_request(client, event_app):
    venue_id = _add_venue(event_app, operating_slots=["AM"])

    created = create_event(client, start_time="07:00", end_time="12:00", venue_id=venue_id)

    assert created["venue_id"] == venue_id


def test_unknown_venue_id_is_rejected(client):
    response = client.post(
        "/api/event-requests", json=event_payload(venue_id=999), headers=headers()
    )

    assert response.status_code == 400
    assert response.json == {"error": "Venue not found."}


def test_venue_id_is_rejected_when_the_time_falls_outside_its_operating_slots(client, event_app):
    venue_id = _add_venue(event_app, operating_slots=["NIGHT"])

    response = client.post(
        "/api/event-requests",
        json=event_payload(start_time="07:00", end_time="12:00", venue_id=venue_id),
        headers=headers(),
    )

    assert response.status_code == 400
    assert response.json == {"error": "Selected time is not available for this venue."}


def test_tc_spl_89_05_active_block_makes_event_request_slot_unavailable(client, event_app):
    venue_id = _add_venue(event_app, operating_slots=["AM"])
    proposed_date = date.today() + timedelta(days=7)
    with Session(event_app.extensions["engine"]) as session:
        session.add(
            VenueOperationalBlock(
                venue_id=venue_id,
                start_date=proposed_date,
                end_date=proposed_date,
                slots=["AM"],
                reason="Inspection",
                created_by_account_id=ORGANISER_ONE,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    response = client.post(
        "/api/event-requests",
        json=event_payload(
            proposed_date=proposed_date.isoformat(),
            start_time="07:00",
            end_time="12:00",
            venue_id=venue_id,
        ),
        headers=headers(),
    )

    assert response.status_code == 400
    assert response.json == {"error": "Selected time is not available for this venue."}
    with Session(event_app.extensions["engine"]) as session:
        assert session.scalars(select(EventRequest)).all() == []


def test_null_venue_id_bypasses_the_slot_availability_check(client):
    created = create_event(client, venue_id=None)

    assert created["venue_id"] is None
