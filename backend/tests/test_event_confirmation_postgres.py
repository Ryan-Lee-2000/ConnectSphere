"""PostgreSQL evidence for SPL-85 (CS-E07-S3): concurrent confirmation and the migration.

SQLite serialises writes, so it cannot show a race. These cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL). Each test builds its own throw-away database on
that server, migrates it with Alembic (so the new migration is exercised), and drops it afterwards.
"""

import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone

import pytest
from app import create_app
from app.equipment_reservation_state import remaining_quantity
from app.models import (
    Account,
    AccountRole,
    EquipmentRequirement,
    EquipmentReservation,
    EquipmentType,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3
STAMP = datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def pg_url():
    server = make_url(os.environ["INTEGRATION_DATABASE_URL"])
    name = f"spl85_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    try:
        upgraded = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        assert upgraded.returncode == 0, upgraded.stderr
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def engine(pg_url):
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


def _seed_accounts(engine):
    roles = {
        "coordinator": Role.EVENT_COORDINATOR,
        "lead": Role.EVENT_OPERATIONS_MANAGER,
        "organiser": Role.EVENT_ORGANISER,
        "technical": Role.TECHNICAL_SUPPORT_STAFF,
        "staff": Role.VENUE_STAFF,
    }
    ids = {name: str(uuid.uuid4()) for name in roles}
    with Session(engine) as session:
        organisation = Organisation(name=f"SPL-85 client {uuid.uuid4()}")
        session.add(organisation)
        session.flush()
        for name, role in roles.items():
            session.add(Account(id=ids[name], display_name=name, organisation_id=organisation.id))
            session.add(AccountRole(account_id=ids[name], role=role.value))
        venue = Venue(
            name="Race Hall",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(venue)
        stock = EquipmentType(
            name="Race Microphone",
            normalised_name=f"race microphone {uuid.uuid4()}",
            total_stock=40,
        )
        session.add(stock)
        session.commit()
        return ids, organisation.id, venue.id, stock.id


def _seed_ready_event(engine, ids, organisation_id, venue_id, type_id, day):
    """A Planning event with an Approved booking and an Essential line reserved 4 of 4."""

    with Session(engine) as session:
        planning_event = EventRequest(
            organiser_account_id=ids["organiser"],
            organisation_id=organisation_id,
            name=f"Confirmation race {day.isoformat()}",
            purpose="Concurrency proof",
            proposed_date=day,
            start_time=time(13),
            end_time=time(18),
            expected_attendance=100,
            status="planning",
        )
        session.add(planning_event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=planning_event.id,
                coordinator_account_id=ids["coordinator"],
                assigned_by_account_id=ids["lead"],
                assigned_at=STAMP,
            )
        )
        session.add(
            VenueBooking(
                event_request_id=planning_event.id,
                venue_id=venue_id,
                status="approved",
                layout="theatre",
                expected_attendance=100,
                booking_date=day,
                event_slots=["PM"],
                requested_by_account_id=ids["coordinator"],
                requested_at=STAMP,
                approved_by_account_id=ids["staff"],
                approved_at=STAMP,
            )
        )
        line = EquipmentRequirement(
            event_request_id=planning_event.id,
            equipment_type="Microphones",
            equipment_type_id=type_id,
            quantity=4,
            required_start_date=day,
            required_end_date=day,
            status="reserved",
            essentiality="essential",
        )
        session.add(line)
        session.flush()
        session.add(
            EquipmentReservation(
                event_request_id=planning_event.id,
                equipment_requirement_id=line.id,
                equipment_type_id=type_id,
                commitment_start_date=day - timedelta(days=1),
                commitment_end_date=day + timedelta(days=1),
                quantity=4,
                reserved_by_account_id=ids["technical"],
                reserved_at=STAMP,
            )
        )
        session.commit()
        return planning_event.id, line.id


def _race(app, calls):
    """Run the calls together, holding each until it is about to take its first row lock."""

    app_engine = app.extensions["engine"]
    barrier = threading.Barrier(len(calls), timeout=10)
    released: set[int] = set()
    guard = threading.Lock()

    def align(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "FOR UPDATE" not in statement and "FOR NO KEY UPDATE" not in statement:
            return
        with guard:
            if threading.get_ident() in released:
                return
            released.add(threading.get_ident())
        barrier.wait()

    def run(call):
        response = call(app.test_client())
        return response.status_code, response.json

    event.listen(app_engine, "before_cursor_execute", align)
    try:
        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            return list(executor.map(run, calls))
    finally:
        event.remove(app_engine, "before_cursor_execute", align)


def _confirm(event_id):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/confirm", headers={"Authorization": "Bearer coordinator"}
    )


def _release_one(line_id):
    return lambda client: client.post(
        f"/api/equipment-requirements/{line_id}/releases",
        json={"quantity": 1, "reason": "One microphone is needed elsewhere."},
        headers={"Authorization": "Bearer technical"},
    )


def _app(pg_url, ids):
    return create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )


# TC-SPL-85-20 — AC5: two simultaneous confirmations produce one Confirmed event and one audit row.
def test_tc_spl_85_20_concurrent_confirmations_exactly_one_succeeds(engine, pg_url):
    ids, organisation_id, venue_id, type_id = _seed_accounts(engine)
    app = _app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2026, 11, 2) + timedelta(days=run)
            event_id, _ = _seed_ready_event(engine, ids, organisation_id, venue_id, type_id, day)

            results = _race(app, [_confirm(event_id), _confirm(event_id)])

            assert sorted(status for status, _ in results) == [200, 409], results
            refused = next(body for status, body in results if status == 409)
            assert refused["error"] == "Only an event in Planning can be confirmed."
            with Session(engine) as session:
                stored = session.get(EventRequest, event_id)
                assert stored.status == "confirmed"
                assert stored.confirmed_by_account_id == ids["coordinator"]
                confirmations = session.scalar(
                    select(func.count(EventStatusHistory.id)).where(
                        EventStatusHistory.event_request_id == event_id,
                        EventStatusHistory.action == "confirm",
                    )
                )
                assert confirmations == 1
    finally:
        app.extensions["engine"].dispose()


# TC-SPL-85-21 — AC3: confirmation racing an essential-unit release never confirms a shortfall.
def test_tc_spl_85_21_confirmation_racing_a_release_has_one_consistent_outcome(engine, pg_url):
    ids, organisation_id, venue_id, type_id = _seed_accounts(engine)
    app = _app(pg_url, ids)
    outcomes = set()
    try:
        for run in range(RUNS):
            day = date(2026, 12, 2) + timedelta(days=run)
            event_id, line_id = _seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )

            (confirm_status, confirm_body), (release_status, _) = _race(
                app, [_confirm(event_id), _release_one(line_id)]
            )

            with Session(engine) as session:
                stored = session.get(EventRequest, event_id)
                line = session.get(EquipmentRequirement, line_id)
                retained = sum(remaining_quantity(item) for item in line.reservations)
                if confirm_status == 200:
                    assert release_status == 409
                    assert (stored.status, retained) == ("confirmed", 4)
                    outcomes.add("confirmed first")
                else:
                    assert release_status == 201
                    assert confirm_status == 409
                    assert [b["code"] for b in confirm_body["blockers"]] == [
                        "essential_not_fully_reserved"
                    ]
                    assert (stored.status, retained) == ("planning", 3)
                    outcomes.add("released first")
        assert outcomes  # every run ended in one of the two consistent states
    finally:
        app.extensions["engine"].dispose()


def _pause(monkeypatch, name):
    """Hold a coordinator equipment request at ``name``, after it has checked the event is in
    Planning, until the test resumes it. Returns (reached, resume) events."""

    import app.equipment_requirements as module

    original = getattr(module, name)
    reached, resume = threading.Event(), threading.Event()

    def held(*args, **kwargs):
        reached.set()
        assert resume.wait(30), "the paused request was never resumed"
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, held)
    return reached, resume


def _interleave(app, paused_call, reached, resume, event_id):
    """Start ``paused_call``; once it is held, start a confirmation and give it a chance to finish
    before the held request resumes. Returns (paused result, confirm result, confirm finished
    while the other request was still held)."""

    def run(call):
        response = call(app.test_client())
        return response.status_code, response.json

    with ThreadPoolExecutor(max_workers=2) as executor:
        paused = executor.submit(run, paused_call)
        assert reached.wait(15), "the equipment request never reached its pause point"
        confirming = executor.submit(run, _confirm(event_id))
        try:
            confirming.result(timeout=3)
        except TimeoutError:
            pass  # expected once both requests share the event lock: confirmation is waiting
        finished_while_held = confirming.done()
        resume.set()
        return paused.result(timeout=30), confirming.result(timeout=30), finished_while_held


# TC-SPL-85-27 — AC3 (Clive's review of PR #86): a coordinator adding an Essential line while the
# event is being confirmed. Both must share the event lock, so confirmation either sees the new
# unreserved line and refuses, or the add sees Confirmed and is refused. Never both succeed.
def test_tc_spl_85_27_confirmation_racing_a_new_essential_line(engine, pg_url, monkeypatch):
    ids, organisation_id, venue_id, type_id = _seed_accounts(engine)
    app = _app(pg_url, ids)
    try:
        day = date(2027, 1, 12)
        event_id, _ = _seed_ready_event(engine, ids, organisation_id, venue_id, type_id, day)
        reached, resume = _pause(monkeypatch, "_new_attributes")

        def add_essential_line(client):
            return client.post(
                f"/api/event-requests/{event_id}/equipment-requirements",
                json={
                    "equipment_type_id": type_id,
                    "quantity": 4,
                    "required_start_date": day.isoformat(),
                    "required_end_date": day.isoformat(),
                    "essentiality": "essential",
                    "consulted_technical_support_account_id": ids["technical"],
                    "essentiality_decision_note": "Needed for the second stage.",
                },
                headers={"Authorization": "Bearer coordinator"},
            )

        (add_status, _), (confirm_status, confirm_body), finished_while_held = _interleave(
            app, add_essential_line, reached, resume, event_id
        )

        assert finished_while_held is False, "confirmation did not wait for the equipment write"
        assert add_status == 201
        assert confirm_status == 409, confirm_body
        assert "essential_not_fully_reserved" in [b["code"] for b in confirm_body["blockers"]]
        with Session(engine) as session:
            assert session.get(EventRequest, event_id).status == "planning"
    finally:
        app.extensions["engine"].dispose()


# TC-SPL-85-28 — AC3/AC4 (Clive's review of PR #86): a coordinator edit that invalidates the
# reservation (quantity 4 -> 6 releases the held units and flags Review required) racing
# confirmation. The edit validated Planning before waiting for its line lock; it must instead hold
# the event lock, so confirmation observes the released, review-flagged line.
def test_tc_spl_85_28_confirmation_racing_a_reservation_invalidating_edit(
    engine, pg_url, monkeypatch
):
    ids, organisation_id, venue_id, type_id = _seed_accounts(engine)
    app = _app(pg_url, ids)
    try:
        day = date(2027, 1, 19)
        event_id, line_id = _seed_ready_event(engine, ids, organisation_id, venue_id, type_id, day)
        reached, resume = _pause(monkeypatch, "_locked_editable_requirement")

        def enlarge_line(client):
            return client.patch(
                f"/api/event-requests/{event_id}/equipment-requirements/{line_id}",
                json={"quantity": 6},
                headers={"Authorization": "Bearer coordinator"},
            )

        (edit_status, _), (confirm_status, confirm_body), finished_while_held = _interleave(
            app, enlarge_line, reached, resume, event_id
        )

        assert finished_while_held is False, "confirmation did not wait for the equipment write"
        assert edit_status == 200
        assert confirm_status == 409, confirm_body
        with Session(engine) as session:
            stored = session.get(EventRequest, event_id)
            line = session.get(EquipmentRequirement, line_id)
            assert stored.status == "planning"
            assert line.quantity == 6
    finally:
        app.extensions["engine"].dispose()


# Migration evidence: the two columns are nullable, the confirmer is an account, and the pair is
# enforced together by the database, not only by the route.
def test_tc_spl_85_16_migration_adds_paired_confirmation_columns(engine):
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("event_requests")}
    assert columns["confirmed_by_account_id"]["nullable"] is True
    assert columns["confirmed_at"]["nullable"] is True
    assert any(
        foreign_key["constrained_columns"] == ["confirmed_by_account_id"]
        and foreign_key["referred_table"] == "accounts"
        for foreign_key in inspector.get_foreign_keys("event_requests")
    )
    checks = {check["name"] for check in inspector.get_check_constraints("event_requests")}
    assert "ck_event_requests_confirmation_complete" in checks
