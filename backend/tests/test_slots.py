from datetime import time

from app.slots import slots_for_range


def test_range_fully_inside_am():
    assert slots_for_range(time(8, 0), time(10, 0)) == ["AM"]


def test_range_spanning_am_and_pm():
    assert slots_for_range(time(11, 0), time(14, 0)) == ["AM", "PM"]


def test_range_spanning_pm_and_night():
    assert slots_for_range(time(17, 30), time(20, 0)) == ["PM", "NIGHT"]


def test_range_entirely_inside_a_gap_matches_no_slot():
    assert slots_for_range(time(12, 15), time(12, 45)) == []


def test_range_late_in_the_night_slot_matches_only_night():
    assert slots_for_range(time(23, 0), time(23, 59)) == ["NIGHT"]
