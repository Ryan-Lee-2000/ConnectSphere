"""QA cases for SPL-104: Venue Staff are notified when a venue booking is requested or withdrawn.

Each test carries the QA-SPL-104 case it proves. Expected values come from the story's
acceptance criteria and the decisions recorded in docs/tasks/SPL-104.md, not from the code.
"""

from datetime import date, datetime, time, timezone

import pytest
from app import create_app
from app import venue_booking_requests as requests_module
from app import venue_booking_withdrawals as withdrawals_module
from app.models import (
    Account,
    AccountRole,
    Base,
    EventCoordinatorAssignment,
    EventRequest,
    Notification,
    Organisation,
    Role,
    Venue,
    VenueBooking,
    VenueLayout,
)
from app.notifications import _event_link, add_venue_booking_notices
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

COORDINATOR = "00000000-0000-0000-0000-000000001041"
OTHER_COORDINATOR = "00000000-0000-0000-0000-000000001042"
ORGANISER = "00000000-0000-0000-0000-000000001043"
STAFF_A = "00000000-0000-0000-0000-000000001044"
STAFF_B = "00000000-0000-0000-0000-000000001045"
INACTIVE_STAFF = "00000000-0000-0000-0000-000000001046"
MANAGER = "00000000-0000-0000-0000-000000001047"
TECHNICAL = "00000000-0000-0000-0000-000000001048"
TOKENS = {
    "coordinator": COORDINATOR,
    "other-coordinator": OTHER_COORDINATOR,
    "organiser": ORGANISER,
    "staff-a": STAFF_A,
    "staff-b": STAFF_B,
    "inactive-staff": INACTIVE_STAFF,
    "manager": MANAGER,
    "technical": TECHNICAL,
}
EVENT_DATE = date(2026, 10, 14)
QUEUE = "/workspace/booking-requests"
SLOT_HARBOUR = (
    "Venue booking requested for Coastal Forum: Harbour Hall on Wed 14 Oct 2026, "
    "13:00–18:00 SGT; venue occupied PM (setup AM, turnaround Night)."
)
EXACT_HARBOUR = (
    "Venue booking requested for Coastal Forum: Harbour Hall on Wed 14 Oct 2026, "
    "10:00–12:00 SGT; venue occupied 09:30–12:45 including setup and turnaround."
)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/qa-spl104.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="SPL-104 client")
        session.add(organisation)
        session.flush()
        for account_id, name, role, active in (
            (COORDINATOR, "Casey Lim", Role.EVENT_COORDINATOR, True),
            (OTHER_COORDINATOR, "Taylor Tan", Role.EVENT_COORDINATOR, True),
            (ORGANISER, "Devon Lee", Role.EVENT_ORGANISER, True),
            (STAFF_A, "Valerie Tan", Role.VENUE_STAFF, True),
            (STAFF_B, "Vivian Goh", Role.VENUE_STAFF, True),
            (INACTIVE_STAFF, "Ivan Lee", Role.VENUE_STAFF, False),
            (MANAGER, "Morgan Ong", Role.EVENT_OPERATIONS_MANAGER, True),
            (TECHNICAL, "Tara Ng", Role.TECHNICAL_SUPPORT_STAFF, True),
        ):
            session.add(
                Account(
                    id=account_id,
                    display_name=name,
                    organisation_id=organisation.id,
                    is_active=active,
                )
            )
            session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()
        app.config["ORGANISATION_ID"] = organisation.id
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def exact(app):
    app.config["EXACT_VENUE_TIMING_ENABLED"] = True
    return app


def make_event(app, name="Coastal Forum", *, start=time(13), end=time(18), status="planning"):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER,
            organisation_id=app.config["ORGANISATION_ID"],
            name=name,
            purpose="Community planning",
            proposed_date=EVENT_DATE,
            start_time=start,
            end_time=end,
            expected_attendance=150,
            required_facilities=["Projector"],
            accessibility_needs=["Step-free access"],
            location_preference="Marina Centre",
            status=status,
        )
        session.add(event)
        session.flush()
        session.add(
            EventCoordinatorAssignment(
                event_request_id=event.id,
                coordinator_account_id=COORDINATOR,
                assigned_by_account_id=MANAGER,
                assigned_at=datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
            )
        )
        session.commit()
        return event.id


def add_venue(app, name="Harbour Hall", *, setup=1, turnaround=1, minutes=(30, 45)):
    with Session(app.extensions["engine"]) as session:
        venue = Venue(
            name=name,
            location="Level 3, Marina Centre",
            facilities=["Projector", "PA system"],
            accessibility_features=["Step-free access"],
            operating_slots=["AM", "PM", "NIGHT"],
            setup_buffer_slots=setup,
            turnaround_buffer_slots=turnaround,
            setup_minutes=minutes[0],
            turnaround_minutes=minutes[1],
            operating_intervals=[[0, 1440]],
            timing_revision=1,
        )
        venue.layouts = [VenueLayout(layout="theatre", capacity=200)]
        session.add(venue)
        session.commit()
        return venue.id


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def request_booking(client, event_id, venue_id, token="coordinator", **extra):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings",
        json={"venue_id": venue_id, "layout": "theatre", **extra},
        headers=headers(token),
    )


def request_exact(client, event_id, venue_id, start="10:00", end="12:00", token="coordinator"):
    return request_booking(
        client,
        event_id,
        venue_id,
        token,
        date=EVENT_DATE.isoformat(),
        start_time=start,
        end_time=end,
        venue_revision=1,
    )


def withdraw(client, event_id, booking_id, token="coordinator", **kwargs):
    return client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{booking_id}/withdraw",
        headers=headers(token),
        **kwargs,
    )


def booked(client, event_id, venue_id):
    response = request_booking(client, event_id, venue_id)
    assert response.status_code == 201, response.json
    return response.json["booking"]["id"]


def booked_exact(client, event_id, venue_id, start="10:00", end="12:00"):
    response = request_exact(client, event_id, venue_id, start, end)
    assert response.status_code == 201, response.json
    return response.json["booking"]["id"]


def inbox(client, token):
    response = client.get("/api/notifications", headers=headers(token))
    assert response.status_code == 200, response.json
    # SPL-133 also tells the requesting coordinator the hold's deadline ("... is held for ...");
    # that notice is asserted in SPL-133's suite, so this suite reads only SPL-104's.
    return [n for n in response.json["notifications"] if " is held for " not in n["message"]]


# SPL-133 tells the coordinator a hold was created; this suite asserts SPL-104's own notices.
NOT_HOLD = ~Notification.dedupe_key.like("arrangement_hold_%")


def notices(app, *, recipient=None):
    with Session(app.extensions["engine"]) as session:
        query = select(Notification).where(NOT_HOLD).order_by(Notification.id)
        if recipient:
            query = query.where(Notification.recipient_account_id == recipient)
        return [
            (row.recipient_account_id, row.dedupe_key, row.message)
            for row in session.scalars(query)
        ]


def keys_by_recipient(app):
    grouped: dict[str, list[str]] = {}
    for recipient, key, _ in notices(app):
        grouped.setdefault(recipient, []).append(key)
    return grouped


def give_role(app, account_id, role):
    with Session(app.extensions["engine"]) as session:
        session.add(AccountRole(account_id=account_id, role=role.value))
        session.commit()


# ---------------------------------------------------------------- AC1: notified on submission


# QA-SPL-104-001 | AC1 | BB
def test_qa_spl_104_001_slot_request_notifies_every_active_venue_staff(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    for token in ("staff-a", "staff-b"):
        [notice] = inbox(client, token)
        assert notice["message"] == SLOT_HARBOUR
        assert notice["event"] == {"id": event_id, "name": "Coastal Forum"}
        assert notice["read"] is False
    assert {key for _, key, _ in notices(app)} == {f"venue_booking_requested:{booking_id}"}


# QA-SPL-104-002 | AC1 | BB
def test_qa_spl_104_002_exact_request_notifies_every_active_venue_staff(exact, client):
    event_id = make_event(exact, start=time(10), end=time(12))
    booked_exact(client, event_id, add_venue(exact))
    for token in ("staff-a", "staff-b"):
        assert [n["message"] for n in inbox(client, token)] == [EXACT_HARBOUR]


# QA-SPL-104-003 | AC1 | BB
def test_qa_spl_104_003_no_one_else_is_notified_of_a_request(app, client):
    booked(client, make_event(app), add_venue(app))
    for token in ("coordinator", "other-coordinator", "organiser", "manager", "technical"):
        assert inbox(client, token) == []
    assert notices(app, recipient=INACTIVE_STAFF) == []


# QA-SPL-104-004 | AC1 | BB
def test_qa_spl_104_004_notice_is_newest_first_alongside_other_notices(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    first = booked(client, event_id, venue_id)
    second = booked(client, make_event(app, "Harbour Gala"), add_venue(app, "Garden Room"))
    listed = inbox(client, "staff-a")
    assert [n["message"].split(":")[0] for n in listed] == [
        "Venue booking requested for Harbour Gala",
        "Venue booking requested for Coastal Forum",
    ]
    assert first != second


# QA-SPL-104-005 | AC1 | WB
def test_qa_spl_104_005_request_notice_is_keyed_to_the_new_booking(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    with Session(app.extensions["engine"]) as session:
        rows = session.scalars(select(Notification).where(NOT_HOLD)).all()
    assert sorted(row.recipient_account_id for row in rows) == sorted([STAFF_A, STAFF_B])
    assert {row.event_request_id for row in rows} == {event_id}
    assert {row.dedupe_key for row in rows} == {f"venue_booking_requested:{booking_id}"}


# QA-SPL-104-006 | AC1 AC2 | BB negative
def test_qa_spl_104_006_approval_and_rejection_send_no_venue_staff_notice(app, client):
    event_id = make_event(app)
    approved = booked(client, event_id, add_venue(app))
    rejected = booked(client, event_id, add_venue(app, "Garden Room"))
    before = notices(app)
    response = client.post(
        f"/api/venue-bookings/{approved}/approve", json={}, headers=headers("staff-a")
    )
    assert response.status_code == 200, response.json
    response = client.post(
        f"/api/venue-bookings/{rejected}/reject",
        json={"reason": "Closed for maintenance."},
        headers=headers("staff-b"),
    )
    assert response.status_code == 200, response.json
    assert [row for row in notices(app) if row[1].startswith("venue_booking_")] == [
        row for row in before
    ]


# ---------------------------------------------------------------- AC2: notified on withdrawal


# QA-SPL-104-010 | AC2 | BB
def test_qa_spl_104_010_slot_withdrawal_notifies_every_active_venue_staff(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    assert withdraw(client, event_id, booking_id).status_code == 200
    for token in ("staff-a", "staff-b"):
        assert [n["message"] for n in inbox(client, token)] == [
            SLOT_HARBOUR.replace("Venue booking requested", "Venue booking request withdrawn"),
            SLOT_HARBOUR,
        ]
    assert notices(app, recipient=INACTIVE_STAFF) == []


# QA-SPL-104-011 | AC2 | BB
def test_qa_spl_104_011_exact_withdrawal_notifies_every_active_venue_staff(exact, client):
    event_id = make_event(exact, start=time(10), end=time(12))
    booking_id = booked_exact(client, event_id, add_venue(exact))
    assert withdraw(client, event_id, booking_id).status_code == 200
    assert inbox(client, "staff-b")[0]["message"] == EXACT_HARBOUR.replace(
        "Venue booking requested", "Venue booking request withdrawn"
    )


# QA-SPL-104-012 | AC2 | BB negative
def test_qa_spl_104_012_booking_and_event_cancellation_are_not_withdrawals(app, client):
    event_id = make_event(app)
    approved = booked(client, event_id, add_venue(app))
    booked(client, event_id, add_venue(app, "Garden Room"))
    assert (
        client.post(
            f"/api/venue-bookings/{approved}/approve", json={}, headers=headers("staff-a")
        ).status_code
        == 200
    )
    response = client.post(
        f"/api/event-requests/{event_id}/venue-bookings/{approved}/cancel",
        json={"reason": "Space no longer needed."},
        headers=headers("coordinator"),
    )
    assert response.status_code == 200, response.json
    response = client.post(
        f"/api/event-requests/{event_id}/cancel",
        json={"reason": "Called off by the client."},
        headers=headers("coordinator"),
    )
    assert response.status_code == 200, response.json
    assert not [key for _, key, _ in notices(app) if key.startswith("venue_booking_withdrawn")]


# QA-SPL-104-013 | AC2 | BB
def test_qa_spl_104_013_a_change_is_withdraw_then_new_request(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    first = booked(client, event_id, venue_id)
    assert withdraw(client, event_id, first).status_code == 200
    second = booked(client, event_id, venue_id)
    assert second != first
    assert keys_by_recipient(app)[STAFF_A] == [
        f"venue_booking_requested:{first}",
        f"venue_booking_withdrawn:{first}",
        f"venue_booking_requested:{second}",
    ]


# QA-SPL-104-014 | AC2 AC7 | BB negative
@pytest.mark.parametrize("case", ["approved", "other-coordinator", "staff", "body", "other-event"])
def test_qa_spl_104_014_refused_withdrawal_sends_nothing(app, client, case):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    if case == "approved":
        client.post(
            f"/api/venue-bookings/{booking_id}/approve", json={}, headers=headers("staff-a")
        )
        response = withdraw(client, event_id, booking_id)
        expected = 409
    elif case == "other-coordinator":
        response = withdraw(client, event_id, booking_id, "other-coordinator")
        expected = 404
    elif case == "staff":
        response = withdraw(client, event_id, booking_id, "staff-a")
        expected = 403
    elif case == "body":
        response = withdraw(client, event_id, booking_id, json={"status": "withdrawn"})
        expected = 400
    else:
        response = withdraw(client, make_event(app, "Other Forum"), booking_id)
        expected = 404
    assert response.status_code == expected, response.json
    assert not [key for _, key, _ in notices(app) if key.startswith("venue_booking_withdrawn")]


# QA-SPL-104-015 | AC2 | WB
def test_qa_spl_104_015_withdrawal_notice_is_keyed_to_the_withdrawn_booking(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    withdraw(client, event_id, booking_id)
    withdrawn = [row for row in notices(app) if row[1].startswith("venue_booking_withdrawn")]
    assert sorted(recipient for recipient, _, _ in withdrawn) == sorted([STAFF_A, STAFF_B])
    assert {key for _, key, _ in withdrawn} == {f"venue_booking_withdrawn:{booking_id}"}


# ---------------------------------------------------------------- AC3: all Venue Staff, by role


# QA-SPL-104-020 | AC3 | BB
def test_qa_spl_104_020_every_active_venue_staff_for_every_venue(app, client):
    extra = [f"00000000-0000-0000-0000-00000000109{n}" for n in range(3)]
    with Session(app.extensions["engine"]) as session:
        for account_id in extra:
            session.add(Account(id=account_id, display_name=f"Staff {account_id[-1]}"))
            session.add(AccountRole(account_id=account_id, role=Role.VENUE_STAFF.value))
        session.commit()
    event_id = make_event(app)
    first = booked(client, event_id, add_venue(app))
    second = booked(client, event_id, add_venue(app, "Garden Room"))
    grouped = keys_by_recipient(app)
    expected = [f"venue_booking_requested:{first}", f"venue_booking_requested:{second}"]
    assert set(grouped) == {STAFF_A, STAFF_B, *extra}
    assert all(keys == expected for keys in grouped.values())


# QA-SPL-104-021 | AC3 | BB
def test_qa_spl_104_021_requester_who_is_also_venue_staff_is_notified(app, client):
    give_role(app, COORDINATOR, Role.VENUE_STAFF)
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    withdraw(client, event_id, booking_id)
    listed = inbox(client, "coordinator")
    assert [n["message"].split(" for ")[0] for n in listed] == [
        "Venue booking request withdrawn",
        "Venue booking requested",
    ]
    assert {n["link"] for n in listed} == {QUEUE}


# QA-SPL-104-022 | AC3 | WB
def test_qa_spl_104_022_account_with_several_roles_gets_one_notice_per_action(app, client):
    give_role(app, STAFF_A, Role.TECHNICAL_SUPPORT_STAFF)
    give_role(app, STAFF_A, Role.EVENT_COORDINATOR)
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    withdraw(client, event_id, booking_id)
    assert keys_by_recipient(app)[STAFF_A] == [
        f"venue_booking_requested:{booking_id}",
        f"venue_booking_withdrawn:{booking_id}",
    ]


# QA-SPL-104-023 | AC3 | BB boundary
def test_qa_spl_104_023_no_active_venue_staff_still_allows_the_action(app, client):
    with Session(app.extensions["engine"]) as session:
        for account_id in (STAFF_A, STAFF_B):
            session.get(Account, account_id).is_active = False
        session.commit()
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    assert withdraw(client, event_id, booking_id).status_code == 200
    assert notices(app) == []


# QA-SPL-104-024 | AC3 | BB security
@pytest.mark.parametrize(
    "extra", [{"recipient_account_id": ORGANISER}, {"notify": [ORGANISER]}, {"recipients": []}]
)
def test_qa_spl_104_024_request_cannot_choose_recipients(app, client, extra):
    response = request_booking(client, make_event(app), add_venue(app), **extra)
    assert response.status_code == 400
    assert notices(app) == []


# QA-SPL-104-025 | AC3 | BB security
def test_qa_spl_104_025_each_staff_member_reads_and_marks_only_their_own(app, client):
    booked(client, make_event(app), add_venue(app))
    [own] = inbox(client, "staff-a")
    [other] = inbox(client, "staff-b")
    refused = client.post(f"/api/notifications/{other['id']}/read", headers=headers("staff-a"))
    assert refused.status_code == 404
    accepted = client.post(f"/api/notifications/{own['id']}/read", headers=headers("staff-a"))
    assert accepted.status_code == 200
    assert inbox(client, "staff-b")[0]["read"] is False


# QA-SPL-104-026 | AC3 | WB performance
def test_qa_spl_104_026_recipient_lookup_does_not_grow_with_staff(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)

    def selects_for_one_call():
        statements = []

        def record(_conn, _cursor, statement, *_):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = app.extensions["engine"]
        sqlalchemy_event.listen(engine, "before_cursor_execute", record)
        try:
            with Session(engine) as session:
                booking = session.get(VenueBooking, booking_id)
                event = session.get(EventRequest, event_id)
                statements.clear()
                add_venue_booking_notices(session, booking, event, kind="withdrawn")
                session.rollback()
        finally:
            sqlalchemy_event.remove(engine, "before_cursor_execute", record)
        return len(statements)

    with_two = selects_for_one_call()
    with Session(app.extensions["engine"]) as session:
        for n in range(4):
            account_id = f"00000000-0000-0000-0000-00000000108{n}"
            session.add(Account(id=account_id, display_name=f"Extra {n}"))
            session.add(AccountRole(account_id=account_id, role=Role.VENUE_STAFF.value))
        session.commit()
    assert selects_for_one_call() == with_two


# ---------------------------------------------------------------- AC4: one notice per booking


# QA-SPL-104-030 | AC4 | BB
def test_qa_spl_104_030_two_bookings_on_one_event_give_two_notices(app, client):
    event_id = make_event(app)
    booked(client, event_id, add_venue(app))
    booked(client, event_id, add_venue(app, "Garden Room", setup=0, turnaround=0))
    assert [n["message"] for n in inbox(client, "staff-a")] == [
        "Venue booking requested for Coastal Forum: Garden Room on Wed 14 Oct 2026, "
        "13:00–18:00 SGT; venue occupied PM.",
        SLOT_HARBOUR,
    ]


# QA-SPL-104-031 | AC4 | BB
def test_qa_spl_104_031_withdrawing_one_leaves_the_others_notices_alone(app, client):
    event_id = make_event(app)
    first = booked(client, event_id, add_venue(app))
    second = booked(client, event_id, add_venue(app, "Garden Room"))
    before = {n["id"]: n for n in inbox(client, "staff-a")}
    assert withdraw(client, event_id, first).status_code == 200
    after = inbox(client, "staff-a")
    assert len(after) == 3
    assert {n["id"]: n for n in after[1:]} == before
    assert "Harbour Hall" in after[0]["message"]
    assert keys_by_recipient(app)[STAFF_B] == [
        f"venue_booking_requested:{first}",
        f"venue_booking_requested:{second}",
        f"venue_booking_withdrawn:{first}",
    ]


# QA-SPL-104-032 | AC4 | BB
def test_qa_spl_104_032_reading_one_bookings_notice_leaves_the_other_unread(app, client):
    event_id = make_event(app)
    booked(client, event_id, add_venue(app))
    booked(client, event_id, add_venue(app, "Garden Room"))
    newest, older = inbox(client, "staff-a")
    client.post(f"/api/notifications/{older['id']}/read", headers=headers("staff-a"))
    newest_after, older_after = inbox(client, "staff-a")
    assert (newest_after["read"], older_after["read"]) == (False, True)


# QA-SPL-104-033 | AC4 | WB
def test_qa_spl_104_033_every_booking_and_action_has_its_own_key(app, client):
    event_id = make_event(app)
    ids = [booked(client, event_id, add_venue(app, name)) for name in ("A", "B", "C")]
    withdraw(client, event_id, ids[1])
    assert keys_by_recipient(app)[STAFF_A] == [
        *(f"venue_booking_requested:{booking_id}" for booking_id in ids),
        f"venue_booking_withdrawn:{ids[1]}",
    ]


# QA-SPL-104-034 | AC4 AC5 | BB
def test_qa_spl_104_034_exact_bookings_each_carry_their_own_times(exact, client):
    event_id = make_event(exact, start=time(9), end=time(17))
    booked_exact(client, event_id, add_venue(exact), "09:00", "11:00")
    booked_exact(
        client, event_id, add_venue(exact, "Garden Room", minutes=(15, 0)), "14:00", "16:30"
    )
    newest, older = (n["message"] for n in inbox(client, "staff-a"))
    assert newest.endswith(
        "Garden Room on Wed 14 Oct 2026, 14:00–16:30 SGT; "
        "venue occupied 13:45–16:30 including setup and turnaround."
    )
    assert older.endswith(
        "Harbour Hall on Wed 14 Oct 2026, 09:00–11:00 SGT; "
        "venue occupied 08:30–11:45 including setup and turnaround."
    )


# ---------------------------------------------------------------- AC5: booking details


# QA-SPL-104-040 | AC5 | BB
def test_qa_spl_104_040_slot_notice_names_every_detail(app, client):
    booked(client, make_event(app), add_venue(app))
    assert inbox(client, "staff-a")[0]["message"] == SLOT_HARBOUR


# QA-SPL-104-041 | AC5 | BB
def test_qa_spl_104_041_exact_notice_gives_times_and_occupancy(exact, client):
    booked_exact(client, make_event(exact, start=time(10), end=time(12)), add_venue(exact))
    assert inbox(client, "staff-a")[0]["message"] == EXACT_HARBOUR


# QA-SPL-104-042 | AC5 | BB boundary
def test_qa_spl_104_042_exact_zero_preparation_occupies_the_event_only(exact, client):
    event_id = make_event(exact, start=time(10), end=time(12))
    booked_exact(client, event_id, add_venue(exact, minutes=(0, 0)), "10:15", "11:45")
    assert inbox(client, "staff-a")[0]["message"].endswith(
        "on Wed 14 Oct 2026, 10:15–11:45 SGT; venue occupied 10:15–11:45 "
        "including setup and turnaround."
    )


# QA-SPL-104-043 | AC5 | BB boundary
@pytest.mark.parametrize(
    "start,end,minutes,occupied",
    [
        ("23:00", "23:45", (0, 30), "23:00–Thu 15 Oct 2026 00:15"),
        ("00:00", "00:30", (30, 0), "Tue 13 Oct 2026 23:30–00:30"),
    ],
)
def test_qa_spl_104_043_exact_occupancy_across_midnight_names_the_other_day(
    exact, client, start, end, minutes, occupied
):
    event_id = make_event(exact, start=time.fromisoformat(start), end=time.fromisoformat(end))
    booked_exact(client, event_id, add_venue(exact, minutes=minutes), start, end)
    assert inbox(client, "staff-a")[0]["message"].endswith(
        f"{start}–{end} SGT; venue occupied {occupied} including setup and turnaround."
    )


# QA-SPL-104-044 | AC5 | BB boundary
def test_qa_spl_104_044_slot_preparation_on_another_day_names_that_day(app, client):
    booked(client, make_event(app, start=time(8), end=time(11)), add_venue(app))
    assert inbox(client, "staff-a")[0]["message"].endswith(
        "on Wed 14 Oct 2026, 08:00–11:00 SGT; venue occupied AM "
        "(setup Night on Tue 13 Oct 2026, turnaround PM)."
    )


# QA-SPL-104-045 | AC5 | BB boundary
def test_qa_spl_104_045_slot_notice_without_preparation_and_across_slots(app, client):
    booked(
        client,
        make_event(app, start=time(10), end=time(20)),
        add_venue(app, setup=0, turnaround=0),
    )
    assert inbox(client, "staff-a")[0]["message"].endswith(
        "on Wed 14 Oct 2026, 10:00–20:00 SGT; venue occupied AM, PM, Night."
    )


# QA-SPL-104-046 | AC5 | BB
def test_qa_spl_104_046_times_come_from_the_booking_not_the_event(exact, client):
    event_id = make_event(exact, start=time(9), end=time(17))
    booking_id = booked_exact(client, event_id, add_venue(exact), "10:00", "11:45")
    with Session(exact.extensions["engine"]) as session:
        stored = session.get(EventRequest, event_id)
        stored.start_time, stored.end_time = time(8), time(18)
        session.commit()
    assert withdraw(client, event_id, booking_id).status_code == 200
    for notice in inbox(client, "staff-a"):
        assert "10:00–11:45 SGT; venue occupied 09:30–12:30" in notice["message"]


# QA-SPL-104-047 | AC5 | BB security
def test_qa_spl_104_047_notice_carries_no_personal_or_unrequested_details(app, client):
    booked(client, make_event(app), add_venue(app))
    message = inbox(client, "staff-a")[0]["message"]
    for leaked in ("Casey Lim", "Devon Lee", "theatre", "150", COORDINATOR, ORGANISER, "Projector"):
        assert leaked not in message


# QA-SPL-104-048 | AC5 | WB
def test_qa_spl_104_048_slot_mode_without_event_times_omits_them(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    with Session(app.extensions["engine"]) as session:
        booking = session.get(VenueBooking, booking_id)
        event = EventRequest(name="Untimed")
        add_venue_booking_notices(session, booking, event, kind="withdrawn")
        added = [row for row in session.new if isinstance(row, Notification)]
        session.rollback()
    assert {row.message for row in added} == {
        "Venue booking request withdrawn for Untimed: Harbour Hall on Wed 14 Oct 2026; "
        "venue occupied PM (setup AM, turnaround Night)."
    }


# ---------------------------------------------------------------- AC7: refused, failed, retried


# QA-SPL-104-060 | AC7 | BB negative
@pytest.mark.parametrize(
    "case", ["not-planning", "unassigned", "staff-role", "no-venue", "unsuitable", "same-venue"]
)
def test_qa_spl_104_060_refused_request_sends_nothing(app, client, case):
    event_id, venue_id = make_event(app), add_venue(app)
    if case == "not-planning":
        response = request_booking(client, make_event(app, "Later", status="approved"), venue_id)
    elif case == "unassigned":
        response = request_booking(client, event_id, venue_id, "other-coordinator")
    elif case == "staff-role":
        response = request_booking(client, event_id, venue_id, "staff-a")
    elif case == "no-venue":
        response = request_booking(client, event_id, 9999)
    elif case == "unsuitable":
        response = client.post(
            f"/api/event-requests/{event_id}/venue-bookings",
            json={"venue_id": venue_id, "layout": "banquet"},
            headers=headers("coordinator"),
        )
    else:
        booked(client, event_id, venue_id)
        response = request_booking(client, event_id, venue_id)
    assert 400 <= response.status_code < 500, response.json
    expected = 2 if case == "same-venue" else 0
    assert len(notices(app)) == expected


# QA-SPL-104-061 | AC7 | BB negative
def test_qa_spl_104_061_occupancy_conflict_rolls_back_without_a_notice(app, client):
    venue_id = add_venue(app)
    booked(client, make_event(app), venue_id)
    response = request_booking(client, make_event(app, "Rival Forum"), venue_id)
    assert response.status_code == 409
    assert "conflict" in response.json
    assert len(notices(app)) == 2


# QA-SPL-104-062 | AC7 | BB retry
def test_qa_spl_104_062_retried_withdrawal_adds_no_second_notice(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    assert withdraw(client, event_id, booking_id).status_code == 200
    assert withdraw(client, event_id, booking_id).status_code == 409
    assert keys_by_recipient(app)[STAFF_A].count(f"venue_booking_withdrawn:{booking_id}") == 1


# QA-SPL-104-063 | AC7 | BB retry
@pytest.mark.parametrize("mode", ["slot", "exact"])
def test_qa_spl_104_063_retried_request_adds_no_second_notice(app, client, mode):
    app.config["EXACT_VENUE_TIMING_ENABLED"] = mode == "exact"
    event_id, venue_id = make_event(app, start=time(10), end=time(12)), add_venue(app)
    send = request_exact if mode == "exact" else request_booking
    assert send(client, event_id, venue_id).status_code == 201
    assert send(client, event_id, venue_id).status_code == 409
    assert len(notices(app, recipient=STAFF_A)) == 1


def _then_fail(real):
    def wrapper(session, *args, **kwargs):
        real(session, *args, **kwargs)
        session.flush()
        raise RuntimeError("injected failure after the notice was written")

    return wrapper


# QA-SPL-104-064 | AC7 | WB failure injection
@pytest.mark.parametrize("mode", ["slot", "exact"])
def test_qa_spl_104_064_failed_request_leaves_no_booking_and_no_notice(
    app, client, monkeypatch, mode
):
    app.config["EXACT_VENUE_TIMING_ENABLED"] = mode == "exact"
    event_id, venue_id = make_event(app, start=time(10), end=time(12)), add_venue(app)
    monkeypatch.setattr(
        requests_module,
        "add_venue_booking_notices",
        _then_fail(requests_module.add_venue_booking_notices),
    )
    send = request_exact if mode == "exact" else request_booking
    with pytest.raises(RuntimeError):
        send(client, event_id, venue_id)
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(VenueBooking)) == 0
    assert notices(app) == []


# QA-SPL-104-065 | AC7 | WB failure injection
def test_qa_spl_104_065_failed_withdrawal_leaves_the_request_and_no_notice(
    app, client, monkeypatch
):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    monkeypatch.setattr(
        withdrawals_module,
        "add_venue_booking_notices",
        _then_fail(withdrawals_module.add_venue_booking_notices),
    )
    with pytest.raises(RuntimeError):
        withdraw(client, event_id, booking_id)
    with Session(app.extensions["engine"]) as session:
        booking = session.get(VenueBooking, booking_id)
        assert (booking.status, booking.withdrawn_at) == ("requested", None)
    assert not [key for _, key, _ in notices(app) if key.startswith("venue_booking_withdrawn")]


# QA-SPL-104-066 | AC7 | WB
def test_qa_spl_104_066_the_same_notice_cannot_be_stored_twice(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    with Session(app.extensions["engine"]) as session:
        booking = session.get(VenueBooking, booking_id)
        event = session.get(EventRequest, event_id)
        add_venue_booking_notices(session, booking, event, kind="requested")
        with pytest.raises(IntegrityError):
            session.flush()
    assert len(notices(app)) == 2


# QA-SPL-104-067 | AC2 AC7 | BB boundary
def test_qa_spl_104_067_withdrawing_a_request_stored_without_timing_still_works(app, client):
    # SPL-83 claims and seeded fixtures can hold a Requested booking with no date or slots;
    # the notice must not stop it being withdrawn.
    event_id, venue_id = make_event(app), add_venue(app)
    with Session(app.extensions["engine"]) as session:
        booking = VenueBooking(event_request_id=event_id, venue_id=venue_id, status="requested")
        session.add(booking)
        session.commit()
        booking_id = booking.id
    response = withdraw(client, event_id, booking_id)
    assert response.status_code == 200, response.json
    assert [message for _, _, message in notices(app, recipient=STAFF_A)] == [
        "Venue booking request withdrawn for Coastal Forum: Harbour Hall."
    ]


# ---------------------------------------------------------------- Link to the booking queue


# QA-SPL-104-080 | AC1 AC2 | BB
def test_qa_spl_104_080_every_notice_opens_the_booking_queue(app, client):
    event_id, venue_id = make_event(app), add_venue(app)
    booking_id = booked(client, event_id, venue_id)
    withdraw(client, event_id, booking_id)
    assert {n["link"] for n in inbox(client, "staff-a")} == {QUEUE}


# QA-SPL-104-081 | AC1 AC2 | WB
@pytest.mark.parametrize(
    "key,link",
    [
        ("venue_booking_requested:1", QUEUE),
        ("venue_booking_withdrawn:1", QUEUE),
        ("xvenue_booking_requested:1", "/workspace/assigned-events/7"),
        ("organiser_venue_booking:1", "/workspace/organisation-events/7"),
        ("technical_added:1", "/workspace/equipment-review-queue"),
        ("coordinator_assigned:1", "/workspace/assigned-events/7"),
    ],
)
def test_qa_spl_104_081_link_follows_the_notice_kind(key, link):
    assert _event_link(Notification(dedupe_key=key, event_request_id=7)) == link


# QA-SPL-104-082 | AC1 | BB security
def test_qa_spl_104_082_the_queue_lists_the_request_for_venue_staff_only(app, client):
    booking_id = booked(client, make_event(app), add_venue(app))
    response = client.get("/api/venue-bookings/pending", headers=headers("staff-a"))
    assert response.status_code == 200
    assert booking_id in {row["id"] for row in response.json["requests"]}
    assert (
        client.get("/api/venue-bookings/pending", headers=headers("organiser")).status_code == 403
    )
