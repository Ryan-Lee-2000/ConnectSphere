"""PostgreSQL evidence for SPL-131: same-venue races, a double cancellation and the migration.

SQLite serialises writes, so it cannot show a race. These cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), reusing SPL-77's throw-away database fixture.
"""

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_venue_booking_requests_postgres as spl77
from app.models import VenueBooking, VenueBookingStatusHistory
from sqlalchemy import event, inspect, select, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3
# SPL-77's throw-away, Alembic-migrated database and its race harness.
pg_url, engine = spl77.pg_url, spl77.engine
_app, _race, _seed = spl77._app, spl77._race, spl77._seed


def _bookings(engine, event_id):
    with Session(engine) as session:
        return session.scalars(
            select(VenueBooking)
            .where(VenueBooking.event_request_id == event_id)
            .order_by(VenueBooking.id)
        ).all()


# TC-SPL-131-28 (BB) AC5: two requests for the same venue at the same moment, for one event
@pytest.mark.parametrize("run", range(RUNS))
def test_tc_spl_131_28_concurrent_same_venue_one_wins(engine, pg_url, run):
    ids, event_ids, venue_ids = _seed(engine, events=["alice"], venues={"Venue A": 0})
    app = _app(pg_url, ids)

    results = _race(
        app,
        "FOR NO KEY UPDATE",
        [("alice", event_ids["alice"], venue_ids["Venue A"])] * 2,
    )

    assert sorted(status for status, _ in results) == [201, 409], results
    refused = next(body for status, body in results if status == 409)
    assert refused["error"].startswith("This event already holds Venue A")
    assert [booking.status for booking in _bookings(engine, event_ids["alice"])] == ["requested"]


# TC-SPL-131-40 (BB) AC7: two simultaneous cancellations of one booking record one cancellation
@pytest.mark.parametrize("run", range(RUNS))
def test_tc_spl_131_40_concurrent_cancellations_once(engine, pg_url, run):
    ids, event_ids, venue_ids = _seed(engine, events=["alice"], venues={"Venue A": 0, "Venue B": 0})
    ids["staff"] = _staff(engine)
    app = _app(pg_url, ids)
    client = app.test_client()
    alice, event_id = {"Authorization": "Bearer alice"}, event_ids["alice"]
    made = [
        client.post(
            f"/api/event-requests/{event_id}/venue-bookings",
            json={"venue_id": venue_ids[name], "layout": "theatre"},
            headers=alice,
        )
        for name in ("Venue A", "Venue B")
    ]
    assert [response.status_code for response in made] == [201, 201]
    booking_id, other_id = (response.json["booking"]["id"] for response in made)
    for target in (booking_id, other_id):
        approved = client.post(
            f"/api/venue-bookings/{target}/approve",
            json={},
            headers={"Authorization": "Bearer staff"},
        )
        assert approved.status_code == 200, approved.json

    results = _together(
        app,
        "FOR NO KEY UPDATE",
        lambda: app.test_client().post(
            f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/cancel",
            json={"reason": "Moved online."},
            headers=alice,
        ),
    )

    assert sorted(response.status_code for response in results) == [200, 409]
    with Session(engine) as session:
        actions = session.scalars(
            select(VenueBookingStatusHistory.action).where(
                VenueBookingStatusHistory.booking_id == booking_id
            )
        ).all()
        assert actions.count("cancel") == 1
        assert session.get(VenueBooking, booking_id).status == "cancelled"
        assert session.get(VenueBooking, other_id).status == "approved"


# TC-SPL-131-48 (WB) AC9: the migration adds one nullable column and keeps existing bookings
def test_tc_spl_131_48_migration_keeps_existing_bookings(engine, pg_url):
    ids, event_ids, venue_ids = _seed(engine, events=["alice"], venues={"Venue A": 0})
    with Session(engine) as session:
        booking = VenueBooking(
            event_request_id=event_ids["alice"],
            venue_id=venue_ids["Venue A"],
            status="approved",
            layout="theatre",
            expected_attendance=100,
        )
        session.add(booking)
        session.commit()
        booking_id = booking.id

    _alembic(pg_url, "downgrade", "s3_event_confirmation")
    assert "required_facilities" not in {
        column["name"] for column in inspect(engine).get_columns("venue_bookings")
    }
    _alembic(pg_url, "upgrade", "head")

    engine.dispose()
    columns = {column["name"]: column for column in inspect(engine).get_columns("venue_bookings")}
    assert columns["required_facilities"]["nullable"] is True
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "select status, layout, expected_attendance, required_facilities "
                "from venue_bookings where id = :id"
            ),
            {"id": booking_id},
        ).one()
        assert tuple(row) == ("approved", "theatre", 100, None)
        assert (
            connection.execute(
                text("select relrowsecurity from pg_class where relname = 'venue_bookings'")
            ).scalar_one()
            is True
        )


def _alembic(url, *arguments):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )
    assert result.returncode == 0, result.stderr


def _staff(engine):
    import uuid

    from app.models import Account, AccountRole, Organisation, Role

    staff_id = str(uuid.uuid4())
    with Session(engine) as session:
        organisation = session.scalars(select(Organisation)).first()
        session.add(
            Account(id=staff_id, display_name="Valerie Tan", organisation_id=organisation.id)
        )
        session.add(AccountRole(account_id=staff_id, role=Role.VENUE_STAFF.value))
        session.commit()
    return staff_id


def _together(app, marker, call):
    """Run the same call twice, releasing both at the first SQL statement containing marker."""

    app_engine = app.extensions["engine"]
    barrier = threading.Barrier(2, timeout=10)
    released: set[int] = set()
    guard = threading.Lock()

    def align(_connection, _cursor, statement, _parameters, _context, _executemany):
        if marker not in statement:
            return
        with guard:
            if threading.get_ident() in released:
                return
            released.add(threading.get_ident())
        barrier.wait()

    event.listen(app_engine, "before_cursor_execute", align)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(lambda _: call(), range(2)))
    finally:
        event.remove(app_engine, "before_cursor_execute", align)
        app_engine.dispose()
