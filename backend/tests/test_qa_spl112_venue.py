"""Accepted attendance must use the existing independent-booking assessment."""

import test_qa_spl106_requirements as venue
import test_qa_spl112 as qa
from app.models import VenueBooking, VenueBookingReviewFinding
from sqlalchemy import select
from sqlalchemy.orm import Session

app = venue.app
base_app = venue.base_app
client = venue.client


# QA-SPL-112-030 | AC2 | WB
def test_qa_spl_112_030_booking_impact(app, client):
    event, _, bookings = venue.scenario(app, client, approved=True)
    req = qa.request(client, event, qa.item("expected_attendance", 100))
    before = qa.state(app)
    check = qa.preview(client, event, req, qa.choices(req))
    assert check.status_code == 200, check.json
    assert check.json["arrangements"]
    assert qa.state(app) == before
    result = qa.save(client, event, req, qa.choices(req))
    assert result.status_code == 200, result.json
    with Session(app.extensions["engine"]) as s:
        booking = s.get(VenueBooking, bookings[0]["id"])
        assert booking.status == "approved" and booking.expected_attendance == 150
        assert s.scalar(select(VenueBookingReviewFinding)).reason_type == "attendance"
