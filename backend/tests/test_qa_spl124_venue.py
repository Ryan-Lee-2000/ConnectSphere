"""SPL-124 QA: venue decisions and equipment edits, on SPL-106's venue scenario.

Case IDs are QA-SPL-124-NNN (see the QA-SPL-124 report). The harness is SPL-106's Planning event,
Coastal Forum, with a real Requested booking at "QA hall", as SPL-109 and SPL-121 use it. One
Registered and one Withdrawn registration are stored directly.
"""

import pytest
import test_qa_spl106_requirements as venue
from qa_spl124_support import attendee_notices, registrations
from test_qa_spl109 import confirmed, equipment
from test_qa_spl109 import save as save_change
from test_qa_spl121_venue import approve, reject

base_app = venue.base_app
app = venue.app
client = venue.client
REGISTERED = venue.base.OTHER_COORDINATOR
WITHDRAWN = venue.base.MANAGER


@pytest.fixture
def scenario(app, client):
    event, _, [booking] = venue.scenario(app, client)
    registrations(app, event, REGISTERED, WITHDRAWN)
    return event, booking


# QA-SPL-124-011 | AC1 AC5 | BB
def test_qa_spl_124_011_an_approved_venue_names_the_venues_now_held(app, client, scenario):
    _, booking = scenario
    assert approve(client, booking).status_code == 200
    assert attendee_notices(app, REGISTERED) == [
        "The venue for Coastal Forum has changed. Venues now: QA hall."
    ]
    assert attendee_notices(app, WITHDRAWN) == []


# QA-SPL-124-012 | AC1 AC4 | BB negative
def test_qa_spl_124_012_a_rejected_or_repeated_decision_adds_nothing(app, client, scenario):
    _, booking = scenario
    assert reject(client, booking, reason="Hall closed for repairs").status_code == 200
    assert approve(client, booking).status_code == 409
    assert attendee_notices(app, REGISTERED) == []


# QA-SPL-124-026 | AC2 | WB (an event holding reserved units, which also notifies SPL-122's staff)
def test_qa_spl_124_026_a_cancellation_that_releases_equipment_still_tells_attendees(
    app, client, scenario
):
    event, _ = scenario
    equipment(app, event)
    response = client.post(
        f"/api/event-requests/{event}/cancel",
        json={"reason": "Called off by the client"},
        headers=venue.base.headers(),
    )
    assert response.status_code == 200, response.json
    assert response.json["released"]["equipment_units"] == 4
    assert attendee_notices(app, REGISTERED) == ["Coastal Forum has been cancelled."]
    assert attendee_notices(app, WITHDRAWN) == []


# QA-SPL-124-013 | AC1 | BB negative
def test_qa_spl_124_013_an_equipment_change_notifies_no_attendee(app, client, scenario):
    event, _ = scenario
    line = equipment(app, event)
    confirmed(app, event)
    response = save_change(client, event, {"quantity": 5}, equipment_requirement_id=line)
    assert response.status_code == 200, response.json
    assert attendee_notices(app, REGISTERED) == []
