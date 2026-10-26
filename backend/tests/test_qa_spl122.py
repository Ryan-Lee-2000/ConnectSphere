"""SPL-122 QA cases: Technical Support is notified of equipment requirement changes.

Each case carries its QA-SPL-122-NNN identifier (see the QA-SPL-122 Confluence page). The fixture
is SPL-91's: a fresh SQLite database with one Planning event, its assigned coordinator, one active
Technical Support account ("technical") and two catalogue types. Extra Technical Support accounts
are added per case. Concurrency and real-transaction rollback are in test_qa_spl122_postgres.py.
"""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
import test_equipment_requirement_changes as spl91
from app import equipment_requirements as requirements_module
from app import notifications as notifications_module
from app.models import (
    Account,
    AccountRole,
    EquipmentRequirement,
    EquipmentRequirementChange,
    EventRequest,
    Notification,
    Role,
)
from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def app(tmp_path, monkeypatch):
    fixture = spl91.app.__wrapped__(tmp_path, monkeypatch)
    application = next(fixture)
    try:
        # SPL-123 review: cancellation notices require the organiser's real client membership.
        with Session(application.extensions["engine"]) as session:
            session.get(Account, IDENTITIES["organiser"]).organisation_id = 1
            session.commit()
        yield application
    finally:
        next(fixture, None)


client = spl91.client
event_id = spl91.event_id
IDENTITIES = spl91.IDENTITIES
EVENT_DATE = spl91.EVENT_DATE
EVENT_NAME = "Community Leadership Forum"
QUEUE = "/workspace/equipment-review-queue"


def lines_url(event):
    return f"/api/event-requests/{event}/equipment-requirements"


def add(client, event, identity="coordinator", **overrides):
    body = {
        "equipment_type_id": 1,
        "quantity": 4,
        "notes": "Panel.",
        "required_start_date": EVENT_DATE.isoformat(),
        "required_end_date": EVENT_DATE.isoformat(),
        "essentiality": "undecided",
        **overrides,
    }
    return client.post(lines_url(event), json=body, headers=spl91.headers(identity))


def cancel(client, event, identity="coordinator", reason="Venue flooded."):
    body = {} if reason is None else {"reason": reason}
    return client.post(
        f"/api/event-requests/{event}/cancel", json=body, headers=spl91.headers(identity)
    )


def notices(app, who=None):
    with Session(app.extensions["engine"]) as session:
        query = select(Notification).order_by(Notification.id)
        if who is not None:
            query = query.where(Notification.recipient_account_id == IDENTITIES[who])
        return [
            (row.recipient_account_id, row.dedupe_key, row.message)
            for row in session.scalars(query)
        ]


def count(app, who=None):
    return len(notices(app, who))


def add_technical(app, monkeypatch, label, *, active=True, also=None):
    """Another Technical Support account, signed in with token ``label``."""

    account_id = str(uuid.uuid4())
    monkeypatch.setitem(IDENTITIES, label, account_id)
    with Session(app.extensions["engine"]) as session:
        session.add(Account(id=account_id, display_name=f"Person {label}", is_active=active))
        session.add(AccountRole(account_id=account_id, role=Role.TECHNICAL_SUPPORT_STAFF.value))
        if also is not None:
            session.add(AccountRole(account_id=account_id, role=also.value))
        session.commit()
    return account_id


def unmapped_line(app, event):
    with Session(app.extensions["engine"]) as session:
        line = EquipmentRequirement(
            event_request_id=event,
            equipment_type="Projector (organiser text)",
            quantity=1,
            status="unmapped",
        )
        session.add(line)
        session.commit()
        return line.id


def set_status(app, event, status):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event).status = status
        session.commit()


def inbox(client, who="technical"):
    response = client.get("/api/notifications", headers=spl91.headers(who))
    assert response.status_code == 200, response.json
    return response.json


# AC1 - recorded, changed (equipment, quantity, dates or technical notes) or removed


# QA-SPL-122-001 | AC1 | BB
def test_qa_spl_122_001_adding_a_catalogue_line_notifies_once(app, client, event_id):
    response = add(client, event_id)
    assert response.status_code == 201, response.json
    line = response.json["requirement"]["id"]
    assert notices(app, "technical") == [
        (
            IDENTITIES["technical"],
            f"technical_requirement_recorded:line-{line}",
            f"Equipment requirement added to {EVENT_NAME}: Wireless Microphone × 4.",
        )
    ]
    assert count(app) == 1


@pytest.mark.parametrize(
    ("values", "label", "item"),
    [
        ({"quantity": 5}, "quantity", "Wireless Microphone × 5"),
        ({"equipment_type_id": 2}, "equipment type", "Portable Speaker × 4"),
        ({"notes": "Two lapel, two handheld."}, "technical notes", "Wireless Microphone × 4"),
    ],
)
# QA-SPL-122-002 | AC1 | BB
def test_qa_spl_122_002_each_reviewed_field_change_notifies_once(
    app, client, event_id, values, label, item
):
    line = spl91.add_line(app, event_id)
    response = spl91.change(client, event_id, line, json=values)
    assert response.status_code == 200, response.json
    entry = spl91.change_rows(app, line)[-1]
    assert notices(app, "technical") == [
        (
            IDENTITIES["technical"],
            f"technical_requirement_changed:{entry.id}",
            f"Equipment requirement changed on {EVENT_NAME}: {item} ({label}).",
        )
    ]


# QA-SPL-122-009 | AC1 | BB
def test_qa_spl_122_009_moving_the_required_dates_notifies_once(app, client, event_id):
    # Requirement dates must equal the event's one recorded date, so they change only after the
    # event moves (SPL-109): the coordinator then moves the line onto the new date.
    line = spl91.add_line(app, event_id)
    moved = EVENT_DATE + timedelta(days=7)
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).proposed_date = moved
        session.commit()
    response = spl91.change(
        client,
        event_id,
        line,
        json={"required_start_date": moved.isoformat(), "required_end_date": moved.isoformat()},
    )
    assert response.status_code == 200, response.json
    entry = spl91.change_rows(app, line)[-1]
    assert notices(app, "technical") == [
        (
            IDENTITIES["technical"],
            f"technical_requirement_changed:{entry.id}",
            f"Equipment requirement changed on {EVENT_NAME}: Wireless Microphone × 4 "
            "(required start date and required end date).",
        )
    ]


@pytest.mark.parametrize("units", [0, 2, 4])
# QA-SPL-122-003 | AC1 | BB
def test_qa_spl_122_003_removal_notifies_once_whatever_it_held(app, client, event_id, units):
    line = spl91.add_line(app, event_id)
    if units:
        spl91.reserve(app, line, units)
    response = spl91.remove(client, event_id, line)
    assert response.status_code == 200, response.json
    entry = spl91.change_rows(app, line)[-1]
    assert entry.action == "removed"
    assert notices(app, "technical") == [
        (
            IDENTITIES["technical"],
            f"technical_requirement_removed:{entry.id}",
            f"Equipment requirement removed from {EVENT_NAME}: Wireless Microphone × 4.",
        )
    ]


# QA-SPL-122-004 | AC1 | BB
def test_qa_spl_122_004_identical_and_criticality_only_saves_send_nothing(app, client, event_id):
    line = spl91.add_line(app, event_id)
    same = spl91.change(client, event_id, line, json={"quantity": 4, "notes": "Panel."})
    assert same.status_code == 200, same.json
    critical = spl91.change(
        client,
        event_id,
        line,
        json={
            "essentiality": "essential",
            "consulted_technical_support_account_id": IDENTITIES["technical"],
            "essentiality_decision_note": "Needed for the panel.",
        },
    )
    assert critical.status_code == 200, critical.json
    with Session(app.extensions["engine"]) as session:
        assert session.get(EquipmentRequirement, line).essentiality == "essential"
    assert count(app) == 0
    # The route does notify when a reviewed field changes, so silence above is not a dead route.
    assert spl91.change(client, event_id, line, json={"quantity": 6}).status_code == 200
    assert count(app, "technical") == 1


# QA-SPL-122-005 | AC1 | BB
def test_qa_spl_122_005_unmapped_lines_notify_only_once_mapped(app, client, event_id):
    removed = unmapped_line(app, event_id)
    assert spl91.remove(client, event_id, removed).status_code == 200
    assert count(app) == 0

    line = unmapped_line(app, event_id)
    mapped = spl91.change(
        client,
        event_id,
        line,
        json={
            "equipment_type_id": 1,
            "quantity": 2,
            "required_start_date": EVENT_DATE.isoformat(),
            "required_end_date": EVENT_DATE.isoformat(),
        },
    )
    assert mapped.status_code == 200, mapped.json
    entry = spl91.change_rows(app, line)[-1]
    assert notices(app, "technical") == [
        (
            IDENTITIES["technical"],
            f"technical_requirement_recorded:{entry.id}",
            f"Equipment requirement added to {EVENT_NAME}: Wireless Microphone × 2.",
        )
    ]
    assert spl91.change(client, event_id, line, json={"quantity": 3}).status_code == 200
    assert notices(app, "technical")[-1][2].endswith("Wireless Microphone × 3 (quantity).")


@pytest.mark.parametrize(
    ("values", "labels"),
    [
        ({"quantity": 5, "notes": "Spare batteries."}, "quantity and technical notes"),
        (
            {"equipment_type_id": 2, "quantity": 3, "notes": "Spare batteries."},
            "equipment type, quantity and technical notes",
        ),
    ],
)
# QA-SPL-122-006 | AC1 | WB
def test_qa_spl_122_006_one_save_of_several_fields_is_one_notice(
    app, client, event_id, values, labels
):
    line = spl91.add_line(app, event_id)
    assert spl91.change(client, event_id, line, json=values).status_code == 200
    assert len(spl91.change_rows(app, line)) == 1
    [(_, _, message)] = notices(app, "technical")
    assert message.endswith(f"({labels}).")


def significant_change(client, event, values, **extra):
    path = f"/api/event-requests/assigned/{event}/significant-changes"
    headers = spl91.headers()
    preview = client.post(path + "/preview", json={"values": values, **extra}, headers=headers)
    assert preview.status_code == 200, preview.json
    token = preview.json["preview_token"]
    return client.patch(
        path, json={"values": values, "preview_token": token, **extra}, headers=headers
    )


# QA-SPL-122-007 | AC1 | BB
def test_qa_spl_122_007_confirmed_event_edits_through_spl_109(app, client, event_id):
    line = spl91.add_line(app, event_id, status="reserved")
    spl91.reserve(app, line, 4)
    set_status(app, event_id, "confirmed")

    # A direct change to the line is a reviewed-field change: one notice.
    direct = significant_change(client, event_id, {"quantity": 5}, equipment_requirement_id=line)
    assert direct.status_code == 200, direct.json
    assert [message for _, _, message in notices(app, "technical")] == [
        f"Equipment requirement changed on {EVENT_NAME}: Wireless Microphone × 5 (quantity)."
    ]

    # Moving the event only flags the line for review; the line's own values are unchanged.
    set_status(app, event_id, "confirmed")
    moved = significant_change(
        client, event_id, {"proposed_date": (EVENT_DATE + timedelta(days=7)).isoformat()}
    )
    assert moved.status_code == 200, moved.json
    assert count(app, "technical") == 1


@pytest.mark.parametrize(
    ("type_id", "action", "old", "new", "expected"),
    [
        (None, "removed", {"status": "requested"}, {"status": "removed"}, None),
        (None, "changed", {}, {"quantity": 3}, None),
        (1, "removed", {"status": "requested"}, {"status": "removed"}, "requirement_removed"),
        (1, "changed", {"status": "reserved"}, {"status": "review_required"}, None),
        (1, "changed", {"essentiality": "undecided"}, {"essentiality": "essential"}, None),
        (
            1,
            "changed",
            {"equipment_type_id": None},
            {"equipment_type_id": 1},
            "requirement_recorded",
        ),
        (1, "changed", {"equipment_type_id": 2}, {"equipment_type_id": 1}, "requirement_changed"),
        (1, "changed", {"quantity": 4}, {"quantity": 5}, "requirement_changed"),
    ],
)
# QA-SPL-122-008 | AC1 | WB
def test_qa_spl_122_008_change_classification(monkeypatch, type_id, action, old, new, expected):
    calls = []
    monkeypatch.setattr(
        requirements_module,
        "_notify_technical_support",
        lambda session, line, kind, source_id, detail="": calls.append((kind, source_id)),
    )
    line = SimpleNamespace(equipment_type_id=type_id)
    entry = SimpleNamespace(id=9, action=action, old_values=old, new_values=new)
    requirements_module._notify_technical_support_of_change(None, line, entry)
    assert calls == ([] if expected is None else [(expected, 9)])


# AC2 - an event holding reservations is cancelled


# QA-SPL-122-020 | AC2 | BB
def test_qa_spl_122_020_cancelling_an_event_holding_units_notifies_once(app, client, event_id):
    line = spl91.add_line(app, event_id, status="reserved")
    spl91.reserve(app, line, 4)
    response = cancel(client, event_id)
    assert response.status_code == 200, response.json
    assert notices(app, "technical") == [
        (
            IDENTITIES["technical"],
            f"technical_event_cancelled:{event_id}",
            f"{EVENT_NAME} was cancelled. 4 reserved equipment unit(s) were released.",
        )
    ]


# QA-SPL-122-021 | AC2 | BB
def test_qa_spl_122_021_cancelling_an_event_holding_nothing_sends_technical_support_nothing(
    app, client, event_id
):
    spl91.add_line(app, event_id)  # Requested: no units held
    unmapped_line(app, event_id)
    response = cancel(client, event_id)
    assert response.status_code == 200, response.json
    assert count(app, "technical") == 0
    [(recipient, key, message)] = notices(app)
    assert recipient == IDENTITIES["organiser"]
    assert key.startswith("organiser_event_cancelled:")
    assert message == f"{EVENT_NAME} has been cancelled. Reason: Venue flooded."


# QA-SPL-122-022 | AC2 | BB
def test_qa_spl_122_022_several_lines_are_one_notice_with_the_total(app, client, event_id):
    first = spl91.add_line(app, event_id, quantity=4)
    second = spl91.add_line(app, event_id, quantity=2, type_id=2)
    spl91.reserve(app, first, 4)
    spl91.reserve(app, second, 2)
    assert cancel(client, event_id).status_code == 200
    [(_, _, message)] = notices(app, "technical")
    assert message == f"{EVENT_NAME} was cancelled. 6 reserved equipment unit(s) were released."


# QA-SPL-122-023 | AC2 | BB
def test_qa_spl_122_023_only_units_still_held_are_counted(app, client, event_id):
    line = spl91.add_line(app, event_id, quantity=4)
    spl91.reserve(app, line, 4)
    released = client.post(
        f"/api/equipment-requirements/{line}/releases",
        json={"quantity": 1, "reason": "One microphone is needed elsewhere."},
        headers=spl91.headers("technical"),
    )
    assert released.status_code in (200, 201), released.json
    assert count(app) == 0
    assert cancel(client, event_id).status_code == 200
    [(_, _, message)] = notices(app, "technical")
    assert message == f"{EVENT_NAME} was cancelled. 3 reserved equipment unit(s) were released."


# QA-SPL-122-024 | AC2 | BB
def test_qa_spl_122_024_an_event_with_no_lines_sends_technical_support_nothing(
    app, client, event_id
):
    assert cancel(client, event_id).status_code == 200
    assert count(app, "technical") == 0
    [(recipient, key, message)] = notices(app)
    assert recipient == IDENTITIES["organiser"]
    assert key.startswith("organiser_event_cancelled:")
    assert message == f"{EVENT_NAME} has been cancelled. Reason: Venue flooded."


# QA-SPL-122-025 | AC2 | BB
def test_qa_spl_122_025_a_confirmed_event_holding_units_notifies(app, client, event_id):
    line = spl91.add_line(app, event_id, status="reserved")
    spl91.reserve(app, line, 2)
    set_status(app, event_id, "confirmed")
    assert cancel(client, event_id).status_code == 200
    assert [message for _, _, message in notices(app, "technical")] == [
        f"{EVENT_NAME} was cancelled. 2 reserved equipment unit(s) were released."
    ]


# AC3 - all active Technical Support Staff


# QA-SPL-122-030 | AC3 | BB
def test_qa_spl_122_030_every_active_account_and_no_inactive_one(
    app, client, event_id, monkeypatch
):
    add_technical(app, monkeypatch, "technical-2")
    add_technical(app, monkeypatch, "technical-3")
    add_technical(app, monkeypatch, "technical-off", active=False)

    line = add(client, event_id).json["requirement"]["id"]
    assert spl91.change(client, event_id, line, json={"quantity": 5}).status_code == 200
    spl91.reserve(app, line, 5)
    other = add(client, event_id, equipment_type_id=2, quantity=1).json["requirement"]["id"]
    assert spl91.remove(client, event_id, other).status_code == 200
    assert cancel(client, event_id).status_code == 200

    for who in ("technical", "technical-2", "technical-3"):
        kinds = [key.split(":")[0] for _, key, _ in notices(app, who)]
        assert kinds == [
            "technical_requirement_recorded",
            "technical_requirement_changed",
            "technical_requirement_recorded",
            "technical_requirement_removed",
            "technical_event_cancelled",
        ], who
    assert count(app, "technical-off") == 0


# QA-SPL-122-031 | AC3 | BB
def test_qa_spl_122_031_other_roles_receive_nothing(app, client, event_id):
    line = add(client, event_id).json["requirement"]["id"]
    spl91.reserve(app, line, 4)
    assert cancel(client, event_id).status_code == 200
    recipients = {recipient for recipient, _, _ in notices(app)}
    assert recipients == {IDENTITIES["technical"], IDENTITIES["organiser"]}
    assert all(key.startswith("technical_") for _, key, _ in notices(app, "technical"))
    [(_, key, message)] = notices(app, "organiser")
    assert key.startswith("organiser_event_cancelled:")
    assert message == f"{EVENT_NAME} has been cancelled. Reason: Venue flooded."
    for who in ("coordinator", "other-coordinator", "venue", "manager"):
        assert inbox(client, who)["notifications"] == [], who


# QA-SPL-122-032 | AC3 | WB
def test_qa_spl_122_032_an_account_with_two_roles_gets_one_notice(
    app, client, event_id, monkeypatch
):
    add_technical(app, monkeypatch, "dual", also=Role.EVENT_COORDINATOR)
    assert add(client, event_id).status_code == 201
    assert count(app, "dual") == 1
    assert count(app, "technical") == 1


# QA-SPL-122-033 | AC3 | BB
def test_qa_spl_122_033_with_no_active_account_the_action_still_succeeds(app, client, event_id):
    with Session(app.extensions["engine"]) as session:
        session.get(Account, IDENTITIES["technical"]).is_active = False
        session.commit()
    response = add(client, event_id)
    assert response.status_code == 201, response.json
    line = response.json["requirement"]["id"]
    assert spl91.remove(client, event_id, line).status_code == 200
    assert count(app) == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"recipient_account_id": IDENTITIES["organiser"]},
        {"notify": [IDENTITIES["organiser"]]},
        {"recipients": [IDENTITIES["coordinator"]]},
    ],
)
# QA-SPL-122-034 | AC3 | BB security
def test_qa_spl_122_034_the_request_cannot_choose_recipients(app, client, event_id, extra):
    response = add(client, event_id, **extra)
    if response.status_code == 201:
        assert {recipient for recipient, _, _ in notices(app)} == {IDENTITIES["technical"]}
    else:
        assert response.status_code == 400, response.json
        assert count(app) == 0
    assert count(app, "organiser") == 0
    assert count(app, "coordinator") == 0


# QA-SPL-122-035 | AC3 | BB
def test_qa_spl_122_035_each_account_reads_its_own_copy(app, client, event_id, monkeypatch):
    add_technical(app, monkeypatch, "technical-2")
    assert add(client, event_id).status_code == 201
    first, second = inbox(client, "technical"), inbox(client, "technical-2")
    assert first["unread_count"] == second["unread_count"] == 1
    mine = second["notifications"][0]["id"]
    read = client.post(f"/api/notifications/{mine}/read", headers=spl91.headers("technical-2"))
    assert read.status_code == 200
    assert inbox(client, "technical")["unread_count"] == 1
    assert inbox(client, "technical-2")["unread_count"] == 0
    # Another account's copy is not found, not readable.
    theirs = first["notifications"][0]["id"]
    refused = client.post(f"/api/notifications/{theirs}/read", headers=spl91.headers("technical-2"))
    assert refused.status_code == 404


# AC4 - refused or failed actions send nothing; retries add no duplicate


@pytest.mark.parametrize(
    ("identity", "overrides", "status", "expected"),
    [
        ("coordinator", {"quantity": 0}, None, 400),
        ("coordinator", {"equipment_type_id": 999}, None, (400, 404)),
        ("technical", {}, None, 403),
        ("other-coordinator", {}, None, (403, 404)),
        ("coordinator", {}, "confirmed", 409),
    ],
)
# QA-SPL-122-040 | AC4 | BB
def test_qa_spl_122_040_a_refused_addition_sends_nothing(
    app, client, event_id, identity, overrides, status, expected
):
    if status:
        set_status(app, event_id, status)
    response = add(client, event_id, identity=identity, **overrides)
    allowed = expected if isinstance(expected, tuple) else (expected,)
    assert response.status_code in allowed, response.json
    assert count(app) == 0
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(EquipmentRequirement)) == 0


# QA-SPL-122-041 | AC4 | BB
def test_qa_spl_122_041_refused_changes_and_removals_send_nothing(app, client, event_id):
    line = spl91.add_line(app, event_id)
    assert spl91.change(client, event_id, line, json={"quantity": 0}).status_code == 400
    assert (
        spl91.change(client, event_id, line, "technical", json={"quantity": 6}).status_code == 403
    )
    assert spl91.change(
        client, event_id, line, "other-coordinator", json={"quantity": 6}
    ).status_code in (403, 404)
    assert spl91.remove(client, event_id, line, "other-coordinator").status_code in (403, 404)
    set_status(app, event_id, "confirmed")
    assert spl91.change(client, event_id, line, json={"quantity": 6}).status_code == 409
    assert spl91.remove(client, event_id, line).status_code == 409
    assert count(app) == 0
    assert spl91.change_rows(app, line) == []


# QA-SPL-122-042 | AC4 | BB
def test_qa_spl_122_042_retrying_a_change_or_removal_adds_no_duplicate(app, client, event_id):
    line = spl91.add_line(app, event_id)
    for _ in range(2):
        assert spl91.change(client, event_id, line, json={"quantity": 5}).status_code == 200
    assert count(app, "technical") == 1
    assert spl91.remove(client, event_id, line).status_code == 200
    retry = spl91.remove(client, event_id, line)
    assert retry.status_code == 409, retry.json
    assert count(app, "technical") == 2


# QA-SPL-122-043 | AC4 | BB
def test_qa_spl_122_043_refused_or_repeated_cancellation_sends_no_extra_notice(
    app, client, event_id
):
    line = spl91.add_line(app, event_id, status="reserved")
    spl91.reserve(app, line, 4)
    assert cancel(client, event_id, reason=None).status_code == 400
    assert cancel(client, event_id, identity="technical").status_code == 403
    assert cancel(client, event_id, identity="other-coordinator").status_code == 404
    assert count(app) == 0
    assert cancel(client, event_id).status_code == 200
    again = cancel(client, event_id, reason="Clicked twice.")
    assert again.status_code == 409, again.json
    assert count(app, "technical") == 1


def fail_after(module, name, monkeypatch):
    real = getattr(module, name)

    def wrapped(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("Injected failure after the notice was written")

    monkeypatch.setattr(module, name, wrapped)


# QA-SPL-122-044 | AC4 | WB
def test_qa_spl_122_044_a_failed_addition_or_change_leaves_no_notice(
    app, client, event_id, monkeypatch
):
    line = spl91.add_line(app, event_id)
    fail_after(requirements_module, "add_technical_support_notices", monkeypatch)
    with pytest.raises(RuntimeError, match="Injected"):
        add(client, event_id, equipment_type_id=2)
    with pytest.raises(RuntimeError, match="Injected"):
        spl91.change(client, event_id, line, json={"quantity": 5})
    with pytest.raises(RuntimeError, match="Injected"):
        spl91.remove(client, event_id, line)
    assert count(app) == 0
    assert spl91.change_rows(app, line) == []
    assert spl91.line_state(app, line)[:2] == ("requested", 4)
    with Session(app.extensions["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(EquipmentRequirement)) == 1


# QA-SPL-122-045 | AC4 | WB
def test_qa_spl_122_045_a_failed_cancellation_leaves_no_notice(app, client, event_id, monkeypatch):
    line = spl91.add_line(app, event_id, status="reserved")
    spl91.reserve(app, line, 4)
    fail_after(notifications_module, "add_technical_support_notices", monkeypatch)
    with pytest.raises(RuntimeError, match="Injected"):
        cancel(client, event_id)
    assert count(app) == 0
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status == "planning"
    assert spl91.held(app, line) == 4


# QA-SPL-122-046 | AC4 | WB
def test_qa_spl_122_046_the_database_refuses_a_second_copy(app, event_id):
    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        for _ in range(2):
            notifications_module.add_technical_support_notices(
                session, event, kind="requirement_removed", source_id=7, message="Removed."
            )
        with pytest.raises(IntegrityError):
            session.commit()
    assert count(app) == 0


# AC5 - each notice opens the Equipment review queue


# QA-SPL-122-050 | AC5 | BB
def test_qa_spl_122_050_every_kind_links_to_the_review_queue(app, client, event_id):
    line = add(client, event_id).json["requirement"]["id"]
    assert spl91.change(client, event_id, line, json={"quantity": 5}).status_code == 200
    other = add(client, event_id, equipment_type_id=2).json["requirement"]["id"]
    assert spl91.remove(client, event_id, other).status_code == 200
    spl91.reserve(app, line, 5)
    assert cancel(client, event_id).status_code == 200
    items = inbox(client)["notifications"]
    assert len(items) == 5
    assert {item["link"] for item in items} == {QUEUE}
    assert {item["event"]["id"] for item in items} == {event_id}


@pytest.mark.parametrize(
    ("key", "link"),
    [
        ("technical_requirement_recorded:line-3", QUEUE),
        ("technical_event_cancelled:7", QUEUE),
        ("organiser_coordinator_assigned:7", "/workspace/organisation-events/7"),
        ("coordinator_assigned:7", "/workspace/assigned-events/7"),
        ("technical:7", "/workspace/assigned-events/7"),
        ("technicalx_requirement:7", "/workspace/assigned-events/7"),
    ],
)
# QA-SPL-122-051 | AC5 | WB
def test_qa_spl_122_051_only_technical_keys_change_the_link(key, link):
    notice = SimpleNamespace(dedupe_key=key, event_request_id=7)
    assert notifications_module._event_link(notice) == link


# QA-SPL-122-052 | AC5 | BB
def test_qa_spl_122_052_technical_support_can_open_the_queue_it_is_sent_to(app, client, event_id):
    line = add(client, event_id).json["requirement"]["id"]
    opened = client.get("/api/equipment-review-queue", headers=spl91.headers("technical"))
    assert opened.status_code == 200, opened.json
    assert line in [
        item["id"] for item in next(v for v in opened.json.values() if isinstance(v, list))
    ]
    refused = client.get("/api/equipment-review-queue", headers=spl91.headers("coordinator"))
    assert refused.status_code == 403


# Cross-cutting


# QA-SPL-122-060 | AC3 | WB performance
def test_qa_spl_122_060_one_recipient_query_whatever_the_team_size(
    app, client, event_id, monkeypatch
):
    statements = []

    def record(_conn, _cursor, statement, *_args):
        if "account_roles" in statement and "notifications" not in statement:
            statements.append(statement)

    engine = app.extensions["engine"]
    sa_event.listen(engine, "before_cursor_execute", record)
    try:
        assert add(client, event_id).status_code == 201
        small = len(statements)
        for number in range(5):
            add_technical(app, monkeypatch, f"technical-{number}")
        statements.clear()
        assert add(client, event_id, equipment_type_id=2).status_code == 201
        assert len(statements) == small
    finally:
        sa_event.remove(engine, "before_cursor_execute", record)
    assert count(app) == 1 + 6


# QA-SPL-122-061 | AC1 | BB security
def test_qa_spl_122_061_messages_carry_no_personal_details_or_free_text(app, client, event_id):
    line = add(client, event_id, notes="Call Devon on 9123 4567.").json["requirement"]["id"]
    assert (
        spl91.change(
            client, event_id, line, json={"notes": "Ask person organiser at home."}
        ).status_code
        == 200
    )
    with Session(app.extensions["engine"]) as session:
        names = [account.display_name for account in session.scalars(select(Account))]
        assert session.scalar(select(func.count()).select_from(EquipmentRequirementChange)) == 1
    for _, _, message in notices(app):
        assert "9123" not in message and "at home" not in message
        assert not any(name in message for name in names)
        for account_id in IDENTITIES.values():
            assert account_id not in message


# Review round 1 (2026-10-22, Ryan on PR #96): a retried addition must not notify twice.

REQUEST = "5b0f0c3e-2a8e-4f7e-9b61-3c2d4e5f6a7b"


def lines(app, event):
    with Session(app.extensions["engine"]) as session:
        return session.scalars(
            select(EquipmentRequirement.id)
            .where(EquipmentRequirement.event_request_id == event)
            .order_by(EquipmentRequirement.id)
        ).all()


# QA-SPL-122-047 | AC4 | BB
def test_qa_spl_122_047_a_retried_addition_returns_the_same_line_and_notifies_once(
    app, client, event_id
):
    first = add(client, event_id, request_id=REQUEST)
    assert first.status_code == 201, first.json
    retry = add(client, event_id, request_id=REQUEST)
    assert retry.status_code == 200, retry.json
    assert retry.json["requirement"]["id"] == first.json["requirement"]["id"]
    assert lines(app, event_id) == [first.json["requirement"]["id"]]
    assert count(app, "technical") == 1

    # A new request id is a deliberate second addition; no id keeps the old behaviour.
    second = add(client, event_id, request_id=str(uuid.uuid4()))
    assert second.status_code == 201, second.json
    third = add(client, event_id)
    assert third.status_code == 201, third.json
    assert len(lines(app, event_id)) == 3
    assert count(app, "technical") == 3


@pytest.mark.parametrize("value", ["", "not-a-uuid", 7, None, True, "x" * 37])
# QA-SPL-122-048 | AC4 | BB negative
def test_qa_spl_122_048_a_malformed_request_id_is_refused(app, client, event_id, value):
    response = add(client, event_id, request_id=value)
    assert response.status_code == 400, response.json
    assert lines(app, event_id) == []
    assert count(app) == 0


# QA-SPL-122-049 | AC4 | BB security
def test_qa_spl_122_049_the_request_id_belongs_to_one_event_and_coordinator(app, client, event_id):
    other_event = spl91.add_event(app, name="Second Forum")
    assert add(client, event_id, request_id=REQUEST).status_code == 201
    elsewhere = add(client, other_event, request_id=REQUEST)
    assert elsewhere.status_code == 201, elsewhere.json
    assert len(lines(app, other_event)) == 1
    replay = add(client, event_id, identity="other-coordinator", request_id=REQUEST)
    assert replay.status_code == 404, replay.json
    assert count(app, "technical") == 2
