"""SPL-130 acceptance coverage for venue timing impact assessment."""

from datetime import date, time

import pytest
import test_venue_booking_requests as legacy
from app.models import (
    Venue,
    VenueBooking,
    VenueBookingOccupancy,
    VenueBookingReviewFinding,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

base_app = legacy.app
FUTURE = date(2026, 12, 20)


@pytest.fixture
def app(base_app):
    base_app.config["EXACT_VENUE_TIMING_ENABLED"] = True
    return base_app


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="venue-staff"):
    return {"Authorization": f"Bearer {token}"} if token else {}


def venue(app, *, setup=0, turnaround=0, hours=None):
    venue_id = legacy.add_venue(app)
    with Session(app.extensions["engine"]) as session:
        row = session.get(Venue, venue_id)
        row.setup_minutes = setup
        row.turnaround_minutes = turnaround
        row.operating_intervals = hours or [[0, 1440]]
        row.timing_revision = 1
        session.commit()
    return venue_id


def event(app, name, start, end, *, day=FUTURE, coordinator=legacy.COORDINATOR):
    return legacy.make_event(app, name=name, day=day, start=start, end=end, coordinator=coordinator)


def book(client, event_id, venue_id, start, end, *, revision=1):
    response = client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        headers=headers("coordinator"),
        json={
            "venue_id": venue_id,
            "layout": "theatre",
            "date": FUTURE.isoformat(),
            "start_time": start,
            "end_time": end,
            "venue_revision": revision,
        },
    )
    assert response.status_code == 201, response.json
    return response.json["booking"]


def timing_patch(client, venue_id, setup, turnaround=0, hours=None):
    return client.patch(
        f"/api/venues/{venue_id}",
        headers=headers(),
        json={
            "setup_minutes": setup,
            "turnaround_minutes": turnaround,
            "operating_intervals": hours or [[0, 1440]],
        },
    )


# TC-SPL-130-001 — AC1: both active statuses are assessed; terminal and past records are preserved.
def test_tc_spl_130_001_assesses_only_active_unfinished_commitments(app, client):
    venue_id = venue(app)
    first_event = event(app, "Requested", time(10), time(11))
    second_event = event(app, "Approved", time(11), time(12))
    first = book(client, first_event, venue_id, "10:00", "11:00")
    second = book(client, second_event, venue_id, "11:00", "12:00")
    assert (
        client.post(
            f"/api/venue-bookings/{second['id']}/approve", headers=headers(), json={}
        ).status_code
        == 200
    )
    with Session(app.extensions["engine"]) as session:
        past_event = legacy.make_event(
            app,
            name="Historical",
            day=date(2026, 1, 1),
            start=time(10),
            end=time(11),
        )
        terminal = VenueBooking(event_request_id=past_event, venue_id=venue_id, status="cancelled")
        session.add(terminal)
        session.commit()
        terminal_id = terminal.id
    response = timing_patch(client, venue_id, 30, 30)
    assert response.status_code == 200
    assert response.json["affected_booking_count"] == 2
    assert response.json["pending_review_count"] == 2
    with Session(app.extensions["engine"]) as session:
        assert session.get(VenueBooking, first["id"]).requires_review
        assert session.get(VenueBooking, second["id"]).requires_review
        assert session.get(VenueBooking, terminal_id).status == "cancelled"
        assert not session.get(VenueBooking, terminal_id).requires_review


# TC-SPL-130-002 — AC1: a future legacy commitment is retained and flagged for exact-time review.
def test_tc_spl_130_002_legacy_booking_is_flagged_without_mutation(app, client):
    venue_id = venue(app)
    event_id = event(app, "Legacy", time(13), time(14))
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(
            event_request_id=event_id,
            venue_id=venue_id,
            status="approved",
            booking_date=FUTURE,
            event_slots=["PM"],
        )
        session.add(booking)
        session.flush()
        session.add(
            VenueBookingOccupancy(
                booking_id=booking.id,
                venue_id=venue_id,
                day=FUTURE,
                slot="PM",
                kind="event",
            )
        )
        session.commit()
        booking_id = booking.id
    assert timing_patch(client, venue_id, 15).status_code == 200
    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueBooking, booking_id)
        finding = session.scalar(
            select(VenueBookingReviewFinding).where(
                VenueBookingReviewFinding.booking_id == booking_id
            )
        )
        assert stored.status == "approved" and stored.exact_timing is None
        assert finding.reason_type == "unresolved_historical_timing"
        assert finding.original_occupancy["legacy_slots"][0]["slot"] == "PM"


# TC-SPL-130-003 — AC2: a buffer increase flags every overlapping participant with evidence.
def test_tc_spl_130_003_overlap_marks_both_with_original_and_new_occupancy(app, client):
    venue_id = venue(app)
    first = book(client, event(app, "Alpha", time(10), time(11)), venue_id, "10:00", "11:00")
    second = book(client, event(app, "Bravo", time(11), time(12)), venue_id, "11:00", "12:00")
    assert timing_patch(client, venue_id, 30, 30).json["affected_booking_count"] == 2
    queue = client.get("/api/venue-bookings/timing-reviews", headers=headers()).json["reviews"]
    assert {item["booking_id"] for item in queue} == {first["id"], second["id"]}
    assert {item["coordinator"]["name"] for item in queue} == {"Casey Lim"}
    for item in queue:
        assert item["event"]["advertised_interval"]["start"]
        assert item["event"]["advertised_interval"]["end"]
        finding = next(f for f in item["findings"] if f["reason_type"] == "overlap")
        assert finding["original_occupancy"]["start"]
        assert finding["current_occupancy"]["start"]
        assert "overlaps" in finding["detail"]


# TC-SPL-130-004 — AC2: outside-hours and operational-block causes remain separate findings.
def test_tc_spl_130_004_multiple_reason_types_are_preserved(app, client):
    venue_id = venue(app)
    booking = book(client, event(app, "Affected", time(10), time(11)), venue_id, "10:00", "11:00")
    assert (
        client.post(
            f"/api/venues/{venue_id}/operational-blocks",
            headers=headers(),
            json={
                "date": FUTURE.isoformat(),
                "start_time": "10:30",
                "end_time": "10:45",
                "reason": "Safety inspection",
            },
        ).status_code
        == 201
    )
    assert timing_patch(client, venue_id, 15, hours=[[600, 660]]).status_code == 200
    review = client.get(f"/api/venue-bookings/{booking['id']}", headers=headers()).json["review"]
    assert {finding["reason_type"] for finding in review["findings"]} == {
        "operational_block",
        "outside_operating_hours",
    }


# TC-SPL-130-005 — AC3: Venue Staff and only the assigned coordinator can read the finding.
def test_tc_spl_130_005_authorized_views_share_the_same_finding(app, client):
    venue_id = venue(app)
    event_id = event(app, "Visible", time(10), time(11))
    booking = book(client, event_id, venue_id, "10:00", "11:00")
    timing_patch(client, venue_id, 15, hours=[[600, 660]])
    staff = client.get("/api/venue-bookings/timing-reviews", headers=headers())
    coordinator = client.get(
        f"/api/event-requests/{event_id}/venue-booking-status",
        headers=headers("coordinator"),
    )
    assert staff.status_code == coordinator.status_code == 200
    assert staff.json["reviews"][0]["findings"] == coordinator.json["review"]["findings"]
    assert (
        client.get("/api/venue-bookings/timing-reviews", headers=headers("coordinator")).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/event-requests/{event_id}/venue-booking-status",
            headers=headers("other-coordinator"),
        ).status_code
        == 404
    )
    assert booking["id"] == staff.json["reviews"][0]["booking_id"]


# TC-SPL-130-006 — AC3: findings never cancel/delete commitments and new overlaps are refused.
def test_tc_spl_130_006_flagged_commitments_still_protect_allocation(app, client):
    venue_id = venue(app)
    event_id = event(app, "Protected", time(10), time(11))
    booking = book(client, event_id, venue_id, "10:00", "11:00")
    timing_patch(client, venue_id, 30, 30)
    attempted = event(app, "New allocation", time(11), time(12))
    response = client.post(
        f"/api/event-requests/{attempted}/venue-bookings",
        headers=headers("coordinator"),
        json={
            "venue_id": venue_id,
            "layout": "theatre",
            "date": FUTURE.isoformat(),
            "start_time": "11:00",
            "end_time": "12:00",
            "venue_revision": 2,
        },
    )
    assert response.status_code == 409
    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueBooking, booking["id"])
        assert stored is not None and stored.status == "requested"


# TC-SPL-130-007 — AC4: repeated assessment updates evidence without duplicate findings.
def test_tc_spl_130_007_reassessment_is_idempotent_and_does_not_silently_clear(app, client):
    venue_id = venue(app)
    booking = book(client, event(app, "Repeat", time(10), time(11)), venue_id, "10:00", "11:00")
    timing_patch(client, venue_id, 15, hours=[[600, 660]])
    timing_patch(client, venue_id, 15, hours=[[0, 1440]])
    with Session(app.extensions["engine"]) as session:
        findings = session.scalars(
            select(VenueBookingReviewFinding).where(
                VenueBookingReviewFinding.booking_id == booking["id"]
            )
        ).all()
        assert len(findings) == 1
        assert findings[0].resolved_at is None
        assert findings[0].venue_timing_revision == 2
        assert session.get(VenueBooking, booking["id"]).requires_review


# TC-SPL-130-008 — AC4: explicit review clears passing timing only; block review remains.
def test_tc_spl_130_008_explicit_review_retains_operational_reason(app, client):
    venue_id = venue(app)
    booking = book(client, event(app, "Explicit", time(10), time(11)), venue_id, "10:00", "11:00")
    timing_patch(client, venue_id, 15, hours=[[600, 660]])
    client.post(
        f"/api/venues/{venue_id}/operational-blocks",
        headers=headers(),
        json={
            "date": FUTURE.isoformat(),
            "start_time": "10:30",
            "end_time": "10:45",
            "reason": "Inspection",
        },
    )
    timing_patch(client, venue_id, 15, hours=[[0, 1440]])
    response = client.post(
        f"/api/venue-bookings/{booking['id']}/timing-review", headers=headers(), json={}
    )
    assert response.status_code == 200, response.json
    assert response.json["review"]["requires_review"] is True
    assert [f["reason_type"] for f in response.json["review"]["findings"]] == ["operational_block"]
    with Session(app.extensions["engine"]) as session:
        timing = session.scalar(
            select(VenueBookingReviewFinding).where(
                VenueBookingReviewFinding.booking_id == booking["id"],
                VenueBookingReviewFinding.reason_type == "outside_operating_hours",
            )
        )
        assert timing.resolved_at is not None
        assert session.get(VenueBooking, booking["id"]).exact_timing["venue_revision"] == 3


# TC-SPL-130-011 — AC4: removing a block is its explicit, audited resolution workflow.
def test_tc_spl_130_011_block_removal_resolves_finding_and_clears_queue(app, client):
    venue_id = venue(app)
    booking = book(
        client,
        event(app, "Block removal", time(10), time(11)),
        venue_id,
        "10:00",
        "11:00",
    )
    created = client.post(
        f"/api/venues/{venue_id}/operational-blocks",
        headers=headers(),
        json={
            "date": FUTURE.isoformat(),
            "start_time": "10:30",
            "end_time": "10:45",
            "reason": "Inspection",
        },
    )
    block_id = created.json["operational_block"]["id"]

    removed = client.delete(
        f"/api/venues/{venue_id}/operational-blocks/{block_id}", headers=headers()
    )
    assert removed.status_code == 200
    assert removed.json["resolved_finding_count"] == 1
    assert client.get("/api/venue-bookings/timing-reviews", headers=headers()).json["count"] == 0
    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueBooking, booking["id"])
        finding = session.scalar(
            select(VenueBookingReviewFinding).where(
                VenueBookingReviewFinding.booking_id == booking["id"],
                VenueBookingReviewFinding.reason_type == "operational_block",
            )
        )
        assert stored.requires_review is False
        assert stored.review_trigger_block_id is None
        assert finding.resolved_at is not None
        assert finding.resolved_by_account_id == legacy.VENUE_STAFF


# TC-SPL-130-012 — AC4: block removal leaves independent timing findings active.
def test_tc_spl_130_012_block_removal_recomputes_from_remaining_findings(app, client):
    venue_id = venue(app)
    booking = book(client, event(app, "Two causes", time(10), time(11)), venue_id, "10:00", "11:00")
    created = client.post(
        f"/api/venues/{venue_id}/operational-blocks",
        headers=headers(),
        json={
            "date": FUTURE.isoformat(),
            "start_time": "10:30",
            "end_time": "10:45",
            "reason": "Inspection",
        },
    )
    timing_patch(client, venue_id, 15, hours=[[600, 660]])
    client.delete(
        f"/api/venues/{venue_id}/operational-blocks/{created.json['operational_block']['id']}",
        headers=headers(),
    )

    review = client.get(f"/api/venue-bookings/{booking['id']}", headers=headers()).json["review"]
    assert review["requires_review"] is True
    assert [finding["reason_type"] for finding in review["findings"]] == ["outside_operating_hours"]


# TC-SPL-130-009 — AC4: a still-overlapping review cannot be cleared.
def test_tc_spl_130_009_failed_review_keeps_findings(app, client):
    venue_id = venue(app)
    first = book(client, event(app, "One", time(10), time(11)), venue_id, "10:00", "11:00")
    book(client, event(app, "Two", time(11), time(12)), venue_id, "11:00", "12:00")
    # Only the later booking's revised setup overlaps the first booking. Explicit review must
    # compare both recalculated intervals, rather than the peer's obsolete saved snapshot.
    timing_patch(client, venue_id, 30, 0)
    response = client.post(
        f"/api/venue-bookings/{first['id']}/timing-review", headers=headers(), json={}
    )
    assert response.status_code == 409
    with Session(app.extensions["engine"]) as session:
        assert (
            session.scalar(
                select(func.count(VenueBookingReviewFinding.id)).where(
                    VenueBookingReviewFinding.booking_id == first["id"],
                    VenueBookingReviewFinding.resolved_at.is_(None),
                )
            )
            == 1
        )
