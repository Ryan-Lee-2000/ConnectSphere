"""Technical Support equipment catalogue routes for SPL-94."""

from typing import Any

from flask import Flask, abort, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization import require_roles
from app.models import EquipmentType, Role


def register_equipment_catalogue_routes(app: Flask) -> None:
    @app.get("/api/equipment-types")
    @require_roles(
        Role.TECHNICAL_SUPPORT_STAFF,
        Role.EVENT_ORGANISER,
        Role.EVENT_COORDINATOR,
    )
    def list_equipment_types():
        with Session(app.extensions["engine"]) as session:
            types = session.scalars(
                select(EquipmentType).order_by(EquipmentType.name, EquipmentType.id)
            ).all()
            return jsonify(equipment_types=[_serialize(item) for item in types])

    @app.post("/api/equipment-types")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def create_equipment_type():
        attributes = _attributes(_request_json(), partial=False)
        item = EquipmentType(**attributes)
        with Session(app.extensions["engine"]) as session:
            session.add(item)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                abort(409, "An equipment type with this name already exists.")
            session.refresh(item)
            return jsonify(equipment_type=_serialize(item)), 201

    @app.patch("/api/equipment-types/<int:equipment_type_id>")
    @require_roles(Role.TECHNICAL_SUPPORT_STAFF)
    def update_equipment_type(equipment_type_id: int):
        attributes = _attributes(_request_json(), partial=True)
        with Session(app.extensions["engine"]) as session:
            item = session.get(EquipmentType, equipment_type_id)
            if item is None:
                abort(404, "Equipment type not found.")
            # SPL-96 AC1 says the unavailable total can never exceed total stock. Lowering stock
            # is the other way to break that rule, so it is refused here with a clear message
            # instead of failing later as a database constraint error.
            new_stock = attributes.get("total_stock")
            if new_stock is not None and new_stock < item.unavailable_units:
                abort(
                    400,
                    f"{item.unavailable_units} unit(s) are marked unavailable, so total stock "
                    f"cannot be lowered to {new_stock}. Restore units first.",
                )
            for name, value in attributes.items():
                setattr(item, name, value)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                abort(409, "An equipment type with this name already exists.")
            session.refresh(item)
            return jsonify(equipment_type=_serialize(item))


def _request_json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    return data


def _attributes(data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    allowed = {"name", "description", "location", "total_stock"}
    unexpected = set(data) - allowed
    if unexpected:
        abort(400, f"Unexpected equipment type field: {sorted(unexpected)[0]}.")
    if partial and not data:
        abort(400, "At least one equipment type field is required.")
    attributes: dict[str, Any] = {}
    if not partial or "name" in data:
        name = _required_text(data.get("name"), "Equipment type name")
        attributes["name"] = name
        attributes["normalised_name"] = name.casefold()
    if not partial or "description" in data:
        attributes["description"] = _optional_text(data.get("description"), "Description")
    if not partial or "location" in data:
        attributes["location"] = _optional_text(data.get("location"), "Location")
    if not partial or "total_stock" in data:
        stock = data.get("total_stock")
        if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
            abort(400, "Total stock must be a whole number of zero or more.")
        attributes["total_stock"] = stock
    return attributes


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


def _serialize(item: EquipmentType) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "location": item.location,
        "total_stock": item.total_stock,
    }
