"""Acceptance coverage for CS-E05-S1 to S3 (SPL-59, SPL-60 and SPL-61).

Test IDs match the specs in docs/tasks. Requests are created directly rather than through
CS-E03-S5, so a submission time can be fixed per case.
"""

from datetime import date, datetime, time, timedelta

import pytest
from app import coordinator_assignment, create_app
from app.coordinator_assignment import (
    ALREADY_ASSIGNED,
    NO_COORDINATOR_AVAILABLE,
    NO_OTHER_COORDINATOR_AVAILABLE,
    SUBMITTED,
    UNDER_REVIEW,
    _serialize_assigned_event_detail,
    is_assigned_coordinator,
)
from app.event_requests import SINGAPORE
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EventCoordinatorAssignment,
    EventCoordinatorHistory,
    EventRequest,
    Organisation,
    Role,
    Venue,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

MANAGER = "00000000-0000-0000-0000-000000000021"
ORGANISER = "00000000-0000-0000-0000-000000000022"
ALICE = "00000000-0000-0000-0000-000000000023"
BOB = "00000000-0000-0000-0000-000000000024"
CAROL = "00000000-0000-0000-0000-000000000025"
INACTIVE_COORDINATOR = "00000000-0000-0000-0000-000000000026"
VENUE_STAFF = "00000000-0000-0000-0000-000000000027"
MANAGER_AND_ORGANISER = "00000000-0000-0000-0000-000000000028"
ORGANISATION_NAME = "Northstar Community Partners"
SUBMITTED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=SINGAPORE)
TOKENS = {
    "manager": MANAGER,
    "organiser": ORGANISER,
    "coordinator": ALICE,
    "coordinator-b": BOB,
    "venue-staff": VENUE_STAFF,
    "manager-and-organiser": MANAGER_AND_ORGANISER,
}
ENDPOINTS = [
    ("get", "/api/event-requests/awaiting-assignment", None),
    ("get", "/api/event-requests/{event_id}/coordinator-options", None),
    ("post", "/api/event-requests/{event_id}/coordinator", {"coordinator_account_id": ALICE}),
    ("put", "/api/event-requests/{event_id}/coordinator", {"coordinator_account_id": BOB}),
    ("get", "/api/event-requests/{event_id}/coordinator-history", None),
]


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/assignment.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    accounts = [
        (MANAGER, "Morgan Manager", True, [Role.EVENT_OPERATIONS_MANAGER]),
        (ORGANISER, "Olivia Organiser", True, [Role.EVENT_ORGANISER]),
        (ALICE, "Alice Tan", True, [Role.EVENT_COORDINATOR]),
        (BOB, "Bob Lim", True, [Role.EVENT_COORDINATOR]),
        (CAROL, "Carol Ng", True, [Role.EVENT_COORDINATOR]),
        (INACTIVE_COORDINATOR, "Ivan Inactive", False, [Role.EVENT_COORDINATOR]),
        (VENUE_STAFF, "Vera Venue", True, [Role.VENUE_STAFF]),
        (
            MANAGER_AND_ORGANISER,
            "Mina Multi",
            True,
            [Role.EVENT_OPERATIONS_MANAGER, Role.EVENT_ORGANISER],
        ),
    ]
    with Session(engine) as session:
        organisation = Organisation(name=ORGANISATION_NAME)
        session.add(organisation)
        session.flush()
        for account_id, name, active, roles in accounts:
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    is_active=active,
                    organisation_id=organisation.id,
                )
            )
            session.add_all(AccountRole(account_id=account_id, role=role.value) for role in roles)
        session.commit()
        app.config["TEST_ORGANISATION_ID"] = organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="manager"):
    return {"Authorization": f"Bearer {token}"}


def add_request(
    app,
    name="Harbour Summit",
    *,
    status=SUBMITTED,
    submitted_at=SUBMITTED_AT,
    proposed_date=date(2026, 10, 12),
):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["TEST_ORGANISATION_ID"],
            name=name,
            purpose="Client showcase",
            proposed_date=proposed_date,
            start_time=time(9, 0),
            end_time=time(12, 0),
            expected_attendance=120,
            status=status,
            submitted_at=submitted_at,
        )
        session.add(event)
        session.commit()
        return event.id


def set_status(app, event_id, status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = status
        session.commit()


def stored_request(app, event_id):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        return event.status, event.status_changed_at


def deactivate(app, *account_ids):
    with Session(app.extensions["engine"]) as session:
        for account_id in account_ids:
            session.get(Account, account_id).is_active = False
        session.commit()


def history_count(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(
            select(func.count())
            .select_from(EventCoordinatorHistory)
            .where(EventCoordinatorHistory.event_request_id == event_id)
        )


def holds_event(app, event_id, account_id):
    with Session(app.extensions["engine"]) as session:
        return is_assigned_coordinator(session, event_id, account_id)


def assign(client, event_id, coordinator=ALICE, token="manager"):
    return client.post(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": coordinator},
        headers=headers(token),
    )


def reassign(client, event_id, coordinator=BOB, token="manager"):
    return client.put(
        f"/api/event-requests/{event_id}/coordinator",
        json={"coordinator_account_id": coordinator},
        headers=headers(token),
    )


def queue(client, token="manager"):
    return client.get("/api/event-requests/awaiting-assignment", headers=headers(token))


def options(client, event_id):
    return client.get(f"/api/event-requests/{event_id}/coordinator-options", headers=headers())


def history(client, event_id):
    return client.get(f"/api/event-requests/{event_id}/coordinator-history", headers=headers())


def organiser_view(client, event_id):
    return client.get(f"/api/event-requests/{event_id}", headers=headers("organiser"))


# SPL-62 / CS-E05-S4: the coordinator's own assignment entry point.


def test_tc_e05_s4_01_02_04_lists_only_current_coordinator_assignments(app, client):
    alice_event = add_request(app, "Alice's event")
    bob_event = add_request(app, "Bob's event", proposed_date=date(2026, 11, 3))
    unassigned = add_request(app, "Unassigned event")
    assert assign(client, alice_event, ALICE).status_code == 201
    assert assign(client, bob_event, BOB).status_code == 201

    alice = client.get("/api/event-requests/assigned", headers=headers("coordinator"))
    assert alice.status_code == 200
    assert alice.json["events"] == [
        {
            "id": alice_event,
            "name": "Alice's event",
            "status": SUBMITTED,
            "status_label": "Submitted",
            "proposed_date": "2026-10-12",
        }
    ]
    bob = client.get("/api/event-requests/assigned", headers=headers("coordinator-b"))
    assert [event["id"] for event in bob.json["events"]] == [bob_event]
    assert unassigned not in [event["id"] for event in alice.json["events"]]


def test_tc_e05_s4_03_opens_only_current_assignment(app, client):
    alice_event = add_request(app)
    assert assign(client, alice_event, ALICE).status_code == 201
    path = f"/api/event-requests/assigned/{alice_event}"
    assert client.get(path, headers=headers("coordinator")).json["event"]["id"] == alice_event
    assert client.get(path, headers=headers("coordinator-b")).status_code == 404
    assert reassign(client, alice_event, BOB).status_code == 200
    assert client.get(path, headers=headers("coordinator")).status_code == 404
    assert client.get(path, headers=headers("coordinator-b")).status_code == 200


def fill_request_details(app, event_id):
    with Session(app.extensions["engine"]) as session:
        venue = Venue(name="Harbour Hall")
        session.add(venue)
        session.flush()
        event = session.get(EventRequest, event_id)
        event.description = "Annual client forum"
        event.venue_id = venue.id
        event.preferred_room_layout = "Theatre"
        event.required_facilities = ["Projector", "Microphone"]
        event.facilities_notes = "Two lapel microphones"
        event.accessibility_needs = ["Step-free access"]
        event.location_preference = "Ground floor"
        event.venue_notes = "Loading bay access"
        event.registration_required = True
        event.registration_notes = "Ticketed"
        event.equipment_requirements = [
            EquipmentRequirement(equipment_type="Podium", quantity=2, notes="Lockable"),
        ]
        session.commit()


# SPL-64 / CS-E06-S1: the assigned coordinator reads the complete submitted request.


def test_tc_spl_64_01_assigned_coordinator_reads_every_request_field(app, client):
    event_id = add_request(app)
    fill_request_details(app, event_id)
    assert assign(client, event_id, ALICE).status_code == 201

    response = client.get(
        f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
    )

    assert response.status_code == 200
    assert response.json["event"] == {
        "id": event_id,
        "name": "Harbour Summit",
        "status": SUBMITTED,
        "status_label": "Submitted",
        "proposed_date": "2026-10-12",
        "purpose": "Client showcase",
        "description": "Annual client forum",
        "start_time": "09:00",
        "end_time": "12:00",
        "expected_attendance": 120,
        "venue_name": "Harbour Hall",
        "preferred_room_layout": "Theatre",
        "required_facilities": ["Projector", "Microphone"],
        "facilities_notes": "Two lapel microphones",
        "accessibility_needs": ["Step-free access"],
        "location_preference": "Ground floor",
        "venue_notes": "Loading bay access",
        "equipment_requirements": [
            {"equipment_type": "Podium", "quantity": 2, "notes": "Lockable"}
        ],
        "registration_required": True,
        "registration_notes": "Ticketed",
        "client_organisation": ORGANISATION_NAME,
        "responsible_organiser": "Olivia Organiser",
        "submitted_at": SUBMITTED_AT.isoformat(),
        "clarifications": [],
    }


def test_tc_spl_64_02_empty_optional_fields_are_returned_empty(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    event = client.get(
        f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
    ).json["event"]

    assert event["description"] is None
    assert event["venue_name"] is None
    assert event["required_facilities"] == []
    assert event["accessibility_needs"] == []
    assert event["equipment_requirements"] == []
    assert event["registration_required"] is False


def test_tc_spl_64_03_04_unassigned_and_missing_requests_leak_nothing(app, client):
    event_id = add_request(app)
    fill_request_details(app, event_id)
    assert assign(client, event_id, ALICE).status_code == 201

    unassigned = client.get(
        f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator-b")
    )
    missing = client.get("/api/event-requests/assigned/9999", headers=headers("coordinator-b"))

    assert unassigned.status_code == missing.status_code == 404
    assert unassigned.json == missing.json == {"error": "Assigned event not found."}
    assert "Harbour" not in unassigned.get_data(as_text=True)


def test_tc_spl_64_03_unassigned_event_is_not_readable_by_any_coordinator(app, client):
    event_id = add_request(app)
    path = f"/api/event-requests/assigned/{event_id}"
    assert client.get(path, headers=headers("coordinator")).status_code == 404
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200
    assert client.get(path, headers=headers("coordinator")).status_code == 404
    assert client.get(path, headers=headers("coordinator-b")).status_code == 200


def test_tc_spl_64_05_detail_is_read_only_and_role_protected(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    path = f"/api/event-requests/assigned/{event_id}"

    for method in ("put", "patch", "post", "delete"):
        response = getattr(client, method)(
            path, json={"name": "Changed"}, headers=headers("coordinator")
        )
        # The default-deny hook refuses an unregistered method before routing can say 405.
        assert response.status_code in (403, 405)
    assert client.get(path, headers=headers("organiser")).status_code == 403
    assert client.get(path, headers=headers("manager")).status_code == 403
    assert client.get(path).status_code == 401
    unchanged = client.get(path, headers=headers("coordinator"))
    assert unchanged.json["event"]["name"] == "Harbour Summit"


# SPL-64 QA additions: white-box serializer cases and black-box boundary partitions.


def transient_event(**overrides):
    """An unsaved request, so the serializer's branches can be driven without a database."""

    values = {
        "id": 7,
        "name": "Unsaved",
        "status": SUBMITTED,
        "organiser": Account(id=ORGANISER, display_name="Olivia Organiser"),
        "organisation": Organisation(name=ORGANISATION_NAME),
        "venue": None,
        "required_facilities": [],
        "accessibility_needs": [],
        "registration_required": False,
        "equipment_requirements": [],
    }
    values.update(overrides)
    return EventRequest(**values)


def test_tc_spl_64_10_serializer_leaves_absent_optionals_null():
    event = _serialize_assigned_event_detail(transient_event())

    assert event["proposed_date"] is None
    assert event["start_time"] is None and event["end_time"] is None
    assert event["expected_attendance"] is None
    assert event["venue_name"] is None
    assert event["submitted_at"] is None
    assert event["equipment_requirements"] == []
    assert event["client_organisation"] == ORGANISATION_NAME
    assert event["responsible_organiser"] == "Olivia Organiser"


def test_tc_spl_64_11_serializer_formats_times_without_seconds():
    event = _serialize_assigned_event_detail(
        transient_event(start_time=time(9, 30, 45), end_time=time(17, 5))
    )

    assert event["start_time"] == "09:30"
    assert event["end_time"] == "17:05"


def test_tc_spl_64_12_serializer_stamps_singapore_on_a_naive_submission_time():
    naive = _serialize_assigned_event_detail(
        transient_event(submitted_at=datetime(2026, 9, 1, 9, 0))
    )
    aware = _serialize_assigned_event_detail(
        transient_event(submitted_at=datetime(2026, 9, 1, 1, 0, tzinfo=SINGAPORE))
    )

    assert naive["submitted_at"] == "2026-09-01T09:00:00+08:00"
    assert aware["submitted_at"] == "2026-09-01T01:00:00+08:00"


def test_tc_spl_64_13_serializer_omits_internal_identifiers_from_equipment_and_event():
    event = _serialize_assigned_event_detail(
        transient_event(
            equipment_requirements=[
                EquipmentRequirement(id=5, equipment_type="Podium", quantity=1, notes=None)
            ]
        )
    )

    assert event["equipment_requirements"] == [
        {"equipment_type": "Podium", "quantity": 1, "notes": None}
    ]
    for internal in ("organiser_account_id", "organisation_id", "venue_id"):
        assert internal not in event


def test_tc_spl_64_14_equipment_lines_keep_entry_order(app, client):
    event_id = add_request(app)
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.equipment_requirements = [
            EquipmentRequirement(equipment_type=name, quantity=index + 1)
            for index, name in enumerate(["Zebra table", "Alpha lamp", "Microphone"])
        ]
        session.commit()
    assert assign(client, event_id, ALICE).status_code == 201

    lines = client.get(
        f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
    ).json["event"]["equipment_requirements"]

    assert [line["equipment_type"] for line in lines] == ["Zebra table", "Alpha lamp", "Microphone"]
    assert [line["quantity"] for line in lines] == [1, 2, 3]


def test_tc_spl_64_15_detail_stays_readable_after_review_begins(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    set_status(app, event_id, UNDER_REVIEW)

    event = client.get(
        f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
    ).json["event"]

    assert event["status"] == UNDER_REVIEW
    assert event["status_label"] == "Under review"
    assert event["purpose"] == "Client showcase"


def test_tc_spl_64_16_malformed_and_out_of_range_ids_return_no_event(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    for bad in ("0", "-1", "abc", "1%20OR%201=1", "99999999999999999999"):
        response = client.get(f"/api/event-requests/assigned/{bad}", headers=headers("coordinator"))
        # Unroutable ids are refused by the default-deny hook (403); routable ones are a 404.
        assert response.status_code in (403, 404)
        assert "Harbour Summit" not in response.get_data(as_text=True)


def test_tc_spl_64_17_reassigned_back_coordinator_regains_access(app, client):
    event_id = add_request(app)
    path = f"/api/event-requests/assigned/{event_id}"
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200
    assert client.get(path, headers=headers("coordinator")).status_code == 404
    assert reassign(client, event_id, ALICE).status_code == 200
    assert client.get(path, headers=headers("coordinator")).status_code == 200
    assert client.get(path, headers=headers("coordinator-b")).status_code == 404


def test_tc_spl_64_18_dual_role_manager_organiser_cannot_read_the_coordinator_detail(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    path = f"/api/event-requests/assigned/{event_id}"

    for token in ("manager-and-organiser", "venue-staff"):
        response = client.get(path, headers=headers(token))
        assert response.status_code == 403
        assert "Harbour Summit" not in response.get_data(as_text=True)


def test_tc_spl_64_19_deactivated_coordinator_cannot_read_the_detail(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    deactivate(app, ALICE)

    response = client.get(
        f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
    )

    assert response.status_code == 403
    assert "Harbour Summit" not in response.get_data(as_text=True)


def test_tc_spl_64_20_long_and_unicode_text_round_trips(app, client):
    event_id = add_request(app)
    long_text = "Café 会议 ✓ " * 400
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        event.description = long_text
        event.venue_notes = "<script>alert(1)</script>"
        session.commit()
    assert assign(client, event_id, ALICE).status_code == 201

    response = client.get(
        f"/api/event-requests/assigned/{event_id}", headers=headers("coordinator")
    )

    assert response.mimetype == "application/json"
    assert response.json["event"]["description"] == long_text
    assert response.json["event"]["venue_notes"] == "<script>alert(1)</script>"


def test_tc_e05_s4_05_empty_and_role_boundaries(app, client):
    response = client.get("/api/event-requests/assigned", headers=headers("coordinator"))
    assert response.json == {"events": []}
    assert client.get("/api/event-requests/assigned", headers=headers("manager")).status_code == 403
    response = client.get("/api/event-requests/assigned/1", headers=headers("organiser"))
    assert response.status_code == 403
    assert client.get("/api/event-requests/assigned").status_code == 401


# SPL-59 / CS-E05-S1: see submitted events awaiting assignment


def test_tc_e05_s1_01_02_11_queue_lists_unassigned_submitted_requests_oldest_first(app, client):
    newest = add_request(app, "Gala Night", submitted_at=SUBMITTED_AT + timedelta(hours=2))
    oldest = add_request(app, "Harbour Summit")
    middle = add_request(
        app,
        "Tech Forum",
        submitted_at=SUBMITTED_AT + timedelta(hours=1),
        proposed_date=date(2026, 11, 3),
    )

    response = queue(client)

    assert response.status_code == 200
    assert response.json == {
        "count": 3,
        "events": [
            {
                "id": oldest,
                "name": "Harbour Summit",
                "organisation_id": app.config["TEST_ORGANISATION_ID"],
                "organisation_name": ORGANISATION_NAME,
                "proposed_date": "2026-10-12",
                "submitted_at": "2026-09-01T09:00:00+08:00",
            },
            {
                "id": middle,
                "name": "Tech Forum",
                "organisation_id": app.config["TEST_ORGANISATION_ID"],
                "organisation_name": ORGANISATION_NAME,
                "proposed_date": "2026-11-03",
                "submitted_at": "2026-09-01T10:00:00+08:00",
            },
            {
                "id": newest,
                "name": "Gala Night",
                "organisation_id": app.config["TEST_ORGANISATION_ID"],
                "organisation_name": ORGANISATION_NAME,
                "proposed_date": "2026-10-12",
                "submitted_at": "2026-09-01T11:00:00+08:00",
            },
        ],
    }


def test_tc_e05_s1_03_empty_queue_reports_zero_events(client):
    response = queue(client)

    assert response.status_code == 200
    assert response.json == {"count": 0, "events": []}


def test_tc_e05_s1_04_queue_excludes_other_statuses_and_assigned_requests(app, client):
    add_request(app, "Under review", status=UNDER_REVIEW)
    add_request(app, "Approved", status="approved")
    add_request(app, "Draft", status="draft", submitted_at=None)
    assigned = add_request(app, "Submitted with coordinator")
    with Session(app.extensions["engine"]) as session:
        session.add(
            EventCoordinatorAssignment(
                event_request_id=assigned,
                coordinator_account_id=ALICE,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime.now(SINGAPORE),
            )
        )
        session.commit()
    awaiting = add_request(app, "Awaiting")

    response = queue(client)

    assert [event["id"] for event in response.json["events"]] == [awaiting]
    assert response.json["count"] == 1


def test_tc_e05_s1_05_assigned_request_leaves_the_queue_on_refresh(app, client):
    event_id = add_request(app)
    other = add_request(app, "Gala Night", submitted_at=SUBMITTED_AT + timedelta(hours=1))
    assert queue(client).json["count"] == 2

    assert assign(client, event_id).status_code == 201

    refreshed = queue(client).json
    assert [event["id"] for event in refreshed["events"]] == [other]
    assert refreshed["count"] == 1


def test_tc_e05_s1_09_single_request_is_listed_rather_than_empty(app, client):
    add_request(app)

    assert queue(client).json["count"] == 1


def test_tc_e05_s1_10_equal_submission_times_tie_break_on_request_id(app, client):
    first = add_request(app, "First recorded")
    second = add_request(app, "Second recorded")

    orders = [[event["id"] for event in queue(client).json["events"]] for _ in range(3)]

    assert orders == [[first, second]] * 3


def test_requests_without_a_submission_time_sort_after_submitted_ones(app, client):
    legacy = add_request(app, "Stored before CS-E03-S5", submitted_at=None)
    submitted = add_request(app, "Submitted", submitted_at=SUBMITTED_AT)

    events = queue(client).json["events"]

    assert [event["id"] for event in events] == [submitted, legacy]
    assert events[1]["submitted_at"] is None


def test_tc_e05_s1_12_viewing_the_queue_has_no_side_effects(app, client):
    event_id = add_request(app)

    assert queue(client).json == queue(client).json
    assert stored_request(app, event_id) == (SUBMITTED, None)
    assert history_count(app, event_id) == 0


def test_tc_e05_s1_13_multi_role_account_with_manager_role_can_open_the_queue(app, client):
    add_request(app)

    assert queue(client, token="manager-and-organiser").status_code == 200


# Authorization shared by every story in the epic. Each test name carries the test
# case IDs it covers so a reader can find it from the QA page by grepping the ID.


@pytest.mark.parametrize("token", ["organiser", "coordinator", "venue-staff"])
def test_tc_e05_s1_06_s2_07_s3_10_roles_other_than_manager_are_denied(app, client, token):
    event_id = add_request(app)

    for method, path, body in ENDPOINTS:
        response = getattr(client, method)(
            path.format(event_id=event_id), json=body, headers=headers(token)
        )
        assert response.status_code == 403, path
        assert response.json == {"error": "Access denied."}

    assert stored_request(app, event_id) == (SUBMITTED, None)
    assert history_count(app, event_id) == 0


def test_tc_e05_s1_07_s2_08_s3_11_unauthenticated_requests_are_rejected(app, client):
    event_id = add_request(app)

    for method, path, body in ENDPOINTS:
        response = getattr(client, method)(path.format(event_id=event_id), json=body)
        assert response.status_code == 401, path

    assert stored_request(app, event_id) == (SUBMITTED, None)
    assert history_count(app, event_id) == 0


def test_tc_e05_s1_08_forged_role_claims_do_not_grant_manager_access(app, client):
    event_id = add_request(app)

    response = client.post(
        f"/api/event-requests/{event_id}/coordinator?role=event_operations_manager",
        json={"coordinator_account_id": ALICE},
        headers={**headers("organiser"), "X-Account-Role": "event_operations_manager"},
    )

    assert response.status_code == 403
    assert stored_request(app, event_id)[0] == SUBMITTED


# SPL-60 / CS-E05-S2: assign an Event Coordinator


def test_tc_e05_s2_01_09_assignment_records_the_coordinator_and_the_history(app, client):
    event_id = add_request(app)

    response = assign(client, event_id, ALICE)

    assert response.status_code == 201
    assignment = response.json["assignment"]
    assert assignment["event_request_id"] == event_id
    assert assignment["status"] == SUBMITTED
    assert assignment["coordinator"] == {"id": ALICE, "name": "Alice Tan"}
    assert assignment["assigned_by"] == {"id": MANAGER, "name": "Morgan Manager"}
    assert holds_event(app, event_id, ALICE)
    status, status_changed_at = stored_request(app, event_id)
    assert status == SUBMITTED
    # Assignment is responsibility metadata; SPL-70 owns the next status transition.
    assert status_changed_at is None
    assert history(client, event_id).json == {
        "history": [
            {
                "id": 1,
                "previous_coordinator": None,
                "new_coordinator": {"id": ALICE, "name": "Alice Tan"},
                "changed_by": {"id": MANAGER, "name": "Morgan Manager"},
                "changed_at": assignment["assigned_at"],
            }
        ]
    }


def test_tc_e05_s2_01b_organiser_sees_the_assigned_coordinator(app, client):
    event_id = add_request(app)
    assert organiser_view(client, event_id).json["event_request"]["coordinator"] is None

    assert assign(client, event_id, ALICE).status_code == 201

    event = organiser_view(client, event_id).json["event_request"]
    assert event["coordinator"] == {"id": ALICE, "name": "Alice Tan"}
    assert event["status"] == SUBMITTED


def test_tc_e05_s2_02_picker_lists_only_active_event_coordinators(app, client):
    event_id = add_request(app)

    response = options(client, event_id)

    assert response.status_code == 200
    assert response.json == {
        "coordinators": [
            {"id": ALICE, "name": "Alice Tan"},
            {"id": BOB, "name": "Bob Lim"},
            {"id": CAROL, "name": "Carol Ng"},
        ],
        "current_coordinator": None,
        "unavailable_reason": None,
    }


def test_tc_e05_s2_03_assigned_request_cannot_be_assigned_again(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    response = assign(client, event_id, BOB)

    assert response.status_code == 409
    assert response.json == {"error": ALREADY_ASSIGNED}
    assert holds_event(app, event_id, ALICE)
    assert history_count(app, event_id) == 1


def test_tc_e05_s2_04_concurrent_assignment_cannot_overwrite_the_first(app, client, monkeypatch):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    # Replay the losing request as if it read the request before the first assignment committed.
    set_status(app, event_id, SUBMITTED)
    monkeypatch.setattr(coordinator_assignment, "_current_assignment", lambda *_: None)

    response = assign(client, event_id, BOB)

    monkeypatch.undo()
    assert response.status_code == 409
    assert response.json == {"error": ALREADY_ASSIGNED}
    assert holds_event(app, event_id, ALICE)
    assert history_count(app, event_id) == 1


def test_tc_e05_s2_05_manager_is_told_why_when_no_coordinator_is_active(app, client):
    event_id = add_request(app)
    deactivate(app, ALICE, BOB, CAROL)

    picker = options(client, event_id)
    response = assign(client, event_id, ALICE)

    assert picker.json["coordinators"] == []
    assert picker.json["unavailable_reason"] == NO_COORDINATOR_AVAILABLE
    assert response.status_code == 409
    assert response.json == {"error": NO_COORDINATOR_AVAILABLE}
    assert stored_request(app, event_id) == (SUBMITTED, None)
    assert history_count(app, event_id) == 0


@pytest.mark.parametrize("status", [UNDER_REVIEW, "approved", "cancelled"])
def test_tc_e05_s2_06_requests_that_are_not_submitted_are_refused_server_side(app, client, status):
    event_id = add_request(app, status=status)

    response = assign(client, event_id)

    assert response.status_code == 409
    assert response.json == {"error": "Only submitted events can be assigned an Event Coordinator."}
    assert stored_request(app, event_id)[0] == status
    assert history_count(app, event_id) == 0


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            {"coordinator_account_id": VENUE_STAFF},
            "Choose an active Event Coordinator from the list.",
        ),
        (
            {"coordinator_account_id": INACTIVE_COORDINATOR},
            "Choose an active Event Coordinator from the list.",
        ),
        ({"coordinator_account_id": "not-an-account"}, "Choose an Event Coordinator."),
        ({"coordinator_account_id": 23}, "Choose an Event Coordinator."),
        ({}, "Choose an Event Coordinator."),
        (
            {"coordinator_account_id": ALICE, "status": "approved"},
            "Unexpected assignment field: status.",
        ),
    ],
)
def test_invalid_coordinator_choices_are_rejected(app, client, body, expected):
    event_id = add_request(app)

    response = client.post(
        f"/api/event-requests/{event_id}/coordinator", json=body, headers=headers()
    )

    assert response.status_code == 400
    assert response.json == {"error": expected}
    assert stored_request(app, event_id)[0] == SUBMITTED


def test_unknown_requests_are_not_found(client):
    for method, path, body in ENDPOINTS[1:]:
        response = getattr(client, method)(path.format(event_id=999), json=body, headers=headers())
        assert response.status_code == 404, path
        assert response.json == {"error": "Event request not found."}


def test_tc_e05_s2_10_single_active_coordinator_is_the_only_option(app, client):
    event_id = add_request(app)
    deactivate(app, BOB, CAROL)

    assert options(client, event_id).json["coordinators"] == [{"id": ALICE, "name": "Alice Tan"}]
    assert assign(client, event_id, ALICE).status_code == 201


# SPL-61 / CS-E05-S3: reassign an Event Coordinator


def test_tc_e05_s3_01_reassignment_moves_responsibility_and_keeps_status(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    response = reassign(client, event_id, BOB)

    assert response.status_code == 200
    assignment = response.json["assignment"]
    assert assignment["coordinator"] == {"id": BOB, "name": "Bob Lim"}
    assert assignment["status"] == SUBMITTED
    assert holds_event(app, event_id, BOB)
    assert not holds_event(app, event_id, ALICE)
    latest = history(client, event_id).json["history"][-1]
    assert latest["previous_coordinator"] == {"id": ALICE, "name": "Alice Tan"}
    assert latest["new_coordinator"] == {"id": BOB, "name": "Bob Lim"}
    assert latest["changed_by"] == {"id": MANAGER, "name": "Morgan Manager"}
    assert latest["changed_at"] == assignment["assigned_at"]


def test_tc_e05_s3_06b_organiser_sees_the_new_coordinator_in_place_of_the_previous_one(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    assert reassign(client, event_id, BOB).status_code == 200

    assert organiser_view(client, event_id).json["event_request"]["coordinator"] == {
        "id": BOB,
        "name": "Bob Lim",
    }


@pytest.mark.parametrize("status", ["completed", "cancelled", "rejected", "withdrawn"])
def test_tc_e05_s3_02_to_04_closed_requests_cannot_be_reassigned(app, client, status):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    set_status(app, event_id, status)

    response = reassign(client, event_id, BOB)

    assert response.status_code == 409
    assert response.json == {
        "error": "Completed, cancelled, rejected or withdrawn events cannot be reassigned."
    }
    assert holds_event(app, event_id, ALICE)
    assert history_count(app, event_id) == 1


def test_tc_e05_s3_06_picker_excludes_the_current_coordinator(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    response = options(client, event_id)

    assert response.json == {
        "coordinators": [{"id": BOB, "name": "Bob Lim"}, {"id": CAROL, "name": "Carol Ng"}],
        "current_coordinator": {"id": ALICE, "name": "Alice Tan"},
        "unavailable_reason": None,
    }


def test_tc_e05_s3_07_manager_is_told_why_when_no_other_coordinator_is_active(app, client):
    event_id = add_request(app)
    deactivate(app, BOB, CAROL)
    assert assign(client, event_id, ALICE).status_code == 201

    picker = options(client, event_id)
    response = reassign(client, event_id, BOB)

    assert picker.json["coordinators"] == []
    assert picker.json["unavailable_reason"] == NO_OTHER_COORDINATOR_AVAILABLE
    assert response.status_code == 409
    assert response.json == {"error": NO_OTHER_COORDINATOR_AVAILABLE}
    assert holds_event(app, event_id, ALICE)


def test_tc_e05_s3_08_history_reads_chronologically_across_reassignments(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    assert reassign(client, event_id, BOB).status_code == 200
    assert reassign(client, event_id, CAROL).status_code == 200

    entries = history(client, event_id).json["history"]

    handovers = [
        (
            entry["previous_coordinator"] and entry["previous_coordinator"]["name"],
            entry["new_coordinator"]["name"],
        )
        for entry in entries
    ]
    assert handovers == [(None, "Alice Tan"), ("Alice Tan", "Bob Lim"), ("Bob Lim", "Carol Ng")]
    assert [entry["changed_at"] for entry in entries] == sorted(
        entry["changed_at"] for entry in entries
    )


@pytest.mark.parametrize("status", [UNDER_REVIEW, "approved"])
def test_tc_e05_s3_09_reassignment_never_changes_status(app, client, status):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201
    set_status(app, event_id, status)

    response = reassign(client, event_id, BOB)

    assert response.status_code == 200
    assert response.json["assignment"]["status"] == status
    assert stored_request(app, event_id)[0] == status


def test_tc_e05_s3_12_single_other_coordinator_is_the_only_option(app, client):
    event_id = add_request(app)
    deactivate(app, CAROL)
    assert assign(client, event_id, ALICE).status_code == 201

    assert options(client, event_id).json["coordinators"] == [{"id": BOB, "name": "Bob Lim"}]
    assert reassign(client, event_id, BOB).status_code == 200


def test_tc_e05_s3_13_request_without_a_coordinator_cannot_be_reassigned(app, client):
    event_id = add_request(app)

    response = reassign(client, event_id, BOB)

    assert response.status_code == 409
    assert response.json == {
        "error": "This event has no Event Coordinator to reassign. Assign one first."
    }
    assert history_count(app, event_id) == 0


def test_reassigning_to_the_current_coordinator_is_rejected(app, client):
    event_id = add_request(app)
    assert assign(client, event_id, ALICE).status_code == 201

    response = reassign(client, event_id, ALICE)

    assert response.status_code == 400
    assert response.json == {"error": "Choose a different Event Coordinator from the current one."}
    assert history_count(app, event_id) == 1
