"""QA acceptance coverage for SPL-119: organisers view event registrations."""

from datetime import date, datetime, time, timezone

import pytest
from app import create_app
from app.models import (
    Account,
    AccountRole,
    Base,
    EventRegistration,
    EventRequest,
    Organisation,
    Role,
)
from sqlalchemy.orm import Session

ORGANISER = "00000000-0000-0000-0000-000000001191"
COLLEAGUE = "00000000-0000-0000-0000-000000001192"
OUTSIDER = "00000000-0000-0000-0000-000000001193"
ATTENDEE = "00000000-0000-0000-0000-000000001194"
SECOND_ATTENDEE = "00000000-0000-0000-0000-000000001195"
TOKENS = {
    "organiser": ORGANISER,
    "colleague": COLLEAGUE,
    "outsider": OUTSIDER,
    "attendee": ATTENDEE,
}
OPEN = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
CLOSE = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
REGISTERED = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": f"sqlite:///{tmp_path}/spl119.db",
            "IDENTITY_VERIFIER": TOKENS.__getitem__,
        }
    )
    engine = app.extensions["engine"]
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        own = Organisation(name="SPL-119 client")
        other = Organisation(name="SPL-119 other client")
        session.add_all([own, other])
        session.flush()
        session.add_all(
            [
                Account(id=ORGANISER, display_name="Olivia Organiser", organisation_id=own.id),
                Account(id=COLLEAGUE, display_name="Colin Colleague", organisation_id=own.id),
                Account(id=OUTSIDER, display_name="Oscar Outsider", organisation_id=other.id),
                Account(id=ATTENDEE, display_name="Avery Attendee"),
                Account(id=SECOND_ATTENDEE, display_name="Blake Attendee"),
                AccountRole(account_id=ORGANISER, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=COLLEAGUE, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=OUTSIDER, role=Role.EVENT_ORGANISER.value),
                AccountRole(account_id=ATTENDEE, role=Role.ATTENDEE.value),
            ]
        )
        session.commit()
        app.config.update(OWN_ORG=own.id, OTHER_ORG=other.id)
    yield app
    engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def headers(token="organiser"):
    return {"Authorization": f"Bearer {token}"}


def make_event(app, *, organisation="own", status="submitted", enabled=True, capacity=100):
    with Session(app.extensions["engine"]) as session:
        event = EventRequest(
            organiser_account_id=ORGANISER if organisation == "own" else OUTSIDER,
            organisation_id=app.config["OWN_ORG" if organisation == "own" else "OTHER_ORG"],
            name=f"SPL-119 {organisation} {status}",
            purpose="Measure expected turnout",
            proposed_date=date(2026, 11, 20),
            start_time=time(14),
            end_time=time(17),
            expected_attendance=100,
            status=status,
            registration_opens_at=OPEN if enabled else None,
            registration_closes_at=CLOSE if enabled else None,
            registration_capacity=capacity if enabled else None,
        )
        session.add(event)
        session.commit()
        return event.id


def add_registration(
    app,
    event_id,
    *,
    attendee=ATTENDEE,
    status="registered",
    name="Avery Attendee",
    email="avery@example.test",
    contact="+65 9000 1191",
    requirements="Step-free access",
    registered_at=REGISTERED,
):
    with Session(app.extensions["engine"]) as session:
        row = EventRegistration(
            event_request_id=event_id,
            attendee_account_id=attendee,
            status=status,
            name=name,
            email=email,
            contact_number=contact,
            special_requirements=requirements,
            registered_at=registered_at,
            withdrawn_at=(registered_at if status == "withdrawn" else None),
        )
        session.add(row)
        session.commit()
        return row.id


def get_list(client, event_id, token="organiser"):
    return client.get(f"/api/organisation/events/{event_id}/registrations", headers=headers(token))


# QA-SPL-119-001 | AC1 | BB happy path
def test_qa_spl_119_001_own_submitted_event_is_visible(app, client):
    event_id = make_event(app)
    response = get_list(client, event_id)
    assert response.status_code == 200
    assert response.json["registration_list"]["enabled"] is True


# QA-SPL-119-002 | AC1 | BB organisation scope
def test_qa_spl_119_002_same_organisation_colleague_can_view(app, client):
    event_id = make_event(app)
    assert get_list(client, event_id, "colleague").status_code == 200


# QA-SPL-119-003 | AC1 | BB security
def test_qa_spl_119_003_other_organisation_is_refused_without_disclosure(app, client):
    event_id = make_event(app, organisation="other")
    response = get_list(client, event_id)
    assert response.status_code == 404
    assert response.json == {"error": "Event not found."}


# QA-SPL-119-004 | AC1 | BB negative
def test_qa_spl_119_004_draft_in_own_organisation_is_refused(app, client):
    event_id = make_event(app, status="draft")
    response = get_list(client, event_id)
    assert response.status_code == 404
    assert response.json == {"error": "Event not found."}


# QA-SPL-119-005 | AC1 | BB role security
def test_qa_spl_119_005_attendee_role_is_refused(app, client):
    event_id = make_event(app)
    assert get_list(client, event_id, "attendee").status_code == 403


# QA-SPL-119-006 | AC2 | BB happy path
def test_qa_spl_119_006_count_capacity_and_all_attendee_fields_are_returned(app, client):
    event_id = make_event(app, capacity=100)
    registration_id = add_registration(app, event_id)
    result = get_list(client, event_id).json["registration_list"]
    assert (result["registered_count"], result["capacity"]) == (1, 100)
    assert result["registered"] == [
        {
            "id": registration_id,
            "name": "Avery Attendee",
            "email": "avery@example.test",
            "contact_number": "+65 9000 1191",
            "special_requirements": "Step-free access",
        }
    ]


# QA-SPL-119-007 | AC2 | BB zero boundary
def test_qa_spl_119_007_zero_registrations_keeps_capacity_visible(app, client):
    event_id = make_event(app, capacity=1)
    result = get_list(client, event_id).json["registration_list"]
    assert (result["registered_count"], result["capacity"], result["registered"]) == (0, 1, [])


# QA-SPL-119-008 | AC2 | BB nullable field boundary
def test_qa_spl_119_008_missing_special_requirements_stays_null(app, client):
    event_id = make_event(app)
    add_registration(app, event_id, requirements=None)
    attendee = get_list(client, event_id).json["registration_list"]["registered"][0]
    assert attendee["special_requirements"] is None


# QA-SPL-119-009 | AC2 | WB deterministic order
def test_qa_spl_119_009_equal_signup_times_use_id_as_stable_tie_break(app, client):
    event_id = make_event(app)
    first = add_registration(app, event_id, name="Avery", email="a@example.test")
    second = add_registration(
        app,
        event_id,
        attendee=SECOND_ATTENDEE,
        name="Blake",
        email="b@example.test",
    )
    attendees = get_list(client, event_id).json["registration_list"]["registered"]
    assert [row["id"] for row in attendees] == [first, second]


# QA-SPL-119-010 | AC2 | BB security allowlist
def test_qa_spl_119_010_attendee_payload_has_only_approved_fields(app, client):
    event_id = make_event(app)
    add_registration(app, event_id)
    attendee = get_list(client, event_id).json["registration_list"]["registered"][0]
    assert set(attendee) == {"id", "name", "email", "contact_number", "special_requirements"}


# QA-SPL-119-011 | AC3 | BB happy path
def test_qa_spl_119_011_registered_and_withdrawn_are_separate(app, client):
    event_id = make_event(app)
    add_registration(app, event_id, name="Current")
    add_registration(app, event_id, attendee=SECOND_ATTENDEE, status="withdrawn", name="Former")
    result = get_list(client, event_id).json["registration_list"]
    assert [row["name"] for row in result["registered"]] == ["Current"]
    assert [row["name"] for row in result["withdrawn"]] == ["Former"]


# QA-SPL-119-012 | AC3 | WB count rule
def test_qa_spl_119_012_withdrawn_rows_do_not_inflate_registered_count(app, client):
    event_id = make_event(app)
    add_registration(app, event_id, status="withdrawn")
    result = get_list(client, event_id).json["registration_list"]
    assert result["registered_count"] == 0
    assert len(result["withdrawn"]) == 1


# QA-SPL-119-013 | AC3 | BB withdrawn-only boundary
def test_qa_spl_119_013_withdrawn_only_event_has_empty_current_list(app, client):
    event_id = make_event(app)
    add_registration(app, event_id, status="withdrawn")
    result = get_list(client, event_id).json["registration_list"]
    assert result["registered"] == []
    assert len(result["withdrawn"]) == 1


# QA-SPL-119-014 | AC3 | BB empty boundary
def test_qa_spl_119_014_no_withdrawals_returns_an_explicit_empty_section(app, client):
    event_id = make_event(app)
    add_registration(app, event_id)
    assert get_list(client, event_id).json["registration_list"]["withdrawn"] == []


# QA-SPL-119-015 | AC3 | WB deterministic order
def test_qa_spl_119_015_withdrawn_rows_keep_signup_order(app, client):
    event_id = make_event(app)
    first = add_registration(app, event_id, status="withdrawn", name="First")
    second = add_registration(
        app,
        event_id,
        attendee=SECOND_ATTENDEE,
        status="withdrawn",
        name="Second",
    )
    withdrawn = get_list(client, event_id).json["registration_list"]["withdrawn"]
    assert [row["id"] for row in withdrawn] == [first, second]


# QA-SPL-119-016 | AC4 | BB happy path
def test_qa_spl_119_016_disabled_registration_is_explicit(app, client):
    event_id = make_event(app, enabled=False)
    result = get_list(client, event_id).json["registration_list"]
    assert result == {
        "enabled": False,
        "capacity": None,
        "registered_count": 0,
        "registered": [],
        "withdrawn": [],
    }


# QA-SPL-119-017 | AC4 | BB contrast boundary
def test_qa_spl_119_017_enabled_empty_is_distinct_from_disabled(app, client):
    enabled = get_list(client, make_event(app, enabled=True)).json["registration_list"]
    disabled = get_list(client, make_event(app, enabled=False)).json["registration_list"]
    assert enabled["enabled"] is True and enabled["registered"] == []
    assert disabled["enabled"] is False and disabled["registered"] == []


# QA-SPL-119-018 | AC4 | WB privacy boundary
def test_qa_spl_119_018_disabled_event_does_not_leak_historical_rows(app, client):
    event_id = make_event(app, enabled=False)
    add_registration(app, event_id)
    result = get_list(client, event_id).json["registration_list"]
    assert result["registered_count"] == 0
    assert result["registered"] == [] and result["withdrawn"] == []


# QA-SPL-119-019 | AC4 | BB contract boundary
def test_qa_spl_119_019_disabled_event_has_no_invented_capacity(app, client):
    event_id = make_event(app, enabled=False)
    assert get_list(client, event_id).json["registration_list"]["capacity"] is None


# QA-SPL-119-021 | AC5 | BB response contract
def test_qa_spl_119_021_list_response_contains_no_export_metadata(app, client):
    event_id = make_event(app)
    result = get_list(client, event_id).json["registration_list"]
    assert set(result) == {"enabled", "capacity", "registered_count", "registered", "withdrawn"}


# QA-SPL-119-022 | AC5 | BB negative method
def test_qa_spl_119_022_list_endpoint_does_not_accept_export_post(app, client):
    event_id = make_event(app)
    response = client.post(f"/api/organisation/events/{event_id}/registrations", headers=headers())
    # Unknown or unsupported API operations remain default-deny rather than disclosing routing.
    assert response.status_code == 403
    assert response.json == {"error": "Access denied."}


# QA-SPL-119-023 | AC5 | BB query boundary
def test_qa_spl_119_023_format_query_does_not_turn_list_into_download(app, client):
    event_id = make_event(app)
    response = client.get(
        f"/api/organisation/events/{event_id}/registrations?format=csv", headers=headers()
    )
    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.headers.get("Content-Disposition") is None


# QA-SPL-119-031 | AC1-AC5 | WB rolling-deploy capability
def test_qa_spl_119_031_event_detail_advertises_registration_list_capability(app, client):
    event_id = make_event(app)
    response = client.get(f"/api/organisation/events/{event_id}", headers=headers())
    assert response.status_code == 200
    assert response.headers["X-ConnectSphere-Registration-List"] == "available"
