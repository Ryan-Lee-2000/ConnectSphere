"""Shared AM/PM/Night slot definitions used by the venue catalogue and event requests."""

from datetime import time

OPERATING_SLOTS = ("AM", "PM", "NIGHT")

# Mirrors the display labels already shown in the venue catalogue UI
# (AM 7am-12pm, PM 1pm-6pm, Night 7pm-12am). NIGHT's upper bound is midnight,
# i.e. the end of the same day, since Release 1 events do not span multiple days.
SLOT_BOUNDARIES: dict[str, tuple[time, time | None]] = {
    "AM": (time(7, 0), time(12, 0)),
    "PM": (time(13, 0), time(18, 0)),
    "NIGHT": (time(19, 0), None),
}


def slots_for_range(start_time: time, end_time: time) -> list[str]:
    """Return the AM/PM/Night slots a start/end time range falls into, for display only."""

    matches = []
    for slot in OPERATING_SLOTS:
        slot_start, slot_end = SLOT_BOUNDARIES[slot]
        if start_time < (slot_end or time(23, 59, 59, 999999)) and end_time > slot_start:
            matches.append(slot)
    return matches
