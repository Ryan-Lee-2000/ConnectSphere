"""TC-SPL-138-09: real lock-wait evidence, not sequential approximations."""

import os

import pytest
from app.models import VenueBooking
from sqlalchemy.orm import Session
from test_exact_venue_bookings_postgres import (
    approve_call,
    headers,
    ordered_race,
    request_call,
)
from test_exact_venue_bookings_postgres import (
    pg_url as pg_url,
)
from test_exact_venue_bookings_postgres import (
    scenario as scenario,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"), reason="Requires disposable PostgreSQL"
)


# TC-SPL-138-09
@pytest.mark.parametrize("operation", ["request", "approve"])
@pytest.mark.parametrize("closure_first", [True, False])
def test_tc_spl_138_09_exact_closure_race(scenario, operation, closure_first):
    app, venue, events, _ = scenario
    call = request_call(events[0], venue)
    booking_id = None
    if operation == "approve":
        booking_id = call(app.test_client()).json["booking"]["id"]
        call = approve_call(booking_id)

    def closure(client):
        return client.post(
            f"/api/venues/{venue}/operational-blocks",
            headers=headers("staff-a"),
            json={
                "date": "2026-10-14",
                "start_time": "12:30",
                "end_time": "13:00",
                "reason": "Repair",
            },
        )

    first, second = (closure, call) if closure_first else (call, closure)
    a, b = ordered_race(app, first, second)
    if closure_first:
        assert a[0] == 201 and b[0] == 409, (a, b)
    else:
        assert a[0] == (200 if operation == "approve" else 201) and b[0] == 201, (a, b)
        booking_id = a[1]["booking"]["id"]
        assert b[1]["affected_booking_count"] == 1
    if booking_id:
        with Session(app.extensions["engine"]) as session:
            booking = session.get(VenueBooking, booking_id)
            assert booking.requires_review
            assert booking.status == (
                "approved" if operation == "approve" and not closure_first else "requested"
            )


# TC-SPL-138-01 / TC-SPL-138-05: populated migration and database constraint.
def test_tc_spl_138_05_populated_migration_preserves_legacy(pg_url):
    import subprocess
    import sys

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    engine = create_engine(pg_url)
    env = {**os.environ, "DATABASE_URL": pg_url}
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    parent = scripts.get_revision("s3_timed_venue_closures").down_revision
    assert isinstance(parent, str)
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", parent],
        env=env,
        check=True,
        capture_output=True,
    )
    with engine.begin() as conn:
        # Main's catalogue and its saved data must survive the closure-only upgrade.
        conn.execute(
            text(
                "INSERT INTO equipment_types(id,name,normalised_name,total_stock) "
                "VALUES (138,'Migration fixture','migration fixture',7)"
            )
        )
        equipment_before = dict(
            conn.execute(text("SELECT * FROM equipment_types WHERE id=138")).mappings().one()
        )
        conn.execute(
            text(
                "INSERT INTO accounts(id,display_name) VALUES ('00000000-0000-0000"
                "-0000-000000000138','Staff')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO venues(id,name,facilities,accessibility_features,oper"
                "ating_slots,setup_buffer_slots,turnaround_buffer_slots,timing_rev"
                "ision) VALUES (138,'Hall','[]','[]','[\"AM\"]',0,0,0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO venue_operational_blocks(id,venue_id,start_date,end_d"
                "ate,slots,reason,created_by_account_id,created_at) VALUES (138,13"
                "8,'2026-10-14','2026-10-15','[\"AM\"]','Original reason','00000000-"
                "0000-0000-0000-000000000138',now())"
            )
        )
        before = dict(
            conn.execute(text("SELECT * FROM venue_operational_blocks WHERE id=138"))
            .mappings()
            .one()
        )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        check=True,
        capture_output=True,
    )
    with engine.connect() as conn:
        after = dict(
            conn.execute(text("SELECT * FROM venue_operational_blocks WHERE id=138"))
            .mappings()
            .one()
        )
        assert after.pop("exact_start") is None and after.pop("exact_end") is None
        assert after == before
        equipment_after = dict(
            conn.execute(text("SELECT * FROM equipment_types WHERE id=138")).mappings().one()
        )
        assert equipment_after == equipment_before
        assert conn.scalar(
            text("SELECT relrowsecurity FROM pg_class WHERE relname='venue_operational_blocks'")
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE venue_operational_blocks SET exact_start='2026-10-14 10:00"
                    "+08' WHERE id=138"
                )
            )
    engine.dispose()
