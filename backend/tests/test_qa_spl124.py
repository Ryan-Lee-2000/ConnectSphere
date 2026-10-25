"""SPL-124 QA: an attendee is told when an event they are registered for changes.

Case IDs are QA-SPL-124-NNN (see the QA-SPL-124 report). The fixture is SPL-118's: one Confirmed
event, Harbour Lights Gala, on Fri 20 Nov 2026 18:00-22:00 at Harbour Hall (one Approved booking),
registration open, assigned coordinator. Every action goes through its real route.
"""

import pytest
import test_registration_withdrawal as base
from app import event_registrations as registrations_module
from app import notifications as notifications_module
from app.models import EventRegistration, EventRequest, Notification, VenueBooking
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_registration_withdrawal import (
    ATTENDEE,
    COORDINATOR,
    DETAILS,
    ORGANISER,
    SECOND_ATTENDEE,
    headers,
    make_event,
    register,
    withdraw,
)

app = base.app
client = base.client
event_id = base.event_id

MY_REGISTRATIONS = "/workspace/my-registrations"
CANCELLED = "Harbour Lights Gala has been cancelled."
NO_VENUE = "The venue for Harbour Lights Gala has changed. Venues now: none confirmed yet."


def notices(app, account=ATTENDEE):
    with Session(app.extensions["engine"]) as session:
        rows = session.scalars(
            select(Notification)
            .where(Notification.recipient_account_id == account)
            .order_by(Notification.id)
        ).all()
        return [(row.dedupe_key, row.message) for row in rows]


def kinds(app, account=ATTENDEE):
    return [key.split(":")[0] for key, _ in notices(app, account)]


def messages(app, account=ATTENDEE):
    return [message for _, message in notices(app, account)]


def attendee_notices(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(
            select(Notification).where(Notification.dedupe_key.like("attendee_%"))
        ).all()


def change(client, event_id, values):
    url = f"/api/event-requests/assigned/{event_id}/significant-changes"
    preview = client.post(url + "/preview", json={"values": values}, headers=headers("coordinator"))
    assert preview.status_code == 200, preview.json
    return client.patch(
        url,
        json={"values": values, "preview_token": preview.json["preview_token"]},
        headers=headers("coordinator"),
    )


def cancel_event(client, event_id, token="coordinator", reason="Typhoon warning issued"):
    return client.post(
        f"/api/event-requests/{event_id}/cancel", json={"reason": reason}, headers=headers(token)
    )


def booking_of(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(
            select(VenueBooking.id).where(VenueBooking.event_request_id == event_id)
        )


def cancel_booking(client, event_id, booking, reason="Moving to a larger room"):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{booking}/cancel",
        json={"reason": reason},
        headers=headers("coordinator"),
    )


def two_registered(client, event_id):
    register(client, event_id)
    register(client, event_id, token="second-attendee")


# ---------------------------------------------------------------- AC1: date, time or venue changes


# QA-SPL-124-001 | AC1 | BB
def test_qa_spl_124_001_a_date_change_names_the_new_and_old_date(app, client, event_id):
    register(client, event_id)
    assert change(client, event_id, {"proposed_date": "2026-11-21"}).status_code == 200
    assert messages(app)[-1] == (
        "Harbour Lights Gala has changed: date now Sat 21 Nov 2026 (was Fri 20 Nov 2026)."
    )


# QA-SPL-124-002 | AC1 | BB boundary (one of the two times)
@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"start_time": "19:00"}, "time now 19:00–22:00 SGT (was 18:00–22:00 SGT)"),
        ({"end_time": "23:00"}, "time now 18:00–23:00 SGT (was 18:00–22:00 SGT)"),
    ],
)
def test_qa_spl_124_002_a_time_change_names_both_times(app, client, event_id, values, expected):
    register(client, event_id)
    assert change(client, event_id, values).status_code == 200
    assert messages(app)[-1] == f"Harbour Lights Gala has changed: {expected}."


# QA-SPL-124-003 | AC1 | BB
def test_qa_spl_124_003_one_save_of_date_and_times_is_one_notice_each(app, client, event_id):
    two_registered(client, event_id)
    values = {"proposed_date": "2026-11-21", "start_time": "19:00", "end_time": "23:00"}
    assert change(client, event_id, values).status_code == 200
    expected = (
        "Harbour Lights Gala has changed: date now Sat 21 Nov 2026 (was Fri 20 Nov 2026); "
        "time now 19:00–23:00 SGT (was 18:00–22:00 SGT)."
    )
    for account in (ATTENDEE, SECOND_ATTENDEE):
        assert kinds(app, account).count("attendee_schedule_changed") == 1
        assert messages(app, account)[-1] == expected


# QA-SPL-124-004 | AC1 | BB negative
@pytest.mark.parametrize(
    "values", [{"expected_attendance": 120}, {"location_preference": "Near an MRT station"}]
)
def test_qa_spl_124_004_a_change_attendees_cannot_see_notifies_nobody(
    app, client, event_id, values
):
    register(client, event_id)
    assert change(client, event_id, values).status_code == 200
    assert kinds(app) == ["attendee_registered"]


# QA-SPL-124-005 | AC1 | BB
def test_qa_spl_124_005_cancelling_the_approved_venue_says_none_is_held(app, client, event_id):
    register(client, event_id)
    # A Confirmed event's bookings change only in Planning; the date change returns it there.
    assert change(client, event_id, {"proposed_date": "2026-11-21"}).status_code == 200
    assert cancel_booking(client, event_id, booking_of(app, event_id)).status_code == 200
    assert messages(app)[-1] == NO_VENUE


# QA-SPL-124-006 | AC1 | BB (internal text stays internal)
def test_qa_spl_124_006_venue_notice_carries_no_reason_or_staff_names(app, client, event_id):
    register(client, event_id)
    change(client, event_id, {"proposed_date": "2026-11-21"})
    cancel_booking(client, event_id, booking_of(app, event_id), reason="Leaking roof in hall")
    text = " ".join(messages(app))
    assert "Leaking roof" not in text and "Casey" not in text


# QA-SPL-124-007 | AC1 | WB
@pytest.mark.parametrize(
    "changes",
    [{}, {"expected_attendance": {"previous": 150, "new": 120}}],
)
def test_qa_spl_124_007_the_helper_ignores_non_public_fields(app, event_id, changes):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        notifications_module.add_schedule_change_notices(session, event, changes, change_id=1)
        assert not [obj for obj in session.new if isinstance(obj, Notification)]


# ------------------------------------------------------------------------- AC2: cancellation


# QA-SPL-124-020 | AC2 | BB
def test_qa_spl_124_020_cancellation_notifies_each_registered_attendee_once(app, client, event_id):
    two_registered(client, event_id)
    assert cancel_event(client, event_id).status_code == 200
    for account in (ATTENDEE, SECOND_ATTENDEE):
        assert messages(app, account).count(CANCELLED) == 1


# QA-SPL-124-021 | AC2 | BB (the reason is for staff)
def test_qa_spl_124_021_the_attendee_is_not_told_the_staff_reason(app, client, event_id):
    register(client, event_id)
    cancel_event(client, event_id, reason="Client budget withdrawn")
    assert all("budget" not in message for message in messages(app))


# QA-SPL-124-022 | AC2 | BB boundary
def test_qa_spl_124_022_an_event_without_registrations_notifies_no_attendee(app, client, event_id):
    assert cancel_event(client, event_id).status_code == 200
    assert attendee_notices(app) == []


# QA-SPL-124-023 | AC2 | BB
def test_qa_spl_124_023_cancelling_from_planning_still_reaches_attendees(app, client, event_id):
    register(client, event_id)
    change(client, event_id, {"proposed_date": "2026-11-21"})
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status == "planning"
    assert cancel_event(client, event_id).status_code == 200
    assert messages(app)[-1] == CANCELLED


# QA-SPL-124-024 | AC2 AC4 | BB negative
def test_qa_spl_124_024_a_second_cancellation_adds_nothing(app, client, event_id):
    register(client, event_id)
    assert cancel_event(client, event_id).status_code == 200
    assert cancel_event(client, event_id).status_code == 409
    assert messages(app).count(CANCELLED) == 1


# QA-SPL-124-025 | AC2 AC4 | BB security
@pytest.mark.parametrize(("token", "code"), [("attendee", 403), ("organiser", 403), (None, 401)])
def test_qa_spl_124_025_a_refused_cancellation_notifies_nobody(app, client, event_id, token, code):
    register(client, event_id)
    assert cancel_event(client, event_id, token=token).status_code == code
    assert kinds(app) == ["attendee_registered"]


# --------------------------------------------------------- AC3: registration and withdrawal acks


# QA-SPL-124-030 | AC3 | BB
def test_qa_spl_124_030_registering_shows_a_confirmation_and_an_inbox_notice(app, client, event_id):
    response = client.post(
        f"/api/event-requests/{event_id}/registrations", json=DETAILS, headers=headers()
    )
    assert response.status_code == 201
    assert response.json["registration"]["status"] == "registered"
    assert notices(app) == [
        (
            f"attendee_registered:{response.json['registration']['id']}",
            "You are registered for Harbour Lights Gala on Fri 20 Nov 2026, 18:00–22:00 SGT.",
        )
    ]


# QA-SPL-124-031 | AC3 | BB
def test_qa_spl_124_031_withdrawing_adds_an_acknowledgement(app, client, event_id):
    registration = register(client, event_id)
    response = withdraw(client, registration)
    assert response.status_code == 200 and response.json["registration"]["status"] == "withdrawn"
    assert notices(app)[-1] == (
        f"attendee_withdrawn:{registration}",
        "You withdrew your registration for Harbour Lights Gala.",
    )


# QA-SPL-124-032 | AC3 | BB
def test_qa_spl_124_032_registering_again_is_acknowledged_again(app, client, event_id):
    first = register(client, event_id)
    withdraw(client, first)
    second = register(client, event_id)
    assert [key for key, _ in notices(app)] == [
        f"attendee_registered:{first}",
        f"attendee_withdrawn:{first}",
        f"attendee_registered:{second}",
    ]


# QA-SPL-124-033 | AC3 AC4 | BB negative
@pytest.mark.parametrize(
    ("body", "code"),
    [(DETAILS, 409), ({**DETAILS, "email": "not-an-email"}, 400), ({"name": "Avery"}, 400)],
)
def test_qa_spl_124_033_a_refused_registration_adds_no_notice(app, client, event_id, body, code):
    register(client, event_id)
    response = client.post(
        f"/api/event-requests/{event_id}/registrations", json=body, headers=headers()
    )
    assert response.status_code == code
    assert kinds(app) == ["attendee_registered"]


# QA-SPL-124-034 | AC3 AC4 | BB negative and security
def test_qa_spl_124_034_a_refused_withdrawal_adds_no_notice(app, client, event_id):
    registration = register(client, event_id)
    assert withdraw(client, registration, token="second-attendee").status_code == 404
    assert withdraw(client, registration).status_code == 200
    assert withdraw(client, registration).status_code == 409
    assert kinds(app) == ["attendee_registered", "attendee_withdrawn"]
    assert notices(app, SECOND_ATTENDEE) == []


# QA-SPL-124-035 | AC3 | BB security
def test_qa_spl_124_035_an_acknowledgement_reaches_only_the_attendee(app, client, event_id):
    register(client, event_id)
    for account in (SECOND_ATTENDEE, COORDINATOR, ORGANISER):
        assert notices(app, account) == []


# --------------------------------------------------------- AC4: refusals, failures and retries


# QA-SPL-124-040 | AC4 | BB negative
def test_qa_spl_124_040_a_stale_preview_saves_and_notifies_nothing(app, client, event_id):
    register(client, event_id)
    response = client.patch(
        f"/api/event-requests/assigned/{event_id}/significant-changes",
        json={"values": {"proposed_date": "2026-11-21"}, "preview_token": "stale"},
        headers=headers("coordinator"),
    )
    assert response.status_code == 409
    assert kinds(app) == ["attendee_registered"]


# QA-SPL-124-041 | AC4 | BB (retry)
def test_qa_spl_124_041_saving_the_same_change_again_adds_nothing(app, client, event_id):
    register(client, event_id)
    assert change(client, event_id, {"proposed_date": "2026-11-21"}).status_code == 200
    again = change(client, event_id, {"proposed_date": "2026-11-21"})
    assert again.status_code == 200 and again.json["change"] is None
    assert kinds(app).count("attendee_schedule_changed") == 1


# QA-SPL-124-042 | AC4 | WB (failure after the notice is written)
def test_qa_spl_124_042_a_failed_registration_leaves_no_notice(app, client, event_id, monkeypatch):
    real = registrations_module.add_registration_notice

    def fail_after_writing(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("simulated failure before commit")

    monkeypatch.setattr(registrations_module, "add_registration_notice", fail_after_writing)
    with pytest.raises(RuntimeError):
        client.post(
            f"/api/event-requests/{event_id}/registrations", json=DETAILS, headers=headers()
        )
    assert notices(app) == []
    with Session(app.extensions["engine"]) as session:
        assert session.scalars(select(EventRegistration)).all() == []


# QA-SPL-124-043 | AC4 | WB (the database refuses a second copy)
def test_qa_spl_124_043_the_same_notice_cannot_be_stored_twice(app, client, event_id):
    register(client, event_id)
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        notifications_module.add_attendee_notices(
            session, event, kind="event_cancelled", source_id=event_id, message=CANCELLED
        )
        session.commit()
        notifications_module.add_attendee_notices(
            session, event, kind="event_cancelled", source_id=event_id, message=CANCELLED
        )
        with pytest.raises(IntegrityError):
            session.commit()


# QA-SPL-124-044 | AC4 | WB (registration's duplicate backstop)
def test_qa_spl_124_044_the_duplicate_backstop_rolls_back_its_notice(
    app, client, event_id, monkeypatch
):
    register(client, event_id)
    monkeypatch.setattr(registrations_module, "_has_active_registration", lambda *args: False)
    response = client.post(
        f"/api/event-requests/{event_id}/registrations", json=DETAILS, headers=headers()
    )
    assert response.status_code == 409
    assert kinds(app) == ["attendee_registered"]


# QA-SPL-124-045 | AC4 | BB negative
def test_qa_spl_124_045_a_refused_booking_cancellation_notifies_nobody(app, client, event_id):
    register(client, event_id)
    # Still Confirmed, so the booking cannot be cancelled.
    assert cancel_booking(client, event_id, booking_of(app, event_id)).status_code == 409
    assert kinds(app) == ["attendee_registered"]


# ------------------------------------------------------- AC5: withdrawn attendees hear nothing


def withdrawn_second(client, event_id):
    register(client, event_id)
    registration = register(client, event_id, token="second-attendee")
    assert withdraw(client, registration, token="second-attendee").status_code == 200
    return registration


# QA-SPL-124-050 | AC5 | BB
def test_qa_spl_124_050_no_date_or_time_notice_after_withdrawing(app, client, event_id):
    withdrawn_second(client, event_id)
    change(client, event_id, {"proposed_date": "2026-11-21", "start_time": "19:00"})
    assert "attendee_schedule_changed" in kinds(app)
    assert kinds(app, SECOND_ATTENDEE) == ["attendee_registered", "attendee_withdrawn"]


# QA-SPL-124-051 | AC5 | BB
def test_qa_spl_124_051_no_venue_notice_after_withdrawing(app, client, event_id):
    withdrawn_second(client, event_id)
    change(client, event_id, {"proposed_date": "2026-11-21"})
    cancel_booking(client, event_id, booking_of(app, event_id))
    assert messages(app)[-1] == NO_VENUE
    assert NO_VENUE not in messages(app, SECOND_ATTENDEE)


# QA-SPL-124-052 | AC5 | BB
def test_qa_spl_124_052_no_cancellation_notice_after_withdrawing(app, client, event_id):
    withdrawn_second(client, event_id)
    cancel_event(client, event_id)
    assert CANCELLED in messages(app)
    assert CANCELLED not in messages(app, SECOND_ATTENDEE)


# QA-SPL-124-053 | AC5 | BB boundary
def test_qa_spl_124_053_registering_again_brings_the_notices_back(app, client, event_id):
    withdrawn_second(client, event_id)
    register(client, event_id, token="second-attendee")
    cancel_event(client, event_id)
    assert messages(app, SECOND_ATTENDEE)[-1] == CANCELLED


# QA-SPL-124-054 | AC5 | BB security
def test_qa_spl_124_054_staff_and_other_events_hear_nothing(app, client, event_id):
    other = make_event(app)
    register(client, other, token="second-attendee")
    register(client, event_id)
    cancel_event(client, event_id)
    assert kinds(app, SECOND_ATTENDEE) == ["attendee_registered"]
    for account in (COORDINATOR, ORGANISER):
        assert not [key for key, _ in notices(app, account) if key.startswith("attendee_")]


# ---------------------------------------------------------------------- AC6: the notice's page


# QA-SPL-124-060 | AC6 | BB
def test_qa_spl_124_060_every_attendee_notice_opens_my_registrations(app, client, event_id):
    register(client, event_id)
    change(client, event_id, {"proposed_date": "2026-11-21"})
    cancel_booking(client, event_id, booking_of(app, event_id))
    cancel_event(client, event_id)
    inbox = client.get("/api/notifications", headers=headers()).json["notifications"]
    assert len(inbox) == 4
    assert {notice["link"] for notice in inbox} == {MY_REGISTRATIONS}


# QA-SPL-124-061 | AC6 | BB security
def test_qa_spl_124_061_the_attendee_can_open_my_registrations_not_staff_pages(
    app, client, event_id
):
    register(client, event_id)
    mine = client.get("/api/my-registrations", headers=headers())
    assert mine.status_code == 200
    staff_page = client.get(f"/api/event-requests/assigned/{event_id}", headers=headers())
    assert staff_page.status_code == 403


# QA-SPL-124-062 | AC6 | WB
@pytest.mark.parametrize(
    ("key", "link"),
    [
        ("attendee_registered:1", MY_REGISTRATIONS),
        ("attendee_venue_removed:4", MY_REGISTRATIONS),
        ("arrangement_booking_approved:3", "/workspace/assigned-events/9"),
        ("organiser_approved:2", "/workspace/organisation-events/9"),
        ("venue_booking_requested:5", "/workspace/booking-requests"),
    ],
)
def test_qa_spl_124_062_the_link_follows_the_notice_kind(key, link):
    notice = Notification(dedupe_key=key, event_request_id=9)
    assert notifications_module._event_link(notice) == link
