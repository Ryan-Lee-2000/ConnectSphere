"""FIRST unit coverage for SPL-71's search-input contract."""

from datetime import date

import pytest
from app.venue_availability import SearchParameterError, parse_search_parameters


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
