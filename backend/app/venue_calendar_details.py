"""SPL-107 detail projection. Shared calendar occupancy grants no event authority."""

from flask import g

from app.coordinator_assignment import is_assigned_coordinator
from app.models import EventRequest, Role


def booking_calendar_detail(session, booking):
    links = []
    if Role.VENUE_STAFF.value in g.account_roles:
        links.append(
            {
                "label": "Open booking",
                "href": f"/workspace/venue-bookings/{booking.id}",
                "role": Role.VENUE_STAFF.value,
            }
        )
    if Role.EVENT_COORDINATOR.value in g.account_roles and is_assigned_coordinator(
        session, booking.event_request_id, g.user_id
    ):
        links.append(
            {
                "label": "Open assigned event",
                "href": f"/workspace/assigned-events/{booking.event_request_id}",
                "role": Role.EVENT_COORDINATOR.value,
            }
        )
    if not links:
        return {}
    event = session.get(EventRequest, booking.event_request_id)
    return {"event_name": event.name, "links": links}


def block_calendar_detail(block):
    if Role.VENUE_STAFF.value not in g.account_roles:
        return {}
    return {"detail": block.reason}
