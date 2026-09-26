"""Shared AM/PM/Night slot and venue-occupancy rules."""

from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import StrEnum
from typing import Iterable

OPERATING_SLOTS = ("AM", "PM", "NIGHT")

# Mirrors the display labels already shown in the venue catalogue UI
# (AM 7am-12pm, PM 1pm-6pm, Night 7pm-12am). NIGHT's upper bound is midnight,
# i.e. the end of the same day, since Release 1 events do not span multiple days.
SLOT_BOUNDARIES: dict[str, tuple[time, time | None]] = {
    "AM": (time(7, 0), time(12, 0)),
    "PM": (time(13, 0), time(18, 0)),
    "NIGHT": (time(19, 0), None),
}


class OccupancyKind(StrEnum):
    """Why a venue slot is occupied."""

    EVENT = "event"
    SETUP = "setup"
    TURNAROUND = "turnaround"


@dataclass(frozen=True)
class VenueOccupancySlot:
    """One dated Singapore operating slot consumed by a venue booking."""

    date: date
    slot: str
    kind: OccupancyKind


def _adjacent_slot(day: date, slot: str, offset: int) -> tuple[date, str]:
    index = OPERATING_SLOTS.index(slot) + offset
    if index < 0:
        return day - timedelta(days=1), OPERATING_SLOTS[-1]
    if index >= len(OPERATING_SLOTS):
        return day + timedelta(days=1), OPERATING_SLOTS[0]
    return day, OPERATING_SLOTS[index]


def slots_for_range(start_time: time, end_time: time) -> list[str]:
    """Return the AM/PM/Night slots a start/end time range falls into, for display only."""

    matches = []
    for slot in OPERATING_SLOTS:
        slot_start, slot_end = SLOT_BOUNDARIES[slot]
        if start_time < (slot_end or time(23, 59, 59, 999999)) and end_time > slot_start:
            matches.append(slot)
    return matches


def derive_venue_occupancy(
    event_slots: Iterable[tuple[date, str]],
    *,
    setup_buffer_slots: int,
    turnaround_buffer_slots: int,
) -> tuple[VenueOccupancySlot, ...]:
    """Derive event and directly adjacent preparation occupancy."""

    preparation_counts = (setup_buffer_slots, turnaround_buffer_slots)
    if any(type(count) is not int or count not in (0, 1) for count in preparation_counts):
        raise ValueError("Preparation requirements must be zero or one slot.")

    ordered = sorted(event_slots, key=lambda item: (item[0], OPERATING_SLOTS.index(item[1])))
    if not ordered:
        raise ValueError("At least one event slot is required.")

    occupancy = [VenueOccupancySlot(day, slot, OccupancyKind.EVENT) for day, slot in ordered]
    if setup_buffer_slots:
        day, slot = ordered[0]
        day, slot = _adjacent_slot(day, slot, -1)
        occupancy.insert(
            0,
            VenueOccupancySlot(day, slot, OccupancyKind.SETUP),
        )
    if turnaround_buffer_slots:
        day, slot = ordered[-1]
        day, slot = _adjacent_slot(day, slot, 1)
        occupancy.append(
            VenueOccupancySlot(day, slot, OccupancyKind.TURNAROUND),
        )
    return tuple(occupancy)
