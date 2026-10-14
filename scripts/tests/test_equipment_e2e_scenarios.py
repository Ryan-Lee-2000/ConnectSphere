"""Shared equipment E2E data must satisfy the real coordinator and availability APIs."""

import runpy
import sys
from datetime import date, time
from pathlib import Path

import pytest
from app import create_app
from app.models import Account, AccountRole, Base, EquipmentType, EventRequest, Organisation, Role
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
NORTHSTAR = "E2E SPL-90 Northstar Leadership Retreat"
STUDIO = "E2E SPL-95 Civic Arts Open Studio"
ACTORS = {
    "organiser": ("developer@example.test", Role.EVENT_ORGANISER),
    "technical": ("technical.support@example.test", Role.TECHNICAL_SUPPORT_STAFF),
    "coordinator": ("event.coordinator@example.test", Role.EVENT_COORDINATOR),
    "manager": ("operations.manager@example.test", Role.EVENT_OPERATIONS_MANAGER),
}
IDS = {name: f"00000000-0000-0000-0000-{index:012d}" for index, name in enumerate(ACTORS, 1)}


@pytest.fixture
def fixture_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'fixtures.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("ATTACH DATABASE ':memory:' AS auth")
        connection.execute("CREATE TABLE auth.users (id TEXT PRIMARY KEY, email TEXT)")
        for name, (email, _) in ACTORS.items():
            connection.execute("INSERT INTO auth.users VALUES (?, ?)", (IDS[name], email))
        connection.commit()

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organisation(id=1, name="Fixture client"))
        session.flush()
        for name, (_, role) in ACTORS.items():
            session.add(Account(id=IDS[name], display_name=name, organisation_id=1))
            session.flush()
            session.add(AccountRole(account_id=IDS[name], role=role.value))
        # A second coordinator sorts first: selecting the first account with the role is wrong.
        decoy = "00000000-0000-0000-0000-000000000000"
        session.add(Account(id=decoy, display_name="Other coordinator"))
        session.flush()
        session.add(AccountRole(account_id=decoy, role=Role.EVENT_COORDINATOR.value))
        session.add(
            EventRequest(
                organiser_account_id=IDS["organiser"],
                organisation_id=1,
                name="Northstar Leadership Retreat",
                purpose="Keep real developer data",
                proposed_date=date(2030, 10, 20),
                start_time=time(9),
                end_time=time(12),
                expected_attendance=20,
                status="planning",
            )
        )
        session.add(
            EquipmentType(
                name="Wireless Microphone", normalised_name="wireless microphone", total_stock=1
            )
        )
        session.commit()
    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture:fixture@127.0.0.1/fixture")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    for key in (
        "VITE_LOCAL_DEMO_EMAIL",
        "VITE_LOCAL_DEMO_TECHNICAL_SUPPORT_EMAIL",
        "VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL",
        "VITE_LOCAL_DEMO_OPERATIONS_MANAGER_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    yield engine


def prepare():
    runpy.run_path(str(ROOT / "scripts/prepare_e2e_equipment.py"), run_name="__main__")


def test_shared_fixtures_are_visible_and_have_expected_availability(fixture_database):
    prepare()
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": str(fixture_database.url),
            "IDENTITY_VERIFIER": IDS.__getitem__,
        }
    )
    app.extensions["engine"] = fixture_database
    client = app.test_client()
    assigned = client.get(
        "/api/event-requests/assigned", headers={"Authorization": "Bearer coordinator"}
    )
    assert assigned.status_code == 200
    planning = next(item for item in assigned.json["events"] if item["name"] == NORTHSTAR)
    assert planning["status"] == "planning"
    editor = client.get(
        f"/api/event-requests/{planning['id']}/equipment-requirements",
        headers={"Authorization": "Bearer coordinator"},
    )
    assert editor.status_code == 200
    assert editor.json["technical_support_staff"]
    availability = client.get(
        "/api/equipment-availability", headers={"Authorization": "Bearer technical"}
    )
    assert availability.status_code == 200
    rows = {item["event"]["name"]: item for item in availability.json["assessments"]}
    retreat = rows[NORTHSTAR]
    assert (retreat["required_quantity"], retreat["reserved_quantity"], retreat["shortfall"]) == (
        6,
        0,
        0,
    )
    assert (retreat["commitment_start"], retreat["commitment_end"]) == ("2030-10-19", "2030-10-20")
    studio = rows[STUDIO]
    assert studio["requirement_status"] == "partially_reserved"
    assert (
        studio["required_quantity"],
        studio["reserved_quantity"],
        studio["available_to_reserve"],
        studio["shortfall"],
    ) == (12, 10, 0, 2)
    assert rows["E2E SPL-97 Feasible review"]["overcommitted_units"] == 0
    assert rows["E2E SPL-97 Infeasible review"]["overcommitted_units"] == 1
    assert rows["E2E SPL-97 Partial reservation"]["available_to_reserve"] == 10


def test_prepare_twice_and_cleanup_preserve_unrelated_records(fixture_database):
    prepare()
    prepare()
    with Session(fixture_database) as session:
        names = list(session.scalars(select(EventRequest.name)))
        assert names.count(NORTHSTAR) == 1
        assert names.count(STUDIO) == 1
        assert len(names) == 6
    runpy.run_path(str(ROOT / "scripts/cleanup_e2e_venues.py"), run_name="__main__")
    with Session(fixture_database) as session:
        assert list(session.scalars(select(EventRequest.name))) == ["Northstar Leadership Retreat"]
        assert list(session.scalars(select(EquipmentType.name))) == ["Wireless Microphone"]
        assert session.scalar(text("SELECT count(*) FROM equipment_reservations")) == 0
        assert session.scalar(text("SELECT count(*) FROM event_coordinator_assignments")) == 0
    prepare()
    with Session(fixture_database) as session:
        assert len(list(session.scalars(select(EventRequest.name)))) == 6


def test_missing_configured_coordinator_refuses_before_replacing_data(
    fixture_database, monkeypatch
):
    prepare()
    with Session(fixture_database) as session:
        before = list(session.execute(select(EventRequest.id, EventRequest.name)))
    monkeypatch.setenv("VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL", "missing@example.test")
    with pytest.raises(SystemExit, match="event_coordinator Auth fixture"):
        prepare()
    with Session(fixture_database) as session:
        assert list(session.execute(select(EventRequest.id, EventRequest.name))) == before


def test_configured_coordinator_email_is_used(fixture_database, monkeypatch):
    with fixture_database.begin() as connection:
        connection.execute(
            text("UPDATE auth.users SET email = :email WHERE id = :id"),
            {"email": "custom.coordinator@example.test", "id": IDS["coordinator"]},
        )
    monkeypatch.setenv("VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL", "custom.coordinator@example.test")
    prepare()
    with Session(fixture_database) as session:
        assert session.scalar(text("SELECT count(*) FROM event_coordinator_assignments")) == 5
