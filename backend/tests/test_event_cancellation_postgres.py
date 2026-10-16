"""PostgreSQL evidence for SPL-86 (CS-E07-S5): concurrent cancellation and the migration.

SQLite serialises writes, so it cannot show a race. These cases run only under
`npm run integration` (INTEGRATION_DATABASE_URL), reusing SPL-85's throw-away database fixture,
seeded event and race harness.
"""

import os
from datetime import date, timedelta

import pytest
import test_event_confirmation_postgres as spl85
from app.equipment_reservation_state import remaining_quantity
from app.models import (
    EquipmentRequirement,
    EquipmentReservationRelease,
    EventRequest,
    EventStatusHistory,
    VenueBooking,
    VenueBookingStatusHistory,
)
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"),
    reason="Run npm run integration with disposable PostgreSQL",
)

RUNS = 3
pg_url, engine = spl85.pg_url, spl85.engine


def _cancel(event_id, reason="Called off by the client."):
    return lambda client: client.post(
        f"/api/event-requests/{event_id}/cancel",
        json={"reason": reason},
        headers={"Authorization": "Bearer coordinator"},
    )


def _counts(session, event_id, line_id):
    return {
        "cancel_history": session.scalar(
            select(func.count(EventStatusHistory.id)).where(
                EventStatusHistory.event_request_id == event_id,
                EventStatusHistory.action == "cancel",
            )
        ),
        "booking_cancels": session.scalar(
            select(func.count(VenueBookingStatusHistory.id))
            .join(VenueBooking, VenueBooking.id == VenueBookingStatusHistory.booking_id)
            .where(
                VenueBooking.event_request_id == event_id,
                VenueBookingStatusHistory.action == "cancel",
            )
        ),
        "releases": session.scalar(
            select(func.sum(EquipmentReservationRelease.quantity)).where(
                EquipmentReservationRelease.reason.like("Event cancelled:%")
            )
        )
        or 0,
        "held": sum(
            remaining_quantity(item)
            for item in session.get(EquipmentRequirement, line_id).reservations
        ),
    }


# TC-SPL-86-36 (BB) AC5: two simultaneous cancellations release everything exactly once
def test_tc_spl_86_36_concurrent_cancellations_release_once(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 2, 2) + timedelta(days=run)
            event_id, line_id = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )

            results = spl85._race(app, [_cancel(event_id), _cancel(event_id, "Duplicate click.")])

            assert sorted(status for status, _ in results) == [200, 409], results
            refused = next(body for status, body in results if status == 409)
            assert refused["error"] == "This event is already cancelled."
            with Session(engine) as session:
                assert session.get(EventRequest, event_id).status == "cancelled"
                counts = _counts(session, event_id, line_id)
                assert counts["cancel_history"] == 1
                assert counts["booking_cancels"] == 1
                assert counts["held"] == 0
            with Session(engine) as session:
                line = session.get(EquipmentRequirement, line_id)
                released_for_event = sum(
                    entry.quantity
                    for reservation in line.reservations
                    for entry in reservation.releases
                    if entry.reason.startswith("Event cancelled:")
                )
                assert released_for_event == 4
    finally:
        app.extensions["engine"].dispose()


# TC-SPL-86-37 (BB) AC4/AC5: cancellation racing confirmation ends in one consistent state
def test_tc_spl_86_37_cancellation_racing_confirmation(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    outcomes = set()
    try:
        for run in range(RUNS):
            day = date(2027, 3, 2) + timedelta(days=run)
            event_id, line_id = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )

            (cancel_status, _), (confirm_status, _) = spl85._race(
                app, [_cancel(event_id), spl85._confirm(event_id)]
            )

            assert cancel_status == 200
            with Session(engine) as session:
                stored = session.get(EventRequest, event_id)
                assert stored.status == "cancelled"
                assert _counts(session, event_id, line_id)["held"] == 0
                actions = session.scalars(
                    select(EventStatusHistory.action)
                    .where(EventStatusHistory.event_request_id == event_id)
                    .order_by(EventStatusHistory.id)
                ).all()
            if confirm_status == 200:
                assert actions == ["confirm", "cancel"]
                outcomes.add("confirmed then cancelled")
            else:
                assert confirm_status == 409
                assert actions == ["cancel"]
                outcomes.add("cancelled first")
        assert outcomes
    finally:
        app.extensions["engine"].dispose()


# TC-SPL-86-38 (BB) AC3/AC4: cancellation racing a Technical Support release keeps stock exact
def test_tc_spl_86_38_cancellation_racing_a_release(engine, pg_url):
    ids, organisation_id, venue_id, type_id = spl85._seed_accounts(engine)
    app = spl85._app(pg_url, ids)
    try:
        for run in range(RUNS):
            day = date(2027, 4, 2) + timedelta(days=run)
            event_id, line_id = spl85._seed_ready_event(
                engine, ids, organisation_id, venue_id, type_id, day
            )

            (cancel_status, _), (release_status, _) = spl85._race(
                app, [_cancel(event_id), spl85._release_one(line_id)]
            )

            assert cancel_status == 200
            assert release_status in (201, 409)
            with Session(engine) as session:
                line = session.get(EquipmentRequirement, line_id)
                released = sum(
                    entry.quantity
                    for reservation in line.reservations
                    for entry in reservation.releases
                )
                assert released == 4  # never more than was held
                assert sum(remaining_quantity(item) for item in line.reservations) == 0
    finally:
        app.extensions["engine"].dispose()


# TC-SPL-86-39 (WB) AC6: the migration adds three nullable, paired cancellation columns
def test_tc_spl_86_39_migration_adds_paired_cancellation_columns(engine):
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("event_requests")}
    for name in ("cancelled_by_account_id", "cancelled_at", "cancellation_reason"):
        assert columns[name]["nullable"] is True
    assert any(
        foreign_key["constrained_columns"] == ["cancelled_by_account_id"]
        and foreign_key["referred_table"] == "accounts"
        for foreign_key in inspector.get_foreign_keys("event_requests")
    )
    checks = {check["name"] for check in inspector.get_check_constraints("event_requests")}
    assert "ck_event_requests_cancellation_complete" in checks
