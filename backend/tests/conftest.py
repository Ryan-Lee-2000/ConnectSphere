"""Shared pytest fixtures, re-exported so other test modules can use them by name
without each one redefining `event_app`/`client` as a local parameter (which ruff's
F811 flags as shadowing the import)."""

from datetime import datetime

import pytest
from app import venue_disruption, venue_hold_expiry
from app.event_requests import SINGAPORE
from test_event_requests import client, event_app  # noqa: F401

# SPL-133: a hold cannot be requested at or after its booking starts. Many suites book fixed
# dates that are now in the past, so the hold clock is pinned before every fixture date; nothing
# expires in those suites, as before SPL-133. The SPL-133 suites drive the hold clock themselves,
# and their PostgreSQL cases need the real one.
PINNED_HOLD_CLOCK = datetime(2026, 1, 1, 9, 0, tzinfo=SINGAPORE)


@pytest.fixture(autouse=True)
def pinned_hold_clock(request, monkeypatch):
    if not request.module.__name__.startswith("test_qa_spl133"):
        monkeypatch.setattr(venue_hold_expiry, "_now", lambda: PINNED_HOLD_CLOCK)


# SPL-132 AC1: a block flags only bookings that have not ended. The same fixed-date suites would
# otherwise see their bookings as past, so the disruption clock is pinned before them too. The
# SPL-132 suites drive it themselves.
@pytest.fixture(autouse=True)
def pinned_disruption_clock(request, monkeypatch):
    if not request.module.__name__.startswith("test_qa_spl132"):
        monkeypatch.setattr(venue_disruption, "_now", lambda: PINNED_HOLD_CLOCK)
