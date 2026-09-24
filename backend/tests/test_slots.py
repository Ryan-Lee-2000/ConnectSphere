from datetime import date, time

import pytest
from app.slots import OccupancyKind, VenueOccupancySlot, derive_venue_occupancy, slots_for_range


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


# TC-SPL-87-01
def test_tc_spl_87_01_derives_adjacent_setup_and_turnaround_slots():
    occupancy = derive_venue_occupancy(
        [(date(2026, 10, 8), "PM")],
        setup_buffer_slots=1,
        turnaround_buffer_slots=1,
    )

    assert occupancy == (
        VenueOccupancySlot(date(2026, 10, 8), "AM", OccupancyKind.SETUP),
        VenueOccupancySlot(date(2026, 10, 8), "PM", OccupancyKind.EVENT),
        VenueOccupancySlot(date(2026, 10, 8), "NIGHT", OccupancyKind.TURNAROUND),
    )


# TC-SPL-87-01
def test_tc_spl_87_01_venue_without_preparation_uses_only_event_slots():
    occupancy = derive_venue_occupancy(
        [(date(2026, 10, 8), "PM")],
        setup_buffer_slots=0,
        turnaround_buffer_slots=0,
    )

    assert occupancy == (VenueOccupancySlot(date(2026, 10, 8), "PM", OccupancyKind.EVENT),)


# TC-SPL-87-02
@pytest.mark.parametrize(
    ("event_slot", "setup", "turnaround", "expected_preparation"),
    [
        (
            (date(2026, 10, 8), "AM"),
            1,
            0,
            VenueOccupancySlot(date(2026, 10, 7), "NIGHT", OccupancyKind.SETUP),
        ),
        (
            (date(2026, 10, 8), "NIGHT"),
            0,
            1,
            VenueOccupancySlot(date(2026, 10, 9), "AM", OccupancyKind.TURNAROUND),
        ),
    ],
)
def test_tc_spl_87_02_derives_preparation_across_singapore_calendar_days(
    event_slot, setup, turnaround, expected_preparation
):
    occupancy = derive_venue_occupancy(
        [event_slot],
        setup_buffer_slots=setup,
        turnaround_buffer_slots=turnaround,
    )

    assert expected_preparation in occupancy


# TC-SPL-87-03
def test_tc_spl_87_03_uses_only_the_first_and_last_event_slots_for_preparation():
    occupancy = derive_venue_occupancy(
        [
            (date(2026, 10, 9), "AM"),
            (date(2026, 10, 8), "NIGHT"),
            (date(2026, 10, 8), "PM"),
        ],
        setup_buffer_slots=1,
        turnaround_buffer_slots=1,
    )

    assert occupancy == (
        VenueOccupancySlot(date(2026, 10, 8), "AM", OccupancyKind.SETUP),
        VenueOccupancySlot(date(2026, 10, 8), "PM", OccupancyKind.EVENT),
        VenueOccupancySlot(date(2026, 10, 8), "NIGHT", OccupancyKind.EVENT),
        VenueOccupancySlot(date(2026, 10, 9), "AM", OccupancyKind.EVENT),
        VenueOccupancySlot(date(2026, 10, 9), "PM", OccupancyKind.TURNAROUND),
    )


# TC-SPL-87-03
@pytest.mark.parametrize(("setup", "turnaround"), [(2, 0), (0, 2)])
def test_tc_spl_87_03_rejects_more_than_one_preparation_slot(setup, turnaround):
    with pytest.raises(ValueError, match="zero or one"):
        derive_venue_occupancy(
            [(date(2026, 10, 8), "PM")],
            setup_buffer_slots=setup,
            turnaround_buffer_slots=turnaround,
        )
