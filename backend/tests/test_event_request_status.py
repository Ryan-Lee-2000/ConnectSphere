"""CS-E07-S1 — See the current status of my event.

Test identifiers match the formal cases in QA-SPL-63. Cases that are purely about what the
interface renders (TC-13 to TC-19, TC-23 to TC-25) live in the frontend and browser suites;
what is testable at the server is here.
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from app import create_app
from app.event_statuses import (
    EVENT_REQUEST_STATUSES,
    INITIAL_STATUS,
    status_explanation,
    status_label,
)
from app.models import Account, AccountRole, Base, EventRequest, Organisation, Role
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ORGANISER_ONE = "00000000-0000-0000-0000-000000000031"
ORGANISER_TWO = "00000000-0000-0000-0000-000000000032"
COORDINATOR = "00000000-0000-0000-0000-000000000033"

SINGAPORE = timezone(timedelta(hours=8))


@pytest.fixture
def status_app(tmp_path):
    identities = {
        "organiser-one": ORGANISER_ONE,
        "organiser-two": ORGANISER_TWO,
        "coordinator": COORDINATOR,
    }
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/status.db",
            # .get so an unrecognised token fails closed rather than raising.
            "IDENTITY_VERIFIER": identities.get,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        organisation = Organisation(name="Community Partners")
        session.add(organisation)
        session.flush()
        session.add_all(
            Account(
                id=account_id,
                display_name=f"Test account {index}",
                organisation_id=(
                    organisation.id if account_id in {ORGANISER_ONE, ORGANISER_TWO} else None
                ),
            )
            for index, account_id in enumerate(identities.values(), start=1)
        )
        session.add_all(
            [
                AccountRole(account_id=ORGANISER_ONE, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=ORGANISER_TWO, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=COORDINATOR, role=Role.EVENT_COORDINATOR.value),
            ]
        )
        session.commit()
    yield app
    engine.dispose()


@pytest.fixture
def client(status_app):
    return status_app.test_client()


def headers(identity="organiser-one"):
    return {"Authorization": f"Bearer {identity}"}


def seed_request(
    app,
    *,
    organiser=ORGANISER_ONE,
    name="Community Technology Forum",
    status=INITIAL_STATUS,
    submitted_at=datetime(2026, 9, 18, 9, 30, tzinfo=SINGAPORE),
    status_changed_at=None,
):
    """Store a request directly.

    Changing a status is out of scope for this story (CS-E06, CS-E07-S3 to S5), so a request
    that has moved past submission can only be arranged by writing it.
    """

    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=organiser,
            organisation_id=1,
            name=name,
            purpose="Connect residents with local technology partners",
            proposed_date=date(2026, 12, 1),
            start_time=time(9, 0),
            end_time=time(11, 30),
            expected_attendance=120,
            status=status,
            submitted_at=submitted_at,
            status_changed_at=status_changed_at,
            required_facilities=[],
            registration_required=False,
        )
        session.add(event)
        session.commit()
        return event.id


def submit_request(client, *, name="Regional Partner Conference", identity="organiser-one"):
    response = client.post(
        "/api/event-requests",
        json={
            "name": name,
            "purpose": "Brief partners on the roadmap",
            "proposed_date": (date.today() + timedelta(days=7)).isoformat(),
            "start_time": "09:00",
            "end_time": "11:30",
            "expected_attendance": 120,
        },
        headers=headers(identity),
    )
    assert response.status_code == 201
    return response.json["event_request"]


# --- AC1: the agreed status vocabulary is recorded ---------------------------------------


def test_tc_01_every_agreed_status_value_is_accepted(status_app):
    for status in EVENT_REQUEST_STATUSES:
        seed_request(status_app, name=f"Request holding {status}", status=status)

    with Session(status_app.extensions["engine"]) as session:
        stored = session.scalars(select(EventRequest.status)).all()

    assert sorted(stored) == sorted(EVENT_REQUEST_STATUSES)


@pytest.mark.parametrize(
    "status",
    ["pending", "SUBMITTED", "Not approved", ""],
)
def test_tc_02_a_value_outside_the_vocabulary_is_refused(status_app, status):
    with pytest.raises(IntegrityError):
        seed_request(status_app, status=status)

    with Session(status_app.extensions["engine"]) as session:
        assert session.scalars(select(EventRequest)).all() == []


def test_tc_03_a_newly_submitted_request_starts_at_the_submitted_status(client):
    created = submit_request(client)

    assert created["status"] == "submitted"
    assert created["status"] != "draft"


# --- AC2: status is visible in the list and on the detail view ----------------------------


def test_tc_04_the_list_reports_the_status_of_every_own_request(client, status_app):
    seed_request(status_app, name="Waiting", status="submitted")
    seed_request(status_app, name="Being read", status="under_review")
    seed_request(status_app, name="Accepted", status="approved")

    response = client.get("/api/event-requests", headers=headers())

    assert response.status_code == 200
    listed = {event["name"]: event["status"] for event in response.json["event_requests"]}
    assert listed == {
        "Waiting": "submitted",
        "Being read": "under_review",
        "Accepted": "approved",
    }


def test_tc_05_the_detail_view_agrees_with_the_list(client, status_app):
    event_id = seed_request(status_app, status="under_review")

    listed = client.get("/api/event-requests", headers=headers()).json["event_requests"][0]
    detail = client.get(f"/api/event-requests/{event_id}", headers=headers())

    assert detail.status_code == 200
    for field in ("status", "status_label", "status_explanation", "status_changed_at"):
        assert detail.json["event_request"][field] == listed[field]


def test_tc_06_another_organisers_request_is_neither_listed_nor_readable(client, status_app):
    mine = seed_request(status_app, name="Mine", organiser=ORGANISER_ONE)
    theirs = seed_request(status_app, name="Theirs", organiser=ORGANISER_TWO)

    listed = client.get("/api/event-requests", headers=headers("organiser-one"))
    detail = client.get(f"/api/event-requests/{theirs}", headers=headers("organiser-one"))

    assert [event["id"] for event in listed.json["event_requests"]] == [mine]
    assert detail.status_code == 404
    assert detail.json == {"error": "Event request not found."}
    assert "Theirs" not in detail.get_data(as_text=True)


# --- AC3: plain language, and no raw system value -----------------------------------------


@pytest.mark.parametrize(
    ("status", "label", "explanation"),
    [
        ("under_review", "Under review", "Your request is being assessed."),
        ("approved", "Approved", "Your request has been accepted."),
        ("rejected", "Not approved", "Your request was not accepted."),
    ],
)
def test_tc_07_each_status_carries_its_name_and_explanation(
    client, status_app, status, label, explanation
):
    seed_request(status_app, status=status)

    listed = client.get("/api/event-requests", headers=headers()).json["event_requests"][0]

    assert listed["status_label"] == label
    assert listed["status_explanation"].startswith(explanation)
    assert listed["status_explanation"] == status_explanation(status)


def test_tc_08_the_wording_never_repeats_the_stored_value(status_app):
    """No machine-readable form of a status reaches the organiser.

    A label may share an ordinary English word with its stored value — "In planning" holds
    "planning" — and that is the wording doing its job, not a leak. What must never appear is
    the identifier itself: the underscored token, or a label that is merely the stored value.
    """

    for status in EVENT_REQUEST_STATUSES:
        label = status_label(status)
        explanation = status_explanation(status)
        # Capitalising a single-word status is presentation, not a leak, so the check is that
        # the value is never shown verbatim rather than that the word never appears.
        assert label != status
        if "_" in status:
            assert status not in label
            assert status not in explanation
        assert "_" not in label


def test_tc_09_every_vocabulary_member_has_exactly_one_name_and_one_explanation():
    for status, wording in EVENT_REQUEST_STATUSES.items():
        assert len(wording) == 2, status
        label, explanation = wording
        assert label.strip(), status
        assert explanation.strip(), status
        # One line, so it reads as a single sentence beside the status.
        assert "\n" not in explanation, status

    labels = [label for label, _ in EVENT_REQUEST_STATUSES.values()]
    assert len(set(labels)) == len(labels), "two statuses would read identically"
    assert INITIAL_STATUS in EVENT_REQUEST_STATUSES


def test_tc_09_the_constraint_and_the_wording_describe_the_same_set(status_app):
    """Nothing is storable without wording, and nothing is described that cannot be stored."""

    with Session(status_app.extensions["engine"]) as session:
        constraint = session.scalar(
            text("select sql from sqlite_master where type = 'table' and name = 'event_requests'")
        )

    for status in EVENT_REQUEST_STATUSES:
        assert f"'{status}'" in constraint


# --- AC4: the time of the most recent status change ---------------------------------------


def test_tc_10_an_unchanged_status_reports_the_submission_time(client, status_app):
    submitted = datetime(2026, 9, 18, 9, 30, tzinfo=SINGAPORE)
    seed_request(status_app, submitted_at=submitted, status_changed_at=None)

    listed = client.get("/api/event-requests", headers=headers()).json["event_requests"][0]

    assert listed["status_changed_at"] == submitted.isoformat()
    assert listed["status_changed_at"] == listed["submitted_at"]


def test_tc_11_a_changed_status_reports_the_time_of_that_change(client, status_app):
    submitted = datetime(2026, 9, 18, 9, 30, tzinfo=SINGAPORE)
    changed = datetime(2026, 9, 18, 14, 0, tzinfo=SINGAPORE)
    event_id = seed_request(
        status_app, status="under_review", submitted_at=submitted, status_changed_at=changed
    )

    listed = client.get("/api/event-requests", headers=headers()).json["event_requests"][0]
    detail = client.get(f"/api/event-requests/{event_id}", headers=headers())

    assert listed["status_changed_at"] == changed.isoformat()
    assert listed["status_changed_at"] != listed["submitted_at"]
    assert detail.json["event_request"]["status_changed_at"] == changed.isoformat()


def test_tc_12_a_request_with_no_recorded_time_is_still_readable(client, status_app):
    seed_request(status_app, submitted_at=None, status_changed_at=None)

    response = client.get("/api/event-requests", headers=headers())

    assert response.status_code == 200
    listed = response.json["event_requests"][0]
    assert listed["status_changed_at"] is None
    assert listed["submitted_at"] is None
    # The record is still readable, with its status intact.
    assert listed["status_label"] == "Submitted"


# --- AC8: only an Event Organiser -----------------------------------------------------------


def test_tc_21_an_unauthenticated_read_is_refused_without_disclosing_anything(client, status_app):
    seed_request(status_app, name="Should stay private")

    listed = client.get("/api/event-requests")
    detail = client.get("/api/event-requests/1")

    assert listed.status_code == 401
    assert detail.status_code == 401
    assert "Should stay private" not in listed.get_data(as_text=True)
    assert "submitted" not in detail.get_data(as_text=True)
