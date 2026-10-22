"""SPL-109 real PostgreSQL atomicity and preview serialization."""

from datetime import date

import test_venue_booking_approval_postgres as base
from app import create_app
from app.models import EventDetailChange, EventRequest, EventStatusHistory, VenueBooking
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = base.pytestmark
pg_url = base.pg_url
engine = base.engine


def scenario(engine, pg_url):
    ids, org, venue = base._seed_accounts(engine)
    event, booking = base._seed_booking(engine, ids, org, venue, date(2030, 6, 15))
    with Session(engine) as s:
        s.get(EventRequest, event).status = "confirmed"
        s.commit()
    app = create_app(
        {"TESTING": True, "DATABASE_URL": pg_url, "IDENTITY_VERIFIER": ids.__getitem__}
    )
    return app, event, booking


# QA-SPL-109-040 | AC4 | WB
def test_qa_spl_109_040_concurrent_saves_one_audit(engine, pg_url):
    app, event, booking = scenario(engine, pg_url)
    try:
        path = f"/api/event-requests/assigned/{event}/significant-changes"
        headers = {"Authorization": "Bearer coordinator"}
        values = {"expected_attendance": 99}
        token = (
            app.test_client()
            .post(path + "/preview", json={"values": values}, headers=headers)
            .json["preview_token"]
        )

        def call(client):
            return client.patch(
                path, json={"values": values, "preview_token": token}, headers=headers
            )

        results = base._race(app, [call, call])
        assert sorted(code for code, _ in results) == [200, 409], results
        with Session(engine) as s:
            assert s.get(EventRequest, event).status == "planning"
            assert s.get(VenueBooking, booking).requires_review
            assert s.get(VenueBooking, booking).status == "requested"
            assert s.scalar(select(func.count()).select_from(EventDetailChange)) == 1
            assert s.scalar(select(func.count()).select_from(EventStatusHistory)) == 1
    finally:
        app.extensions["engine"].dispose()


# QA-SPL-109-041 | AC5 | WB
def test_qa_spl_109_041_rollback_all_side_effects(engine, pg_url, monkeypatch):
    import pytest

    app, event, booking = scenario(engine, pg_url)
    try:
        path = f"/api/event-requests/assigned/{event}/significant-changes"
        headers = {"Authorization": "Bearer coordinator"}
        values = {"expected_attendance": 99}
        token = (
            app.test_client()
            .post(path + "/preview", json={"values": values}, headers=headers)
            .json["preview_token"]
        )

        def fail(*args, **kwargs):
            raise RuntimeError("Injected final audit failure")

        monkeypatch.setattr("app.significant_event_changes.EventDetailChange", fail)
        with pytest.raises(RuntimeError, match="Injected"):
            app.test_client().patch(
                path, json={"values": values, "preview_token": token}, headers=headers
            )
        with Session(engine) as s:
            assert s.get(EventRequest, event).status == "confirmed"
            assert s.get(EventRequest, event).expected_attendance == 100
            assert not s.get(VenueBooking, booking).requires_review
            assert s.scalar(select(func.count()).select_from(EventStatusHistory)) == 0
    finally:
        app.extensions["engine"].dispose()
