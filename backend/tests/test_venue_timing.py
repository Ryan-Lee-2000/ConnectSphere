"""SPL-129 public interval contract; dataset executions map to documented cases."""

from datetime import datetime

import pytest
from app.venue_timing import (
    Interval,
    historical_intervals,
    legacy_slot_interval,
    occupied_interval,
    opening_covers,
    parse_event_interval,
    validate_intervals,
)

# TC-SPL-129-04


def test_tc_spl_129_04_expands_advertised_time_without_changing_it():
    event = parse_event_interval("2026-10-12", "10:00", "12:00")
    occupied = occupied_interval(event, 30, 45)
    assert event.start.isoformat() == "2026-10-12T10:00:00+08:00"
    assert event.end.isoformat() == "2026-10-12T12:00:00+08:00"
    assert occupied.start.isoformat() == "2026-10-12T09:30:00+08:00"
    assert occupied.end.isoformat() == "2026-10-12T12:45:00+08:00"


# TC-SPL-129-02


@pytest.mark.parametrize("start", ["10:00", "10:15", "10:30", "10:45"])
def test_tc_spl_129_02_quarter_hours_and_end_of_day(start):
    interval = parse_event_interval("2026-10-12", start, "24:00")
    assert interval.start.strftime("%H:%M") == start
    assert interval.end.isoformat() == "2026-10-13T00:00:00+08:00"


# TC-SPL-129-03


@pytest.mark.parametrize(
    "start,end",
    [
        ("10:07", "12:00"),
        ("10:00:01", "12:00"),
        ("10:00:00", "12:00"),
        ("12:00", "12:00"),
        ("12:00", "10:00"),
        ("23:00", "00:00"),
        ("24:00", "24:00"),
    ],
)
def test_tc_spl_129_03_invalid_search(start, end):
    with pytest.raises(ValueError):
        parse_event_interval("2026-10-12", start, end)


# TC-SPL-129-03


@pytest.mark.parametrize("value", [-1, 0.5, True, None, "30", 2147483648])
def test_tc_spl_129_03_invalid_buffers(value):
    with pytest.raises(ValueError):
        occupied_interval(parse_event_interval("2026-10-12", "10:00", "12:00"), value, 0)


# TC-SPL-129-05


@pytest.mark.parametrize("minute,overlap", [(29, False), (30, False), (31, True)])
def test_tc_spl_129_05_touching_is_not_overlap(minute, overlap):
    target = occupied_interval(parse_event_interval("2026-10-12", "10:00", "12:00"), 30, 45)
    adjacent = Interval(
        datetime.fromisoformat("2026-10-12T09:00+08:00"),
        datetime.fromisoformat(f"2026-10-12T09:{minute}+08:00"),
    )
    assert target.overlaps(adjacent) is overlap


# TC-SPL-129-06


@pytest.mark.parametrize(
    "hours,expected",
    [
        ([[0, 1440]], True),
        ([[0, 60], [1380, 1440]], True),
        ([[0, 60], [1380, 1439]], False),
        ([[0, 30], [30, 60], [1380, 1440]], True),
        ([], False),
    ],
)
def test_tc_spl_129_06_opening_covers_cross_midnight(hours, expected):
    target = occupied_interval(parse_event_interval("2026-10-12", "00:15", "00:45"), 30, 0)
    assert opening_covers(target, validate_intervals(hours)) is expected


# TC-SPL-129-06


@pytest.mark.parametrize("start,end", [("12:00", "13:00"), ("18:00", "19:00")])
@pytest.mark.parametrize("day", ["2026-10-12", "2026-10-17", "2026-12-25"])
def test_tc_spl_129_06_no_meal_or_weekday_blackout(day, start, end):
    assert opening_covers(parse_event_interval(day, start, end), [[540, 1200]])


# TC-SPL-129-03


@pytest.mark.parametrize(
    "hours",
    [
        None,
        [[0, 0]],
        [[60, 0]],
        [[-1, 60]],
        [[0, 1441]],
        [[True, 60]],
        [[0, 60], [59, 90]],
        [[0]],
        "09:00",
    ],
)
def test_tc_spl_129_03_invalid_hours(hours):
    with pytest.raises(ValueError):
        validate_intervals(hours)


# TC-SPL-129-07


def test_tc_spl_129_07_booking_owned_exact_evidence_retains_old_claims():
    old = legacy_slot_interval(
        parse_event_interval("2026-10-12", "10:00", "12:00").start.date(), "AM"
    )
    exact = Interval(
        datetime.fromisoformat("2026-10-12T09:30+08:00"),
        datetime.fromisoformat("2026-10-12T12:45+08:00"),
    )
    assert historical_intervals([old], exact) == (old, exact)
    assert historical_intervals([old], None) == (old,)
    with pytest.raises(ValueError):
        Interval(datetime(2026, 10, 12, 10), datetime(2026, 10, 12, 12))
