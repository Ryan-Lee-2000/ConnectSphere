"""Shared remaining-quantity rule for reservation consumers.

SPL-97 reservations are append-only commitments. SPL-98 releases are also append-only, so every
availability, review and return-date path must derive the still-held quantity in one place.
"""

from app.models import EquipmentReservation


def released_quantity(reservation: EquipmentReservation) -> int:
    """Return the recorded release total for one reservation."""

    return sum(release.quantity for release in reservation.releases)


def remaining_quantity(reservation: EquipmentReservation) -> int:
    """Return the units that still consume shared stock for one reservation."""

    return max(0, reservation.quantity - released_quantity(reservation))
