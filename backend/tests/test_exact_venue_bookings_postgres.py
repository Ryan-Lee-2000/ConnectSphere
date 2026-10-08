"""SPL-137 real PostgreSQL transaction races; each case owns a disposable database."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timezone
from time import monotonic, sleep

import pytest
from app import create_app
from app.models import (
    EventCoordinatorAssignment,
    EventRequest,
    Venue,
    VenueBooking,
    VenueBookingStatusHistory,
)
from sqlalchemy import event as sql_event
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_venue_booking_approval_postgres import _seed_accounts
from test_venue_booking_approval_postgres import pg_url as isolated_pg_url

pg_url = isolated_pg_url

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"), reason="Requires disposable PostgreSQL"
)


@pytest.fixture
def scenario(pg_url):
    app = create_app({"TESTING": True, "DATABASE_URL": pg_url, "EXACT_VENUE_TIMING_ENABLED": True})
    engine = app.extensions["engine"]
    ids, org, venue_id = _seed_accounts(engine)
    app.config["IDENTITY_VERIFIER"] = ids.__getitem__
    with Session(engine) as session:
        venue = session.get(Venue, venue_id)
        venue.setup_minutes = 30
        venue.turnaround_minutes = 45
        venue.operating_intervals = [[0, 1440]]
        venue.timing_revision = 1
        events = []
        for number in range(2):
            row = EventRequest(
                organiser_account_id=ids["organiser"],
                organisation_id=org,
                name=f"Exact race {number}",
                status="planning",
                proposed_date=datetime(2026, 10, 14).date(),
                start_time=time(10),
                end_time=time(12),
                expected_attendance=100,
            )
            session.add(row)
            session.flush()
            session.add(
                EventCoordinatorAssignment(
                    event_request_id=row.id,
                    coordinator_account_id=ids["coordinator"],
                    assigned_by_account_id=ids["manager"],
                    assigned_at=datetime.now(timezone.utc),
                )
            )
            events.append(row.id)
        session.commit()
    yield app, venue_id, events, ids
    engine.dispose()


def headers(token="coordinator"):
    return {"Authorization": f"Bearer {token}"}


def request_call(event, venue, **changes):
    data = {
        "venue_id": venue,
        "layout": "theatre",
        "date": "2026-10-14",
        "start_time": "10:00",
        "end_time": "12:00",
        "venue_revision": 1,
    }
    data.update(changes)
    return lambda client: client.post(
        f"/api/event-requests/{event}/venue-bookings", headers=headers(), json=data
    )


def approve_call(booking):
    return lambda client: client.post(
        f"/api/venue-bookings/{booking}/approve", headers=headers("staff-a"), json={}
    )


def block_call(venue):
    return lambda client: client.post(
        f"/api/venues/{venue}/operational-blocks",
        headers=headers("staff-a"),
        json={"start_date": "2026-10-14", "slots": ["AM"], "reason": "Maintenance"},
    )


def ordered_race(app, first, second):
    """Hold first immediately before commit; prove second really waits on a PG lock."""
    engine = app.extensions["engine"]
    held = threading.Event()
    release = threading.Event()
    thread_ids = {}
    pids = {}

    def before_commit(conn):
        if threading.get_ident() == thread_ids.get("first"):
            held.set()
            assert release.wait(10), "Race driver did not release first writer"

    def observe(conn, cursor, statement, params, context, many):
        if (
            threading.get_ident() == thread_ids.get("second")
            and "FOR " in statement
            and "SELECT" in statement
        ):
            pids["second"] = conn.connection.driver_connection.info.backend_pid

    def run(label, call):
        thread_ids[label] = threading.get_ident()
        response = call(app.test_client())
        return response.status_code, response.json

    sql_event.listen(engine, "commit", before_commit)
    sql_event.listen(engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(run, "first", first)
            assert held.wait(10), "First writer never reached commit"
            b = pool.submit(run, "second", second)
            try:
                deadline = monotonic() + 8
                blocked = False
                while monotonic() < deadline:
                    if "second" in pids:
                        with engine.connect() as conn:
                            blocked = bool(
                                conn.scalar(
                                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                    {"pid": pids["second"]},
                                )
                            )
                        if blocked:
                            break
                    sleep(0.01)
                assert blocked, "Second writer did not wait on the shared boundary"
            finally:
                release.set()
            return a.result(timeout=10), b.result(timeout=10)
    finally:
        release.set()
        sql_event.remove(engine, "commit", before_commit)
        sql_event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("overlap", [True, False])
def test_tc_07_requests_share_boundary_and_loser_leaves_no_history(scenario, overlap):
    app, venue, events, _ = scenario
    if not overlap:
        with Session(app.extensions["engine"]) as session:
            event = session.get(EventRequest, events[1])
            event.start_time, event.end_time = time(13, 15), time(14)
            session.commit()
    later = {} if overlap else {"start_time": "13:15", "end_time": "14:00"}
    a, b = ordered_race(
        app, request_call(events[0], venue), request_call(events[1], venue, **later)
    )
    assert a[0] == 201
    assert b[0] == (409 if overlap else 201), b
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count(VenueBooking.id))) == (1 if overlap else 2)
        assert session.scalar(select(func.count(VenueBookingStatusHistory.id))) == (
            1 if overlap else 2
        )


@pytest.mark.parametrize("operation", ["request", "approve"])
@pytest.mark.parametrize("block_first", [True, False])
def test_tc_08_block_races_both_orders(scenario, operation, block_first):
    app, venue, events, _ = scenario
    booking = None
    call = request_call(events[0], venue)
    if operation == "approve":
        booking = call(app.test_client()).json["booking"]["id"]
        call = approve_call(booking)
    first, second = (block_call(venue), call) if block_first else (call, block_call(venue))
    a, b = ordered_race(app, first, second)
    if block_first:
        assert a[0] == 201 and b[0] == 409, (a, b)
    else:
        assert a[0] == (200 if operation == "approve" else 201) and b[0] == 201, (a, b)
        booking = a[1]["booking"]["id"]
        read = (
            app.test_client().get(f"/api/venue-bookings/{booking}", headers=headers("staff-a")).json
        )
        assert read["review"]["requires_review"]
        assert read["booking"]["review_reasons"]


@pytest.mark.parametrize("operation", ["request", "approve"])
def test_tc_09_configuration_first_refuses_stale_operation(scenario, operation):
    app, venue, events, _ = scenario
    call = request_call(events[0], venue)
    if operation == "approve":
        booking = call(app.test_client()).json["booking"]["id"]
        call = approve_call(booking)

    def configure(client):
        return client.patch(
            f"/api/venues/{venue}",
            headers=headers("staff-a"),
            json={
                "setup_minutes": 60,
                "turnaround_minutes": 45,
                "operating_intervals": [[0, 1440]],
            },
        )

    a, b = ordered_race(app, configure, call)
    assert a[0] == 200 and b[0] == 409, (a, b)


def test_tc_09_approval_then_withdrawal_has_one_terminal_outcome(scenario):
    app, venue, events, _ = scenario
    booking = request_call(events[0], venue)(app.test_client()).json["booking"]["id"]

    def withdraw(client):
        return client.post(
            f"/api/event-requests/{events[0]}/venue-bookings/{booking}/withdraw", headers=headers()
        )

    a, b = ordered_race(app, approve_call(booking), withdraw)
    assert a[0] == 200 and b[0] == 409, (a, b)


def test_tc_11_concurrent_cancellations_release_once(scenario):
    from types import SimpleNamespace

    from app.exact_venue_bookings import cancel_booking
    from werkzeug.exceptions import HTTPException

    app, venue, events, ids = scenario
    booking = request_call(events[0], venue)(app.test_client()).json["booking"]["id"]
    assert approve_call(booking)(app.test_client()).status_code == 200

    def cancel(_client):
        with Session(app.extensions["engine"]) as session:
            try:
                result = cancel_booking(
                    session,
                    booking,
                    coordinator_id=ids["coordinator"],
                    changed_at=datetime.now(timezone.utc),
                )
                session.commit()
                return SimpleNamespace(status_code=200, json={"status": result.status})
            except HTTPException as exc:
                session.rollback()
                return SimpleNamespace(status_code=exc.code, json={"error": str(exc)})

    a, b = ordered_race(app, cancel, cancel)
    assert a[0] == 200 and b[0] == 409, (a, b)
    with Session(app.extensions["engine"]) as session:
        assert (
            session.scalar(
                select(func.count(VenueBookingStatusHistory.id)).where(
                    VenueBookingStatusHistory.action == "cancel"
                )
            )
            == 1
        )
    assert request_call(events[1], venue)(app.test_client()).status_code == 201


def test_tc_02_09_reassignment_history_can_finish_while_request_waits(scenario):
    """The assignment FK must not deadlock with the request's event lock."""
    import uuid

    from app.models import Account, AccountRole, EventCoordinatorHistory, Role

    app, venue, events, ids = scenario
    engine = app.extensions["engine"]
    new_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(Account(id=new_id, display_name="New coordinator"))
        session.add(AccountRole(account_id=new_id, role=Role.EVENT_COORDINATOR.value))
        session.commit()
    reached = threading.Event()

    def observe(conn, cursor, statement, params, context, many):
        if "event_coordinator_assignments" in statement and "FOR UPDATE" in statement:
            reached.set()

    sql_event.listen(engine, "before_cursor_execute", observe)
    try:
        with Session(engine) as reassign:
            assignment = reassign.get(EventCoordinatorAssignment, events[0])
            assignment.coordinator_account_id = new_id
            reassign.flush()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(request_call(events[0], venue), app.test_client())
                assert reached.wait(10)
                reassign.add(
                    EventCoordinatorHistory(
                        event_request_id=events[0],
                        previous_coordinator_account_id=ids["coordinator"],
                        new_coordinator_account_id=new_id,
                        changed_by_account_id=ids["manager"],
                        changed_at=datetime.now(timezone.utc),
                    )
                )
                reassign.commit()
                assert pending.result(timeout=10).status_code == 404
        with Session(engine) as session:
            assert session.scalar(select(func.count(VenueBooking.id))) == 0
    finally:
        sql_event.remove(engine, "before_cursor_execute", observe)
