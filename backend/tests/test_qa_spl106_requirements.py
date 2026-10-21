"""SPL-106 requirement-driven QA; event edits exercise the SPL-109/112 handoff."""

from copy import deepcopy
from datetime import date, datetime, time, timezone

import pytest
import test_venue_booking_requests as base
from app.models import (
    EventRequest,
    Venue,
    VenueBooking,
    VenueBookingReviewFinding,
    VenueBookingStatusHistory,
)
from app.venue_requirement_review import (
    assess_event_bookings,
    legacy_timing_reasons,
    requirement_reasons,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

base_app = base.app
DAY = date(2030, 6, 15)
WHEN = datetime(2030, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def app(base_app):
    base_app.config["EXACT_VENUE_TIMING_ENABLED"] = True
    return base_app


@pytest.fixture
def client(app):
    return app.test_client()


def room(app, name="QA hall"):
    venue_id = base.add_venue(app, name, setup=0, turnaround=0)
    with Session(app.extensions["engine"]) as session:
        venue = session.get(Venue, venue_id)
        venue.setup_minutes = venue.turnaround_minutes = 0
        venue.operating_intervals = [[0, 1440]]
        venue.timing_revision = 1
        session.commit()
    return venue_id


def request(client, event, venue, **changes):
    body = {
        "venue_id": venue,
        "layout": "theatre",
        "attendee_count": 150,
        "required_facilities": ["Projector"],
        "date": DAY.isoformat(),
        "start_time": "10:00",
        "end_time": "11:00",
        "venue_revision": 1,
        **changes,
    }
    return client.post(
        f"/api/event-requests/{event}/venue-bookings", json=body, headers=base.headers()
    )


def scenario(app, client, *, approved=False, siblings=False):
    event = base.make_event(app, day=DAY, start=time(10), end=time(12), attendance=300)
    venue = room(app)
    response = request(client, event, venue)
    assert response.status_code == 201, response.json
    bookings = [response.json["booking"]]
    if siblings:
        response = request(
            client, event, room(app, "QA sibling"), start_time="11:00", end_time="12:00"
        )
        assert response.status_code == 201, response.json
        bookings.append(response.json["booking"])
    if approved:
        for booking in bookings:
            response = client.post(
                f"/api/venue-bookings/{booking['id']}/approve",
                json={},
                headers=base.headers("venue-staff"),
            )
            assert response.status_code == 200, response.json
    return event, venue, bookings


def edit(app, event_id, mutation=lambda event, session: None, *, commit=True):
    with Session(app.extensions["engine"]) as session:
        event = session.scalar(
            select(EventRequest).where(EventRequest.id == event_id).with_for_update()
        )
        mutation(event, session)
        affected = assess_event_bookings(
            session, event, assessed_by_account_id=base.COORDINATOR, assessed_at=WHEN
        )
        if commit:
            session.commit()
        else:
            session.rollback()
        return affected


def detail(client, booking, token="venue-staff"):
    response = client.get(f"/api/venue-bookings/{booking['id']}", headers=base.headers(token))
    assert response.status_code == 200, response.json
    return response.json


def kinds(client, booking):
    return {row["reason_type"] for row in detail(client, booking)["review"].get("findings", [])}


def capacity(client, venue, value):
    response = client.patch(
        f"/api/venues/{venue}",
        json={"layouts": [{"layout": "theatre", "capacity": value}]},
        headers=base.headers("venue-staff"),
    )
    assert response.status_code == 200, response.json
    return response.json


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("expected_attendance", 201, "layout_capacity"),
        ("layout", "cabaret", "layout_capacity"),
    ],
)
# QA-SPL-106-001 | AC1 | WB
def test_qa_spl_106_001_independent_allocation(app, client, field, value, reason):
    event, _, (first, sibling) = scenario(app, client, approved=True, siblings=True)
    before = detail(client, sibling)
    assert (
        edit(app, event, lambda e, s: setattr(s.get(VenueBooking, first["id"]), field, value)) == 1
    )
    assert reason in kinds(client, first)
    assert detail(client, sibling) == before


# QA-SPL-106-002 | AC1 | WB
def test_qa_spl_106_002_event_total_keeps_allocations(app, client):
    event, _, bookings = scenario(app, client, siblings=True)
    before = [detail(client, booking) for booking in bookings]
    assert edit(app, event, lambda e, s: setattr(e, "expected_attendance", 500)) == 0
    after = [detail(client, booking) for booking in bookings]
    for original, current in zip(before, after, strict=True):
        assert current["booking"] == original["booking"]
        assert current["review"] == original["review"]
        assert current["event"]["expected_attendance"] == 500


# QA-SPL-106-003 | AC1 | WB
def test_qa_spl_106_003_arrangement_facilities_isolated(app, client):
    event, _, (first, sibling) = scenario(app, client, siblings=True)
    assert (
        edit(
            app,
            event,
            lambda e, s: setattr(
                s.get(VenueBooking, first["id"]), "required_facilities", ["Hearing loop"]
            ),
        )
        == 1
    )
    assert kinds(client, first) == {"facilities"}
    assert kinds(client, sibling) == set()


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("accessibility_needs", ["Lift"], "accessibility"),
        ("location_preference", "West campus", "location"),
    ],
)
# QA-SPL-106-004 | AC1 | WB
def test_qa_spl_106_004_shared_requirements(app, client, field, value, reason):
    event, _, bookings = scenario(app, client, siblings=True)
    assert edit(app, event, lambda e, s: setattr(e, field, value)) == 2
    assert all(kinds(client, booking) == {reason} for booking in bookings)


# QA-SPL-106-005 | AC1 | WB
def test_qa_spl_106_005_exact_event_boundary(app, client):
    event, _, (first, sibling) = scenario(app, client, siblings=True)
    assert edit(app, event, lambda e, s: setattr(e, "end_time", time(11))) == 1
    assert kinds(client, first) == set()
    assert kinds(client, sibling) == {"event_times"}


# QA-SPL-106-006 | AC2 | BB
def test_qa_spl_106_006_persisted_reason_after_reload(app, client):
    _, venue, (booking,) = scenario(app, client)
    assert capacity(client, venue, 149)["affected_booking_count"] == 1
    body = detail(app.test_client(), booking)
    assert body["review"]["requires_review"]
    assert body["review"]["findings"][0]["detail"]
    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueBooking, booking["id"])
        assert stored.review_marked_by_account_id == base.VENUE_STAFF
        assert stored.review_marked_at is not None


# QA-SPL-106-007 | AC2 | BB
def test_qa_spl_106_007_all_failed_checks_listed(app, client):
    _, venue, (booking,) = scenario(app, client)
    response = client.patch(
        f"/api/venues/{venue}",
        headers=base.headers("venue-staff"),
        json={
            "facilities": [],
            "accessibility_features": [],
            "location": "Other campus",
            "layouts": [{"layout": "theatre", "capacity": 149}],
        },
    )
    assert response.status_code == 200
    assert kinds(client, booking) == {"layout_capacity", "facilities", "accessibility", "location"}


# QA-SPL-106-008 | AC2 | WB
def test_qa_spl_106_008_retries_do_not_duplicate_flags(app, client):
    _, venue, (booking,) = scenario(app, client)
    capacity(client, venue, 149)
    capacity(client, venue, 149)
    with Session(app.extensions["engine"]) as session:
        findings = session.scalars(
            select(VenueBookingReviewFinding).where(
                VenueBookingReviewFinding.booking_id == booking["id"]
            )
        ).all()
        events = session.scalars(
            select(VenueBookingStatusHistory).where(
                VenueBookingStatusHistory.booking_id == booking["id"],
                VenueBookingStatusHistory.action == "review_required",
            )
        ).all()
        assert len(findings) == len(events) == 1


@pytest.mark.parametrize(
    "token,expected", [(None, 401), ("organiser", 403), ("other-coordinator", 403)]
)
# QA-SPL-106-009 | AC2 | BB
def test_qa_spl_106_009_review_details_authorized(app, client, token, expected):
    _, venue, (booking,) = scenario(app, client)
    capacity(client, venue, 149)
    response = client.get(f"/api/venue-bookings/{booking['id']}", headers=base.headers(token))
    assert response.status_code == expected
    assert "No theatre" not in response.get_data(as_text=True)


# QA-SPL-106-010 | AC2 | BB
def test_qa_spl_106_010_capacity_equality_is_valid(app, client):
    _, venue, (booking,) = scenario(app, client)
    assert capacity(client, venue, 150)["affected_booking_count"] == 0
    assert not detail(client, booking)["review"]["requires_review"]


@pytest.mark.parametrize("approved", [False, True])
# QA-SPL-106-011 | AC3 | BB
def test_qa_spl_106_011_status_and_occupancy_preserved(app, client, approved):
    _, venue, (booking,) = scenario(app, client, approved=approved)
    before = detail(client, booking)["booking"]
    capacity(client, venue, 149)
    after = detail(client, booking)["booking"]
    assert after["status"] == before["status"]
    assert after["timing"] == before["timing"]
    assert after["expected_attendance"] == before["expected_attendance"]


# QA-SPL-106-012 | AC3 | WB
def test_qa_spl_106_012_date_change_does_not_release_old_time(app, client):
    event, venue, (booking,) = scenario(app, client, approved=True)
    assert edit(app, event, lambda e, s: setattr(e, "proposed_date", DAY.replace(day=16))) == 1
    assert detail(client, booking)["booking"]["timing"] == booking["timing"]
    other = base.make_event(app, name="Competing event", day=DAY, start=time(10), end=time(12))
    assert request(client, other, venue).status_code == 409


# QA-SPL-106-013 | AC3 | WB
def test_qa_spl_106_013_caller_owns_transaction(app, client):
    event, _, (booking,) = scenario(app, client)
    assert edit(app, event, lambda e, s: setattr(e, "expected_attendance", 100), commit=False) == 1
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event).expected_attendance == 300
        assert session.scalar(select(VenueBookingReviewFinding)) is None
        assert not session.get(VenueBooking, booking["id"]).requires_review


@pytest.mark.parametrize("status", ["cancelled", "withdrawn", "rejected"])
# QA-SPL-106-014 | AC3 | WB
def test_qa_spl_106_014_terminal_bookings_unchanged(app, client, status):
    event, _, (booking,) = scenario(app, client)
    with Session(app.extensions["engine"]) as session:
        session.get(VenueBooking, booking["id"]).status = status
        session.commit()
    assert edit(app, event, lambda e, s: setattr(e, "expected_attendance", 100)) == 0
    assert not kinds(client, booking)


# QA-SPL-106-015 | AC3 | BB
def test_qa_spl_106_015_explicit_cancellation_retains_history(app, client):
    event, venue, (booking,) = scenario(app, client, approved=True)
    capacity(client, venue, 149)
    response = client.post(
        f"/api/event-requests/{event}/venue-bookings/{booking['id']}/cancel",
        headers=base.headers(),
        json={"reason": "Choose a suitable room"},
    )
    assert response.status_code == 200, response.json
    with Session(app.extensions["engine"]) as session:
        assert session.get(VenueBooking, booking["id"]).status == "cancelled"
        assert session.scalar(select(VenueBookingReviewFinding)) is not None
        actions = session.scalars(
            select(VenueBookingStatusHistory.action).where(
                VenueBookingStatusHistory.booking_id == booking["id"]
            )
        ).all()
        assert "review_required" in actions and "cancel" in actions


# QA-SPL-106-016 | AC4 | BB
def test_qa_spl_106_016_restoration_clears_with_audit(app, client):
    _, venue, (booking,) = scenario(app, client)
    capacity(client, venue, 149)
    capacity(client, venue, 150)
    assert not detail(client, booking)["review"]["requires_review"]
    with Session(app.extensions["engine"]) as session:
        finding = session.scalar(select(VenueBookingReviewFinding))
        assert finding.resolved_at and finding.resolved_by_account_id == base.VENUE_STAFF
        assert session.scalar(
            select(VenueBookingStatusHistory).where(
                VenueBookingStatusHistory.action == "review_resolved"
            )
        )


# QA-SPL-106-017 | AC4 | BB
def test_qa_spl_106_017_acknowledgement_keeps_failure(app, client):
    _, venue, (booking,) = scenario(app, client)
    capacity(client, venue, 149)
    response = client.post(
        f"/api/venue-bookings/{booking['id']}/timing-review",
        json={},
        headers=base.headers("venue-staff"),
    )
    assert response.status_code == 200
    assert response.json["review"]["requires_review"]
    assert kinds(client, booking) == {"layout_capacity"}


# QA-SPL-106-018 | AC4 | BB
def test_qa_spl_106_018_all_current_checks_must_pass(app, client):
    _, venue, (booking,) = scenario(app, client)
    capacity(client, venue, 149)
    response = client.patch(
        f"/api/venues/{venue}", json={"facilities": []}, headers=base.headers("venue-staff")
    )
    assert response.status_code == 200
    capacity(client, venue, 200)
    assert kinds(client, booking) == {"layout_capacity", "facilities"}


# QA-SPL-106-019 | AC4 | BB
def test_qa_spl_106_019_unrelated_block_not_cleared(app, client):
    _, venue, (booking,) = scenario(app, client)
    capacity(client, venue, 149)
    response = client.post(
        f"/api/venues/{venue}/operational-blocks",
        headers=base.headers("venue-staff"),
        json={
            "date": DAY.isoformat(),
            "start_time": "10:00",
            "end_time": "11:00",
            "reason": "QA maintenance",
        },
    )
    assert response.status_code == 201, response.json
    capacity(client, venue, 200)
    assert {"operational_block", "layout_capacity"} <= kinds(client, booking)


# QA-SPL-106-020 | AC4 | WB
def test_qa_spl_106_020_reopen_retains_history(app, client):
    _, venue, (booking,) = scenario(app, client)
    for value in [149, 200, 149]:
        capacity(client, venue, value)
    with Session(app.extensions["engine"]) as session:
        assert len(session.scalars(select(VenueBookingReviewFinding)).all()) == 1
        actions = session.scalars(
            select(VenueBookingStatusHistory.action)
            .where(VenueBookingStatusHistory.booking_id == booking["id"])
            .order_by(VenueBookingStatusHistory.id)
        ).all()
        assert actions[-3:] == ["review_required", "review_resolved", "review_required"]


# QA-SPL-106-021 | AC5 | BB
def test_qa_spl_106_021_single_layout_update(app, client):
    _, venue, (booking,) = scenario(app, client)
    with Session(app.extensions["engine"]) as session:
        layout_id = session.get(Venue, venue).layouts[0].id
    response = client.patch(
        f"/api/venues/{venue}/layouts/{layout_id}",
        json={"layout": "theatre", "capacity": 149},
        headers=base.headers("venue-staff"),
    )
    assert response.status_code == 200
    assert kinds(client, booking) == {"layout_capacity"}


# QA-SPL-106-022 | AC5 | BB
def test_qa_spl_106_022_layout_delete_and_recreate(app, client):
    _, venue, (booking,) = scenario(app, client)
    with Session(app.extensions["engine"]) as session:
        layout_id = session.get(Venue, venue).layouts[0].id
    assert (
        client.delete(
            f"/api/venues/{venue}/layouts/{layout_id}", headers=base.headers("venue-staff")
        ).status_code
        == 204
    )
    assert kinds(client, booking) == {"layout_capacity"}
    assert (
        client.post(
            f"/api/venues/{venue}/layouts",
            json={"layout": "theatre", "capacity": 150},
            headers=base.headers("venue-staff"),
        ).status_code
        == 201
    )
    assert not kinds(client, booking)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("facilities", [], "facilities"),
        ("accessibility_features", [], "accessibility"),
        ("location", "Other campus", "location"),
    ],
)
# QA-SPL-106-023 | AC5 | BB
def test_qa_spl_106_023_profile_edit_triggers_assessment(app, client, field, value, reason):
    _, venue, (booking,) = scenario(app, client)
    response = client.patch(
        f"/api/venues/{venue}", json={field: value}, headers=base.headers("venue-staff")
    )
    assert response.status_code == 200
    assert kinds(client, booking) == {reason}


@pytest.mark.parametrize("setup,turnaround", [(15, 0), (0, 15)])
# QA-SPL-106-024 | AC5 | BB
def test_qa_spl_106_024_buffers_recheck_and_preserve_times(app, client, setup, turnaround):
    event, venue, (booking,) = scenario(app, client)
    second = request(client, event, venue, start_time="11:00", end_time="12:00")
    assert second.status_code == 201, second.json
    response = client.patch(
        f"/api/venues/{venue}",
        headers=base.headers("venue-staff"),
        json={
            "setup_minutes": setup,
            "turnaround_minutes": turnaround,
            "operating_intervals": [[0, 1440]],
        },
    )
    assert response.status_code == 200
    assert "overlap" in kinds(client, booking)
    assert detail(client, booking)["booking"]["timing"] == booking["timing"]


@pytest.mark.parametrize("token,status", [(None, 401), ("organiser", 403), ("coordinator", 403)])
# QA-SPL-106-025 | AC5 | BB
def test_qa_spl_106_025_profile_authority_cannot_be_spoofed(app, client, token, status):
    _, venue, (booking,) = scenario(app, client)
    response = client.patch(
        f"/api/venues/{venue}",
        headers=base.headers(token),
        json={"facilities": [], "user_id": base.VENUE_STAFF, "role": "venue_staff"},
    )
    assert response.status_code == status
    assert not kinds(client, booking)


# QA-SPL-106-026 | AC1 | WB
def test_qa_spl_106_026_empty_event_and_default_time(app, client):
    event = base.make_event(app, day=DAY)
    with Session(app.extensions["engine"]) as session:
        assert (
            assess_event_bookings(
                session, session.get(EventRequest, event), assessed_by_account_id=base.COORDINATOR
            )
            == 0
        )


@pytest.mark.parametrize(
    "timing", [{"event": {}}, {"event": {"start": "invalid", "end": "invalid"}}]
)
# QA-SPL-106-027 | AC4 | WB
def test_qa_spl_106_027_malformed_timing_cannot_clear(app, client, timing):
    event, _, (booking,) = scenario(app, client)
    assert (
        edit(
            app,
            event,
            lambda e, s: setattr(s.get(VenueBooking, booking["id"]), "exact_timing", timing),
        )
        == 1
    )
    assert "event_times" in kinds(client, booking)


# QA-SPL-106-028 | AC1 | WB
def test_qa_spl_106_028_legacy_requirements_and_date(app, client):
    event, venue, (booking,) = scenario(app, client)
    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueBooking, booking["id"])
        stored.exact_timing = None
        stored.event_slots = ["AM"]
        stored.expected_attendance = None
        row = session.get(EventRequest, event)
        row.expected_attendance = 150
        row.end_time = time(12)
        assert not requirement_reasons(session.get(Venue, venue), row, stored)
        row.proposed_date = DAY.replace(day=16)
        assert {
            kind for _, kind, _ in requirement_reasons(session.get(Venue, venue), row, stored)
        } == {"event_times"}


# QA-SPL-106-029 | AC3 | WB
def test_qa_spl_106_029_completed_event_is_untouched(app, client):
    event, _, (booking,) = scenario(app, client)

    def change(row, session):
        row.status = "completed"
        row.expected_attendance = 100

    assert edit(app, event, change) == 0
    with Session(app.extensions["engine"]) as session:
        assert not session.get(VenueBooking, booking["id"]).requires_review


# QA-SPL-106-030 | AC4 | WB
def test_qa_spl_106_030_original_peer_occupancy_stays_protected(app, client):
    event, venue, (booking,) = scenario(app, client)
    second = request(client, event, venue, start_time="11:00", end_time="12:00").json["booking"]
    with Session(app.extensions["engine"]) as session:
        peer = session.get(VenueBooking, second["id"])
        timing = deepcopy(peer.exact_timing)
        timing["occupied"]["start"] = f"{DAY}T10:45:00+08:00"
        peer.exact_timing = timing
        session.commit()
    assert edit(app, event) >= 1
    assert "overlap" in kinds(client, booking)


@pytest.mark.parametrize(
    "problem,reason",
    [
        ("none", None),
        ("invalid", "unresolved_historical_timing"),
        ("hours", "outside_operating_hours"),
        ("block", "operational_block"),
        ("peer", "overlap"),
        ("unknown-peer", "overlap"),
        ("distant-peer", None),
    ],
)
# QA-SPL-106-035 | AC4 | WB
def test_qa_spl_106_035_legacy_clearance_checks(app, client, problem, reason):
    app.config["EXACT_VENUE_TIMING_ENABLED"] = False
    event = base.make_event(app, day=DAY, start=time(10), end=time(12))
    venue = base.add_venue(app, setup=0, turnaround=0)
    response = base.request_booking(client, event, venue)
    assert response.status_code == 201, response.json
    booking = response.json["booking"]
    if problem == "block":
        base.add_block(app, venue, DAY, ["AM"])
    with Session(app.extensions["engine"]) as session:
        stored = session.get(VenueBooking, booking["id"])
        place = session.get(Venue, venue)
        if problem == "invalid":
            stored.event_slots = []
        if problem == "hours":
            place.operating_slots = ["PM"]
        if problem in ("peer", "unknown-peer", "distant-peer"):
            peer = VenueBooking(event_request_id=event, venue_id=venue, status="requested")
            if problem != "unknown-peer":
                start = "14:00" if problem == "distant-peer" else "10:00"
                end = "15:00" if problem == "distant-peer" else "11:00"
                peer.exact_timing = {
                    "occupied": {"start": f"{DAY}T{start}:00+08:00", "end": f"{DAY}T{end}:00+08:00"}
                }
            session.add(peer)
        reasons = legacy_timing_reasons(session, place, stored)
        assert {kind for _, kind, _ in reasons} == ({reason} if reason else set())


# QA-SPL-106-036 | AC1 | WB
def test_qa_spl_106_036_missing_legacy_event_times(app, client):
    event, venue, (booking,) = scenario(app, client)
    with Session(app.extensions["engine"]) as session:
        row = session.get(EventRequest, event)
        stored = session.get(VenueBooking, booking["id"])
        place = session.get(Venue, venue)
        stored.exact_timing = None
        stored.event_slots = ["AM"]
        row.start_time = None
        assert "event_times" in {kind for _, kind, _ in requirement_reasons(place, row, stored)}


# QA-SPL-106-037 | AC2 | BB
def test_qa_spl_106_037_assigned_coordinator_status_isolation(app, client):
    event, venue, (booking,) = scenario(app, client)
    capacity(client, venue, 149)
    allowed = client.get(
        f"/api/event-requests/{event}/venue-booking-status", headers=base.headers()
    )
    assert allowed.status_code == 200
    assert allowed.json["review"]["findings"][0]["reason_type"] == "layout_capacity"
    refused = client.get(
        f"/api/event-requests/{event}/venue-booking-status",
        headers=base.headers("other-coordinator"),
    )
    assert refused.status_code == 404
    assert "layout_capacity" not in refused.get_data(as_text=True)


# QA-SPL-106-038 | AC5 | BB
def test_qa_spl_106_038_legacy_profile_edit_no_invented_timing_failure(app, client):
    app.config["EXACT_VENUE_TIMING_ENABLED"] = False
    event = base.make_event(app, day=DAY, start=time(10), end=time(12))
    venue = base.add_venue(app, setup=0, turnaround=0)
    response = base.request_booking(client, event, venue)
    assert response.status_code == 201, response.json
    booking = response.json["booking"]
    capacity(client, venue, 149)
    assert kinds(client, booking) == {"layout_capacity"}
    capacity(client, venue, 150)
    assert not kinds(client, booking)
