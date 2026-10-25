"""SPL-124 QA: SPL-112's accepted change-request items reach registered attendees.

Case IDs are QA-SPL-124-NNN (see the QA-SPL-124 report). SPL-112's harness: a Confirmed event,
Harbour Lights Gala, on Sat 5 Dec 2026, an organiser's change request decided by the assigned
coordinator. One Registered and one Withdrawn registration are stored directly.
"""

import pytest
import test_event_change_requests as base
from qa_spl124_support import attendee_notices, registrations
from test_qa_spl112 import choices, item, request, save

app = base.app
client = base.client


@pytest.fixture
def event(app):
    event = base.make_event(app, "confirmed")
    registrations(app, event, base.ATTENDEE, base.COLLEAGUE)
    return event


# QA-SPL-124-008 | AC1 AC5 | BB
def test_qa_spl_124_008_an_accepted_date_item_notifies_registered_attendees(app, client, event):
    req = request(client, event, item("proposed_date", "2026-12-12"))
    assert save(client, event, req, choices(req)).status_code == 200
    assert attendee_notices(app, base.ATTENDEE) == [
        "Harbour Lights Gala has changed: date now Sat 12 Dec 2026 (was Sat 5 Dec 2026)."
    ]
    assert attendee_notices(app, base.COLLEAGUE) == []


# QA-SPL-124-009 | AC1 | BB negative
def test_qa_spl_124_009_a_declined_date_item_notifies_nobody(app, client, event):
    req = request(client, event, item("proposed_date", "2026-12-12"))
    decisions = choices(req, decision="declined", reason="Venue unavailable that day")
    assert save(client, event, req, decisions).status_code == 200
    assert attendee_notices(app, base.ATTENDEE) == []


# QA-SPL-124-010 | AC1 | BB
def test_qa_spl_124_010_accepted_start_and_end_items_are_one_notice(app, client, event):
    req = request(client, event, item("start_time", "09:00"), item("end_time", "10:00"))
    assert save(client, event, req, choices(req)).status_code == 200
    messages = attendee_notices(app, base.ATTENDEE)
    assert len(messages) == 1 and "time now 09:00–10:00 SGT" in messages[0]
