"""SPL-121 QA cases, equipment side: Technical Support decisions (AC2) and flags (AC4), with AC5.

Each case carries its QA-SPL-121-NNN identifier (see the QA-SPL-121 Confluence page). The fixture
is SPL-91's: a Planning event assigned to the coordinator, one active Technical Support account
and two catalogue types (Wireless Microphone, 10 in stock; Portable Speaker, 6). Lines are added
directly; every action under test goes through its real route.
"""

import pytest
import test_equipment_requirement_changes as spl91
from app import equipment_availability as availability_module
from app import equipment_requirement_unavailability as unavailable_module
from app import equipment_unavailability as units_module
from app.models import EquipmentRequirement, EquipmentReservation, Notification
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

app = spl91.app
client = spl91.client
event_id = spl91.event_id
IDENTITIES = spl91.IDENTITIES
EVENT = "Community Leadership Forum"
TECH = spl91.headers("technical")


def notices(app, who="coordinator"):
    with Session(app.extensions["engine"]) as session:
        return [
            (row.dedupe_key, row.message)
            for row in session.scalars(
                select(Notification)
                .where(
                    Notification.recipient_account_id == IDENTITIES[who],
                    Notification.dedupe_key.like("arrangement_%"),
                )
                .order_by(Notification.id)
            )
        ]


def kinds(app, who="coordinator"):
    return [key.split(":")[0] for key, _ in notices(app, who)]


def reserve(client, line, quantity, token="technical"):
    return client.post(
        f"/api/equipment-requirements/{line}/reservations",
        json={"quantity": quantity},
        headers=spl91.headers(token),
    )


def mark_unavailable(client, line, token="technical", **body):
    body = body or {"reason": "Supplier recall", "alternative_suggestion": "Use wired units"}
    return client.post(
        f"/api/equipment-requirements/{line}/mark-unavailable",
        json=body,
        headers=spl91.headers(token),
    )


def units(client, type_id, quantity, action="unavailable-units", token="technical", **extra):
    return client.post(
        f"/api/equipment-types/{type_id}/{action}",
        json={"quantity": quantity, "reason": "Water damage in store", **extra},
        headers=spl91.headers(token),
    )


def status(app, line):
    with Session(app.extensions["engine"]) as session:
        return session.get(EquipmentRequirement, line).status


def reservation_count(app):
    with Session(app.extensions["engine"]) as session:
        return session.scalar(select(func.count()).select_from(EquipmentReservation))


# AC2 - reserves or partially reserves a line, or marks a requirement Unavailable


# QA-SPL-121-020 | AC2 | BB
def test_qa_spl_121_020_a_partial_reservation_notifies_with_the_units_held(app, client, event_id):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, 2).status_code == 201
    [(key, message)] = notices(app)
    assert key.startswith("arrangement_equipment_reserved:")
    assert message == (
        f"Equipment partially reserved for {EVENT}: Wireless Microphone × 4 (2 of 4 units)."
    )


# QA-SPL-121-021 | AC2 | BB
def test_qa_spl_121_021_a_full_reservation_and_a_completing_one_each_notify(app, client, event_id):
    whole = spl91.add_line(app, event_id, quantity=3, type_id=2)
    assert reserve(client, whole, 3).status_code == 201
    split = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, split, 1).status_code == 201
    assert reserve(client, split, 3).status_code == 201
    messages = [message for _, message in notices(app)]
    assert messages == [
        f"Equipment reserved for {EVENT}: Portable Speaker × 3 (3 of 3 units).",
        f"Equipment partially reserved for {EVENT}: Wireless Microphone × 4 (1 of 4 units).",
        f"Equipment reserved for {EVENT}: Wireless Microphone × 4 (4 of 4 units).",
    ]
    assert len({key for key, _ in notices(app)}) == 3


# QA-SPL-121-022 | AC2 | BB
def test_qa_spl_121_022_marking_a_line_unavailable_notifies_without_the_reason(
    app, client, event_id
):
    line = spl91.add_line(app, event_id, quantity=2, type_id=2)
    assert mark_unavailable(client, line).status_code == 201
    [(key, message)] = notices(app)
    assert key.startswith("arrangement_equipment_unavailable:")
    assert message == f"Equipment marked unavailable for {EVENT}: Portable Speaker × 2."
    assert "recall" not in message and "wired" not in message


@pytest.mark.parametrize(
    ("quantity", "token", "expected"),
    [
        (5, "technical", 409),
        (0, "technical", 400),
        ("2", "technical", 400),
        (2, "coordinator", 403),
        (2, "other-coordinator", 403),
    ],
)
# QA-SPL-121-023 | AC2 AC5 | BB negative
def test_qa_spl_121_023_a_refused_reservation_sends_nothing(
    app, client, event_id, quantity, token, expected
):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, quantity, token=token).status_code == expected
    assert notices(app) == []
    assert reservation_count(app) == 0


# QA-SPL-121-024 | AC2 AC5 | BB negative
def test_qa_spl_121_024_a_refused_mark_unavailable_sends_nothing(app, client, event_id):
    held = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, held, 4).status_code == 201
    assert mark_unavailable(client, held).status_code == 409
    line = spl91.add_line(app, event_id, quantity=2, type_id=2)
    assert mark_unavailable(client, line, reason=" ").status_code == 400
    assert mark_unavailable(client, line, token="coordinator").status_code == 403
    assert mark_unavailable(client, line).status_code == 201
    assert mark_unavailable(client, line).status_code == 409
    assert kinds(app) == ["arrangement_equipment_reserved", "arrangement_equipment_unavailable"]


# QA-SPL-121-025 | AC2 | BB boundary
def test_qa_spl_121_025_restoring_or_revalidating_a_line_sends_nothing(app, client, event_id):
    line = spl91.add_line(app, event_id, quantity=2, type_id=2)
    assert mark_unavailable(client, line).status_code == 201
    restored = client.post(f"/api/equipment-requirements/{line}/restore-requested", headers=TECH)
    assert restored.status_code in (200, 201), restored.json
    held = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, held, 4).status_code == 201
    assert units(client, 1, 8).status_code == 201
    assert units(client, 1, 8, action="restored-units").status_code == 201
    revalidated = client.post(
        f"/api/equipment-requirements/{held}/revalidate-reservation", headers=TECH
    )
    assert revalidated.status_code == 200, revalidated.json
    assert kinds(app) == [
        "arrangement_equipment_unavailable",
        "arrangement_equipment_reserved",
        "arrangement_equipment_flagged",
    ]


def fail_after(module, monkeypatch):
    real = module.add_arrangement_notice

    def wrapped(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("Injected failure after the notice was written")

    monkeypatch.setattr(module, "add_arrangement_notice", wrapped)


# QA-SPL-121-026 | AC2 AC5 | WB failure injection
def test_qa_spl_121_026_a_failed_reservation_or_marking_leaves_no_notice(
    app, client, event_id, monkeypatch
):
    held = spl91.add_line(app, event_id, quantity=4)
    line = spl91.add_line(app, event_id, quantity=2, type_id=2)
    fail_after(availability_module, monkeypatch)
    fail_after(unavailable_module, monkeypatch)
    with pytest.raises(RuntimeError, match="Injected"):
        reserve(client, held, 2)
    with pytest.raises(RuntimeError, match="Injected"):
        mark_unavailable(client, line)
    assert notices(app) == []
    assert reservation_count(app) == 0
    assert status(app, held) == status(app, line) == "requested"


# QA-SPL-121-027 | AC2 AC4 | BB boundary
def test_qa_spl_121_027_reserving_a_review_required_line_notifies_the_reservation(
    app, client, event_id
):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, 2).status_code == 201
    assert units(client, 1, 9).status_code == 201
    assert status(app, line) == "review_required"
    assert units(client, 1, 9, action="restored-units").status_code == 201
    assert reserve(client, line, 2).status_code == 201
    assert kinds(app) == [
        "arrangement_equipment_reserved",
        "arrangement_equipment_flagged",
        "arrangement_equipment_reserved",
    ]
    assert notices(app)[-1][1].endswith("(4 of 4 units).")


# AC4 - recording units as unavailable flags one of my lines Review Required


# QA-SPL-121-040 | AC4 | BB
def test_qa_spl_121_040_units_out_of_service_notify_the_flagged_line_once(app, client, event_id):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, 4).status_code == 201
    response = units(client, 1, 8)
    assert response.status_code == 201, response.json
    assert response.json["flagged_requirement_ids"] == [line]
    key, message = notices(app)[-1]
    assert key.startswith("arrangement_equipment_flagged:") and key.endswith(f"-line-{line}")
    assert message == (
        f"Equipment for {EVENT} needs review: Wireless Microphone × 4; units became unavailable."
    )
    assert "Water damage" not in message


# QA-SPL-121-041 | AC4 | BB negative
def test_qa_spl_121_041_units_out_of_service_without_a_shortfall_send_nothing(
    app, client, event_id
):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, 4).status_code == 201
    response = units(client, 1, 6)
    assert response.status_code == 201
    assert response.json["flagged_requirement_ids"] == []
    assert kinds(app) == ["arrangement_equipment_reserved"]


# QA-SPL-121-042 | AC4 AC5 | BB retry
def test_qa_spl_121_042_an_already_flagged_line_is_not_announced_again(app, client, event_id):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, 4).status_code == 201
    assert units(client, 1, 8).status_code == 201
    second = units(client, 1, 1)
    assert second.status_code == 201
    assert second.json["flagged_requirement_ids"] == [line]
    assert kinds(app) == ["arrangement_equipment_reserved", "arrangement_equipment_flagged"]


# QA-SPL-121-043 | AC4 AC5 | BB
def test_qa_spl_121_043_each_coordinator_hears_only_of_their_own_line(app, client, event_id):
    other_event = spl91.add_event(app, coordinator="other-coordinator", name="Second Forum")
    mine = spl91.add_line(app, event_id, quantity=4)
    theirs = spl91.add_line(app, other_event, quantity=4)
    assert reserve(client, mine, 4).status_code == 201
    assert reserve(client, theirs, 4).status_code == 201
    response = units(client, 1, 8)
    assert sorted(response.json["flagged_requirement_ids"]) == sorted([mine, theirs])
    assert notices(app)[-1][0].endswith(f"-line-{mine}")
    assert notices(app, "other-coordinator")[-1][0].endswith(f"-line-{theirs}")
    assert "Second Forum" in notices(app, "other-coordinator")[-1][1]
    assert all("Second Forum" not in message for _, message in notices(app))


@pytest.mark.parametrize(
    ("quantity", "token", "expected"),
    [(11, "technical", 400), (0, "technical", 400), (8, "coordinator", 403)],
)
# QA-SPL-121-044 | AC4 AC5 | BB negative
def test_qa_spl_121_044_a_refused_marking_sends_nothing(
    app, client, event_id, quantity, token, expected
):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, 4).status_code == 201
    assert units(client, 1, quantity, token=token).status_code == expected
    assert status(app, line) == "reserved"
    assert kinds(app) == ["arrangement_equipment_reserved"]


# QA-SPL-121-045 | AC4 AC5 | WB failure injection
def test_qa_spl_121_045_a_failed_marking_leaves_no_notice_and_no_flag(
    app, client, event_id, monkeypatch
):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, 4).status_code == 201
    fail_after(units_module, monkeypatch)
    with pytest.raises(RuntimeError, match="Injected"):
        units(client, 1, 8)
    assert status(app, line) == "reserved"
    assert kinds(app) == ["arrangement_equipment_reserved"]


# QA-SPL-121-046 | AC4 | BB boundary
def test_qa_spl_121_046_a_line_flagged_for_another_reason_is_not_announced(app, client, event_id):
    line = spl91.add_line(app, event_id, quantity=4)
    assert reserve(client, line, 2).status_code == 201
    # SPL-91: the coordinator's own change puts the line in Review Required first.
    assert spl91.change(client, event_id, line, json={"quantity": 5}).status_code == 200
    assert status(app, line) == "review_required"
    assert units(client, 1, 9).status_code == 201
    assert kinds(app) == ["arrangement_equipment_reserved"]


# AC5 - only the assigned coordinator; refusals and retries


# QA-SPL-121-050 | AC5 | BB
def test_qa_spl_121_050_no_other_account_hears_of_equipment_decisions(app, client, event_id):
    held = spl91.add_line(app, event_id, quantity=4)
    line = spl91.add_line(app, event_id, quantity=2, type_id=2)
    assert reserve(client, held, 4).status_code == 201
    assert mark_unavailable(client, line).status_code == 201
    assert units(client, 1, 8).status_code == 201
    assert len(notices(app)) == 3
    for who in ("other-coordinator", "technical", "organiser", "venue", "manager"):
        assert notices(app, who) == [], who


# QA-SPL-121-053 | AC5 | WB
def test_qa_spl_121_053_the_database_refuses_a_second_copy(app, event_id):
    from app.models import EventRequest
    from app.notifications import add_arrangement_notice

    with Session(app.extensions["engine"]) as session:
        event = session.get(EventRequest, event_id)
        for _ in range(2):
            add_arrangement_notice(
                session, event, kind="equipment_reserved", source_id=7, message="Reserved."
            )
        with pytest.raises(IntegrityError):
            session.commit()
    assert notices(app) == []
