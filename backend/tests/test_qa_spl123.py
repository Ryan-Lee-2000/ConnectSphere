"""SPL-123 acceptance contracts for organiser confirmation-state notices."""

import pytest
import test_event_cancellation as cancellation
import test_event_confirmation as confirmation
import test_qa_spl112 as decisions
from app import notifications
from app.models import (
    Account,
    AccountRole,
    EventChangeRequest,
    EventChangeRequestItem,
    EventCoordinatorAssignment,
    EventRequest,
    EventStatusHistory,
    Notification,
    Organisation,
)
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

app = confirmation.app
client = confirmation.client


@pytest.fixture
def decision_app(tmp_path, monkeypatch):
    yield from decisions.base.app.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def decision_client(decision_app):
    return decision_app.test_client()


def rows(app, event_id):
    with Session(app.extensions["engine"]) as session:
        return [
            (row.recipient_account_id, row.dedupe_key, row.message)
            for row in session.scalars(
                select(Notification)
                .where(
                    Notification.event_request_id == event_id,
                    Notification.dedupe_key.like("organiser_%"),
                )
                .order_by(Notification.id)
            )
        ]


def organiser_identity(app, event_id, actor, *, submitter=None):
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).organiser_account_id = actor
        session.add(AccountRole(account_id=actor, role="event_organiser"))
        if submitter is not None:
            session.get(EventChangeRequest, submitter).submitted_by_account_id = actor
        session.commit()


def significant(client, event_id, values):
    path = f"/api/event-requests/assigned/{event_id}/significant-changes"
    headers = decisions.base.headers("coordinator")
    preview = client.post(path + "/preview", headers=headers, json={"values": values})
    assert preview.status_code == 200, preview.json
    return client.patch(
        path,
        headers=headers,
        json={"values": values, "preview_token": preview.json["preview_token"]},
    )


def inject_failure(monkeypatch, target="app.notifications.add_organiser_notice", *, after=1):
    original = notifications.add_organiser_notice
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        original(*args, **kwargs)
        calls += 1
        if calls == after:
            raise RuntimeError("SPL-123 injected write failure")

    monkeypatch.setattr(target, fail)


# QA-SPL-123-001 | AC1 | BB
def test_qa_spl_123_001_confirmation_is_persisted_and_reloadable(app, client):
    event_id = confirmation.ready_event(app)
    assert confirmation.confirm(client, event_id).status_code == 200
    inbox = client.get("/api/notifications", headers=confirmation.headers("organiser")).json
    assert len(inbox["notifications"]) == 1
    notice = inbox["notifications"][0]
    assert notice["message"] == "Community Leadership Forum has been confirmed."
    assert notice["link"] == f"/workspace/organisation-events/{event_id}"
    assert notice["read"] is False
    assert client.get("/api/notifications", headers=confirmation.headers("organiser")).json == inbox


# QA-SPL-123-002 | AC1 AC5 | BB
def test_qa_spl_123_002_unready_confirmation_has_no_notice(app, client):
    event_id = confirmation.add_event(app)
    assert confirmation.confirm(client, event_id).status_code == 409
    assert rows(app, event_id) == []


@pytest.mark.parametrize(
    "identity,code", [(None, 401), ("organiser", 403), ("other-coordinator", 404)]
)
# QA-SPL-123-003 | AC1 AC5 | BB
def test_qa_spl_123_003_only_assigned_coordinator_can_trigger_confirmation(
    app, client, identity, code
):
    event_id = confirmation.ready_event(app)
    assert confirmation.confirm(client, event_id, identity).status_code == code
    assert rows(app, event_id) == []


# QA-SPL-123-004 | AC1 | WB
def test_qa_spl_123_004_new_confirmation_uses_new_history_identity(app, client):
    event_id = confirmation.ready_event(app)
    assert confirmation.confirm(client, event_id).status_code == 200
    with Session(app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).status = "planning"
        session.commit()
    assert confirmation.confirm(client, event_id).status_code == 200
    notices = rows(app, event_id)
    assert len(notices) == 2 and notices[0][1] != notices[1][1]
    assert all(row[0] == confirmation.ORGANISER for row in notices)


# QA-SPL-123-005 | AC1 | WB
def test_qa_spl_123_005_dual_role_actor_gets_no_self_confirmation(app, client):
    event_id = confirmation.ready_event(app)
    organiser_identity(app, event_id, confirmation.COORDINATOR)
    assert confirmation.confirm(client, event_id).status_code == 200
    assert rows(app, event_id) == []


# QA-SPL-123-006 | AC2 | BB
def test_qa_spl_123_006_direct_significant_edit_notifies_return_to_planning(
    decision_app, decision_client
):
    event_id = decisions.base.make_event(decision_app, "confirmed")
    result = significant(decision_client, event_id, {"expected_attendance": 151})
    assert result.status_code == 200 and result.json["event"]["status"] == "planning"
    [(recipient, key, message)] = rows(decision_app, event_id)
    assert recipient == decisions.base.ORGANISER
    assert key.startswith("organiser_returned_to_planning:")
    assert message == (
        "Harbour Lights Gala has returned to Planning after a significant change "
        "and must be confirmed again."
    )


# QA-SPL-123-007 | AC2 AC4 | BB
def test_qa_spl_123_007_two_significant_items_send_one_planning_notice(
    decision_app, decision_client
):
    event_id = decisions.base.make_event(decision_app, "confirmed")
    request = decisions.request(
        decision_client,
        event_id,
        decisions.item("start_time", "09:00"),
        decisions.item("end_time", "10:00"),
    )
    result = decisions.save(decision_client, event_id, request, decisions.choices(request))
    assert result.status_code == 200, result.json
    notices = rows(decision_app, event_id)
    assert len(notices) == 3
    assert sum(key.startswith("organiser_returned_to_planning:") for _, key, _ in notices) == 1
    assert sum(key.startswith("organiser_change_item_decided:") for _, key, _ in notices) == 2


# QA-SPL-123-008 | AC2 | BB
def test_qa_spl_123_008_edit_while_planning_sends_no_return_notice(decision_app, decision_client):
    event_id = decisions.base.make_event(decision_app, "planning")
    assert significant(decision_client, event_id, {"expected_attendance": 151}).status_code == 200
    assert rows(decision_app, event_id) == []


# QA-SPL-123-009 | AC2 AC5 | BB
def test_qa_spl_123_009_noop_and_preview_do_not_notify(decision_app, decision_client):
    event_id = decisions.base.make_event(decision_app, "confirmed")
    assert significant(decision_client, event_id, {"expected_attendance": 150}).status_code == 200
    assert rows(decision_app, event_id) == []
    path = f"/api/event-requests/assigned/{event_id}/significant-changes/preview"
    result = decision_client.post(
        path,
        headers=decisions.base.headers("coordinator"),
        json={"values": {"expected_attendance": 151}},
    )
    assert result.status_code == 200 and result.json["returns_to_planning"]
    assert rows(decision_app, event_id) == []


# QA-SPL-123-010 | AC2 | WB
def test_qa_spl_123_010_self_significant_change_is_silent(decision_app, decision_client):
    event_id = decisions.base.make_event(decision_app, "confirmed")
    organiser_identity(decision_app, event_id, decisions.base.COORDINATOR)
    assert significant(decision_client, event_id, {"expected_attendance": 151}).status_code == 200
    assert rows(decision_app, event_id) == []


@pytest.mark.parametrize("reason", ["  Storm warning.  ", "x" * 2000])
# QA-SPL-123-011 | AC3 | BB
def test_qa_spl_123_011_cancellation_includes_trimmed_reason(app, client, reason):
    event_id = confirmation.ready_event(app, status="confirmed")
    assert cancellation.cancel(client, event_id, reason).status_code == 200
    [(recipient, key, message)] = rows(app, event_id)
    assert recipient == confirmation.ORGANISER and key.startswith("organiser_event_cancelled:")
    assert message == f"Community Leadership Forum has been cancelled. Reason: {reason.strip()}"


# QA-SPL-123-012 | AC3 | BB
def test_qa_spl_123_012_cancellation_notifies_without_arrangements(app, client):
    event_id = confirmation.add_event(app)
    assert cancellation.cancel(client, event_id, "Venue closed.").status_code == 200
    assert len(rows(app, event_id)) == 1


@pytest.mark.parametrize("reason", [None, "", "  ", 123, "x" * 2001])
# QA-SPL-123-013 | AC3 AC5 | BB
def test_qa_spl_123_013_invalid_cancellation_reason_writes_nothing(app, client, reason):
    event_id = confirmation.add_event(app)
    assert cancellation.cancel(client, event_id, reason).status_code == 400
    assert rows(app, event_id) == []


@pytest.mark.parametrize("status", ["completed", "rejected", "withdrawn"])
# QA-SPL-123-014 | AC3 AC5 | BB
def test_qa_spl_123_014_terminal_event_refuses_cancellation_without_notice(app, client, status):
    event_id = confirmation.add_event(app, status=status)
    assert cancellation.cancel(client, event_id).status_code == 409
    assert rows(app, event_id) == []


# QA-SPL-123-015 | AC3 | WB
def test_qa_spl_123_015_self_cancellation_is_silent(app, client):
    event_id = confirmation.add_event(app)
    organiser_identity(app, event_id, confirmation.COORDINATOR)
    assert cancellation.cancel(client, event_id).status_code == 200
    assert rows(app, event_id) == []


# QA-SPL-123-016 | AC4 | BB
def test_qa_spl_123_016_ordinary_accepted_item_names_field_and_outcome(
    decision_app, decision_client
):
    event_id = decisions.base.make_event(decision_app, "confirmed")
    request = decisions.request(decision_client, event_id)
    assert (
        decisions.save(decision_client, event_id, request, decisions.choices(request)).status_code
        == 200
    )
    [(recipient, key, message)] = rows(decision_app, event_id)
    assert recipient == decisions.base.ORGANISER and key.endswith(f":{request['items'][0]['id']}")
    assert message == "Your change request for Revised gala: Event name was accepted."


# QA-SPL-123-017 | AC4 | BB
def test_qa_spl_123_017_decline_has_reason_without_proposed_values(decision_app, decision_client):
    event_id = decisions.base.make_event(decision_app)
    request = decisions.request(
        decision_client, event_id, decisions.item("description", "PRIVATE PROPOSED VALUE")
    )
    assert (
        decisions.save(
            decision_client,
            event_id,
            request,
            decisions.choices(request, "declined", "No safe alternative."),
        ).status_code
        == 200
    )
    [(_, _, message)] = rows(decision_app, event_id)
    assert message.endswith("was declined. Reason: No safe alternative.")
    assert "PRIVATE PROPOSED VALUE" not in message


# QA-SPL-123-018 | AC4 | BB
def test_qa_spl_123_018_partial_then_mixed_final_decisions_notify_each_item(
    decision_app, decision_client
):
    event_id = decisions.base.make_event(decision_app)
    request = decisions.request(
        decision_client, event_id, decisions.item(), decisions.item("venue_notes", "East entrance")
    )
    choices = decisions.choices(request)
    first = decisions.save(decision_client, event_id, request, choices[:1])
    assert first.status_code == 200 and first.json["change_request"]["status"] == "pending"
    assert len(rows(decision_app, event_id)) == 1
    remaining = [{**choices[1], "decision": "declined", "decline_reason": "Access restricted."}]
    second = decisions.save(decision_client, event_id, request, remaining)
    assert second.status_code == 200 and second.json["change_request"]["status"] == "closed"
    assert len(rows(decision_app, event_id)) == 2


# QA-SPL-123-019 | AC4 | WB
def test_qa_spl_123_019_item_recipient_comes_from_stored_submitter(decision_app, decision_client):
    event_id = decisions.base.make_event(decision_app)
    request = decisions.request(decision_client, event_id)
    with Session(decision_app.extensions["engine"]) as session:
        session.get(
            EventChangeRequest, request["id"]
        ).submitted_by_account_id = decisions.base.COLLEAGUE
        session.commit()
    assert (
        decisions.save(decision_client, event_id, request, decisions.choices(request)).status_code
        == 200
    )
    assert rows(decision_app, event_id)[0][0] == decisions.base.COLLEAGUE


# QA-SPL-123-020 | AC4 | WB
def test_qa_spl_123_020_self_decision_is_silent(decision_app, decision_client):
    event_id = decisions.base.make_event(decision_app)
    request = decisions.request(decision_client, event_id)
    organiser_identity(decision_app, event_id, decisions.base.COORDINATOR, submitter=request["id"])
    assert (
        decisions.save(decision_client, event_id, request, decisions.choices(request)).status_code
        == 200
    )
    assert rows(decision_app, event_id) == []


# QA-SPL-123-021 | AC5 | WB
def test_qa_spl_123_021_confirmation_failure_rolls_back_notice_and_transition(
    app, client, monkeypatch
):
    event_id = confirmation.ready_event(app)
    inject_failure(monkeypatch)
    with pytest.raises(RuntimeError, match="injected write failure"):
        confirmation.confirm(client, event_id)
    assert rows(app, event_id) == []
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status == "planning"
        assert session.scalar(select(func.count()).select_from(EventStatusHistory)) == 0


# QA-SPL-123-022 | AC5 | WB
def test_qa_spl_123_022_cancellation_failure_rolls_back_notice_and_action(app, client, monkeypatch):
    event_id = confirmation.ready_event(app, status="confirmed")
    inject_failure(monkeypatch)
    with pytest.raises(RuntimeError, match="injected write failure"):
        cancellation.cancel(client, event_id)
    assert rows(app, event_id) == []
    with Session(app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).status == "confirmed"


# QA-SPL-123-023 | AC5 | WB
def test_qa_spl_123_023_significant_change_failure_rolls_back(
    decision_app, decision_client, monkeypatch
):
    event_id = decisions.base.make_event(decision_app, "confirmed")
    inject_failure(monkeypatch, "app.significant_event_changes.add_organiser_notice")
    with pytest.raises(RuntimeError, match="injected write failure"):
        significant(decision_client, event_id, {"expected_attendance": 151})
    assert rows(decision_app, event_id) == []
    with Session(decision_app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).expected_attendance == 150
        assert session.get(EventRequest, event_id).status == "confirmed"


# QA-SPL-123-024 | AC5 | WB
def test_qa_spl_123_024_later_item_failure_rolls_back_entire_batch(
    decision_app, decision_client, monkeypatch
):
    event_id = decisions.base.make_event(decision_app)
    request = decisions.request(
        decision_client, event_id, decisions.item(), decisions.item("venue_notes", "East entrance")
    )
    inject_failure(monkeypatch, "app.event_change_decisions.add_organiser_notice", after=2)
    with pytest.raises(RuntimeError, match="injected write failure"):
        decisions.save(decision_client, event_id, request, decisions.choices(request))
    assert rows(decision_app, event_id) == []
    with Session(decision_app.extensions["engine"]) as session:
        assert session.get(EventRequest, event_id).name == "Harbour Lights Gala"
        assert all(
            item.decision is None for item in session.scalars(select(EventChangeRequestItem))
        )


@pytest.mark.parametrize("action", ["confirmation", "cancellation", "decision"])
# QA-SPL-123-025 | AC5 | BB
def test_qa_spl_123_025_retries_do_not_duplicate(
    app, client, decision_app, decision_client, action
):
    if action == "decision":
        target = decision_app
        event_id = decisions.base.make_event(target)
        request = decisions.request(decision_client, event_id)
        assert (
            decisions.save(
                decision_client, event_id, request, decisions.choices(request)
            ).status_code
            == 200
        )
        before = rows(target, event_id)
        retry = decision_client.post(
            decisions.url(event_id, request),
            headers=decisions.base.headers("coordinator"),
            json={"decisions": decisions.choices(request), "preview_token": "old"},
        )
    else:
        target = app
        event_id = confirmation.ready_event(app)
        call = confirmation.confirm if action == "confirmation" else cancellation.cancel
        assert call(client, event_id).status_code == 200
        before = rows(target, event_id)
        retry = call(client, event_id)
    assert retry.status_code == 409
    assert rows(target, event_id) == before


# QA-SPL-123-026 | AC1 AC3 AC4 | BB
def test_qa_spl_123_026_foreign_inbox_cannot_read_notices(app, client):
    event_id = confirmation.ready_event(app)
    assert confirmation.confirm(client, event_id).status_code == 200
    for actor in ("coordinator", "other-coordinator", "technical", "venue-staff", "lead"):
        assert (
            client.get("/api/notifications", headers=confirmation.headers(actor)).json[
                "notifications"
            ]
            == []
        )


# QA-SPL-123-027 | AC5 | WB
def test_qa_spl_123_027_database_dedupe_constraint(app, client):
    event_id = confirmation.ready_event(app)
    assert confirmation.confirm(client, event_id).status_code == 200
    with Session(app.extensions["engine"]) as session:
        source = session.scalar(select(Notification))
        session.add(
            Notification(
                recipient_account_id=source.recipient_account_id,
                event_request_id=event_id,
                message=source.message,
                dedupe_key=source.dedupe_key,
                created_at=source.created_at,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    assert len(rows(app, event_id)) == 1


# QA-SPL-123-028 | AC4 AC5 | BB
def test_qa_spl_123_028_reassignment_after_preview_refuses_decisions(decision_app, decision_client):
    event_id = decisions.base.make_event(decision_app)
    request = decisions.request(decision_client, event_id)
    chosen = decisions.choices(request)
    check = decisions.preview(decision_client, event_id, request, chosen)
    assert check.status_code == 200
    with Session(decision_app.extensions["engine"]) as session:
        session.get(
            EventCoordinatorAssignment, event_id
        ).coordinator_account_id = decisions.base.OTHER_COORDINATOR
        session.commit()
    response = decision_client.post(
        decisions.url(event_id, request),
        headers=decisions.base.headers("coordinator"),
        json={"decisions": chosen, "preview_token": check.json["preview_token"]},
    )
    assert response.status_code == 404
    assert rows(decision_app, event_id) == []


# QA-SPL-123-029 | AC4 AC5 | BB
def test_qa_spl_123_029_stale_preview_sends_no_notice(decision_app, decision_client):
    event_id = decisions.base.make_event(decision_app)
    request = decisions.request(decision_client, event_id)
    chosen = decisions.choices(request)
    check = decisions.preview(decision_client, event_id, request, chosen)
    assert check.status_code == 200
    with Session(decision_app.extensions["engine"]) as session:
        session.get(EventRequest, event_id).name = "Changed elsewhere"
        session.commit()
    response = decision_client.post(
        decisions.url(event_id, request),
        headers=decisions.base.headers("coordinator"),
        json={"decisions": chosen, "preview_token": check.json["preview_token"]},
    )
    assert response.status_code == 409
    assert rows(decision_app, event_id) == []


# QA-SPL-123-030 | AC5 | BB
def test_qa_spl_123_030_client_cannot_choose_notice_recipient(app, client):
    event_id = confirmation.ready_event(app)
    response = confirmation.confirm(
        client, event_id, json={"recipient_id": confirmation.OTHER_COORDINATOR}
    )
    assert response.status_code == 400
    assert rows(app, event_id) == []


@pytest.mark.parametrize("name_first", [True, False])
# QA-SPL-123-031 | AC2 AC4 AC5 | BB review regression
def test_qa_spl_123_031_mixed_rename_uses_one_name_for_all_notices(
    decision_app, decision_client, name_first
):
    event_id = decisions.base.make_event(decision_app, "confirmed")
    accepted = [decisions.item("name", "New programme"), decisions.item("expected_attendance", 151)]
    if not name_first:
        accepted.reverse()
    request = decisions.request(
        decision_client, event_id, *accepted, decisions.item("description", "Private proposal")
    )
    choices = decisions.choices(request)
    choices[-1].update(decision="declined", decline_reason="Keep the original description.")
    response = decisions.save(decision_client, event_id, request, choices)
    assert response.status_code == 200, response.json
    assert response.json["event"]["name"] == "New programme"
    assert response.json["event"]["status"] == "planning"
    notices = rows(decision_app, event_id)
    assert len(notices) == 4
    assert all("New programme" in message for _, _, message in notices), notices
    assert all("Harbour Lights Gala" not in message for _, _, message in notices)
    assert any("Reason: Keep the original description." in message for _, _, message in notices)
    assert all("Private proposal" not in message for _, _, message in notices)


def revoke_organiser_access(session, account_id, change):
    if change == "role":
        session.execute(
            delete(AccountRole).where(
                AccountRole.account_id == account_id, AccountRole.role == "event_organiser"
            )
        )
    else:
        other = Organisation(name="Former organiser's new organisation")
        session.add(other)
        session.flush()
        session.get(Account, account_id).organisation_id = other.id


@pytest.mark.parametrize("change", ["role", "organisation"])
@pytest.mark.parametrize("submitter", ["organiser", "colleague"])
# QA-SPL-123-033 | AC4 | WB review privacy regression
def test_qa_spl_123_033_former_submitter_gets_no_notice_or_fallback(
    decision_app, decision_client, change, submitter
):
    event_id = decisions.base.make_event(decision_app)
    request = decisions.request(decision_client, event_id)
    recipient = decisions.base.ORGANISER if submitter == "organiser" else decisions.base.COLLEAGUE
    with Session(decision_app.extensions["engine"]) as session:
        session.get(EventChangeRequest, request["id"]).submitted_by_account_id = recipient
        revoke_organiser_access(session, recipient, change)
        session.commit()
    response = decisions.save(
        decision_client, event_id, request, decisions.choices(request, "declined", "Private reason")
    )
    assert response.status_code == 200, response.json
    assert rows(decision_app, event_id) == []
    assert response.json["change_request"]["items"][0]["decision"] == "declined"


@pytest.mark.parametrize("change", ["role", "organisation"])
# QA-SPL-123-034 | AC1 | WB review privacy regression
def test_qa_spl_123_034_former_responsible_organiser_gets_no_confirmation(app, client, change):
    event_id = confirmation.ready_event(app)
    with Session(app.extensions["engine"]) as session:
        revoke_organiser_access(session, confirmation.ORGANISER, change)
        session.commit()
    response = confirmation.confirm(client, event_id)
    assert response.status_code == 200, response.json
    assert rows(app, event_id) == []


# QA-SPL-123-032 | AC1 AC5 | WB review helper contract
def test_qa_spl_123_032_unflushed_sources_get_distinct_durable_keys(app):
    from app.event_review import transition_event_status

    event_ids = [confirmation.add_event(app), confirmation.add_event(app)]
    with Session(app.extensions["engine"], autoflush=False) as session:
        for event_id in event_ids:
            event = session.get(EventRequest, event_id)
            source = transition_event_status(
                session,
                event_request_id=event_id,
                action="confirm",
                actor_account_id=confirmation.COORDINATOR,
                changed_at=confirmation.NOW,
            )
            assert source.id is None
            notifications.add_organiser_notice(
                session,
                event,
                actor_id=confirmation.COORDINATOR,
                kind="event_confirmed",
                source=source,
                message=f"{event.name} has been confirmed.",
            )
            assert source.id is not None
        session.commit()
    keys = [rows(app, event_id)[0][1] for event_id in event_ids]
    assert len(set(keys)) == 2
    assert all(key.startswith("organiser_event_confirmed:") and ":None" not in key for key in keys)
