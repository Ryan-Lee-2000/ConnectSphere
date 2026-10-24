"""SPL-121 QA cases on real PostgreSQL: simultaneous decisions and real rollback.

SQLite serialises writes, so it cannot show a race. These run only under `npm run integration`
(INTEGRATION_DATABASE_URL), reusing SPL-85's throw-away database, seeded event (a Planning event
with a booking and an Essential line reserved 4 of 4) and race harness.
"""

import os
from datetime import date, timedelta

import pytest
import test_event_confirmation_postgres as spl85
from app import venue_booking_approvals as approvals_module
from app.models import EquipmentRequirement, Notification, VenueBooking
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3
pg_url, engine = spl85.pg_url, spl85.engine


def _keys(engine, event_id, account_id):
    with Session(engine) as session:
        return session.scalars(
            select(Notification.dedupe_key).where(
                Notification.event_request_id == event_id,
                Notification.recipient_account_id == account_id,
                Notification.dedupe_key.like("arrangement_%"),
            )
        ).all()


def _requested(engine, booking_id):
    with Session(engine) as session:
        session.get(VenueBooking, booking_id).status = "requested"
        session.commit()


def _booking_of(engine, event_id):
    with Session(engine) as session:
        return session.scalar(
            select(VenueBooking.id).where(VenueBooking.event_request_id == event_id)
        )


def _reject(booking_id):
    return lambda client: client.post(
        f"/api/venue-bookings/{booking_id}/reject",
        json={"reason": "maintenance"},
        headers={"Authorization": "Bearer staff"},
    )


def _reserve(line_id, quantity):
    return lambda client: client.post(
        f"/api/equipment-requirements/{line_id}/reservations",
        json={"quantity": quantity},
        headers={"Authorization": "Bearer technical"},
    )


def _units(type_id, quantity):
    return lambda client: client.post(
        f"/api/equipment-types/{type_id}/unavailable-units",
        json={"quantity": quantity, "reason": "Water damage"},
        headers={"Authorization": "Bearer technical"},
    )


# QA-SPL-121-070 | AC1 AC5 | WB concurrency
def test_qa_spl_121_070_simultaneous_rejections_notify_once(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 9, 2) + timedelta(days=run)
            event_id, _ = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )
            booking_id = _booking_of(engine, event_id)
            _requested(engine, booking_id)
            results = spl85._race(app, [_reject(booking_id), _reject(booking_id)])
            assert sorted(code for code, _ in results) == [200, 409], results
            keys = _keys(engine, event_id, ids["coordinator"])
            assert len(keys) == 1 and keys[0].startswith("arrangement_booking_rejected:")
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-121-071 | AC2 AC5 | WB concurrency
def test_qa_spl_121_071_racing_reservations_notify_once_per_success(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 10, 2) + timedelta(days=run)
            event_id, _ = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )
            with Session(engine) as session:
                line = EquipmentRequirement(
                    event_request_id=event_id,
                    equipment_type="Microphones",
                    equipment_type_id=type_id,
                    quantity=4,
                    required_start_date=day,
                    required_end_date=day,
                    status="requested",
                )
                session.add(line)
                session.commit()
                line_id = line.id
            results = spl85._race(app, [_reserve(line_id, 3), _reserve(line_id, 3)])
            assert sorted(code for code, _ in results) == [201, 409], results
            keys = _keys(engine, event_id, ids["coordinator"])
            assert len(keys) == 1 and keys[0].startswith("arrangement_equipment_reserved:")
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-121-072 | AC4 AC5 | WB concurrency
def test_qa_spl_121_072_racing_markings_announce_the_flagged_line_once(engine, pg_url):
    for run in range(RUNS):
        ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
        app = spl85._app(pg_url, ids)
        try:
            day = date(2027, 11, 2) + timedelta(days=run)
            event_id, line_id = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )
            # Stock 40 with 4 held: marking 37 leaves 3 usable and flags the line; 1 more alone
            # flags nothing. Whichever commits first, the line is announced exactly once.
            results = spl85._race(app, [_units(type_id, 37), _units(type_id, 1)])
            assert sorted(code for code, _ in results) == [201, 201], results
            keys = _keys(engine, event_id, ids["coordinator"])
            assert keys == [k for k in keys if k.endswith(f"-line-{line_id}")]
            assert len(keys) == 1
        finally:
            app.extensions["engine"].dispose()


# QA-SPL-121-073 | AC1 AC5 | WB rollback
def test_qa_spl_121_073_a_failed_rejection_rolls_the_notice_back(engine, pg_url, monkeypatch):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    real = approvals_module.add_arrangement_notice

    def fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("Injected failure after the notice was written")

    monkeypatch.setattr(approvals_module, "add_arrangement_notice", fail)
    try:
        event_id, _ = spl85._seed_ready_event(
            engine, ids, organisation_id, venue_id, type_id, date(2027, 12, 2)
        )
        booking_id = _booking_of(engine, event_id)
        _requested(engine, booking_id)
        with pytest.raises(RuntimeError, match="Injected"):
            _reject(booking_id)(app.test_client())
        with Session(engine) as session:
            assert session.get(VenueBooking, booking_id).status == "requested"
        assert _keys(engine, event_id, ids["coordinator"]) == []
    finally:
        app.extensions["engine"].dispose()
