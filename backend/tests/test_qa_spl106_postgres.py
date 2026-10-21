"""SPL-106 PostgreSQL migration, transaction and lock evidence."""

import os
import subprocess
import sys
from datetime import date

import pytest
import test_venue_booking_approval_postgres as base
from app.models import EventRequest, Venue, VenueBooking, VenueBookingReviewFinding
from app.venue_requirement_review import assess_event_bookings
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

pytestmark = base.pytestmark
pg_url = base.pg_url
engine = base.engine


def seed(engine):
    ids, organisation, venue = base._seed_accounts(engine)
    event, booking = base._seed_booking(engine, ids, organisation, venue, date(2030, 6, 15))
    return ids, venue, event, booking


def migrate(url, direction, revision):
    return subprocess.run(
        [sys.executable, "-m", "alembic", direction, revision],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": url},
    )


# QA-SPL-106-039 | AC2 | WB
def test_qa_spl_106_039_migration_retains_resolved_history(engine, pg_url):
    down = migrate(pg_url, "downgrade", "s3_ordinary_event_details")
    assert down.returncode == 0, down.stderr
    up = migrate(pg_url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    ids, _, event_id, booking_id = seed(engine)
    with Session(engine) as session:
        event = session.get(EventRequest, event_id)
        event.expected_attendance = 99
        assert assess_event_bookings(session, event, assessed_by_account_id=ids["coordinator"]) == 1
        session.commit()
        event.expected_attendance = 100
        assert assess_event_bookings(session, event, assessed_by_account_id=ids["coordinator"]) == 0
        session.commit()
        finding = session.scalar(select(VenueBookingReviewFinding))
        assert finding.reason_type == "attendance"
        assert finding.resolved_at is not None
        assert not session.get(VenueBooking, booking_id).requires_review
    refused = migrate(pg_url, "downgrade", "s3_ordinary_event_details")
    assert refused.returncode != 0
    assert "Cannot downgrade while requirement review history exists" in refused.stderr
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "s4_booking_requirement_review"
        )
        assert connection.scalar(text("SELECT count(*) FROM venue_booking_review_findings")) == 1


# QA-SPL-106-040 | AC3 | WB
def test_qa_spl_106_040_transaction_rollback_preserves_booking(engine):
    ids, _, event_id, booking_id = seed(engine)
    with Session(engine) as session:
        event = session.scalar(
            select(EventRequest).where(EventRequest.id == event_id).with_for_update()
        )
        event.expected_attendance = 99
        assert assess_event_bookings(session, event, assessed_by_account_id=ids["coordinator"]) == 1
        session.rollback()
    with Session(engine) as session:
        booking = session.get(VenueBooking, booking_id)
        assert session.get(EventRequest, event_id).expected_attendance == 100
        assert booking.status == "requested"
        assert booking.expected_attendance == 100
        assert booking.event_slots == ["PM"]
        assert not booking.requires_review
        assert session.scalar(select(VenueBookingReviewFinding)) is None


# QA-SPL-106-041 | AC5 | WB
def test_qa_spl_106_041_event_recheck_waits_for_venue_edit(engine):
    ids, venue_id, event_id, _ = seed(engine)
    with Session(engine) as editor, Session(engine) as checker:
        editor.scalar(select(Venue).where(Venue.id == venue_id).with_for_update())
        checker.execute(text("SET LOCAL lock_timeout = '250ms'"))
        event = checker.get(EventRequest, event_id)
        with pytest.raises(OperationalError, match="lock timeout"):
            assess_event_bookings(checker, event, assessed_by_account_id=ids["coordinator"])
        checker.rollback()
        editor.rollback()
        assert (
            assess_event_bookings(
                checker,
                checker.get(EventRequest, event_id),
                assessed_by_account_id=ids["coordinator"],
            )
            == 0
        )
