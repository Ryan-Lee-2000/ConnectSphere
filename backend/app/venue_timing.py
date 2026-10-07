"""Exact, half-open Singapore intervals shared by venue consumers (SPL-129)."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

SGT = timezone(timedelta(hours=8))
MAX_MINUTES = 2_147_483_647  # PostgreSQL INTEGER storage, not a business duration limit.


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.utcoffset() is None or self.end.utcoffset() is None or self.end <= self.start:
            raise ValueError("Intervals require aware timestamps with end after start.")

    def overlaps(self, other):
        return self.start < other.end and other.start < self.end

    def serialize(self):
        return {
            "start": self.start.astimezone(SGT).isoformat(),
            "end": self.end.astimezone(SGT).isoformat(),
        }


def parse_event_interval(raw_date, start, end):
    if not isinstance(raw_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
        raise ValueError("Search date must use YYYY-MM-DD.")
    day = date.fromisoformat(raw_date)

    def minutes(value, endpoint=False):
        if endpoint and value == "24:00":
            return 1440
        if not isinstance(value, str) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):(?:00|15|30|45)", value
        ):
            raise ValueError("Choose start/end times on 15-minute boundaries (HH:MM).")
        hour, minute = map(int, value.split(":"))
        return hour * 60 + minute

    begin = minutes(start)
    finish = minutes(end, True)
    base = datetime.combine(day, time(), SGT)
    try:
        return Interval(base + timedelta(minutes=begin), base + timedelta(minutes=finish))
    except OverflowError:
        raise ValueError("Timing exceeds supported calendar dates.") from None


def validate_minutes(value):
    if type(value) is not int or not 0 <= value <= MAX_MINUTES:
        raise ValueError("Preparation must be non-negative whole minutes within database range.")
    return value


def occupied_interval(event, setup, turnaround):
    validate_minutes(setup)
    validate_minutes(turnaround)
    try:
        return Interval(
            event.start - timedelta(minutes=setup), event.end + timedelta(minutes=turnaround)
        )
    except OverflowError:
        raise ValueError("Occupied timing exceeds supported calendar dates.") from None


def validate_intervals(value):
    if not isinstance(value, list):
        raise ValueError("Operating intervals must be a list of minute pairs.")
    result = []
    for pair in value:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(type(n) is not int for n in pair)
            or not 0 <= pair[0] < pair[1] <= 1440
        ):
            raise ValueError("Operating intervals need whole-minute endpoints within 00:00–24:00.")
        result.append(list(pair))
    result.sort()
    for previous, current in zip(result, result[1:]):
        if previous[1] > current[0]:
            raise ValueError("Operating intervals must not overlap.")
    return result


def opening_covers(interval, hours):
    """Cover using a daily union; bounded work even with very large buffers."""
    merged = []
    for begin, end in hours:
        if merged and merged[-1][1] == begin:
            merged[-1][1] = end
        else:
            merged.append([begin, end])
    if merged == [[0, 1440]]:
        return True
    start, end = interval.start.astimezone(SGT), interval.end.astimezone(SGT)
    if end - start >= timedelta(days=1):
        return False  # Any non-full daily union has a gap in a full day.

    def covers(begin, finish):
        return begin == finish or any(a <= begin and finish <= b for a, b in merged)

    begin = start.hour * 60 + start.minute + start.second / 60 + start.microsecond / 60000000
    finish = end.hour * 60 + end.minute + end.second / 60 + end.microsecond / 60000000
    if start.date() == end.date():
        return covers(begin, finish)
    return covers(begin, 1440) and covers(0, finish)


def legacy_slot_interval(day, slot):
    """Historical evidence only; these gaps do not define new operating hours."""
    boundaries = {"AM": (420, 720), "PM": (780, 1080), "NIGHT": (1140, 1440)}
    if slot not in boundaries:
        raise ValueError("Unrecognised historical slot.")
    begin, end = boundaries[slot]
    base = datetime.combine(day, time(), SGT)
    try:
        return Interval(base + timedelta(minutes=begin), base + timedelta(minutes=end))
    except OverflowError:
        raise ValueError("Historical timing exceeds supported calendar dates.") from None


def historical_intervals(claims, booking_owned_exact=None):
    """Never infer a snapshot from an EventRequest; preserve original claims too.
    Consumers may provide only an established booking-owned occupied interval.
    This does not resolve ambiguous records or replace their evidence.
    """
    evidence = tuple(claims)
    if booking_owned_exact is not None:
        if not isinstance(booking_owned_exact, Interval):
            raise ValueError("Exact historical evidence must be a validated Interval.")
        evidence += (booking_owned_exact,)
    return evidence
