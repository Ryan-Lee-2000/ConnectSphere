"""Acceptance coverage for CS-E03-S5: submit an event request.

Case identifiers match QA-SPL-55. CS-E03-S1 already covers the individual field rules; this
module tests only the submission behaviour this story adds or asserts.
"""

from datetime import date, datetime, timedelta

import pytest
from app import create_app
from app.event_requests import SINGAPORE
from app.models import Account, AccountRole, Base, EventRequest, Organisation, Role
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ORGANISER_ID = "00000000-0000-0000-0000-000000000031"
OTHER_ORGANISER_ID = "00000000-0000-0000-0000-000000000032"
COORDINATOR_ID = "00000000-0000-0000-0000-000000000033"
VENUE_STAFF_ID = "00000000-0000-0000-0000-000000000034"

TOMORROW = (date.today() + timedelta(days=1)).isoformat()

MANDATORY_KEYS = [
    "name",
    "purpose",
    "proposed_date",
    "start_time",
    "end_time",
    "expected_attendance",
]


@pytest.fixture
def app(tmp_path):
    identities = {
        "organiser": ORGANISER_ID,
        "other-organiser": OTHER_ORGANISER_ID,
        "coordinator": COORDINATOR_ID,
        "venue-staff": VENUE_STAFF_ID,
    }
    application = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/submission.db",
            "IDENTITY_VERIFIER": identities.get,
        }
    )
    engine = application.extensions["engine"]
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
                    organisation.id if account_id in {ORGANISER_ID, OTHER_ORGANISER_ID} else None
                ),
            )
            for index, account_id in enumerate(identities.values(), start=1)
        )
        session.add_all(
            [
                AccountRole(account_id=ORGANISER_ID, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=OTHER_ORGANISER_ID, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=COORDINATOR_ID, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=VENUE_STAFF_ID, role=Role.VENUE_STAFF.value),
            ]
        )
        session.commit()
    yield application
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="organiser"):
    return {"Authorization": f"Bearer {token}"}


def payload(**overrides):
    body = {
        "name": "Regional Partner Conference",
        "purpose": "Brief partners on the roadmap",
        "proposed_date": TOMORROW,
        "start_time": "09:00",
        "end_time": "11:30",
        "expected_attendance": 120,
    }
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not _ABSENT}


class _Absent:
    pass


_ABSENT = _Absent()


def submit(client, token="organiser", **overrides):
    return client.post("/api/event-requests", json=payload(**overrides), headers=headers(token))


def stored_request_count(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(EventRequest))


# --- AC1: record when the request was submitted, from a source the caller cannot control ---


def test_tc_cs_e03_s5_01_stores_a_submitted_request_with_its_submission_time(client):
    before = datetime.now(SINGAPORE)
    response = submit(client)
    after = datetime.now(SINGAPORE)

    assert response.status_code == 201
    created = response.json["event_request"]
    assert created["status"] == "submitted"
    assert created["submitted_at"] is not None

    submitted_at = datetime.fromisoformat(created["submitted_at"])
    # The API always carries an offset, whichever backend stored the value.
    assert submitted_at.tzinfo is not None
    assert before - timedelta(minutes=1) <= submitted_at <= after + timedelta(minutes=1)

    read_back = client.get(f"/api/event-requests/{created['id']}", headers=headers())
    assert read_back.status_code == 200
    assert read_back.json["event_request"]["submitted_at"] == created["submitted_at"]


def test_tc_cs_e03_s5_02_caller_cannot_set_the_submission_time(client):
    response = client.post(
        "/api/event-requests",
        json={**payload(), "submitted_at": "2020-01-01T00:00:00+08:00"},
        headers=headers(),
    )

    # The field is not accepted as input at all, so the forged value can never be stored.
    assert response.status_code == 400
    assert response.json == {"error": "Unexpected event request field: submitted_at."}

    honest = submit(client)
    assert honest.status_code == 201
    assert not honest.json["event_request"]["submitted_at"].startswith("2020")


def test_tc_cs_e03_s5_03_a_request_stored_before_this_story_remains_readable(app, client):
    # A request written by CS-E03-S1 before the additive migration has no submission time.
    with Session(app.extensions["engine"]) as session:
        session.add(
            EventRequest(
                organiser_account_id=ORGANISER_ID,
                organisation_id=1,
                name="Legacy Request",
                purpose="Created before CS-E03-S5",
                proposed_date=date.fromisoformat(TOMORROW),
                start_time=datetime.strptime("09:00", "%H:%M").time(),
                end_time=datetime.strptime("11:30", "%H:%M").time(),
                expected_attendance=50,
                status="submitted",
                submitted_at=None,
                required_facilities=[],
                registration_required=False,
            )
        )
        session.commit()

    listed = client.get("/api/event-requests", headers=headers())
    assert listed.status_code == 200
    legacy = listed.json["event_requests"][0]
    assert legacy["name"] == "Legacy Request"
    assert legacy["submitted_at"] is None

    detail = client.get(f"/api/event-requests/{legacy['id']}", headers=headers())
    assert detail.status_code == 200
    assert detail.json["event_request"]["submitted_at"] is None


# --- AC2: refuse an incomplete submission naming every missing mandatory field ---


def test_tc_cs_e03_s5_04_empty_submission_names_every_missing_field(app, client):
    response = client.post("/api/event-requests", json={}, headers=headers())

    assert response.status_code == 400
    assert response.json["error"] == "Complete the required fields before submitting."
    assert response.json["missing_fields"] == MANDATORY_KEYS
    assert response.json["missing_field_labels"] == [
        "Event name",
        "Purpose",
        "Proposed date",
        "Start time",
        "End time",
        "Expected attendance",
    ]
    assert stored_request_count(app) == 0


def test_tc_cs_e03_s5_05_partial_submission_names_only_what_is_missing(client):
    response = client.post(
        "/api/event-requests",
        json={"name": "Quarterly Briefing", "purpose": "Update the client"},
        headers=headers(),
    )

    assert response.status_code == 400
    assert response.json["missing_fields"] == [
        "proposed_date",
        "start_time",
        "end_time",
        "expected_attendance",
    ]
    assert "name" not in response.json["missing_fields"]
    assert "purpose" not in response.json["missing_fields"]


def test_tc_cs_e03_s5_06_blank_sits_in_the_same_partition_as_absent(client):
    refused = client.post(
        "/api/event-requests",
        json={
            "name": "   ",
            "proposed_date": TOMORROW,
            "start_time": "09:00",
            "end_time": "11:30",
            "expected_attendance": 120,
        },
        headers=headers(),
    )
    assert refused.status_code == 400
    assert refused.json["missing_fields"] == ["name", "purpose"]

    # One character is inside the boundary of "present".
    accepted = submit(client, name="A")
    assert accepted.status_code == 201
    assert accepted.json["event_request"]["name"] == "A"


# --- AC3: a refused submission stores nothing at all ---


def test_tc_cs_e03_s5_07_a_refusal_writes_no_equipment_lines_either(app, client):
    response = client.post(
        "/api/event-requests",
        json={
            "name": "Missing The Rest",
            "equipment_requirements": [
                {"equipment_type": "Projector", "quantity": 2},
                {"equipment_type": "Microphone", "quantity": 4},
            ],
        },
        headers=headers(),
    )

    assert response.status_code == 400
    assert stored_request_count(app) == 0
    with Session(app.extensions["engine"]) as session:
        equipment_rows = session.execute(
            select(func.count()).select_from(Base.metadata.tables["equipment_requirements"])
        ).scalar()
    assert equipment_rows == 0


# --- AC4: a submitted request cannot be changed by the organiser ---


def test_tc_cs_e03_s5_08_a_submitted_request_cannot_be_amended_or_deleted(client):
    created = submit(client).json["event_request"]
    path = f"/api/event-requests/{created['id']}"

    # Q102 places post-submission changes with the Event Coordinator, so no organiser write
    # route exists. No endpoint resolves for these methods, so CS-E01-S2 default-deny refuses
    # them before a "method not allowed" reply could disclose the supported methods.
    for refused in (
        client.patch(path, json={"name": "Renamed"}, headers=headers()),
        client.put(path, json={"name": "Renamed"}, headers=headers()),
        client.delete(path, headers=headers()),
    ):
        assert refused.status_code == 403
        assert refused.json == {"error": "Access denied."}

    assert client.get(path, headers=headers()).json["event_request"]["name"] == created["name"]


def test_tc_cs_e03_s5_09_submitting_again_does_not_alter_the_earlier_request(client):
    first = submit(client).json["event_request"]
    second = submit(client, name="Second Request").json["event_request"]

    assert second["id"] != first["id"]

    reread = client.get(f"/api/event-requests/{first['id']}", headers=headers())
    assert reread.json["event_request"]["name"] == first["name"]
    assert reread.json["event_request"]["submitted_at"] == first["submitted_at"]

    listed = client.get("/api/event-requests", headers=headers()).json["event_requests"]
    assert sorted(item["id"] for item in listed) == sorted([first["id"], second["id"]])


# --- AC7: only an Event Organiser may submit ---


@pytest.mark.parametrize("token", ["coordinator", "venue-staff"])
def test_tc_cs_e03_s5_14_only_event_organisers_may_submit(app, client, token):
    response = submit(client, token=token)

    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}
    assert stored_request_count(app) == 0


@pytest.mark.parametrize("authorization", [None, "Basic abc", "Bearer  "])
def test_tc_cs_e03_s5_15_unauthenticated_submission_is_refused(app, client, authorization):
    request_headers = {"Authorization": authorization} if authorization else {}
    response = client.post("/api/event-requests", json=payload(), headers=request_headers)

    assert response.status_code == 401
    assert response.json == {"error": "Sign in to continue."}
    assert stored_request_count(app) == 0


def test_tc_cs_e03_s5_15b_an_unrecognised_token_is_refused(app, client):
    response = client.post(
        "/api/event-requests",
        json=payload(),
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    # The identity verifier resolves nothing, so the request fails closed before the handler.
    assert response.status_code == 401
    assert stored_request_count(app) == 0
