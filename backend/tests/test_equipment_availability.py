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
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

TECHNICAL_SUPPORT = "11111111-1111-4111-8111-111111111111"
OUTSIDER = "22222222-2222-4222-8222-222222222222"


@pytest.fixture()
def client(tmp_path):
    """Create a planning requirement mapped to stock for every route-level test."""

    database_url = f"sqlite:///{tmp_path}/equipment-availability.db"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(id=1, name="Northstar Community Partners")
        technical_support = Account(id=TECHNICAL_SUPPORT, display_name="Taylor Goh", is_active=True)
        outsider = Account(id=OUTSIDER, display_name="Outside User", is_active=True)
        session.add_all(
            [
                organisation,
                technical_support,
                outsider,
                AccountRole(account_id=TECHNICAL_SUPPORT, role="technical_support_staff"),
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
        session.add_all([event, microphone])
        session.add(
            EquipmentRequirement(
                id=1,
                event_request_id=1,
                equipment_type="Wireless microphones",
                quantity=6,
                equipment_type_id=1,
                required_start_date=date(2026, 10, 15),
                required_end_date=date(2026, 10, 15),
                status="requested",
            )
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


def test_tc_spl_95_001_busiest_day_controls_available_stock():
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


def test_tc_spl_95_002_returned_units_are_available_on_the_following_day():
    """AC1 boundary: commitment includes collection through return, so reuse starts the next day."""

    assert (
        calculate_availability(
            total_stock=4,
            required_quantity=1,
            collection_date=date(2026, 10, 14),
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


def test_tc_spl_95_007_retained_units_are_not_counted_twice_or_turned_into_a_negative_shortfall():
    """AC2/AC3: retained units count once and the shortfall cannot become negative."""

    assessment = calculate_availability(
        total_stock=10,
        required_quantity=8,
        reserved_quantity=3,
        collection_date=date(2026, 10, 14),
        return_date=date(2026, 10, 15),
        reservations_by_day={date(2026, 10, 14): 4},
    )

    assert assessment.available_to_reserve == 6
    assert assessment.shortfall == 0


def test_tc_spl_95_003_endpoint_shows_requirement_quantities_without_creating_a_reservation(client):
    """AC3/AC4: Technical Support sees an assessment and the endpoint remains read-only."""

    response = client.get("/api/equipment-availability", headers=headers())

    assert response.status_code == 200
    line = response.json["assessments"][0]
    assert line["required_quantity"] == 6
    assert line["reserved_quantity"] == 0
    assert line["available_to_reserve"] == 10
    assert line["commitment_start"] == "2026-10-14"
    assert line["commitment_end"] == "2026-10-15"


def test_tc_spl_95_004_only_technical_support_can_read_availability(client):
    """AC4 negative/security: a valid account without Technical Support permission is refused."""

    assert client.get("/api/equipment-availability", headers=headers(OUTSIDER)).status_code == 403
