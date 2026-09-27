"""FIRST unit coverage for SPL-71's search-input contract."""

from datetime import date

import pytest
from app.models import VenueLayout
from app.venue_availability import (
    SearchParameterError,
    parse_requirement_filters,
    parse_search_parameters,
    qualifying_layouts,
)


# TC-SPL-71-07: valid equivalence partitions for each fixed operating slot.
@pytest.mark.parametrize(
    ("raw_slots", "expected_slots"),
    [
        (["AM"], ["AM"]),
        (["PM"], ["PM"]),
        (["NIGHT"], ["NIGHT"]),
        (["NIGHT", "AM", "PM"], ["AM", "PM", "NIGHT"]),
    ],
)
def test_tc_spl_71_07_normalises_each_valid_fixed_slot_in_operational_order(
    raw_slots, expected_slots
):
    assert parse_search_parameters("2026-10-12", raw_slots) == (
        date(2026, 10, 12),
        expected_slots,
        None,
        None,
    )


# TC-SPL-71-08: invalid equivalence partitions are rejected before a search can run.
@pytest.mark.parametrize(
    ("raw_date", "raw_slots", "message"),
    [
        (None, ["AM"], "Search date is required."),
        ("12-10-2026", ["AM"], "Search date must use YYYY-MM-DD."),
        ("2026-10-12", [], "Select at least one operating slot."),
        ("2026-10-12", ["DAY"], "Search uses only AM, PM or NIGHT slots."),
        ("2026-10-12", ["AM", "AM"], "Operating slots must not contain duplicates."),
    ],
)
def test_tc_spl_71_08_refuses_each_invalid_search_partition(raw_date, raw_slots, message):
    with pytest.raises(SearchParameterError, match=f"^{message}$"):
        parse_search_parameters(raw_date, raw_slots)


def test_tc_spl_72_07_normalises_optional_catalogue_capacity_and_layout_filters():
    assert parse_search_parameters(
        "2026-10-12",
        ["AM"],
        "80",
        " classroom ",
        attendance_supplied=True,
        layout_supplied=True,
    ) == (date(2026, 10, 12), ["AM"], 80, "classroom")


@pytest.mark.parametrize("raw_attendance", ["", "0", "12.5", "-1", "many"])
def test_tc_spl_72_08_refuses_invalid_catalogue_attendance_filter(raw_attendance):
    with pytest.raises(
        SearchParameterError,
        match="^Expected attendance must be a positive whole number.$",
    ):
        parse_search_parameters("2026-10-12", ["AM"], raw_attendance, attendance_supplied=True)


@pytest.mark.parametrize(
    ("expected_attendance", "preferred_layout", "expected"),
    [
        (80, None, [("theatre", 80), ("classroom", 120)]),
        (81, None, [("classroom", 120)]),
        (80, "Theatre", [("theatre", 80)]),
        (121, "classroom", []),
        (80, "banquet", []),
    ],
)
def test_tc_spl_72_03_applies_capacity_boundary_and_preferred_layout_partitions(
    expected_attendance, preferred_layout, expected
):
    layouts = [
        VenueLayout(layout="theatre", capacity=80),
        VenueLayout(layout="classroom", capacity=120),
    ]

    qualified = qualifying_layouts(layouts, expected_attendance, preferred_layout)

    assert [(layout.layout, layout.capacity) for layout in qualified] == expected


def test_tc_spl_72_04_requires_event_level_expected_attendance():
    layouts = [VenueLayout(layout="theatre", capacity=80)]

    assert qualifying_layouts(layouts, None, None) == []


def test_tc_spl_73_03_normalises_requirement_filter_equivalence_partitions():
    assert parse_requirement_filters(
        [" Projector ", "projector", "PA system", ""],
        ["Step-free access", "step-free access"],
        " Marina Centre ",
    ) == (["Projector", "PA system"], ["Step-free access"], "Marina Centre")


@pytest.mark.parametrize(
    ("facilities", "accessibility", "location", "message"),
    [
        (["x" * 101], [], None, "Required facility must be 100 characters or fewer."),
        ([], ["x" * 101], None, "Accessibility need must be 100 characters or fewer."),
        ([], [], "x" * 201, "Location preference must be 200 characters or fewer."),
    ],
)
def test_tc_spl_73_04_refuses_requirement_filter_values_outside_the_contract(
    facilities, accessibility, location, message
):
    with pytest.raises(SearchParameterError, match=f"^{message}$"):
        parse_requirement_filters(facilities, accessibility, location)
