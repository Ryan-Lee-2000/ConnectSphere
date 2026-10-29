"""SPL-132 QA cases on real PostgreSQL: the replacement link's constraints and simultaneous actions.

SQLite serialises writes, so it cannot show a race. These run only under `npm run integration`
(INTEGRATION_DATABASE_URL), reusing SPL-85's throw-away database, seeded event (a Planning event
with an Approved PM booking at "Race Hall" and an Essential line reserved 4 of 4) and race harness.
Events are dated 2030, so the bookings have not ended.
"""

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
import test_event_confirmation_postgres as spl85
from app.models import (
    EventRequest,
    Notification,
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingStatusHistory,
    VenueLayout,
)
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3
pg_url, engine = spl85.pg_url, spl85.engine
DAY = date(2030, 9, 2)


def _annex(engine):
    with Session(engine) as session:
        venue = Venue(
            name="Race Annex",
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=0,
            turnaround_buffer_slots=0,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(venue)
        session.commit()
        return venue.id


def _seed(engine, run):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    day = DAY + timedelta(days=run)
    event_id, _ = spl85._seed_ready_event(engine, ids, organisation_id, venue_id, type_id, day)
    with Session(engine) as session:
        booking_id = session.scalar(
            select(VenueBooking.id).where(VenueBooking.event_request_id == event_id)
        )
        # SPL-85's seed has no occupancy claim; a block finds the bookings it overlaps by claim.
        session.add(
            VenueBookingOccupancy(
                booking_id=booking_id, venue_id=venue_id, day=day, slot="PM", kind="event"
            )
        )
        session.commit()
    return ids, venue_id, event_id, booking_id, day


def _block(venue_id, day):
    return lambda client: client.post(
        f"/api/venues/{venue_id}/operational-blocks",
        json={"start_date": day.isoformat(), "slots": ["PM"], "reason": "Burst pipe"},
        headers={"Authorization": "Bearer staff"},
    )


def _replace(event_id, original_id, venue_id):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": venue_id, "layout": "theatre", "replaces_booking_id": original_id},
        headers={"Authorization": "Bearer coordinator"},
    )


def _approve(booking_id):
    return lambda client: client.post(
        f"/api/venue-bookings/{booking_id}/approve",
        json={},
        headers={"Authorization": "Bearer staff"},
    )


def _cancel(event_id, booking_id):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/cancel",
        json={"reason": "No longer needed."},
        headers={"Authorization": "Bearer coordinator"},
    )


def _call(app, call):
    response = call(app.test_client())
    assert response.status_code < 300, response.json
    return response.json


def _status(engine, model, row_id):
    with Session(engine) as session:
        return session.get(model, row_id).status


# QA-SPL-132-150 | AC5 AC7 | WB PostgreSQL
def test_qa_spl_132_150_the_migration_adds_the_link_index_and_set_null(engine):
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("venue_bookings")}
    assert columns["replaces_booking_id"]["nullable"] is True
    [link] = [
        key
        for key in inspector.get_foreign_keys("venue_bookings")
        if key["constrained_columns"] == ["replaces_booking_id"]
    ]
    assert link["referred_table"] == "venue_bookings"
    assert link["options"].get("ondelete") == "SET NULL"
    with engine.connect() as connection:
        definition = connection.scalar(
            text(
                "select indexdef from pg_indexes "
                "where indexname = 'uq_venue_bookings_one_requested_replacement'"
            )
        )
    assert "UNIQUE" in definition and "replaces_booking_id" in definition
    assert "'requested'" in definition


# QA-SPL-132-151 | AC6 | WB PostgreSQL
def test_qa_spl_132_151_the_database_allows_one_requested_replacement(engine, pg_url):
    ids, venue_id, event_id, booking_id, _ = _seed(engine, 0)
    with Session(engine) as session:
        for status in ("rejected", "withdrawn", "requested"):
            session.add(
                VenueBooking(
                    event_request_id=event_id,
                    venue_id=venue_id,
                    status=status,
                    replaces_booking_id=booking_id,
                )
            )
        session.commit()
        session.add(
            VenueBooking(
                event_request_id=event_id,
                venue_id=venue_id,
                status="requested",
                replaces_booking_id=booking_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        # Deleting the original keeps every replacement, unlinked (ON DELETE SET NULL).
        session.execute(text("delete from venue_bookings where id = :id"), {"id": booking_id})
        session.commit()
        links = session.scalars(
            select(VenueBooking.replaces_booking_id).where(
                VenueBooking.event_request_id == event_id
            )
        ).all()
    assert links == [None, None, None]


# QA-SPL-132-152 | AC5 AC6 | WB concurrency
def test_qa_spl_132_152_simultaneous_replacement_requests_create_one(engine, pg_url):
    for run in range(RUNS):
        ids, venue_id, event_id, booking_id, day = _seed(engine, run)
        annex = _annex(engine)
        app = spl85._app(pg_url, ids)
        try:
            _call(app, _block(venue_id, day))
            results = spl85._race(
                app, [_replace(event_id, booking_id, annex), _replace(event_id, booking_id, annex)]
            )
            codes = sorted(code for code, _ in results)
            # The loser either sees the pending replacement (409) or the annex already held (409).
            assert codes == [201, 409], results
            with Session(engine) as session:
                pending = session.scalars(
                    select(VenueBooking).where(
                        VenueBooking.replaces_booking_id == booking_id,
                        VenueBooking.status == "requested",
                    )
                ).all()
            assert len(pending) == 1
        finally:
            app.extensions["engine"].dispose()


# QA-SPL-132-153 | AC10 AC11 | WB concurrency
def test_qa_spl_132_153_a_block_racing_confirmation_never_leaves_it_confirmed(engine, pg_url):
    outcomes = set()
    for run in range(RUNS):
        ids, venue_id, event_id, booking_id, day = _seed(engine, run)
        app = spl85._app(pg_url, ids)
        try:
            results = spl85._race(app, [spl85._confirm(event_id), _block(venue_id, day)])
            (confirm_code, _), (block_code, block_body) = results
            assert block_code == 201, block_body
            assert block_body["affected_booking_count"] == 1
            assert confirm_code in (200, 409), results
            outcomes.add(confirm_code)
            with Session(engine) as session:
                event = session.get(EventRequest, event_id)
                assert event.status == "planning"
                assert session.get(VenueBooking, booking_id).requires_review is True
                returned = session.scalars(
                    select(Notification.message).where(
                        Notification.event_request_id == event_id,
                        Notification.recipient_account_id == ids["organiser"],
                        Notification.dedupe_key.like("%returned_to_planning%"),
                    )
                ).all()
            # The organiser hears of a return only when the confirmation won the race.
            assert len(returned) == (1 if confirm_code == 200 else 0)
        finally:
            app.extensions["engine"].dispose()
    assert outcomes <= {200, 409}


# QA-SPL-132-154 | AC7 AC9 | WB concurrency
def test_qa_spl_132_154_approval_racing_cancellation_releases_the_original_once(engine, pg_url):
    for run in range(RUNS):
        ids, venue_id, event_id, booking_id, day = _seed(engine, run)
        annex = _annex(engine)
        app = spl85._app(pg_url, ids)
        try:
            _call(app, _block(venue_id, day))
            replacement = _call(app, _replace(event_id, booking_id, annex))["booking"]["id"]
            results = spl85._race(app, [_approve(replacement), _cancel(event_id, booking_id)])
            (approve_code, approve_body), (cancel_code, _) = results
            assert approve_code == 200, approve_body
            assert cancel_code in (200, 409), results
            assert _status(engine, VenueBooking, booking_id) == "cancelled"
            assert _status(engine, VenueBooking, replacement) == "approved"
            with Session(engine) as session:
                endings = session.scalars(
                    select(VenueBookingStatusHistory.action).where(
                        VenueBookingStatusHistory.booking_id == booking_id,
                        VenueBookingStatusHistory.resulting_status == "cancelled",
                    )
                ).all()
            assert endings == (["cancel"] if cancel_code == 200 else ["replaced"])
        finally:
            app.extensions["engine"].dispose()


def _approved_replacement_pair(engine, run):
    """Two events whose replacements cross: Hall -> Annex for one, Annex -> Hall for the other."""

    ids, organisation_id, hall, type_id = spl85._seed_accounts(engine)
    annex = _annex(engine)
    first_day = DAY + timedelta(days=10 + 2 * run)
    second_day = first_day + timedelta(days=1)
    pairs = []
    for day, original_venue, replacement_venue in (
        (first_day, hall, annex),
        (second_day, annex, hall),
    ):
        event_id, _ = spl85._seed_ready_event(
            engine, ids, organisation_id, original_venue, type_id, day
        )
        with Session(engine) as session:
            original_id = session.scalar(
                select(VenueBooking.id).where(VenueBooking.event_request_id == event_id)
            )
            replacement = VenueBooking(
                event_request_id=event_id,
                venue_id=replacement_venue,
                status="requested",
                layout="theatre",
                expected_attendance=100,
                booking_date=day,
                event_slots=["PM"],
                requested_by_account_id=ids["coordinator"],
                requested_at=spl85.STAMP,
                replaces_booking_id=original_id,
            )
            session.add(replacement)
            session.flush()
            for booking_id, venue_id in (
                (original_id, original_venue),
                (replacement.id, replacement_venue),
            ):
                session.add(
                    VenueBookingOccupancy(
                        booking_id=booking_id, venue_id=venue_id, day=day, slot="PM", kind="event"
                    )
                )
            session.commit()
            pairs.append((original_id, replacement.id))
    return ids, pairs


def _race_at_second_venue_lock(app, calls):
    """Hold each approval at its second venue lock, so each already holds one venue.

    Before the fix that is the original's venue, taken after the replacement's. Once the order is
    consistent, one approval waits on the other's first venue lock instead and never reaches the
    barrier, so the barrier gives up after a short wait and both carry on.
    """

    app_engine = app.extensions["engine"]
    barrier = threading.Barrier(len(calls), timeout=3)
    seen: dict[int, int] = {}
    guard = threading.Lock()
    venue_lock = re.compile(r"FROM venues.*FOR NO KEY UPDATE", re.DOTALL)

    def align(_connection, _cursor, statement, _parameters, _context, _executemany):
        if not venue_lock.search(statement):
            return
        with guard:
            seen[threading.get_ident()] = seen.get(threading.get_ident(), 0) + 1
            second = seen[threading.get_ident()] == 2
        if second:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass

    def run(call):
        try:
            response = call(app.test_client())
        except Exception as error:  # a deadlock surfaces as a raised DBAPI error in testing
            return 500, repr(error)
        return response.status_code, response.json

    event.listen(app_engine, "before_cursor_execute", align)
    try:
        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            return list(executor.map(run, calls))
    finally:
        event.remove(app_engine, "before_cursor_execute", align)


# QA-SPL-132-155 | AC7 | WB concurrency (review round 1, P2 from Clive)
def test_qa_spl_132_155_opposite_replacement_approvals_both_complete(engine, pg_url):
    for run in range(RUNS):
        ids, pairs = _approved_replacement_pair(engine, run)
        app = spl85._app(pg_url, ids)
        try:
            results = _race_at_second_venue_lock(
                app, [_approve(replacement) for _, replacement in pairs]
            )
            assert [code for code, _ in results] == [200, 200], results
            with Session(engine) as session:
                for original, replacement in pairs:
                    assert session.get(VenueBooking, replacement).status == "approved"
                    assert session.get(VenueBooking, original).status == "cancelled"
                    endings = session.scalars(
                        select(VenueBookingStatusHistory.action).where(
                            VenueBookingStatusHistory.booking_id == original,
                            VenueBookingStatusHistory.resulting_status == "cancelled",
                        )
                    ).all()
                    assert endings == ["replaced"]
        finally:
            app.extensions["engine"].dispose()
