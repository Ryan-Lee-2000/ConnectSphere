"""SPL-129 database adapter for read-only exact venue timing."""

from datetime import timedelta

from flask import abort, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Venue, VenueBooking, VenueOperationalBlock
from app.venue_timing import (
    legacy_slot_interval,
    occupied_interval,
    opening_covers,
    parse_event_interval,
    validate_intervals,
)


def timing_for(venue, event):
    occupied = occupied_interval(event, venue.setup_minutes, venue.turnaround_minutes)
    return occupied, {
        "event": event.serialize(),
        "occupied": occupied.serialize(),
        "setup_minutes": venue.setup_minutes,
        "turnaround_minutes": venue.turnaround_minutes,
    }


def exact_availability(session, venue, event):
    if (
        venue.setup_minutes is None
        or venue.turnaround_minutes is None
        or venue.operating_intervals is None
    ):
        return False, "Confirm venue operating hours and preparation minutes.", None
    try:
        occupied, timing = timing_for(venue, event)
        hours = validate_intervals(venue.operating_intervals)
        if not opening_covers(occupied, hours):
            return False, "The complete occupied interval is outside operating hours.", timing
        bookings = session.scalars(
            select(VenueBooking)
            .where(
                VenueBooking.venue_id == venue.id,
                VenueBooking.status.in_(("requested", "approved")),
            )
            .options(selectinload(VenueBooking.occupancy))
        ).all()
        for booking in bookings:
            if not booking.occupancy:
                return False, "An active legacy booking needs timing review.", timing
            for claim in booking.occupancy:
                if occupied.overlaps(legacy_slot_interval(claim.day, claim.slot)):
                    return (
                        False,
                        "An active booking protects part of the occupied interval.",
                        timing,
                    )
        blocks = session.scalars(
            select(VenueOperationalBlock).where(
                VenueOperationalBlock.venue_id == venue.id,
                VenueOperationalBlock.removed_at.is_(None),
                VenueOperationalBlock.start_date <= occupied.end.date(),
                VenueOperationalBlock.end_date >= occupied.start.date(),
            )
        ).all()
        for block in blocks:
            first = max(block.start_date, occupied.start.date())
            last = min(block.end_date, occupied.end.date())
            # At most two edge days plus an interior day: block slots repeat daily.
            days = {first, last}
            if (last - first).days > 1:
                days.add(first + timedelta(days=1))
            for day in days:
                for slot in block.slots:
                    if occupied.overlaps(legacy_slot_interval(day, slot)):
                        return (
                            False,
                            "An operational block covers part of the occupied interval.",
                            timing,
                        )
        return True, "Available for the full advertised and preparation interval.", timing
    except ValueError:
        return False, "Venue timing evidence requires review.", None


def exact_suitability(session, venue, event):
    from app.venue_availability import profile_suitability_checks

    passed, detail, timing = False, "Record a valid event date and quarter-hour times.", None
    if event.proposed_date and event.start_time and event.end_time:
        try:
            if (
                event.start_time.second
                or event.end_time.second
                or event.start_time.microsecond
                or event.end_time.microsecond
            ):
                raise ValueError("Historical event precision requires review.")
            interval = parse_event_interval(
                event.proposed_date.isoformat(),
                event.start_time.strftime("%H:%M"),
                event.end_time.strftime("%H:%M"),
            )
            passed, detail, timing = exact_availability(session, venue, interval)
        except ValueError:
            pass
    checks = [
        {"key": "timing", "label": "Timing and preparation", "passed": passed, "detail": detail}
    ] + profile_suitability_checks(venue, event)
    return {
        "suitable": all(check["passed"] for check in checks),
        "checks": checks,
        "timing": timing,
    }


def find_exact_venues(app, event_request_id):
    from app.venue_availability import (
        SearchParameterError,
        _planning_event,
        _requirement_parameters,
        parse_search_parameters,
        qualifying_layouts,
        venue_satisfies_requirements,
    )

    if not app.config["EXACT_VENUE_TIMING_ENABLED"]:
        abort(409, "Exact venue timing is not enabled.")
    with Session(app.extensions["engine"]) as session:
        event = _planning_event(session, event_request_id)
        try:
            allowed = {
                "date",
                "start_time",
                "end_time",
                "expected_attendance",
                "preferred_room_layout",
                "required_facility",
                "accessibility_need",
                "location_preference",
            }
            if set(request.args) - allowed:
                raise ValueError("Unexpected exact-time search parameter.")
            if any(
                len(request.args.getlist(key)) != 1
                for key in allowed - {"required_facility", "accessibility_need"}
                if key in request.args
            ):
                raise ValueError("Search values must not be repeated.")
            interval = parse_event_interval(
                request.args.get("date"),
                request.args.get("start_time"),
                request.args.get("end_time"),
            )
            attendance_supplied = "expected_attendance" in request.args
            layout_supplied = "preferred_room_layout" in request.args
            _, _, attendance, layout = parse_search_parameters(
                request.args.get("date"),
                ["AM"],
                request.args.get("expected_attendance"),
                request.args.get("preferred_room_layout"),
                attendance_supplied,
                layout_supplied,
            )
        except (ValueError, SearchParameterError) as exc:
            abort(400, str(exc))
        facilities, accessibility, location, fs, acs, ls = _requirement_parameters()
        attendance = attendance if attendance_supplied else event.expected_attendance
        layout = layout if layout_supplied else event.preferred_room_layout
        facilities = facilities if fs else event.required_facilities
        accessibility = accessibility if acs else event.accessibility_needs
        location = location if ls else event.location_preference
        venues = session.scalars(
            select(Venue).options(selectinload(Venue.layouts)).order_by(Venue.name, Venue.id)
        ).all()
        results = []
        for venue in venues:
            layouts = qualifying_layouts(venue.layouts, attendance, layout)
            if not layouts or not venue_satisfies_requirements(
                venue, facilities, accessibility, location
            ):
                continue
            available, _, timing = exact_availability(session, venue, interval)
            if available:
                results.append(
                    {
                        "id": venue.id,
                        "name": venue.name,
                        "location": venue.location,
                        "maximum_layout_capacity": max(item.capacity for item in venue.layouts),
                        "matching_layouts": [
                            {"layout": item.layout, "capacity": item.capacity} for item in layouts
                        ],
                        "timing": timing,
                        "suitability": exact_suitability(session, venue, event),
                    }
                )
        return jsonify(
            search={"date": request.args["date"], "event": interval.serialize()}, venues=results
        )
