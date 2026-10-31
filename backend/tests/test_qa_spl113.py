"""Organiser outcomes, durable history, current values and trusted access."""

import pytest
import test_event_change_requests as base
import test_qa_spl112 as decisions
from app.models import Account, EventRequest, Organisation
from sqlalchemy.orm import Session

app = base.app
client = base.client


def closed(client, event, field="name", value="Updated gala"):
    request = decisions.request(client, event, decisions.item(field, value))
    result = decisions.save(client, event, request, decisions.choices(request))
    assert result.status_code == 200, result.json
    return request


def history(client, event):
    result = base.read(client, event)
    assert result.status_code == 200
    return result.json["change_requests"]


# QA-SPL-113-006 | AC2 | BB
def test_qa_spl_113_006_closed_survives_new_read(app, client):
    event = base.make_event(app)
    request = closed(client, event)
    result = history(app.test_client(), event)
    assert result[0]["id"] == request["id"]
    assert result[0]["status"] == "closed"
    assert result[0]["items"][0]["decision"] == "accepted"


# QA-SPL-113-007 | AC2 | BB
def test_qa_spl_113_007_multiple_closed_newest_first(app, client):
    event = base.make_event(app)
    first = closed(client, event)
    second = closed(client, event, value="Latest gala")
    assert [r["id"] for r in history(client, event)] == [second["id"], first["id"]]


# QA-SPL-113-008 | AC2 | BB
def test_qa_spl_113_008_pending_does_not_hide_history(app, client):
    event = base.make_event(app)
    old = closed(client, event)
    pending = decisions.request(client, event)
    assert [(r["id"], r["status"]) for r in history(client, event)] == [
        (pending["id"], "pending"),
        (old["id"], "closed"),
    ]


@pytest.mark.parametrize("status", ["completed", "cancelled", "rejected", "withdrawn"])
# QA-SPL-113-009 | AC2 | WB
def test_qa_spl_113_009_history_after_terminal_state(app, client, status):
    event = base.make_event(app)
    request = closed(client, event)
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event).status = status
        session.commit()
    assert history(client, event)[0]["id"] == request["id"]
    assert base.submit(client, event).status_code == 409


# QA-SPL-113-010 | AC2 | BB
def test_qa_spl_113_010_original_snapshot_survives_later_change(app, client):
    event = base.make_event(app)
    old = closed(client, event)
    closed(client, event, value="Latest gala")
    original = next(r for r in history(client, event) if r["id"] == old["id"])
    assert original["items"][0]["current_value"] == "Harbour Lights Gala"
    assert original["items"][0]["requested_value"] == "Updated gala"


def current(client, event):
    response = client.get(f"/api/organisation/events/{event}", headers=base.headers())
    assert response.status_code == 200, response.json
    return response.json["event"]


# QA-SPL-113-011 | AC3 | BB
def test_qa_spl_113_011_accepted_name_visible_after_reload(app, client):
    event = base.make_event(app)
    closed(client, event)
    assert current(app.test_client(), event)["name"] == "Updated gala"


# QA-SPL-113-012 | AC3 | BB
def test_qa_spl_113_012_accepted_layout_visible(app, client):
    event = base.make_event(app)
    closed(client, event, "preferred_room_layout", "Theatre")
    assert current(client, event)["preferred_room_layout"] == "Theatre"


# QA-SPL-113-013 | AC3 | BB
def test_qa_spl_113_013_accepted_facilities_visible(app, client):
    event = base.make_event(app)
    closed(client, event, "required_facilities", ["Stage", "Projector"])
    assert current(client, event)["required_facilities"] == ["Stage", "Projector"]


# QA-SPL-113-014 | AC3 | BB
def test_qa_spl_113_014_accepted_accessibility_visible(app, client):
    event = base.make_event(app)
    closed(client, event, "accessibility_needs", ["Step-free access"])
    assert current(client, event)["accessibility_needs"] == ["Step-free access"]


# QA-SPL-113-015 | AC3 | BB
def test_qa_spl_113_015_declined_does_not_replace_current_notes(app, client):
    event = base.make_event(app, venue_notes="North entrance")
    request = decisions.request(client, event, decisions.item("venue_notes", "South entrance"))
    result = decisions.save(
        client, event, request, decisions.choices(request, "declined", "Closed")
    )
    assert result.status_code == 200
    assert current(client, event)["venue_notes"] == "North entrance"
    closed(client, event, "venue_notes", "East entrance")
    assert current(client, event)["venue_notes"] == "East entrance"


def move_account(app, account_id, *, unassigned=False):
    with Session(app.extensions["engine"]) as session:
        other = Organisation(name="Other client")
        session.add(other)
        session.flush()
        session.get(Account, account_id).organisation_id = None if unassigned else other.id
        session.commit()


# QA-SPL-113-016 | AC4 | BB
def test_qa_spl_113_016_foreign_organiser_generic_denial(app, client):
    event = base.make_event(app)
    closed(client, event)
    move_account(app, base.COLLEAGUE)
    denied = base.read(client, event, "colleague")
    missing = base.read(client, event + 999, "colleague")
    assert denied.status_code == missing.status_code == 404
    assert denied.json == missing.json
    assert "Updated gala" not in denied.get_data(as_text=True)


@pytest.mark.parametrize("unassigned", [False, True])
# QA-SPL-113-017 | AC4 | WB
def test_qa_spl_113_017_owner_loses_access_when_membership_changes(app, client, unassigned):
    event = base.make_event(app)
    closed(client, event)
    assert base.read(client, event).status_code == 200
    move_account(app, base.ORGANISER, unassigned=unassigned)
    assert base.read(client, event).status_code == 404


# QA-SPL-113-018 | AC4 | BB
def test_qa_spl_113_018_same_org_colleague_has_no_request_access(app, client):
    event = base.make_event(app)
    closed(client, event)
    assert base.read(client, event, "colleague").status_code == 404
    response = client.get(f"/api/organisation/events/{event}", headers=base.headers("colleague"))
    assert response.status_code == 200


# QA-SPL-113-019 | AC4 | BB
def test_qa_spl_113_019_client_claims_cannot_restore_membership(app, client):
    event = base.make_event(app)
    closed(client, event)
    move_account(app, base.ORGANISER)
    response = client.get(
        f"/api/event-requests/{event}/change-requests?organisation_id={app.config['ORGANISATION_ID']}",
        headers={**base.headers(), "X-Organisation-ID": str(app.config["ORGANISATION_ID"])},
    )
    assert response.status_code == 404


# QA-SPL-113-020 | AC4 | WB
def test_qa_spl_113_020_coordinator_assignment_and_auth_still_apply(app, client):
    event = base.make_event(app)
    closed(client, event)
    move_account(app, base.COORDINATOR)
    assert base.read(client, event, "coordinator").status_code == 200
    assert base.read(client, event, "other-coordinator").status_code == 404
    assert base.read(client, event, None).status_code == 401
    assert base.read(client, event, "attendee").status_code == 403
