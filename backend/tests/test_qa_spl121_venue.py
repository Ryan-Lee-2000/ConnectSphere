"""SPL-121 QA cases, venue side: booking decisions (AC1) and venue flags (AC3), with AC5.

Each case carries its QA-SPL-121-NNN identifier (see the QA-SPL-121 Confluence page). The fixture
is SPL-106's: a Planning event assigned to the coordinator, a venue, and a Requested booking made
through the real route. Equipment cases are in test_qa_spl121_equipment.py and PostgreSQL races
in test_qa_spl121_postgres.py.
"""

from datetime import time
from types import SimpleNamespace

import pytest
import test_qa_spl106_requirements as venue
from app import notifications as notifications_module
from app import venue_booking_approvals as approvals_module
from app.models import EventCoordinatorAssignment, EventRequest, Notification, VenueBooking
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

base = venue.base
base_app = venue.base_app
app = venue.app
client = venue.client
STAFF = base.headers("venue-staff")
EVENT = "Coastal Forum"
HALL = "QA hall"


def notices(app, account=base.COORDINATOR):
    with Session(app.extensions["engine"]) as session:
        return [
            (row.dedupe_key, row.message)
            for row in session.scalars(
                select(Notification)
                .where(
                    Notification.recipient_account_id == account,
                    Notification.dedupe_key.like("arrangement_%"),
                    # SPL-133's hold notices are asserted in its own suite.
                    ~Notification.dedupe_key.like("arrangement_hold_%"),
                )
                .order_by(Notification.id)
            )
        ]


def everyone_else(app):
    return {
        account: notices(app, account)
        for account in (base.OTHER_COORDINATOR, base.ORGANISER, base.VENUE_STAFF, base.MANAGER)
    }


def approve(client, booking, token="venue-staff", **body):
    return client.post(
        f"/api/venue-bookings/{booking['id']}/approve", json=body, headers=base.headers(token)
    )


def reject(client, booking, token="venue-staff", **body):
    return client.post(
        f"/api/venue-bookings/{booking['id']}/reject", json=body, headers=base.headers(token)
    )


def block(client, venue_id, start="10:00", end="11:00", token="venue-staff", **extra):
    body = {
        "date": venue.DAY.isoformat(),
        "start_time": start,
        "end_time": end,
        "reason": "Burst pipe in the plant room",
        **extra,
    }
    return client.post(
        f"/api/venues/{venue_id}/operational-blocks", json=body, headers=base.headers(token)
    )


def booking_status(app, booking):
    with Session(app.extensions["engine"]) as session:
        return session.get(VenueBooking, booking["id"]).status


# AC1 - notified when a venue booking is approved or rejected (with the reason)


# QA-SPL-121-001 | AC1 | BB
def test_qa_spl_121_001_an_approval_notifies_the_coordinator_once(app, client):
    _, _, [booking] = venue.scenario(app, client)
    response = approve(client, booking)
    assert response.status_code == 200, response.json
    [(key, message)] = notices(app)
    assert key.startswith("arrangement_booking_approved:")
    assert message == f"Venue booking for {EVENT} at {HALL} was approved."
    assert all(not rows for rows in everyone_else(app).values())


# QA-SPL-121-002 | AC1 | BB
def test_qa_spl_121_002_a_rejection_notice_carries_the_reason_only(app, client):
    _, _, [booking] = venue.scenario(app, client)
    response = reject(
        client, booking, reason="maintenance", alternative_suggestion="Try the Sky Room"
    )
    assert response.status_code == 200, response.json
    [(key, message)] = notices(app)
    assert key.startswith("arrangement_booking_rejected:")
    assert message == f"Venue booking for {EVENT} at {HALL} was rejected: maintenance"
    assert "Sky Room" not in message


@pytest.mark.parametrize(
    ("token", "prepare", "status"),
    [
        ("coordinator", None, 403),
        ("other-coordinator", None, 403),
        (None, None, 401),
        ("venue-staff", "approved", 409),
        ("venue-staff", "event_confirmed", 409),
    ],
)
# QA-SPL-121-003 | AC1 AC5 | BB negative
def test_qa_spl_121_003_a_refused_approval_sends_nothing(app, client, token, prepare, status):
    event, _, [booking] = venue.scenario(app, client, approved=prepare == "approved")
    if prepare == "event_confirmed":
        with Session(app.extensions["engine"]) as session:
            session.get(EventRequest, event).status = "confirmed"
            session.commit()
    before = notices(app)
    response = approve(client, booking, token=token)
    assert response.status_code == status, response.json
    assert notices(app) == before


@pytest.mark.parametrize(
    ("token", "body", "status"),
    [
        ("venue-staff", {"reason": "   "}, 400),
        ("venue-staff", {}, 400),
        ("venue-staff", {"reason": "maintenance", "notify": "everyone"}, 400),
        ("coordinator", {"reason": "maintenance"}, 403),
        ("manager", {"reason": "maintenance"}, 403),
    ],
)
# QA-SPL-121-004 | AC1 AC5 | BB negative
def test_qa_spl_121_004_a_refused_rejection_sends_nothing(app, client, token, body, status):
    _, _, [booking] = venue.scenario(app, client)
    response = reject(client, booking, token=token, **body)
    assert response.status_code == status, response.json
    assert notices(app) == []
    assert booking_status(app, booking) == "requested"


# QA-SPL-121-005 | AC1 AC5 | BB retry
def test_qa_spl_121_005_a_repeated_decision_adds_no_second_notice(app, client):
    _, _, [first, second] = venue.scenario(app, client, siblings=True)
    assert approve(client, first).status_code == 200
    assert approve(client, first).status_code == 409
    assert reject(client, second, reason="maintenance").status_code == 200
    assert reject(client, second, reason="maintenance").status_code == 409
    assert [key.split(":")[0] for key, _ in notices(app)] == [
        "arrangement_booking_approved",
        "arrangement_booking_rejected",
    ]


# QA-SPL-121-006 | AC1 | BB security
def test_qa_spl_121_006_the_approval_note_stays_out_of_the_notice(app, client):
    _, _, [booking] = venue.scenario(app, client)
    assert approve(client, booking, note="VIP client, keep quiet").status_code == 200
    [(_, message)] = notices(app)
    assert "VIP" not in message


def fail_after(module, monkeypatch):
    real = module.add_arrangement_notice

    def wrapped(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("Injected failure after the notice was written")

    monkeypatch.setattr(module, "add_arrangement_notice", wrapped)


# QA-SPL-121-007 | AC1 AC5 | WB failure injection
def test_qa_spl_121_007_a_failed_decision_leaves_no_notice(app, client, monkeypatch):
    _, _, [first, second] = venue.scenario(app, client, siblings=True)
    fail_after(approvals_module, monkeypatch)
    with pytest.raises(RuntimeError, match="Injected"):
        approve(client, first)
    with pytest.raises(RuntimeError, match="Injected"):
        reject(client, second, reason="maintenance")
    assert notices(app) == []
    assert booking_status(app, first) == booking_status(app, second) == "requested"


# AC3 - notified when a venue block or a change to a venue's attributes flags one of my bookings


# QA-SPL-121-030 | AC3 | BB
def test_qa_spl_121_030_a_block_over_the_booking_notifies_without_its_reason(app, client):
    _, venue_id, [booking] = venue.scenario(app, client, approved=True)
    before = len(notices(app))
    response = block(client, venue_id)
    assert response.status_code == 201, response.json
    rows = notices(app)
    assert len(rows) == before + 1
    key, message = rows[-1]
    assert key.startswith("arrangement_booking_flagged:block-")
    assert key.endswith(f"-booking-{booking['id']}")
    assert message == (
        f"Venue booking for {EVENT} at {HALL} needs review: Venue Staff blocked time it uses."
    )
    assert "Burst pipe" not in message


# QA-SPL-121-031 | AC3 | BB
def test_qa_spl_121_031_a_venue_attribute_change_that_flags_the_booking_notifies(app, client):
    _, venue_id, _ = venue.scenario(app, client)
    venue.capacity(client, venue_id, 100)
    [(key, message)] = notices(app)
    assert key.startswith("arrangement_booking_flagged:")
    assert message == (
        f"Venue booking for {EVENT} at {HALL} needs review: the venue's details changed."
    )


# QA-SPL-121-032 | AC3 | BB negative
def test_qa_spl_121_032_changes_that_flag_nothing_send_nothing(app, client):
    _, venue_id, _ = venue.scenario(app, client)
    assert block(client, venue_id, start="15:00", end="16:00").status_code == 201
    venue.capacity(client, venue_id, 400)
    assert notices(app) == []


# QA-SPL-121-033 | AC3 | BB boundary
def test_qa_spl_121_033_the_coordinators_own_event_edits_send_nothing(app, client):
    event, _, [booking] = venue.scenario(app, client)
    # The coordinator's own requirement change on the booking flags it (SPL-106) ...
    venue.edit(
        app,
        event,
        lambda item, session: setattr(
            session.get(VenueBooking, booking["id"]), "expected_attendance", 201
        ),
    )
    assert "layout_capacity" in venue.kinds(client, booking)
    flagged_by_edit = venue.kinds(client, booking)
    # ... and so does a significant change on a Confirmed event (SPL-109), through its route.
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event).status = "confirmed"
        session.commit()
    path = f"/api/event-requests/assigned/{event}/significant-changes"
    values = {"proposed_date": "2030-06-16"}
    preview = client.post(path + "/preview", json={"values": values}, headers=base.headers())
    assert preview.status_code == 200, preview.json
    saved = client.patch(
        path,
        json={"values": values, "preview_token": preview.json["preview_token"]},
        headers=base.headers(),
    )
    assert saved.status_code == 200, saved.json
    assert venue.kinds(client, booking) - flagged_by_edit
    assert notices(app) == []


# QA-SPL-121-034 | AC3 AC5 | BB retry
def test_qa_spl_121_034_repeating_a_venue_change_adds_nothing_but_a_new_block_does(app, client):
    _, venue_id, _ = venue.scenario(app, client, approved=True)
    approval = len(notices(app))
    venue.capacity(client, venue_id, 100)
    venue.capacity(client, venue_id, 100)
    venue.capacity(client, venue_id, 90)
    assert len(notices(app)) == approval + 1
    assert block(client, venue_id).status_code == 201
    assert block(client, venue_id, start="10:30", end="11:00").status_code == 201
    assert len(notices(app)) == approval + 3


@pytest.mark.parametrize(
    ("token", "extra", "status"),
    [
        ("coordinator", {}, 403),
        ("venue-staff", {"reason": ""}, 400),
        ("venue-staff", {"notify": True}, 400),
    ],
)
# QA-SPL-121-035 | AC3 AC5 | BB negative
def test_qa_spl_121_035_a_refused_block_or_venue_edit_sends_nothing(
    app, client, token, extra, status
):
    _, venue_id, _ = venue.scenario(app, client)
    assert block(client, venue_id, token=token, **extra).status_code == status
    refused = client.patch(
        f"/api/venues/{venue_id}",
        json={"layouts": [{"layout": "theatre", "capacity": -1}]},
        headers=STAFF,
    )
    assert refused.status_code == 400, refused.json
    assert notices(app) == []


# QA-SPL-121-036 | AC3 | BB
def test_qa_spl_121_036_one_notice_per_flagged_booking(app, client):
    first_event, venue_id, [first] = venue.scenario(app, client)
    second_event = base.make_event(
        app, "Harbour Summit", day=venue.DAY, start=time(14), end=time(16), attendance=150
    )
    second = venue.request(client, second_event, venue_id, start_time="14:00", end_time="15:00")
    assert second.status_code == 201, second.json
    venue.capacity(client, venue_id, 100)
    messages = sorted(message for _, message in notices(app))
    assert messages == [
        f"Venue booking for {EVENT} at {HALL} needs review: the venue's details changed.",
        f"Venue booking for Harbour Summit at {HALL} needs review: the venue's details changed.",
    ]
    assert first_event != second_event


# QA-SPL-121-037 | AC3 | BB boundary
def test_qa_spl_121_037_a_resolved_flag_or_removed_block_sends_nothing(app, client):
    _, venue_id, _ = venue.scenario(app, client)
    venue.capacity(client, venue_id, 100)
    created = block(client, venue_id)
    assert created.status_code == 201
    flagged = len(notices(app))
    venue.capacity(client, venue_id, 400)
    block_id = created.json["operational_block"]["id"]
    removed = client.delete(f"/api/venues/{venue_id}/operational-blocks/{block_id}", headers=STAFF)
    assert removed.status_code in (200, 204), removed.json
    assert len(notices(app)) == flagged


# QA-SPL-121-038 | AC3 AC5 | BB retry
def test_qa_spl_121_038_a_venue_edit_after_a_block_does_not_announce_the_block_again(app, client):
    _, venue_id, _ = venue.scenario(app, client, approved=True)
    assert block(client, venue_id).status_code == 201
    after_block = len(notices(app))
    renamed = client.patch(
        f"/api/venues/{venue_id}", json={"location": "Level 4, Marina Centre"}, headers=STAFF
    )
    assert renamed.status_code == 200, renamed.json
    assert len(notices(app)) == after_block


# QA-SPL-121-039 | AC3 | BB boundary
def test_qa_spl_121_039_a_flag_that_is_resolved_sends_no_second_notice(app, client):
    _, venue_id, [booking] = venue.scenario(app, client)
    venue.capacity(client, venue_id, 100)
    assert "layout_capacity" in venue.kinds(client, booking)
    flagged = notices(app)
    venue.capacity(client, venue_id, 400)
    assert venue.kinds(client, booking) == set()
    assert notices(app) == flagged


# AC5 - only the assigned coordinator


# QA-SPL-121-050 | AC5 | BB
def test_qa_spl_121_050_no_other_account_hears_of_venue_decisions(app, client):
    _, venue_id, [first, second] = venue.scenario(app, client, siblings=True)
    assert approve(client, first).status_code == 200
    assert reject(client, second, reason="maintenance").status_code == 200
    assert block(client, venue_id).status_code == 201
    venue.capacity(client, venue_id, 100)
    assert len(notices(app)) >= 3
    assert all(not rows for rows in everyone_else(app).values())


# QA-SPL-121-051 | AC5 | BB
def test_qa_spl_121_051_after_reassignment_the_new_coordinator_is_told(app, client):
    event, _, [first, second] = venue.scenario(app, client, siblings=True)
    assert approve(client, first).status_code == 200
    with Session(app.extensions["engine"]) as session:
        session.scalar(
            select(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event
            )
        ).coordinator_account_id = base.OTHER_COORDINATOR
        session.commit()
    assert reject(client, second, reason="maintenance").status_code == 200
    assert [key.split(":")[0] for key, _ in notices(app)] == ["arrangement_booking_approved"]
    assert [key.split(":")[0] for key, _ in notices(app, base.OTHER_COORDINATOR)] == [
        "arrangement_booking_rejected"
    ]


# QA-SPL-121-052 | AC5 | BB boundary
def test_qa_spl_121_052_an_unassigned_event_notifies_nobody(app, client):
    event, _, [booking] = venue.scenario(app, client)
    with Session(app.extensions["engine"]) as session:
        session.execute(
            delete(EventCoordinatorAssignment).where(
                EventCoordinatorAssignment.event_request_id == event
            )
        )
        session.commit()
    assert reject(client, booking, reason="maintenance").status_code == 200
    with Session(app.extensions["engine"]) as session:
        # SPL-104's Venue Staff notice of the booking request is the only notice; no one is told
        # of the rejection.
        keys = select(Notification.dedupe_key).where(
            ~Notification.dedupe_key.like("arrangement_hold_%")
        )
        assert session.scalars(keys).all() == [f"venue_booking_requested:{booking['id']}"]


# QA-SPL-121-054 | AC5 | BB
def test_qa_spl_121_054_the_notice_opens_a_page_the_coordinator_can_open(app, client):
    event, _, [booking] = venue.scenario(app, client)
    assert approve(client, booking).status_code == 200
    inbox = client.get("/api/notifications", headers=base.headers())
    assert inbox.status_code == 200
    [item] = [n for n in inbox.json["notifications"] if "was approved" in n["message"]]
    assert item["link"] == f"/workspace/assigned-events/{event}"
    opened = client.get(f"/api/event-requests/assigned/{event}", headers=base.headers())
    assert opened.status_code == 200, opened.json
    refused = client.get(
        f"/api/event-requests/assigned/{event}", headers=base.headers("other-coordinator")
    )
    assert refused.status_code == 404


@pytest.mark.parametrize(
    "key", ["arrangement_booking_approved:9", "arrangement_equipment_flagged:3-line-4"]
)
# QA-SPL-121-055 | AC5 | WB
def test_qa_spl_121_055_arrangement_notices_link_to_the_assigned_event(key):
    notice = SimpleNamespace(dedupe_key=key, event_request_id=7)
    assert notifications_module._event_link(notice) == "/workspace/assigned-events/7"
