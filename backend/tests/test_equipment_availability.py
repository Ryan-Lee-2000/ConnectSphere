"""SPL-95 tests for equipment availability calculation and Technical Support access."""

from datetime import date

import pytest
from app import create_app
from app.equipment_availability import calculate_availability
from app.models import (
    Account,
    AccountRole,
    Base,
    EquipmentRequirement,
    EquipmentType,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

TECHNICAL_SUPPORT = "11111111-1111-4111-8111-111111111111"
EVENT_ORGANISER = "22222222-2222-4222-8222-222222222222"
EVENT_COORDINATOR = "33333333-3333-4333-8333-333333333333"
VENUE_STAFF = "44444444-4444-4444-8444-444444444444"
OPERATIONS_MANAGER = "55555555-5555-4555-8555-555555555555"


@pytest.fixture()
def client(tmp_path):
    """Create a planning requirement mapped to stock for every route-level test."""

    database_url = f"sqlite:///{tmp_path}/equipment-availability.db"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(id=1, name="Northstar Community Partners")
        accounts = [
            Account(id=TECHNICAL_SUPPORT, display_name="Taylor Goh", is_active=True),
            Account(id=EVENT_ORGANISER, display_name="Olivia Organiser", is_active=True),
            Account(id=EVENT_COORDINATOR, display_name="Casey Coordinator", is_active=True),
            Account(id=VENUE_STAFF, display_name="Valerie Venue", is_active=True),
            Account(id=OPERATIONS_MANAGER, display_name="Morgan Manager", is_active=True),
        ]
        session.add_all(
            [
                organisation,
                *accounts,
                AccountRole(account_id=TECHNICAL_SUPPORT, role="technical_support_staff"),
                AccountRole(account_id=EVENT_ORGANISER, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=EVENT_COORDINATOR, role=Role.EVENT_COORDINATOR.value),
                AccountRole(account_id=VENUE_STAFF, role=Role.VENUE_STAFF.value),
                AccountRole(
                    account_id=OPERATIONS_MANAGER,
                    role=Role.EVENT_OPERATIONS_MANAGER.value,
                ),
            ]
        )
        event = EventRequest(
            id=1,
            organiser_account_id=TECHNICAL_SUPPORT,
            organisation_id=1,
            name="Community Leadership Forum",
            proposed_date=date(2026, 10, 15),
            expected_attendance=80,
            status="planning",
        )
        microphone = EquipmentType(
            id=1,
            name="Wireless Microphone",
            normalised_name="wireless microphone",
            description="Handheld microphone",
            location="Technical Store",
            total_stock=10,
        )
        confirmed_event = EventRequest(
            id=2,
            organiser_account_id=EVENT_ORGANISER,
            organisation_id=1,
            name="Already Confirmed Conference",
            proposed_date=date(2026, 10, 20),
            expected_attendance=80,
            status="confirmed",
        )
        session.add_all([event, confirmed_event, microphone])
        session.add_all(
            [
                # TC-SPL-95-06 fixture: an assessable line returned by the route.
                EquipmentRequirement(
                    id=1,
                    event_request_id=1,
                    equipment_type="Wireless microphones",
                    quantity=6,
                    equipment_type_id=1,
                    required_start_date=date(2026, 10, 15),
                    required_end_date=date(2026, 10, 15),
                    status="requested",
                ),
                # Each following line must remain outside the planning workspace for one reason.
                EquipmentRequirement(
                    id=2,
                    event_request_id=2,
                    equipment_type="Confirmed event microphone",
                    quantity=2,
                    equipment_type_id=1,
                    required_start_date=date(2026, 10, 20),
                    required_end_date=date(2026, 10, 20),
                    status="requested",
                ),
                EquipmentRequirement(
                    id=3,
                    event_request_id=1,
                    equipment_type="Unmapped microphone",
                    quantity=2,
                    status="unmapped",
                ),
                EquipmentRequirement(
                    id=4,
                    event_request_id=1,
                    equipment_type="Removed microphone",
                    quantity=2,
                    equipment_type_id=1,
                    required_start_date=date(2026, 10, 15),
                    required_end_date=date(2026, 10, 15),
                    status="removed",
                ),
                EquipmentRequirement(
                    id=5,
                    event_request_id=1,
                    equipment_type="Undated microphone",
                    quantity=2,
                    equipment_type_id=1,
                    status="requested",
                ),
                # Every active requirement status remains visible as Technical Support work.
                EquipmentRequirement(
                    id=6,
                    event_request_id=1,
                    equipment_type="Partially reserved microphone",
                    quantity=2,
                    equipment_type_id=1,
                    required_start_date=date(2026, 10, 15),
                    required_end_date=date(2026, 10, 15),
                    status="partially_reserved",
                ),
                EquipmentRequirement(
                    id=7,
                    event_request_id=1,
                    equipment_type="Reserved microphone",
                    quantity=2,
                    equipment_type_id=1,
                    required_start_date=date(2026, 10, 15),
                    required_end_date=date(2026, 10, 15),
                    status="reserved",
                ),
                EquipmentRequirement(
                    id=8,
                    event_request_id=1,
                    equipment_type="Review-required microphone",
                    quantity=2,
                    equipment_type_id=1,
                    required_start_date=date(2026, 10, 15),
                    required_end_date=date(2026, 10, 15),
                    status="review_required",
                ),
                EquipmentRequirement(
                    id=9,
                    event_request_id=1,
                    equipment_type="Unavailable microphone",
                    quantity=2,
                    equipment_type_id=1,
                    required_start_date=date(2026, 10, 15),
                    required_end_date=date(2026, 10, 15),
                    status="unavailable",
                ),
            ]
        )
        session.commit()

    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": database_url,
            "IDENTITY_VERIFIER": lambda token: token,
        }
    )
    return app.test_client()


def headers(account_id=TECHNICAL_SUPPORT):
    """Use a test-only verified identity; production roles are always server-owned."""

    return {"Authorization": f"Bearer {account_id}"}


# TC-SPL-95-01 — busiest-day calculation with non-overlapping reservations.
def test_tc_spl_95_01_busiest_day_controls_available_stock():
    """AC1/AC2: availability is the worst daily balance, not a sum across different days."""

    assessment = calculate_availability(
        total_stock=10,
        required_quantity=6,
        collection_date=date(2026, 10, 14),
        return_date=date(2026, 10, 15),
        unavailable_by_day={date(2026, 10, 14): 1},
        reservations_by_day={date(2026, 10, 14): 4, date(2026, 10, 15): 4},
    )

    assert assessment.busiest_day == date(2026, 10, 14)
    assert assessment.available_to_reserve == 5
    assert assessment.shortfall == 1


# TC-SPL-95-02 — adjacent D-1 collection boundary after a return day.
def test_tc_spl_95_02_returned_units_are_available_for_collection_from_the_following_day():
    """AC1 boundary: a return on the 15th blocks collection on the 15th, not on the 16th.

    Collection on the 16th represents an event whose required-use date is the 17th. This makes the
    D-1 rule explicit instead of labelling the required-use date as the availability boundary.
    """

    assert (
        calculate_availability(
            total_stock=4,
            required_quantity=1,
            collection_date=date(2026, 10, 15),
            return_date=date(2026, 10, 15),
            reservations_by_day={date(2026, 10, 15): 4},
        ).available_to_reserve
        == 0
    )
    assert (
        calculate_availability(
            total_stock=4,
            required_quantity=1,
            collection_date=date(2026, 10, 16),
            return_date=date(2026, 10, 16),
            reservations_by_day={date(2026, 10, 15): 4},
        ).available_to_reserve
        == 4
    )


# TC-SPL-95-03 — own retained units occupy stock once and reduce the remaining need once.
def test_tc_spl_95_03_retained_units_do_not_hide_a_real_shortfall():
    """AC2/AC3: all reservations include this line's three retained units exactly once."""

    assessment = calculate_availability(
        total_stock=10,
        required_quantity=8,
        reserved_quantity=3,
        collection_date=date(2026, 10, 14),
        return_date=date(2026, 10, 15),
        reservations_by_day={date(2026, 10, 14): 7},
    )

    assert assessment.available_to_reserve == 3
    assert assessment.shortfall == 2


# TC-SPL-95-04 — read-only endpoint presents a mapped planning requirement.
def test_tc_spl_95_04_endpoint_shows_requirement_quantities_without_creating_a_reservation(client):
    """AC3/AC4: Technical Support sees an assessment and the endpoint remains read-only."""

    response = client.get("/api/equipment-availability", headers=headers())

    assert response.status_code == 200
    line = response.json["assessments"][0]
    assert line["required_quantity"] == 6
    assert line["reserved_quantity"] == 0
    assert line["available_to_reserve"] == 10
    assert line["commitment_start"] == "2026-10-14"
    assert line["commitment_end"] == "2026-10-15"


# TC-SPL-95-05 — authentication and every non-Technical-Support staff role are refused.
@pytest.mark.parametrize(
    "account_id",
    [EVENT_ORGANISER, EVENT_COORDINATOR, VENUE_STAFF, OPERATIONS_MANAGER],
)
def test_tc_spl_95_05_only_technical_support_can_read_availability(client, account_id):
    """AC4 negative/security: authentication alone never grants the availability workspace."""

    assert client.get("/api/equipment-availability").status_code == 401
    assert client.get("/api/equipment-availability", headers=headers(account_id)).status_code == 403


# TC-SPL-95-06 — only active, mapped, dated requirements on planning events are actionable.
def test_tc_spl_95_06_endpoint_filters_to_assessable_planning_requirements(client):
    """Scope: each active planning status appears; excluded lines are not staff work."""

    response = client.get("/api/equipment-availability", headers=headers())

    assert response.status_code == 200
    assert [line["requirement_id"] for line in response.json["assessments"]] == [1, 6, 7, 8, 9]


# TC-SPL-95-07 — an exhausted stock pool remains explicit rather than looking healthy.
def test_tc_spl_95_07_overcommitment_is_exposed_separately_from_available_stock():
    """AC3 boundary: availability floors at zero while overcommitment remains visible to staff."""

    assessment = calculate_availability(
        total_stock=4,
        required_quantity=3,
        collection_date=date(2026, 10, 14),
        return_date=date(2026, 10, 15),
        reservations_by_day={date(2026, 10, 14): 6},
    )

    assert assessment.available_to_reserve == 0
    assert assessment.overcommitted_units == 2
    assert assessment.shortfall == 3
