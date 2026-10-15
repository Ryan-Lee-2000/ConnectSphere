"""PostgreSQL migration evidence for SPL-130."""

import json
import os
import subprocess
import sys

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from test_exact_venue_bookings_postgres import pg_url as pg_url

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION_DATABASE_URL"), reason="Requires disposable PostgreSQL"
)


def _alembic(url, *args):
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


# TC-SPL-130-002 — AC1/AC2: the deployment migration assesses populated active commitments.
def test_tc_spl_130_002_populated_migration_flags_both_overlaps(pg_url):
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    parent = scripts.get_revision("s3_booking_review_findings").down_revision
    assert isinstance(parent, str)
    _alembic(pg_url, "downgrade", parent)
    engine = create_engine(pg_url)
    account = "00000000-0000-0000-0000-000000130001"
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO organisations(id,name) VALUES (130001,'SPL-130 client')"))
        conn.execute(
            text("INSERT INTO accounts(id,display_name) VALUES (:id,'SPL-130 owner')"),
            {"id": account},
        )
        conn.execute(
            text(
                "INSERT INTO venues(id,name,facilities,accessibility_features,operating_slots,"
                "setup_buffer_slots,turnaround_buffer_slots,setup_minutes,turnaround_minutes,"
                "operating_intervals,timing_revision) VALUES "
                "(130001,'Review Hall','[]','[]','[\"AM\",\"PM\"]',0,0,30,30,"
                "'[[0,1440]]',2)"
            )
        )
        for event_id, name, start, end in (
            (130001, "Migration Alpha", "10:00", "11:00"),
            (130002, "Migration Bravo", "11:00", "12:00"),
        ):
            conn.execute(
                text(
                    "INSERT INTO event_requests(id,organiser_account_id,organisation_id,name,"
                    "status,proposed_date,start_time,end_time,required_facilities,"
                    "accessibility_needs,registration_required) VALUES "
                    "(:id,:account,130001,:name,'planning','2030-12-20',:start,:end,'[]','[]',false)"
                ),
                {"id": event_id, "account": account, "name": name, "start": start, "end": end},
            )
            timing = {
                "event": {
                    "start": f"2030-12-20T{start}:00+08:00",
                    "end": f"2030-12-20T{end}:00+08:00",
                },
                "occupied": {
                    "start": f"2030-12-20T{start}:00+08:00",
                    "end": f"2030-12-20T{end}:00+08:00",
                },
                "setup_minutes": 0,
                "turnaround_minutes": 0,
                "venue_revision": 1,
            }
            conn.execute(
                text(
                    "INSERT INTO venue_bookings(id,event_request_id,venue_id,status,"
                    "requires_review,exact_timing,event_slots) VALUES "
                    "(:id,:id,130001,'requested',false,CAST(:timing AS jsonb),'[]')"
                ),
                {"id": event_id, "timing": json.dumps(timing)},
            )
    _alembic(pg_url, "upgrade", "head")
    with engine.connect() as conn:
        findings = (
            conn.execute(
                text(
                    "SELECT booking_id,reason_type,original_occupancy,current_occupancy "
                    "FROM venue_booking_review_findings WHERE booking_id IN (130001,130002) "
                    "ORDER BY booking_id"
                )
            )
            .mappings()
            .all()
        )
        assert [row["booking_id"] for row in findings] == [130001, 130002]
        assert {row["reason_type"] for row in findings} == {"overlap"}
        assert all(row["original_occupancy"] and row["current_occupancy"] for row in findings)
        rows = conn.execute(
            text(
                "SELECT id,status,requires_review FROM venue_bookings "
                "WHERE id IN (130001,130002) ORDER BY id"
            )
        ).all()
        assert rows == [(130001, "requested", True), (130002, "requested", True)]
    engine.dispose()
