"""Shared hand-rolled request validation helpers for JSON API modules."""

from typing import Any

from flask import abort, request


def request_json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "A JSON object is required.")
    return data


def required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        abort(400, f"{label} is required.")
    return value.strip()


def optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        abort(400, f"{label} must be text.")
    return value.strip() or None


def string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        abort(400, f"{label} must be a list of non-empty text values.")
    return [item.strip() for item in value]


def positive_whole_number(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        abort(400, f"{label} must be a positive whole number.")
    return value
