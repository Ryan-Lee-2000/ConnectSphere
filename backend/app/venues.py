"""Venue catalogue routes for Sprint 1 stories SPL-47 through SPL-50."""

from typing import Any

from flask import Flask, abort, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.authorization import require_roles
from app.models import Role, Venue, VenueLayout

OPERATING_SLOTS = ("AM", "PM", "NIGHT")


def register_venue_routes(app: Flask) -> None:
    @app.post("/api/venues")
    @require_roles(Role.VENUE_STAFF)
    def create_venue():
        data = _request_json()
        venue = Venue(**_venue_attributes(data, partial=False))
        venue.layouts = [
            VenueLayout(**attributes) for attributes in _layout_list(data.get("layouts", []))
        ]
        with Session(app.extensions["engine"]) as session:
            session.add(venue)
            session.commit()
            session.refresh(venue)
            return jsonify(venue=_serialize_venue(venue)), 201

    @app.get("/api/venues")
    @require_roles(Role.VENUE_STAFF, Role.EVENT_COORDINATOR)
    def list_venues():
        with Session(app.extensions["engine"]) as session:
            venues = session.scalars(select(Venue).order_by(Venue.name, Venue.id)).all()
            return jsonify(
                venues=[_serialize_venue_summary(venue) for venue in venues],
                capabilities={"can_manage": Role.VENUE_STAFF.value in g.account_roles},
            )

    @app.get("/api/venues/<int:venue_id>")
    @require_roles(Role.VENUE_STAFF, Role.EVENT_COORDINATOR)
    def get_venue(venue_id: int):
        with Session(app.extensions["engine"]) as session:
            venue = _find_venue(session, venue_id)
            return jsonify(
                venue=_serialize_venue(venue),
                capabilities={"can_manage": Role.VENUE_STAFF.value in g.account_roles},
            )

    @app.patch("/api/venues/<int:venue_id>")
    @require_roles(Role.VENUE_STAFF)
    def update_venue(venue_id: int):
        data = _request_json()
        attributes = _venue_attributes(data, partial=True)
        layouts = _layout_list(data["layouts"]) if "layouts" in data else None
        with Session(app.extensions["engine"]) as session:
            venue = _find_venue(session, venue_id)
            for name, value in attributes.items():
                setattr(venue, name, value)
            if layouts is not None:
                for layout in list(venue.layouts):
                    session.delete(layout)
                session.flush()
                session.add_all(VenueLayout(venue_id=venue.id, **layout) for layout in layouts)
            session.commit()
            session.refresh(venue)
            session.expire(venue, ["layouts"])
            return jsonify(venue=_serialize_venue(venue))

    @app.post("/api/venues/<int:venue_id>/layouts")
    @require_roles(Role.VENUE_STAFF)
    def create_venue_layout(venue_id: int):
        attributes = _layout_attributes(_request_json())
        with Session(app.extensions["engine"]) as session:
            _find_venue(session, venue_id)
            _ensure_layout_is_unique(session, venue_id, attributes["layout"])
            layout = VenueLayout(venue_id=venue_id, **attributes)
            session.add(layout)
            session.commit()
            session.refresh(layout)
            return jsonify(layout=_serialize_layout(layout)), 201

    @app.patch("/api/venues/<int:venue_id>/layouts/<int:layout_id>")
    @require_roles(Role.VENUE_STAFF)
    def update_venue_layout(venue_id: int, layout_id: int):
        attributes = _layout_attributes(_request_json())
        with Session(app.extensions["engine"]) as session:
            _find_venue(session, venue_id)
            layout = _find_layout(session, venue_id, layout_id)
            if layout.layout != attributes["layout"]:
                _ensure_layout_is_unique(session, venue_id, attributes["layout"])
            layout.layout = attributes["layout"]
            layout.capacity = attributes["capacity"]
            session.commit()
            session.refresh(layout)
            return jsonify(layout=_serialize_layout(layout))

    @app.delete("/api/venues/<int:venue_id>/layouts/<int:layout_id>")
    @require_roles(Role.VENUE_STAFF)
    def delete_venue_layout(venue_id: int, layout_id: int):
        with Session(app.extensions["engine"]) as session:
            _find_venue(session, venue_id)
            layout = _find_layout(session, venue_id, layout_id)
            session.delete(layout)
            session.commit()
        return "", 204


def _request_json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    return data


def _venue_attributes(data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    allowed = {
        "name",
        "location",
        "description",
        "facilities",
        "accessibility_features",
        "operating_slots",
        "setup_buffer_slots",
        "turnaround_buffer_slots",
        "layouts",
    }
    unexpected = set(data) - allowed
    if unexpected:
        abort(400, f"Unexpected venue field: {sorted(unexpected)[0]}.")
    if partial and not data:
        abort(400, "At least one venue field is required.")

    attributes: dict[str, Any] = {}
    if not partial or "name" in data:
        attributes["name"] = _required_text(data.get("name"), "Venue name")
    if not partial or "location" in data:
        attributes["location"] = _optional_text(data.get("location"), "Location")
    if not partial or "description" in data:
        attributes["description"] = _optional_text(data.get("description"), "Description")
    if not partial or "facilities" in data:
        attributes["facilities"] = _string_list(data.get("facilities", []), "Facilities")
    if not partial or "accessibility_features" in data:
        attributes["accessibility_features"] = _string_list(
            data.get("accessibility_features", []), "Accessibility features"
        )
    if not partial or "operating_slots" in data:
        operating_slots = _string_list(data.get("operating_slots", []), "Operating slots")
        invalid_slots = set(operating_slots) - set(OPERATING_SLOTS)
        if invalid_slots:
            abort(400, f"Unsupported operating slot: {sorted(invalid_slots)[0]}.")
        if len(operating_slots) != len(set(operating_slots)):
            abort(400, "Operating slots must not contain duplicates.")
        if not operating_slots:
            abort(400, "Select at least one operating slot.")
        attributes["operating_slots"] = operating_slots
    if not partial or "setup_buffer_slots" in data:
        attributes["setup_buffer_slots"] = _whole_slots(
            data.get("setup_buffer_slots", 0), "Setup buffer"
        )
    if not partial or "turnaround_buffer_slots" in data:
        attributes["turnaround_buffer_slots"] = _whole_slots(
            data.get("turnaround_buffer_slots", 0), "Turnaround buffer"
        )
    return attributes


def _layout_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        abort(400, "Room layouts must be a list.")
    if any(not isinstance(item, dict) for item in value):
        abort(400, "Each room layout must be an object.")
    layouts = [_layout_attributes(item) for item in value]
    names = [layout["layout"] for layout in layouts]
    if len(names) != len(set(names)):
        abort(400, "Room layouts must not contain duplicates.")
    return layouts


def _layout_attributes(data: dict[str, Any]) -> dict[str, Any]:
    unexpected = set(data) - {"layout", "capacity"}
    if unexpected:
        abort(400, f"Unexpected layout field: {sorted(unexpected)[0]}.")
    layout = _required_text(data.get("layout"), "Room layout").lower()
    if layout == "other":
        abort(400, "A custom room layout name is required when Other is selected.")
    capacity = data.get("capacity")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
        abort(400, "Capacity must be a positive whole number.")
    return {"layout": layout, "capacity": capacity}


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        abort(400, f"{label} is required.")
    return value.strip()


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        abort(400, f"{label} must be text.")
    return value.strip() or None


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        abort(400, f"{label} must be a list of non-empty text values.")
    return [item.strip() for item in value]


def _whole_slots(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        abort(400, f"{label} must be a non-negative whole number of slots.")
    return value


def _find_venue(session: Session, venue_id: int) -> Venue:
    venue = session.scalar(
        select(Venue).where(Venue.id == venue_id).options(selectinload(Venue.layouts))
    )
    if venue is None:
        abort(404, "Venue not found.")
    return venue


def _find_layout(session: Session, venue_id: int, layout_id: int) -> VenueLayout:
    layout = session.scalar(
        select(VenueLayout).where(VenueLayout.id == layout_id, VenueLayout.venue_id == venue_id)
    )
    if layout is None:
        abort(404, "Room layout not found.")
    return layout


def _ensure_layout_is_unique(session: Session, venue_id: int, layout_name: str) -> None:
    existing = session.scalar(
        select(VenueLayout.id).where(
            VenueLayout.venue_id == venue_id, VenueLayout.layout == layout_name
        )
    )
    if existing is not None:
        abort(409, "This room layout is already recorded for the venue.")


def _serialize_venue_summary(venue: Venue) -> dict[str, Any]:
    return {"id": venue.id, "name": venue.name, "location": venue.location}


def _serialize_venue(venue: Venue) -> dict[str, Any]:
    return {
        "id": venue.id,
        "name": venue.name,
        "location": venue.location,
        "description": venue.description,
        "facilities": venue.facilities,
        "accessibility_features": venue.accessibility_features,
        "operating_slots": venue.operating_slots,
        "setup_buffer_slots": venue.setup_buffer_slots,
        "turnaround_buffer_slots": venue.turnaround_buffer_slots,
        "layouts": [_serialize_layout(layout) for layout in venue.layouts],
    }


def _serialize_layout(layout: VenueLayout) -> dict[str, Any]:
    return {"id": layout.id, "layout": layout.layout, "capacity": layout.capacity}
